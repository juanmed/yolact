#! /bin/bash
common_args="--top_k=100 --score_threshold=0.50 --no_bar --fast_nms=True"
export CUDA_LAUNCH_BLOCKING=1

function my_eval {
    local weight_dir=$1
    local weight=$2
    local config_name=${weight_dir}_config

    # If you want to change the test image source directory, change this
    local images_dir=/repos/dataset/minjae/
    local depth_images_dir=/repos/dataset/minjae

    mkdir -p ./results/summary/${weight_dir}/image_result
    mkdir -p ./results/summary/${weight_dir}/prof
    echo "[weight: ${weight}] " >>./results/summary/${weight_dir}/log.txt
    echo "[images: ${images_dir}]" >>./results/summary/${weight_dir}/log.txt

    # uncomment this for qualitative results
    # rgbd
    # python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --depth_images=${depth_images_dir} --images=${images_dir}:results/summary/${weight_dir}/image_result --config=${config_name} ${common_args}
    # rgb
     python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --images=${images_dir}:results/summary/${weight_dir}/image_result --config=${config_name} ${common_args}

    # uncomment this for mAP log
    # rgbd
    # python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --config=${config_name} --test_dataset ${common_args} >>./results/summary/${weight_dir}/log.txt
    # rgb
    # python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --config=${config_name} ${common_args} >>./results/summary/${weight_dir}/log.txt

    # uncomment this for benchmark log
    # rgbd
    # python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --config=${config_name} ${common_args} --test_dataset --benchmark >>./results/summary/${weight_dir}/log.txt
    # rgb
    # python3 ./eval.py --trained_model=./weights/${weight_dir}/${weight} --config=${config_name} ${common_args} --benchmark >>./results/summary/${weight_dir}/log.txt

    # uncomment this for profiler. not for evaluating but profiling.
    # python3 -m cProfile -o ./results/summary/${weight_dir}/prof/${img_sz}.prof ./eval.py --trained_model=./weights/${weight_dir}/${weight} --dataset=ul_aug_benchmark${img_sz} ${common_args} --config=${config_name} --benchmark
}

# my_eval yolact_resnet50_max1024 yolact_resnet50_max1024_config_892_100000.pth 2048
# my_eval yolact_resnet50_max1024 yolact_resnet50_max1024_config_892_100000.pth failed
# my_eval yolact_mobilenetv2_max1024 yolact_mobilenetv2_max1024_892_50000.pth 2048
# my_eval yolact_resnet50_max1024_depth_to_red yolact_resnet50_max1024_depth_to_red_3333_10000.pth 2048
# my_eval yolact_resnet50_max1024_bgrd16uc4 yolact_resnet50_max1024_bgrd16uc4_5038_15114_interrupt.pth 2048
# my_eval yolact_resnet50_wisdom yolact_resnet50_wisdom_1176_20000.pth 2048
my_eval yolact_resnet50_max1024 yolact_resnet50_max1024_1501_6004_interrupt.pth
#my_eval yolact_mobilenetv2_max1024 yolact_mobilenetv2_max1024_191_21494_interrupt.pth
