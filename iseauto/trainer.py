#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import torch
import torch.nn as nn
from tqdm import tqdm
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.tensorboard import SummaryWriter

from fcn.fusion_net import FusionNet
from utils.metrics import find_overlap
from dpt.dpt import DPT
from utils.helpers import EarlyStopping
from utils.helpers import save_model_dict
from utils.helpers import adjust_learning_rate

writer = SummaryWriter()


def get_optimizer_dpt(config, net):
    for name, _ in net.named_modules():
        print(name)
    names = (set([name.split('.')[0] for name, _ in net.named_modules()]) -
             {'', 'transformer_encoders'})

    params_backbone = net.transformer_encoders.parameters()
    params_scratch = list()
    for name in names:
        params_scratch += list(eval("net." + name).parameters())

    optimizer_dpt_backbone = torch.optim.Adam(params_backbone,
                                              lr=config['General']['dpt']['lr_backbone'])
    optimizer_dpt_scratch = torch.optim.Adam(params_scratch,
                                             lr=config['General']['dpt']['lr_scratch'])

    return optimizer_dpt_backbone, optimizer_dpt_scratch


class Trainer(object):
    def __init__(self, config, args):
        super().__init__()
        self.config = config
        self.args = args
        self.finished_epochs = 0
        self.type = self.config['General']['type']

        self.device = torch.device(self.config['General']['device']
                                   if torch.cuda.is_available() else "cpu")
        print("device: %s" % self.device)

        if args.backbone == 'fcn':
            self.model = FusionNet()
            print(f'Using backbone {args.backbone}')
            self.optimizer_fcn = torch.optim.Adam(self.model.parameters(),
                                                  lr=config['General']['fcn'][
                                                      f"lr_{config['General']['sensor_modality']}"])
            self.scheduler_fcn = ReduceLROnPlateau(self.optimizer_fcn)

        elif args.backbone == 'dpt':
            resize = config['Dataset']['transforms']['resize']
            self.model = DPT(
                RGB_tensor_size=(3, resize, resize),
                XYZ_tensor_size=(3, resize, resize),
                emb_dim=config['General']['emb_dim'],
                resample_dim=config['General']['resample_dim'],
                read=config['General']['read'],
                nclasses=len(config['Dataset']['classes']),
                hooks=config['General']['hooks'],
                model_timm=config['General']['model_timm'],
                type=self.type,
                patch_size=config['General']['patch_size'], )
            print(f'Using backbone {args.backbone}')
            self.optimizer_dpt = torch.optim.Adam(self.model.parameters(),
                                                  lr=config['General']['dpt_lr'])
        # self.optimizer_dpt_backbone, self.optimizer_dpt_scratch = \
        # 	get_optimizer_dpt(config, self.model)
        # self.scheduler_backbone = ReduceLROnPlateau(self.optimizer_dpt_backbone)
        # self.scheduler_scratch = ReduceLROnPlateau(self.optimizer_dpt_scratch)

        else:
            sys.exit("A backbone must be specified! (dpt or fcn)")

        self.model.to(self.device)

        self.nclasses = len(config['Dataset']['classes'])
        weight_loss = torch.Tensor(self.nclasses).fill_(0)
        # define weight of different classes, 0-background, 1-car, 2-people.
        # weight_loss[3] = 0
        weight_loss[0] = 1
        weight_loss[1] = 4
        weight_loss[2] = 10
        self.criterion = nn.CrossEntropyLoss(weight=weight_loss).to(self.device)

        if self.config['General']['resume_training'] is True:
            print('Resume training...')
            model_path = self.config['General']['resume_training_model_path']
            checkpoint = torch.load(model_path, map_location=self.device)

            if self.config['General']['reset_lr'] is True:
                print('Reset the epoch to 0')
                self.finished_epochs = 0
            else:
                self.finished_epochs = checkpoint['epoch']
                print(
                    f"Finished epochs in previous training: {self.finished_epochs}")

            if self.config['General']['epochs'] <= self.finished_epochs:
                print(
                    'Present epochs amount is smaller than finished epochs!!!')
                print(
                    f"Please setting the epochs bigger than {self.finished_epochs}")
                sys.exit()
            else:
                print('Loading trained model weights...')
                self.model.load_state_dict(checkpoint['model_state_dict'])
                print('Loading trained optimizer...')
                self.optimizer_dpt.load_state_dict(checkpoint['optimizer_state_dict'])

        else:
            print('Training from the beginning')

    def train_dpt(self, train_dataloader, valid_dataloader, modal):
        """
        The training of one epoch
        """
        epochs = self.config['General']['epochs']
        modality = modal
        early_stopping = EarlyStopping(self.config)
        self.model.train()
        for epoch in range(self.finished_epochs, epochs):
            lr = adjust_learning_rate(self.config, self.optimizer_dpt, epoch)
            print('Epoch: {:.0f}, LR: {:.6f}'.format(epoch, lr))
            print('Training...')
            train_loss = 0.0
            overlap_cum, pred_cum, label_cum, union_cum = 0, 0, 0, 0
            progress_bar = tqdm(train_dataloader)
            for i, batch in enumerate(progress_bar):
                batch['rgb'] = batch['rgb'].to(self.device, non_blocking=True)
                batch['lidar'] = batch['lidar'].to(self.device,
                                                   non_blocking=True)
                batch['anno'] = batch['anno'].to(self.device, non_blocking=True)

                self.optimizer_dpt.zero_grad()

                _, output_seg = self.model(batch['rgb'], batch['lidar'], modality)

                # 1xHxW -> HxW
                output_seg = output_seg.squeeze(1)
                # print(output_seg)
                # print(output_seg.size())
                anno = batch['anno']
                # print(1 in anno)
                batch_overlap, batch_pred, batch_label, batch_union = \
                    find_overlap(self.nclasses, output_seg, anno)
                # print(batch_label)
                overlap_cum += batch_overlap
                pred_cum += batch_pred
                label_cum += batch_label
                union_cum += batch_union

                loss = self.criterion(output_seg, batch['anno'])
                # w_rgb = 1.1
                # w_lid = 0.9
                # loss = w_rgb*loss_rgb + w_lid*loss_lidar + loss_fusion

                train_loss += loss.item()
                loss.backward()
                self.optimizer_dpt.step()
                progress_bar.set_description(f'DPT train loss:{loss:.4f}')

            # The IoU of one epoch
            train_epoch_IoU = overlap_cum / union_cum
            print(
                f'Training vehicles IoU for Epoch:'
                f' {train_epoch_IoU[0]:.4f}')
            print(
                f'Training human IoU for Epoch: {train_epoch_IoU[1]:.4f}')
            # The loss_rgb of one epoch
            train_epoch_loss = train_loss / (i + 1)
            print(
                f'Average Training Loss for Epoch: {train_epoch_loss:.4f}')

            valid_epoch_loss, valid_epoch_IoU = self.validate_dpt(
                valid_dataloader,
                modality)

            # self.scheduler_backbone.step(valid_epoch_loss)
            # self.scheduler_scratch.step(valid_epoch_loss)

            # Plot the train and validation loss in Tensorboard
            writer.add_scalars('Loss', {'train': train_epoch_loss,
                                        'valid': valid_epoch_loss}, epoch)
            # Plot the train and validation IoU in Tensorboard
            writer.add_scalars('Vehicle_IoU',
                               {'train': train_epoch_IoU[0],
                                'valid': valid_epoch_IoU[0]}, epoch)
            writer.add_scalars('Human_IoU',
                               {'train': train_epoch_IoU[1],
                                'valid': valid_epoch_IoU[1]}, epoch)
            writer.close()

            early_stop_index = round(valid_epoch_IoU[0].item(), 4)
            early_stopping(early_stop_index, epoch, self.model,
                           self.optimizer_dpt)
            if ((epoch + 1) % self.config['General']['save_epoch'] == 0 and
                    epoch > 0):
                print('Saving model for every 10 epochs...')
                save_model_dict(self.config, epoch, self.model,
                                self.optimizer_dpt, True)
                print('Saving Model Complete')
            if early_stopping.early_stop_trigger is True:
                break
        print('Training Complete')

    def validate_dpt(self, valid_dataloader, modal):
        """
            The validation of one epoch
        """
        self.model.eval()
        print('Validating...')
        valid_loss = 0.0
        overlap_cum, pred_cum, label_cum, union_cum = 0, 0, 0, 0
        with torch.no_grad():
            progress_bar = tqdm(valid_dataloader)
            for i, batch in enumerate(progress_bar):
                batch['rgb'] = batch['rgb'].to(self.device, non_blocking=True)
                batch['lidar'] = batch['lidar'].to(self.device,
                                                   non_blocking=True)
                batch['anno'] = batch['anno'].to(self.device, non_blocking=True)

                _, output_seg = self.model(batch['rgb'], batch['lidar'],
                                           modal)
                # 1xHxW -> HxW
                output_seg = output_seg.squeeze(1)
                anno = batch['anno']

                batch_overlap, batch_pred, batch_label, batch_union = \
                    find_overlap(self.nclasses, output_seg, anno)

                overlap_cum += batch_overlap
                pred_cum += batch_pred
                label_cum += batch_label
                union_cum += batch_union

                loss = self.criterion(output_seg, batch['anno'])
                valid_loss += loss.item()
                progress_bar.set_description(f'valid fusion loss:'
                                             f'{loss:.4f}')
        # The IoU of one epoch
        valid_epoch_IoU = overlap_cum / union_cum
        print(
            f'Validation vehicles IoU for Epoch:'
            f' {valid_epoch_IoU[0]:.4f}')
        print(
            f'Validation human IoU for Epoch:'
            f' {valid_epoch_IoU[1]:.4f}')
        # The loss_rgb of one epoch
        valid_epoch_loss = valid_loss / (i + 1)
        print(f'Average Validation Loss for Epoch: '
              f'{valid_epoch_loss:.4f}')

        return valid_epoch_loss, valid_epoch_IoU

