#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Configurations of model training and validation

Created on May 12nd, 2021
'''

DATAROOT = '/home/claude/Data/mauro_waymo'
LOG_DIR = '/home/claude/Data/logs/9th_gpu_test/'  # Path to save checkpoints
TRAIN_SPLITS = 'training_7'  # training split file name (.txt file)
VALID_SPLITS = 'validation_7'  # Validation(while training) split file name
EVAL_SPLITS = 'validation_1'  # Evaluation split file name (.txt file)

# Data augment configurations
RANDOM_CROP_SIZE = 128
ROTATE_RANGE = 20
JITTER_PARAM = [0.4, 0.4, 0.4, 0.1]  # [brightness, contrast, saturation, hue]

LIDAR_MEAN = [-0.17263354, 0.85321806, 24.5527253]
LIDAR_STD = [7.34546552, 1.17227659, 15.83745082]

IMAGE_MEAN = [0.485, 0.456, 0.406]
IMAGE_STD = [0.229, 0.224, 0.225]

DEVICE = 'cuda:0'  # 'cpu' for CPU training. Default ID for GPU is :0
CLASS_TOTAL = 4  # number of classes
WORKERS = 16  # number of data loading workers (CPU threads)
BATCH_SIZE = 16  # batch size
EPOCHS = 100  # number of total epochs to run
SAVE_EPOCH = 10  # save the checkpoint after this mount of epochs

EPOCHS_COTRAIN = 300  # number of total epochs to run
LR = 0.00003  # initial learning rate
LR_SEMI = 0.00005


TEST_IMAGE = './test_images/test_img.png'
TEST_LIDAR = './test_images/test_lidar.pkl'
TEST_ANNO = './test_images/test_anno.png'
