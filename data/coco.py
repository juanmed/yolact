import os
import os.path as osp
import sys
import torch
import torch.utils.data as data
import torch.nn.functional as F
import cv2
import numpy as np
from .config import cfg
from pycocotools import mask as maskUtils
import random


def get_label_map():
    if cfg.dataset.label_map is None:
        return {x + 1: x + 1 for x in range(len(cfg.dataset.class_names))}
    else:
        return cfg.dataset.label_map


class COCOAnnotationTransform(object):
    """Transforms a COCO annotation into a Tensor of bbox coords and label index
    Initilized with a dictionary lookup of classnames to indexes
    """

    def __init__(self):
        self.label_map = get_label_map()

    def __call__(self, target, width, height):
        """
        Args:
            target (dict): COCO target json annotation as a python dict
            height (int): height
            width (int): width
        Returns:
            a list containing lists of bounding boxes  [bbox coords, class idx]
        """
        scale = np.array([width, height, width, height])
        res = []
        for obj in target:
            if "bbox" in obj:
                bbox = obj["bbox"]
                label_idx = obj["category_id"]
                if label_idx >= 0:
                    label_idx = self.label_map[label_idx] - 1
                final_box = list(
                    np.array([bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]])
                    / scale
                )
                final_box.append(label_idx)
                res += [final_box]  # [xmin, ymin, xmax, ymax, label_idx]
            else:
                print("No bbox found for object ", obj)

        return res