# def train_fcn(train_dataset, train_loader, model, criterion, optimizer,
# 		  epoch, lr):
# 	'''
# 	The training of one epoch
# 	'''
# 	model.train()
# 	print('Epoch: {:.0f}, LR: {:.6f}'.format(epoch, lr))
# 	print('Training...')
# 	train_loss = 0.0
# 	overlap_cum, pred_cum, label_cum, union_cum = 0, 0, 0, 0
# 	batches_amount = int(len(train_dataset) / configs.BATCH_SIZE)
# 	progress_bar = tqdm(train_loader, total=batches_amount)
# 	count = 0
# 	for _, batch in enumerate(progress_bar):
# 		count += 1
# 		batch['rgb'] = batch['rgb'].to(device, non_blocking=True)
# 		batch['lidar'] = batch['lidar'].to(device,
# 										   non_blocking=True)
# 		batch['annotation'] = \
# 			batch['annotation'].to(device,
# 								   non_blocking=True).squeeze(1)
#
# 		optimizer.zero_grad()
# 		outputs = model(batch['rgb'], batch['lidar'], 'all')
#
# 		output = outputs[args.model]
# 		annotation = batch['annotation']
# 		batch_overlap, batch_pred, batch_label, batch_union = \
# 			find_overlap(output, annotation)
#
# 		overlap_cum += batch_overlap
# 		pred_cum += batch_pred
# 		label_cum += batch_label
# 		union_cum += batch_union
#
# 		loss_rgb = criterion(outputs['rgb'], batch['annotation'])
# 		loss_lidar = criterion(outputs['lidar'],
# 							   batch['annotation'])
# 		loss_fusion = criterion(outputs['fusion'],
# 								batch['annotation'])
# 		loss = loss_rgb + loss_lidar + loss_fusion
#
# 		if args.model == 'rgb':
# 			train_loss += loss_rgb.item()
# 			loss_rgb.backward()
# 			optimizer.step()
# 			progress_bar.set_description(
# 				f'train rgb loss:{loss_rgb:.4f}')
#
# 		elif args.model == 'lidar':
# 			train_loss += loss_lidar.item()
# 			loss_lidar.backward()
# 			optimizer.step()
# 			progress_bar.set_description(
# 				f'train lidar loss:{loss_lidar:.4f}')
#
# 		elif args.model == 'fusion':
# 			train_loss += loss.item()
# 			loss.backward()
# 			optimizer.step()
# 			progress_bar.set_description(
# 				f'train fusion loss:{loss:.4f}')
# 	# The IoU of one epoch
# 	train_epoch_IoU = overlap_cum / union_cum
# 	print(
# 		f'Training IoU of vehicles for Epoch: {train_epoch_IoU[0]:.4f}')
# 	print(
# 		f'Training IoU of human for Epoch: {train_epoch_IoU[1]:.4f}')
# 	# The loss_rgb of one epoch
# 	train_epoch_loss = train_loss / count
# 	print(
# 		f'Average Training Loss for Epoch: {train_epoch_loss:.4f}')
#
# 	return train_epoch_loss, train_epoch_IoU

