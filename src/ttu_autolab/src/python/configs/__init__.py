#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Configurations of model training and validation

Created on May 12nd, 2021
'''

DATAROOT = '/home/claude/Data/mauro_waymo'
SPLITS = '2'  # .txt file name

AUGMENT = 'square_crop' #'random_crop' 'random_rotate' 'random_colour_jiter'

# rot_range=20, 
# factor=4 
# crop_size=128

LIDAR_MEAN = [-0.17263354, 0.85321806, 24.5527253]
LIDAR_STD = [7.34546552, 1.17227659, 15.83745082]

IMAGE_MEAN = [0.485, 0.456, 0.406]
IMAGE_STD = [0.229, 0.224, 0.225]


IMAGE_BRIGHTNESS = 0.4
IMAGE_CONTRAST = 0.4
IMAGE_SATURATION = 0.4
IMAGE_HUE = 0.1

WORKERS = 4  #number of data loading workers(CPU threads)
GPU = None
EPOCHS = 10  #number of total epochs to run
BATCH_SIZE = 8 #batch size
EPOCHS_COTRAIN = 300  #number of total epochs to run
CLASS_TOTAL = 4  #number of classes
LR = 0.0003  #'initial learning rate', dest='lr')
LR_SEMI = 0.00005

LOG_DIR = '/home/claude/Data/logs/3rd_test/'

TEST_IMAGE = '/home/claude/1.png'
TEST_LIDAR = '/home/claude/2.pkl'