class COCODetection(data.Dataset):
    """`MS Coco Detection <http://mscoco.org/dataset/#detections-challenge2016>`_ Dataset.
    Args:
        root (string): Root directory where images are downloaded to.
        set_name (string): Name of the specific set of COCO images.
        transform (callable, optional): A function/transform that augments the
                                        raw images`
        target_transform (callable, optional): A function/transform that takes
        in the target (bbox) and transforms it.
        prep_crowds (bool): Whether or not to prepare crowds for the evaluation step.
    """

    def __init__(
        self,
        color_img_path,
        depth_img_path,
        info_file,
        transform=None,
        target_transform=None,
        dataset_name="MS COCO",
        has_gt=True,
    ):
        # Do this here because we have too many things named COCO
        from pycocotools.coco import COCO

        if target_transform is None:
            target_transform = COCOAnnotationTransform()

        self.color_root = color_img_path
        self.depth_root = depth_img_path
        self.coco = COCO(info_file)

        self.ids = list(self.coco.imgToAnns.keys())
        if len(self.ids) == 0 or not has_gt:
            self.ids = list(self.coco.imgs.keys())

        self.transform = transform
        self.target_transform = COCOAnnotationTransform()

        self.name = dataset_name
        self.has_gt = has_gt

    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: Tuple (image, (target, masks, num_crowds)).
                   target is the object returned by ``coco.loadAnns``.
        """
        color_im, gt, masks, h, w, num_crowds = self.pull_item(index)
        return color_im, (gt, masks, num_crowds)

    def __len__(self):
        return len(self.ids)

    def pull_item(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: Tuple (image, target, masks, height, width, crowd).
                   target is the object returned by ``coco.loadAnns``.
            Note that if no crowd annotations exist, crowd will be None
        """
        img_id = self.ids[index]

        if self.has_gt:
            ann_ids = self.coco.getAnnIds(imgIds=img_id)

            # Target has {'segmentation', 'area', iscrowd', 'image_id', 'bbox', 'category_id'}
            target = [x for x in self.coco.loadAnns(ann_ids) if x["image_id"] == img_id]
        else:
            target = []

        # Separate out crowd annotations. These are annotations that signify a large crowd of
        # objects of said class, where there is no annotation for each individual object. Both
        # during testing and training, consider these crowds as neutral.
        crowd = [x for x in target if ("iscrowd" in x and x["iscrowd"])]
        target = [x for x in target if not ("iscrowd" in x and x["iscrowd"])]
        num_crowds = len(crowd)

        for x in crowd:
            x["category_id"] = -1

        # This is so we ensure that all crowd annotations are at the end of the array
        target += crowd

        # The split here is to have compatibility with both COCO2014 and 2017 annotations.
        # In 2014, images have the pattern COCO_{train/val}2014_%012d.jpg, while in 2017 it's %012d.jpg.
        # Our script downloads the images as %012d.jpg so convert accordingly.
        file_name = self.coco.loadImgs(img_id)[0]["file_name"]

        if file_name.startswith("COCO"):
            file_name = file_name.split("_")[-1]

        color_path = osp.join(self.color_root, file_name)
        assert osp.exists(color_path), "Color image path does not exist: {}".format(
            color_path
        )

        depth_path = osp.join(self.depth_root, file_name)
        assert osp.exists(depth_path), "Depth image path does not exist: {}".format(
            depth_path
        )

        # read color image in BGR color encoding.
        color_img = cv2.imread(color_path, cv2.IMREAD_COLOR)
        height, width, _ = color_img.shape

        # read depth image with the encoding unchanged.
        depth_img = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)

        # depth image preprocess
        # considering 16uc1 depth encoding only. unit is [mm]

        # create channel dimension
        if len(depth_img.shape) < 3:
            depth_img = np.expand_dims(depth_img, axis=2)
        depth_height, depth_width, _ = depth_img.shape

        # depth, color size match assertion
        assert (depth_height == height) and (
            depth_width == width
        ), "image size does not match (color:[{}, {}], depth:[{},{}] in [h,w] format)".format(
            height, width, depth_height, depth_width
        )

        if len(target) > 0:
            # Pool all the masks for this image into one [num_objects,height,width] matrix
            masks = [self.coco.annToMask(obj).reshape(-1) for obj in target]
            masks = np.vstack(masks)
            masks = masks.reshape(-1, height, width)

        if self.target_transform is not None and len(target) > 0:
            target = self.target_transform(target, width, height)

        if self.transform is not None:
            if len(target) > 0:
                target = np.array(target)
                img, masks, boxes, labels = self.transform(
                    color_img,
                    depth_img,
                    masks,
                    target[:, :4],
                    {"num_crowds": num_crowds, "labels": target[:, 4]},
                )

                # I stored num_crowds in labels so I didn't have to modify the entirety of augmentations
                num_crowds = labels["num_crowds"]
                labels = labels["labels"]

                target = np.hstack((boxes, np.expand_dims(labels, axis=1)))
            else:
                img, _, _, _ = self.transform(
                    color_img,
                    depth_img,
                    np.zeros((1, height, width), dtype=np.float),
                    np.array([[0, 0, 1, 1]]),
                    {"num_crowds": 0, "labels": np.array([0])},
                )
                masks = None
                target = None

        if target.shape[0] == 0:
            print(
                "Warning: Augmentation output an example with no ground truth. Resampling..."
            )
            return self.pull_item(random.randint(0, len(self.ids) - 1))

        return (
            torch.from_numpy(img).permute(2, 0, 1),
            target,
            masks,
            height,
            width,
            num_crowds,
        )

    def pull_image(self, index):
        """Returns the original image object at index in PIL form

        Note: not using self.__getitem__(), as any transformations passed in
        could mess up this functionality.

        Argument:
            index (int): index of img to show
        Return:
            cv2 img
        """
        img_id = self.ids[index]
        path = self.coco.loadImgs(img_id)[0]["file_name"]
        return cv2.imread(osp.join(self.color_root, path), cv2.IMREAD_COLOR)

    def pull_anno(self, index):
        """Returns the original annotation of image at index

        Note: not using self.__getitem__(), as any transformations passed in
        could mess up this functionality.

        Argument:
            index (int): index of img to get annotation of
        Return:
            list:  [img_id, [(label, bbox coords),...]]
                eg: ('001718', [('dog', (96, 13, 438, 332))])
        """
        img_id = self.ids[index]
        ann_ids = self.coco.getAnnIds(imgIds=img_id)
        return self.coco.loadAnns(ann_ids)

    def pull_depth(self, index):
        """Returns the original depth image object at index in PIL form

        Note: not using self.__getitem__(), as any transformations passed in
        could mess up this functionality.

        Argument:
            index (int): index of img to show
        Return:
            cv2 img
        """
        img_id = self.ids[index]
        path = self.coco.loadImgs(img_id)[0]["file_name"]
        return cv2.imread(osp.join(self.depth_root, path), cv2.IMREAD_UNGHANCED)

    def __repr__(self):
        fmt_str = "Dataset " + self.__class__.__name__ + "\n"
        fmt_str += "    Number of datapoints: {}\n".format(self.__len__())
        fmt_str += "    Color Root Location: {}\n".format(self.color_root)
        fmt_str += "    Depth Root Location: {}\n".format(self.depth_root)
        tmp = "    Transforms (if any): "
        fmt_str += "{0}{1}\n".format(
            tmp, self.transform.__repr__().replace("\n", "\n" + " " * len(tmp))
        )
        tmp = "    Target Transforms (if any): "
        fmt_str += "{0}{1}".format(
            tmp, self.target_transform.__repr__().replace("\n", "\n" + " " * len(tmp))
        )
        return fmt_str