# def validate_fcn(valid_dataset, valid_loader, model, criterion, epoch):
# 	'''
# 		The validation of one epoch
# 		'''
# 	model.eval()
# 	print('Validating...')
# 	valid_loss = 0.0
# 	overlap_cum, pred_cum, label_cum, union_cum = 0, 0, 0, 0
# 	with torch.no_grad():
# 		batches_amount = int(len(valid_dataset) / configs.BATCH_SIZE)
# 		progress_bar = tqdm(valid_loader, total=batches_amount)
# 		count = 0
# 		for _, batch in enumerate(progress_bar):
# 			count += 1
# 			batch['rgb'] = batch['rgb'].to(device, non_blocking=True)
# 			batch['lidar'] = batch['lidar'].to(device,
# 											   non_blocking=True)
# 			batch['annotation'] = \
# 				batch['annotation'].to(device,
# 									   non_blocking=True).squeeze(1)
#
# 			outputs = model(batch['rgb'], batch['lidar'], 'all')
#
# 			output = outputs[args.model]
# 			annotation = batch['annotation']
# 			batch_overlap, batch_pred, batch_label, batch_union = \
# 				find_overlap(output, annotation)
#
# 			overlap_cum += batch_overlap
# 			pred_cum += batch_pred
# 			label_cum += batch_label
# 			union_cum += batch_union
#
# 			loss_rgb = criterion(outputs['rgb'], batch['annotation'])
# 			loss_lidar = criterion(outputs['lidar'],
# 								   batch['annotation'])
# 			loss_fusion = criterion(outputs['fusion'],
# 									batch['annotation'])
# 			loss = loss_rgb + loss_lidar + loss_fusion
#
# 			if args.model == 'rgb':
# 				valid_loss += loss_rgb.item()
# 				progress_bar.set_description(
# 					f'valid rgb loss:{loss_rgb:.4f}')
#
# 			elif args.model == 'lidar':
# 				valid_loss += loss_lidar.item()
# 				progress_bar.set_description(
# 					f'valid lidar loss:{loss_lidar:.4f}')
#
# 			elif args.model == 'fusion':
# 				valid_loss += loss.item()
# 				progress_bar.set_description(
# 					f'valid fusion loss:{loss:.4f}')
# 	# The IoU of one epoch
# 	valid_epoch_IoU = overlap_cum / union_cum
# 	print(
# 		f'Validatoin IoU of vehicles for Epoch: {valid_epoch_IoU[0]:.4f}')
# 	print(
# 		f'Validatoin IoU of human for Epoch: {valid_epoch_IoU[1]:.4f}')
# 	# The loss_rgb of one epoch
# 	valid_epoch_loss = valid_loss / count
# 	print(f'Average Validation Loss for Epoch: {valid_epoch_loss:.4f}')
#
# 	return valid_epoch_loss, valid_epoch_IoU