def enforce_size(color_img, depth_img, targets, masks, num_crowds, new_w, new_h):
    """Ensures that the image is the given size without distorting aspect ratio."""
    with torch.no_grad():
        _, h, w = color_img.size()

        if h == new_h and w == new_w:
            return color_img, depth_img, targets, masks, num_crowds

        # Resize the image so that it fits within new_w, new_h
        w_prime = new_w
        h_prime = h * new_w / w

        if h_prime > new_h:
            w_prime *= new_h / h_prime
            h_prime = new_h

        w_prime = int(w_prime)
        h_prime = int(h_prime)

        # Do all the resizing
        color_img = F.interpolate(
            color_img.unsqueeze(0),
            (h_prime, w_prime),
            mode="bilinear",
            align_corners=False,
        )
        color_img.squeeze_(0)

        depth_img = F.interpolate(
            depth_img.unsqueeze(0),
            (h_prime, w_prime),
            mode="bilinear",
            align_corners=False,
        )
        depth_img.squeeze_(0)

        # Act like each object is a color channel
        masks = F.interpolate(
            masks.unsqueeze(0), (h_prime, w_prime), mode="bilinear", align_corners=False
        )
        masks.squeeze_(0)

        # Scale bounding boxes (this will put them in the top left corner in the case of padding)
        targets[:, [0, 2]] *= w_prime / new_w
        targets[:, [1, 3]] *= h_prime / new_h

        # Finally, pad everything to be the new_w, new_h
        pad_dims = (0, new_w - w_prime, 0, new_h - h_prime)
        color_img = F.pad(color_img, pad_dims, mode="constant", value=0)
        depth_img = F.pad(depth_img, pad_dims, mode="constant", value=0)
        masks = F.pad(masks, pad_dims, mode="constant", value=0)

        return color_img, depth_img, targets, masks, num_crowds


def detection_collate(batch):
    """Custom collate fn for dealing with batches of images that have a different
    number of associated object annotations (bounding boxes).

    Arguments:
        batch: (tuple) A tuple of tensor images and (lists of annotations, masks)

    Return:
        A tuple containing:
            1) (tensor) batch of images stacked on their 0 dim
            2) (list<tensor>, list<tensor>, list<int>) annotations for a given image are stacked
                on 0 dim. The output gt is a tuple of annotations and masks.
    """
    targets = []
    imgs = []
    masks = []
    num_crowds = []

    for sample in batch:
        imgs.append(sample[0])
        targets.append(torch.FloatTensor(sample[1][0]))
        masks.append(torch.FloatTensor(sample[1][1]))
        num_crowds.append(sample[1][2])

    return imgs, (targets, masks, num_crowds)
