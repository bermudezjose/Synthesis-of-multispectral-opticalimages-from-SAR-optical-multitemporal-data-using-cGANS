from __future__ import division
import os
import time
import glob
import tensorflow as tf
import numpy as np
from six.moves import xrange
from sklearn import preprocessing as pre
import scipy.io as io
import matplotlib.pyplot as plt

from ops import *
from utils import *
from saveweigths import *

class pix2pix(object):
    def __init__(self, sess, image_size=256, load_size=286,
                 batch_size=1, sample_size=1, output_size=256,
                 gf_dim=64, df_dim=64, L1_lambda=100,
                 input_c_dim=11, output_c_dim=7, dataset_name='facades',
                 checkpoint_dir=None, sample_dir=None):
        """

        Args:
            sess: TensorFlow session
            batch_size: The size of batch. Should be specified before training.
            output_size: (optional) The resolution in pixels of the images. [256]
            gf_dim: (optional) Dimension of gen filters in first conv layer. [64]
            df_dim: (optional) Dimension of discrim filters in first conv layer. [64]
            input_c_dim: (optional) Dimension of input image color. For grayscale input, set to 1. [3]
            output_c_dim: (optional) Dimension of output image color. For grayscale input, set to 1. [3]
        """
        self.sess = sess
        self.is_grayscale = (input_c_dim == 1)
        self.batch_size = batch_size
        self.image_size = image_size
        self.sample_size = sample_size
        self.output_size = output_size
        self.load_size = load_size
        self.fine_size = image_size
        self.sar_root_patch = '/mnt/Data/DataBases/RS/SAR/Campo Verde/npy_format/'
        self.opt_root_patch = '/mnt/Data/DataBases/RS/SAR/Campo Verde/LANDSAT/'
        self.sar_name = '14_31Jul_2016.npy'

        self.gf_dim = gf_dim
        self.df_dim = df_dim

        self.input_c_dim = input_c_dim
        self.output_c_dim = output_c_dim

        self.L1_lambda = L1_lambda

        self.d_bnr = batch_norm(name='d_bnr')
        # batch normalization : deals with poor initialization helps gradient flow
        self.d_bn1 = batch_norm(name='d_bn1')
        self.d_bn2 = batch_norm(name='d_bn2')
        self.d_bn3 = batch_norm(name='d_bn3')

        self.g_bn_er = batch_norm(name='g_bn_er')
        self.g_bn_e2 = batch_norm(name='g_bn_e2')
        self.g_bn_e3 = batch_norm(name='g_bn_e3')
        self.g_bn_e4 = batch_norm(name='g_bn_e4')
        self.g_bn_e5 = batch_norm(name='g_bn_e5')
        self.g_bn_e6 = batch_norm(name='g_bn_e6')
        self.g_bn_e7 = batch_norm(name='g_bn_e7')
        self.g_bn_e8 = batch_norm(name='g_bn_e8')

        self.g_bn_d1 = batch_norm(name='g_bn_d1')
        self.g_bn_d2 = batch_norm(name='g_bn_d2')
        self.g_bn_d3 = batch_norm(name='g_bn_d3')
        self.g_bn_d4 = batch_norm(name='g_bn_d4')
        self.g_bn_d5 = batch_norm(name='g_bn_d5')
        self.g_bn_d6 = batch_norm(name='g_bn_d6')
        self.g_bn_d7 = batch_norm(name='g_bn_d7')

        self.dataset_name = dataset_name
        self.checkpoint_dir = checkpoint_dir
        self.build_model()

    def build_model(self):
        self.bands_sar = 2
        self.sar_t0 = tf.placeholder(tf.float32,
                                    [self.batch_size, 3*self.image_size, 3*self.image_size, self.bands_sar],
                                    name='sar_t0')
        self.opt_t0 = tf.placeholder(tf.float32,
                                    [self.batch_size, self.image_size, self.image_size, self.output_c_dim],
                                    name='opt_t0')
        self.sar_t1 = tf.placeholder(tf.float32,
                                    [self.batch_size, 3*self.image_size, 3*self.image_size, self.bands_sar],
                                    name='sar_t1')
        self.opt_t1 = tf.placeholder(tf.float32,
                                    [self.batch_size, self.image_size, self.image_size, self.output_c_dim],
                                    name='opt_t1')
        ################################ Original Multitemporal ################################################
        self.SAR = tf.concat([self.sar_t0, self.sar_t1], 3)
        self.OPT = tf.concat([self.opt_t0, self.opt_t1], 3)
        #########################################################################################################

        self.fake_opt_t0 = self.generator(self.SAR, self.opt_t1)
        self.OPT_fake = tf.concat([self.fake_opt_t0, self.opt_t1], 3)

        self.D, self.D_logits = self.discriminator(self.SAR, self.OPT, reuse=False)
        self.D_, self.D_logits_ = self.discriminator(self.SAR, self.OPT_fake, reuse=True)

        self.fake_B_sample = self.sampler(self.SAR, self.opt_t1)

        self.d_sum = tf.summary.histogram("d", self.D)
        self.d__sum = tf.summary.histogram("d_", self.D_)
#        self.fake_B_sum = tf.summary.image("fake_B", self.fake_B)

        self.d_loss_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits, labels=tf.ones_like(self.D)))
        self.d_loss_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.zeros_like(self.D_)))
        self.g_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_, labels=tf.ones_like(self.D_))) \
                        + self.L1_lambda * tf.reduce_mean(tf.abs(self.opt_t0 - self.fake_opt_t0))

        self.d_loss_real_sum = tf.summary.scalar("d_loss_real", self.d_loss_real)
        self.d_loss_fake_sum = tf.summary.scalar("d_loss_fake", self.d_loss_fake)

        self.d_loss = self.d_loss_real + self.d_loss_fake

        self.g_loss_sum = tf.summary.scalar("g_loss", self.g_loss)
        self.d_loss_sum = tf.summary.scalar("d_loss", self.d_loss)

        t_vars = tf.trainable_variables()

        self.d_vars = [var for var in t_vars if 'd_' in var.name]
        self.g_vars = [var for var in t_vars if 'g_' in var.name]

        self.saver = tf.train.Saver()


#    def load_random_samples(self):
#        data = np.random.choice(glob('./datasets/{}/val/*.jpg'.format(self.dataset_name)), self.batch_size)
#        sample = [load_data(sample_file) for sample_file in data]
#
#        if (self.is_grayscale):
#            sample_images = np.array(sample).astype(np.float32)[:, :, :, None]
#        else:
#            sample_images = np.array(sample).astype(np.float32)
#        return sample_images

#    def sample_model(self, sample_dir, epoch, idx):
#        sample_images = self.load_random_samples()
#        samples, d_loss, g_loss = self.sess.run(
#            [self.fake_B_sample, self.d_loss, self.g_loss],
#            feed_dict={self.real_data: sample_images}
#        )
#        save_images(samples, [self.batch_size, 1],
#                    './{}/train_{:02d}_{:04d}.png'.format(sample_dir, epoch, idx))
#        print("[Sample] d_loss: {:.8f}, g_loss: {:.8f}".format(d_loss, g_loss))

    def train(self, args):
        """Train pix2pix"""
        d_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
                          .minimize(self.d_loss, var_list=self.d_vars)
        g_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
                          .minimize(self.g_loss, var_list=self.g_vars)

        init_op = tf.global_variables_initializer()
        self.sess.run(init_op)

#        self.g_sum = tf.summary.merge([self.d__sum,
#            self.fake_B_sum, self.d_loss_fake_sum, self.g_loss_sum])
#        self.d_sum = tf.summary.merge([self.d_sum, self.d_loss_real_sum, self.d_loss_sum])
        self.writer = tf.summary.FileWriter("./logs", self.sess.graph)

        counter = 0
        start_time = time.time()

        if self.load(self.checkpoint_dir):
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")


        sample_dir_root = self.checkpoint_dir
        model_dir = "%s_%s_%s" % (self.dataset_name, self.batch_size, self.output_size)
        sample_dir_root = os.path.join(self.checkpoint_dir, model_dir)
        sample_dir = os.path.join(sample_dir_root, 'samples')
        # sample_dir = sample_dir + 'samples/'
        if not os.path.exists(sample_dir):
            os.makedirs(sample_dir)

        # data_list = glob.glob('../Campo_Verde/Training/*.npy')
        data_list_trn = glob.glob('../datasets/Campo_Verde_Crops/Training/*.npy')
        data_list_tst = glob.glob('../datasets/Campo_Verde_Crops/Testing/*.npy')
        save_samples_multiresolution(self, data_list_tst, output_path=sample_dir, idx=6, epoch=0, multitemporal=True)

        for epoch in xrange(counter, args.epoch):
            # data_original = glob.glob('/mnt/Data/Pix2Pix_datasets/Campo_Verde/Training/*.npy')
            # data_fliped = glob.glob('/mnt/Data/Pix2Pix_datasets/Campo_Verde/Training_flip/*.npy')
            # data = data_original + data_fliped
            data_original = glob.glob('../datasets/Campo_Verde_Crops/Training/*.npy')
            # data_fliped = glob.glob('/mnt/Data/Pix2Pix_datasets/Campo_Verde/Training_flip/*.npy')
            data = data_original
            np.random.shuffle(data)
            batch_idxs = min(len(data), args.train_size) // self.batch_size
            for idx in xrange(0, batch_idxs):
                batch_images = load_data_Dic_Multiresolution(samples_list=data,
                                                             idxc=idx,
                                                             load_size=self.load_size,
                                                             fine_size=self.fine_size,
                                                             random_transformation=True,
                                                             multitemporal=True)
                sar_t0 = batch_images[0].reshape(self.batch_size, 3*self.image_size, 3*self.image_size, -1)
                opt_t0 = batch_images[1].reshape(self.batch_size, self.image_size, self.image_size, -1)
                sar_t1 = batch_images[2].reshape(self.batch_size, 3*self.image_size, 3*self.image_size, -1)
                opt_t1 = batch_images[3].reshape(self.batch_size, self.image_size, self.image_size, -1)
                # Update D network
                _, summary_str = self.sess.run([d_optim, self.d_sum],
                                               feed_dict={self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
                self.writer.add_summary(summary_str, epoch)

                # Update G network
                _ = self.sess.run([g_optim],
                                     feed_dict={self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
#                self.writer.add_summary(summary_str, counter)

                # Run g_optim twice to make sure that d_loss does not go to zero (different from paper)
                _ = self.sess.run([g_optim],
                                  feed_dict={self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
#                self.writer.add_summary(summary_str, counter)

                if np.mod(idx + 1, 100) == 0:
                    errD_fake = self.d_loss_fake.eval({self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
                    errD_real = self.d_loss_real.eval({self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
                    errG = self.g_loss.eval({self.sar_t0: sar_t0, self.opt_t0: opt_t0, self.sar_t1: sar_t1, self.opt_t1: opt_t1})
                    print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss: %.8f, g_loss: %.8f" \
                        % (epoch, idx, batch_idxs,
                            time.time() - start_time, errD_fake+errD_real, errG))

            self.save(args.checkpoint_dir, epoch)
            # save sample
            save_samples_multiresolution(self, data_list_tst, output_path=sample_dir, idx=6, epoch=epoch, multitemporal=True)


    def discriminator(self, img_A, img_B, y=None, reuse=False):

        with tf.variable_scope("discriminator") as scope:

            # image is 256 x 256 x (input_c_dim + output_c_dim)
            if reuse:
                tf.get_variable_scope().reuse_variables()
            else:
                assert tf.get_variable_scope().reuse == False
            # tf.tanh
            # print(img_A.get_shape()[-1])
            img_A_R = tf.tanh(conv2d(img_A, img_A.get_shape()[-1], d_h=3, d_w=3, name='d_hr_conv'))
            image = tf.concat([img_A_R, img_B], 3)

            h0 = lrelu(conv2d(image, self.df_dim, name='d_h0_conv'))
            # h0 is (128 x 128 x self.df_dim)
            h1 = lrelu(self.d_bn1(conv2d(h0, self.df_dim*2, name='d_h1_conv')))
            # h1 is (64 x 64 x self.df_dim*2)
            h2 = lrelu(self.d_bn2(conv2d(h1, self.df_dim*4, name='d_h2_conv')))
            # h2 is (32x 32 x self.df_dim*4)
            h3 = lrelu(self.d_bn3(conv2d(h2, self.df_dim*8, d_h=1, d_w=1, name='d_h3_conv')))
            # h3 is (16 x 16 x self.df_dim*8)
            h4 = linear(tf.reshape(h3, [self.batch_size, -1]), 1, 'd_h3_lin')

            return tf.nn.sigmoid(h4), h4

    def generator(self, img_A, img_B=None, y=None):
        with tf.variable_scope("generator") as scope:

            s = self.output_size
            s2, s4, s8, s16, s32, s64, s128 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128)

            img_A_R = tf.tanh(conv2d(img_A, img_A.get_shape()[-1], d_h=3, d_w=3, name='g_er_conv'))
            image = tf.concat([img_A_R, img_B], 3)

            # image is (256 x 256 x input_c_dim)
            e1 = conv2d(image, self.gf_dim, name='g_e1_conv') # 64x2x5x5+64 = 3,264
            # e1 is (128 x 128 x self.gf_dim)
            e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv')) # (2x64)x64x5x5 + (2x64) = 204,928
            # e2 is (64 x 64 x self.gf_dim*2)
            e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv')) # (4x64)x(2x64)x5x5 + (4x64) = 819,456
            # e3 is (32 x 32 x self.gf_dim*4)
            e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv')) # (8x64)x(4x64)x5x5 + (8x64) = 3,277,312
            # e4 is (16 x 16 x self.gf_dim*8)
            e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv')) # (8x64)x(8x64)x5x5 + (8x64) = 6,554,112
            # e5 is (8 x 8 x self.gf_dim*8)
            e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv')) # (8x64)x(8x64)x5x5 + (8x64) = 6,554,112
            # e6 is (4 x 4 x self.gf_dim*8)
            e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv')) # (8x64)x(8x64)x5x5 + (8x64) = 6,554,112
            # e7 is (2 x 2 x self.gf_dim*8)
            e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv')) # (8x64)x(8x64)x5x5 + (8x64) = 6,554,112
            # e8 is (1 x 1 x self.gf_dim*8)

            self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
                [self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True) # (8x64)x(8x64)x5x5 + (8x64) = 6,554,112
            d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
            d1 = tf.concat([d1, e7], 3)
            # d1 is (2 x 2 x self.gf_dim*8*2)

            self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
                [self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True) # (2*8x64)x(8x64)x5x5 + (2*8x64) = 13,108,224
            d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
            d2 = tf.concat([d2, e6], 3)
            # d2 is (4 x 4 x self.gf_dim*8*2)

            self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
                [self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True) # (2*8x64)x(8x64)x5x5 + (2*8x64) = 13,108,224
            d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
            d3 = tf.concat([d3, e5], 3)
            # d3 is (8 x 8 x self.gf_dim*8*2)

            self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
                [self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True) # (2*8x64)x(8x64)x5x5 + (2*8x64) = 13,108,224
            d4 = self.g_bn_d4(self.d4)
            d4 = tf.concat([d4, e4], 3)
            # d4 is (16 x 16 x self.gf_dim*8*2)

            self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
                [self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True) # (2*4x64)x(8x64)x5x5 + (2*4x64) = 6,554,112
            d5 = self.g_bn_d5(self.d5)
            d5 = tf.concat([d5, e3], 3)
            # d5 is (32 x 32 x self.gf_dim*4*2)

            self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
                [self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True) # (2*2x64)x(4x64)x5x5 + (2*2x64) = 1,638,656
            d6 = self.g_bn_d6(self.d6)
            d6 = tf.concat([d6, e2], 3)
            # d6 is (64 x 64 x self.gf_dim*2*2)

            self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
                [self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True) # (2*1x64)x(2x64)x5x5 + (2*1x64) = 409,728
            d7 = self.g_bn_d7(self.d7)
            d7 = tf.concat([d7, e1], 3)
            # d7 is (128 x 128 x self.gf_dim*1*2)

            self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
                [self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True) # (1*1x64)x(1x7)x5x5 + (1*1x7) = 11,207
            # d8 is (256 x 256 x output_c_dim)

            return tf.nn.tanh(self.d8)

    def sampler(self, img_A, img_B=None, y=None):

        with tf.variable_scope("generator") as scope:
            scope.reuse_variables()

            s = self.output_size
            s2, s4, s8, s16, s32, s64, s128 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128)

            img_A_R = tf.tanh(conv2d(img_A, img_A.get_shape()[-1], d_h=3, d_w=3, name='g_er_conv'))
            image = tf.concat([img_A_R, img_B], 3)

            # image is (256 x 256 x input_c_dim)
            e1 = conv2d(image, self.gf_dim, name='g_e1_conv')
            # e1 is (128 x 128 x self.gf_dim)
            e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv'))
            # e2 is (64 x 64 x self.gf_dim*2)
            e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv'))
            # e3 is (32 x 32 x self.gf_dim*4)
            e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv'))
            # e4 is (16 x 16 x self.gf_dim*8)
            e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv'))
            # e5 is (8 x 8 x self.gf_dim*8)
            e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv'))
            # e6 is (4 x 4 x self.gf_dim*8)
            e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv'))
            # e7 is (2 x 2 x self.gf_dim*8)
            e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv'))
            # e8 is (1 x 1 x self.gf_dim*8)

            self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
                [self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
            d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
            d1 = tf.concat([d1, e7], 3)
            # d1 is (2 x 2 x self.gf_dim*8*2)

            self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
                [self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True)
            d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
            d2 = tf.concat([d2, e6], 3)
            # d2 is (4 x 4 x self.gf_dim*8*2)

            self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
                [self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True)
            d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
            d3 = tf.concat([d3, e5], 3)
            # d3 is (8 x 8 x self.gf_dim*8*2)

            self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
                [self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True)
            d4 = self.g_bn_d4(self.d4)
            d4 = tf.concat([d4, e4], 3)
            # d4 is (16 x 16 x self.gf_dim*8*2)

            self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
                [self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True)
            d5 = self.g_bn_d5(self.d5)
            d5 = tf.concat([d5, e3], 3)
            # d5 is (32 x 32 x self.gf_dim*4*2)

            self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
                [self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True)
            d6 = self.g_bn_d6(self.d6)
            d6 = tf.concat([d6, e2], 3)
            # d6 is (64 x 64 x self.gf_dim*2*2)

            self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
                [self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True)
            d7 = self.g_bn_d7(self.d7)
            d7 = tf.concat([d7, e1], 3)
            # d7 is (128 x 128 x self.gf_dim*1*2)

            self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
                [self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True)
            # d8 is (256 x 256 x output_c_dim)

            return tf.nn.tanh(self.d8)

    def save(self, checkpoint_dir, step):
        model_name = "pix2pix.model"
        model_dir = "%s_%s_%s" % (self.dataset_name, self.batch_size, self.output_size)
        checkpoint_dir = os.path.join(checkpoint_dir, model_dir)

        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

        self.saver.save(self.sess,
                        os.path.join(checkpoint_dir, model_name),
                        global_step=step)
        print "Saving checkpoint!"
#        self.saver.save(self.sess, checkpoint_dir +'/my-model')
#        self.saver.export_meta_graph(filename=checkpoint_dir +'/my-model.meta')

    def load(self, checkpoint_dir):
#        return False
        print(" [*] Reading checkpoint...")
#
        model_dir = "%s_%s_%s" % (self.dataset_name, self.batch_size, self.output_size)
        checkpoint_dir = os.path.join(checkpoint_dir, model_dir)
        print(checkpoint_dir)
#2832, 2665,
#        new_placeholder = tf.placeholder(tf.float32, shape=[self.batch_size, 2831, 2665,
#                                         self.input_c_dim + self.output_c_dim], name='inputs_new_name')
#        self.saver = tf.train.import_meta_graph(checkpoint_dir +'/my-model.meta', input_map={"real_A_and_B_images:0": new_placeholder})
##        self.saver = tf.train.import_meta_graph(checkpoint_dir +'/my-model.meta')
#        self.saver.restore(self.sess, checkpoint_dir +'/my-model')
#
        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
#            self.saver.export_meta_graph(filename='my-model.meta')
#            print 'model convertion success'
#            self.saver = tf.import_graph_def(os.path.join(checkpoint_dir, ckpt_name), input_map={"real_A_and_B_images:0": new_placeholder})
            return True
        else:
            return False

    def test(self, args):
        """Test pix2pix"""
        init_op = tf.global_variables_initializer()
        self.sess.run(init_op)

        sample_files = sorted(glob.glob('/home/jose/Templates/Pix2Pix/pix2pix-tensorflow_jose/datasets/'+self.dataset_name+'/test/*.npy'))

        # change this directoty

        # sort testing input
        n = [int(i) for i in map(lambda x: x.split('/')[-1].split('.npy')[0], sample_files)]
        sample_files = [x for (y, x) in sorted(zip(n, sample_files))]


        # load testing input
        print("Loading testing images ...")
        sample_images = [load_data(sample_file, is_test=True) for sample_file in sample_files]

#        if (self.is_grayscale):
#            sample_images = np.array(sample).astype(np.float32)[:, :, :, None]
#        else:
#            sample_images = np.array(sample).astype(np.float32)

        sample_images = [sample_images[i:i+self.batch_size]
                         for i in xrange(0, len(sample_images), self.batch_size)]
        sample_images = np.array(sample_images)
        print(sample_images.shape)

        start_time = time.time()
        if self.load(self.checkpoint_dir):
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        for i, sample_image in enumerate(sample_images):
            idx = i+1
            print("sampling image ", idx)
            samples = self.sess.run(
                self.fake_B_sample,
                feed_dict={self.real_data: sample_image}
            )
            print samples.shape
            output_folder = '/home/jose/Templates/'
            np.save(output_folder+str(i), samples.reshape(256, 256, 7))
#            save_images(samples, [self.batch_size, 1],
#                        './{}/test_{:04d}.png'.format(args.test_dir, idx))
    def generate_image(self, args):

        output_folder = '/home/jose/Templates/Pix2Pix/pix2pix-tensorflow_jose/'
        init_op = tf.global_variables_initializer()
        self.sess.run(init_op)
        print(" [*] Load SUCCESS")
        if self.load(self.checkpoint_dir):
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        print 'Case A ...'
        print 'generating image for_' + args.dataset_name

        scalers_root = '/mnt/Data/Pix2Pix_datasets/Campo_Verde/'
        scaler_sar_t0 = joblib.load(scalers_root + "sar_may2016_10m_scaler.pkl")
        scaler_sar_t1 = joblib.load(scalers_root + "sar_may2017_10m_scaler.pkl")
        scaler_opt_t1 = joblib.load(scalers_root + "opt_may2017_scaler.pkl")

        sar_img_name_t0 = '10_08May_2016.npy'
        sar_img_name_t1 = '20170520.npy'
        opt_img_name_t1 = '20170524/'
        sar_path_t0 = self.sar_root_patch + sar_img_name_t0
        sar_path_t1 = self.sar_root_patch + sar_img_name_t1
        opt_path_t1 = self.opt_root_patch + opt_img_name_t1
        
        
        sar_t0 = np.load(sar_path_t0)
        sar_t1 = np.load(sar_path_t1)
        opt_t1, _ = load_landsat(opt_path_t1)
        sar_t0[sar_t0 > 1.0] = 1.0
        sar_t1[sar_t1 > 1.0] = 1.0
        opt_t1[np.isnan(opt_t1)] = 0.0
        num_rows, num_cols, bands = sar_t0.shape
        sar_t0 = sar_t0.reshape(num_rows * num_cols, bands)
        sar_t1 = sar_t1.reshape(num_rows * num_cols, bands)
        opt_t1 = opt_t1.reshape((num_rows+1)//3 * num_cols//3, -1)
        sar_t0 = np.float32(scaler_sar_t0.transform(sar_t0))
        sar_t1 = np.float32(scaler_sar_t1.transform(sar_t1))
        opt_t1 = np.float32(scaler_opt_t1.transform(opt_t1))
        sar_t0 = sar_t0.reshape(1, num_rows, num_cols, bands)
        sar_t1 = sar_t1.reshape(1, num_rows, num_cols, bands)
        opt_t1 = opt_t1.reshape(1, (num_rows+1)//3, num_cols//3, -1)

        fake_opt = np.zeros(((num_rows+1)//3, num_cols//3, self.output_c_dim),
                            dtype='float32')

        # s = 64
        # stride = self.image_size-2*s
        # for row in range(0, num_rows, stride):
        #     for col in range(0, num_cols, stride):
        #         if (row+self.image_size <= num_rows) and (col+self.image_size <= num_cols):

        #             print row + s, row + self.image_size - s
        #             sample_image = img_A[:, row:row+self.image_size, col:col+self.image_size]
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.real_A: sample_image}
        #                                    )
        #             print sample.shape
        #             fake_opt[row+s:row+self.image_size-s, col+s:col+self.image_size-s] = sample[0, s:self.image_size-s, s:self.image_size-s]
        #         elif col+self.image_size <= num_cols:
        #             sample_image = img_A[:, num_rows-self.image_size:num_rows, col:col+self.image_size]
        #             print(sample_image.shape)
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.real_A: sample_image}
        #                                    )
        #             print sample.shape
        #             fake_opt[row+s:num_rows, col+s:col+self.image_size-s] = sample[0, self.image_size-num_rows+row+s:self.image_size, s:self.image_size-s]
        #         elif row+self.image_size <= num_rows:
        #             print col
        #             sample_image = img_A[:, row:row+self.image_size, num_cols-self.image_size:num_cols]
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.real_A: sample_image}
        #                                    )
        #             fake_opt[row+s:row+self.image_size-s, col+s:num_cols] = sample[0, s:self.image_size-s, self.image_size-num_cols+col+s:self.image_size]

        # np.save(self.dataset_name + '_fake_opt', fake_opt)

        stride = 64
        pad = (self.image_size - stride) // 2
        for row in range(0, num_rows, 3*stride):
            for col in range(0, num_cols, 3*stride):
                if (row + 3*self.image_size <= num_rows) and (col+3*self.image_size <= num_cols):

                    print row//3 + pad, col//3 + pad
                    sars_t0 = sar_t0[:, row:row+3*self.image_size, col:col+3*self.image_size]
                    sars_t1 = sar_t1[:, row:row+3*self.image_size, col:col+3*self.image_size]
                    opts_t1 = opt_t1[:, row//3:row//3+self.image_size, col//3:col//3+self.image_size]
                    sample = self.sess.run(self.fake_B_sample,
                                           feed_dict={self.sar_t0: sars_t0, self.sar_t1: sars_t1, self.opt_t1: opts_t1})
                    print sample.shape
                    fake_opt[row//3+pad:row//3+self.image_size-pad, col//3+pad:col//3+self.image_size-pad] = sample[0, pad:self.image_size-pad, pad:self.image_size-pad]
                elif col+3*self.image_size <= num_cols:
                    sars_t0 = sar_t0[:, num_rows-3*self.image_size:num_rows, col:col+3*self.image_size]
                    sars_t1 = sar_t1[:, num_rows-3*self.image_size:num_rows, col:col+3*self.image_size]
                    opts_t1 = opt_t1[:, num_rows//3-self.image_size:num_rows//3, col//3:col//3+self.image_size]
                    sample = self.sess.run(self.fake_B_sample,
                                           feed_dict={self.sar_t0: sars_t0, self.sar_t1: sars_t1, self.opt_t1: opts_t1})
                    print sample.shape
                    fake_opt[row//3+pad:num_rows//3, col//3+pad:col//3+self.image_size-pad] = sample[0, self.image_size-num_rows//3+row//3+pad:self.image_size, pad:self.image_size-pad]
                elif row+3*self.image_size <= num_rows:
                    print col
                    sars_t0 = sar_t0[:, row:row+3*self.image_size, num_cols-3*self.image_size:num_cols]
                    sars_t1 = sar_t1[:, row:row+3*self.image_size, num_cols-3*self.image_size:num_cols]
                    opts_t1 = opt_t1[:, row//3:row//3+self.image_size, num_cols//3-self.image_size:num_cols//3]
                    sample = self.sess.run(self.fake_B_sample,
                                           feed_dict={self.sar_t0: sars_t0, self.sar_t1: sars_t1, self.opt_t1: opts_t1})
                    fake_opt[row//3+pad:row//3+self.image_size-pad, col//3+pad:num_cols//3] = sample[0, pad:self.image_size-pad, self.image_size-num_cols//3+col//3+pad:self.image_size]

        np.save(self.dataset_name + '_synthesized', fake_opt)

        # output_folder = '/home/jose/Templates/Pix2Pix/pix2pix-tensorflow_jose/'
        # init_op = tf.global_variables_initializer()
        # self.sess.run(init_op)
        # print(" [*] Load SUCCESS")
        # if self.load(self.checkpoint_dir):
        #     print(" [*] Load SUCCESS")
        # else:
        #     print(" [!] Load failed...")
        # # if args.experiment_type is 'case_A':
        # # sar_t0: scaler_name='sar_may2016_scaler.pkl'
        # # opt_t0: scaler_name='opt_may2016_scaler.pkl'
        # # sar_t1: scaler_name='sar_may2017_scaler.pkl'
        # # opt_t1: scaler_name='opt_may2017_scaler.pkl'
        # # img_A = np.concatenate((sar_t0, sar_t1, opt_t1), axis=2)
        # scaler_sar_t0 = joblib.load("sar_may2016_10m_scaler.pkl")
        # scaler_sar_t1 = joblib.load("sar_may2017_10m_scaler.pkl")
        # scaler_opt_t1 = joblib.load("opt_may2017_scaler.pkl")
        # print 'Case A ...'
        # print 'generating image for_' + args.dataset_name
        # sar_img_name_t0 = '10_08May_2016.npy'
        # sar_img_name_t1 = '20170520.npy'
        # sar_path_t0=self.sar_root_patch + sar_img_name_t0
        # sar_path_t1=self.sar_root_patch + sar_img_name_t1
        # sar_t0 = np.load(sar_path_t0)
        # sar_t1 = np.load(sar_path_t1)
        # # sar_t0 = resampler(sar_t0, 'float32')
        # # sar_t1 = resampler(sar_t1, 'float32')
        # sar_t0[sar_t0 > 1.0] = 1.0
        # sar_t1[sar_t1 > 1.0] = 1.0

        # mask_sar = sar_t0[:, :, 0].copy()
        # mask_sar[sar_t0[:, :, 0] < 1] = 1
        # mask_sar[sar_t0[:, :, 0] == 1] = 0

        # mask = load_mask()
        # mask_gan = np.load('mask_gan_original.npy')
        # mask_gan[mask == 0] = 0
        # mask_gan[mask_gan != 0] = 2
        # mask_gan[(mask != 0) * (mask_gan == 0)] = 1

        # mask_gans_trn = mask_gan * mask_sar

        # plt.figure()
        # plt.imshow(mask_gans_trn)
        # plt.show(block=False)
 
        # num_rows_sar, num_cols_sar, num_bands_sar = sar_t0.shape
        # print('sar_t0.shape --->', sar_t0.shape)
        # # sar_t0 = sar_t0.reshape(num_rows_sar * num_cols_sar, num_bands_sar)
        # # sar_t1 = sar_t1.reshape(num_rows_sar * num_cols_sar, num_bands_sar)
        # sar_t0 = np.float32(minmaxnormalization(sar_t0, mask_sar))
        # sar_t1 = np.float32(minmaxnormalization(sar_t1, mask_sar))
        # # sar_t0 = np.float32(sar_t0.reshape(num_rows_sar, num_cols_sar, num_bands_sar))
        # # sar_t1 = np.float32(sar_t1.reshape(num_rows_sar, num_cols_sar, num_bands_sar))
        # SAR = np.concatenate((sar_t0, sar_t1), axis=2)
        # SAR = SAR.reshape(1, num_rows_sar, num_cols_sar, 2*num_bands_sar)


        # opt_name_t1 = '20170524/'
        # opt_path_t1=self.opt_root_patch + opt_name_t1
        # opt_t1, _ = load_landsat(opt_path_t1)
        # opt_t1[np.isnan(opt_t1)] = 0.0
        # print("opt_t1 -->", opt_t1.shape)
        # mask_gans_trn_opt = resampler(mask_gans_trn, 'uint8')
        # num_rows_opt, num_cols_opt, num_bands_opt = opt_t1.shape
        # # opt_t1 = opt_t1.reshape(num_rows_opt * num_cols_opt, self.output_c_dim)
        # opt_t1 = np.float32(minmaxnormalization(opt_t1, mask_gans_trn_opt))
        # # opt_t1 = opt_t1.reshape(num_rows_opt, num_cols_opt, self.output_c_dim)
        # opt_t0 = np.zeros_like(opt_t1)
        # OPT = np.concatenate((opt_t1, opt_t0), axis=2)
        # OPT = OPT.reshape(1, num_rows_opt, num_cols_opt, 2*self.output_c_dim)
        # fake_opt = np.zeros((num_rows_opt, num_cols_opt, self.output_c_dim),
        #                     dtype='float32')

        # # sars = batch_images[id_batch][0].reshape(self.batch_size, 3*self.image_size, 3*self.image_size, -1)
        # #         opts = batch_images[id_batch][1].reshape(self.batch_size, self.image_size, self.image_size, -1)
        # #         # Update D network
        # #         _, summary_str = self.sess.run([d_optim, self.d_sum],
        # #                                        feed_dict={self.sar: sars, self.opt: opts})
        
        # s = 3 * 64
        # stride = 3 * self.image_size - 2 * s
        # for row in range(0, num_rows_sar, stride):
        #     for col in range(0, num_cols_sar, stride):
        #         if (row + 3*self.image_size <= num_rows_sar) and (col+3*self.image_size <= num_cols_sar):

        #             print row + s, row + 3*self.image_size - s
        #             sars = SAR[:, row:row+3*self.image_size, col:col+3*self.image_size]
        #             opts = OPT[:, row//3:row//3+self.image_size, col//3:col//3+self.image_size]
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.sar: sars, self.opt: opts}
        #                                    )
        #             print sample.shape
        #             fake_opt[row//3+s//3:row//3+self.image_size-s//3, col//3+s//3:col//3+self.image_size-s//3] = sample[0, s//3:self.image_size-s//3, s//3:self.image_size-s//3]
        #         elif col+3*self.image_size <= num_cols_sar:
        #             sars = SAR[:, num_rows_sar-3*self.image_size:num_rows_sar, col:col+3*self.image_size]
        #             opts = OPT[:, num_rows_sar//3-self.image_size:num_rows_sar//3, col//3:col//3+self.image_size]
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.sar: sars, self.opt: opts}
        #                                    )
        #             print sample.shape
        #             fake_opt[row//3+s//3:num_rows_sar//3, col//3+s//3:col//3+self.image_size-s//3] = sample[0, self.image_size-num_rows_sar//3+row//3+s//3:self.image_size, s//3:self.image_size-s//3]
        #         elif row+3*self.image_size <= num_rows_sar:
        #             print col
        #             sars = SAR[:, row:row+3*self.image_size, num_cols_sar-3*self.image_size:num_cols_sar]
        #             opts = OPT[:, row//3:row//3+self.image_size, num_cols_sar//3-self.image_size:num_cols_sar//3]
        #             sample = self.sess.run(self.fake_B_sample,
        #                                    feed_dict={self.sar: sars, self.opt: opts}
        #                                    )
        #             fake_opt[row//3+s//3:row//3+self.image_size-s//3, col//3+s//3:num_cols_sar//3] = sample[0, s//3:self.image_size-s//3, self.image_size-num_cols_sar//3+col//3+s//3:self.image_size]

        # np.save(self.dataset_name + '_fake_opt', fake_opt)
#   20151111 -- 02_10Nov_2015 ok !
#   20151127 -- 03_22Nov_2015 too much clouds !
#   20151213 -- 05_16Dec_2015 ummmm, differen protocol ...
#   20160318 -- 09_21Mar_2016 ok !
#   20160505 -- 10_08May_2016 ok !
#   20160708 -- 13_07Jul_2016 ok !
#   20160724 -- 14_31Jul_2016 ok !
#             mask, sar, opt, cloud_mask = load_images(sar_path=self.sar_root_patch + sar_img_name,
#                                                      opt_path=self.opt_root_patch + opt_img_name + '/'
#                                                      )
#             mask_gan_path = '/mnt/Data/DataBases/RS/SAR/Campo Verde/New_Masks/TrainTestMasks/TrainTestMask_GAN.tif'
#             mask_gan = load_tiff_image(mask_gan_path)
#             np.save('mask_gan_original', mask_gan)
# #            mask_gan[mask_gan == 0] = 1
# #            mask_gan[mask_gan != 1] = 0
# #            mask_gan = resampler(mask_gan)
# #            mask = resampler(mask)
# #            sar = resampler(sar)
# #            mask_sar = sar[:, :, 0].copy()
# #            mask_sar[sar[:, :, 0] < 1] = 1
# #            mask_sar[sar[:, :, 0] == 1] = 0
#             sar = resampler(sar, 'float32')
#             sar[sar > 1.0] = 1.0
#             mask_sar = sar[:, :, 0].copy()
#             mask_sar[sar[:, :, 0] < 1] = 1
#             mask_sar[sar[:, :, 0] == 1] = 0
#             mask = resampler(mask, 'uint8')
#             mask_gan = np.load('mask_gan.npy')
#             mask_gan[mask == 0] = 0
#             mask_gan[(mask != 0) * (mask_gan != 1) ] = 2
#             mask_gans_trn = mask_gan + mask_sar
#             mask_gans_trn[mask_gans_trn == 3] = 0
#             mask_gans_trn[mask_gans_trn == 2] = 1
#             np.save(output_folder + 'mask', mask)
#             io.savemat(output_folder + 'mask.mat', {"mask":mask})

#             num_rows, num_cols = mask.shape
# #            mask_gans_trn = mask_4_trn_gans(num_rows, num_cols, args.image_region)
#         #    mask_gans_trn = mask_gans_trn * mask
# #            mask_gans_trn = mask_gan * mask_sar
#             img_source = minmaxnormalization(sar, mask_gans_trn)
#             num_rows, num_cols, bands = sar.shape
#             np.save(output_folder + self.dataset_name + '_' + sar_img_name + '_sar', sar)
#             np.save(output_folder + self.dataset_name + '_' + sar_img_name + '_sar_nor', img_source)
#             io.savemat(output_folder + self.dataset_name + '_' + sar_img_name + '_sar' + '.mat', {"sar":sar})
#             np.save(output_folder + self.dataset_name + '_opt', opt)
#             np.save(output_folder + self.dataset_name + '_cloud_mask', cloud_mask)
#         elif args.experiment_type is 'case_015':
#             # Load images
#             print 'Case 01.5 ...'
#             sar_img_name = '13_07Jul_2016.npy'
#             opt_img_name = '20160708'
# #            10_08May_2016.npy
# #            20160505
# #            mask, sar, opt, _ = load_images(sar_path=self.sar_root_patch + '14_31Jul_2016.npy',
# #                                            opt_path=self.opt_root_patch + '20160724/'
# #                                            )
# #            mask, sar, opt, _ = load_images(sar_path=self.sar_root_patch + '13_07Jul_2016.npy',
# #                                            opt_path=self.opt_root_patch + '20160708/'
# #                                            )
#             mask, sar, opt, cloud_mask = load_images(sar_path=self.sar_root_patch + sar_img_name,
#                                                      opt_path=self.opt_root_patch + opt_img_name + '/'
#                                                      )
#             mask = resampler(mask)
#             sar = resampler(sar)
#             mask_sar = sar[:, :, 0].copy()
#             mask_sar[sar[:, :, 0]<1] = 1
#             mask_sar[sar[:, :, 0]==1] = 0
#             np.save(output_folder + 'mask', mask)
#             io.savemat(output_folder + 'mask.mat', {"mask":mask})

#             num_rows, num_cols = mask.shape
#             mask_gans_trn = mask_4_trn_gans(num_rows, num_cols, args.image_region)
#         #    mask_gans_trn = mask_gans_trn * mask
#             mask_gans_trn = mask_gans_trn * mask_sar
#             img_source = minmaxnormalization(sar, mask_sar)
#             num_rows, num_cols, bands = sar.shape
#             np.save(output_folder + self.dataset_name + '_' + sar_img_name + '_sar', sar)
#             io.savemat(output_folder + self.dataset_name + '_' + sar_img_name + '_sar' + '.mat', {"sar":sar})
#             np.save(output_folder + self.dataset_name + '_' + opt_img_name + '_opt', opt)
#             np.save(output_folder + self.dataset_name + '_' + opt_img_name + '_cloud_mask', cloud_mask)

#         elif args.experiment_type is 'case_02':
#             print 'Case 02 ...'
#             mask, sar, opt, _ = load_images(sar_path=self.sar_root_patch + '13_07Jul_2016.npy',
#                                             opt_path=self.opt_root_patch + '20160708/'
#                                             )
#             mask = resampler(mask)
#             sar = resampler(sar)
#             mask_sar = sar[:, :, 0].copy()
#             mask_sar[sar[:, :, 0] < 1] = 1
#             mask_sar[sar[:, :, 0] == 1] = 0
#             np.save(output_folder + 'mask', mask)
#             io.savemat(output_folder + 'mask.mat', {"mask":mask})

#             num_rows, num_cols = mask.shape
#             mask_gans_trn = mask_4_trn_gans(num_rows, num_cols, args.image_region)
#         #    mask_gans_trn = mask_gans_trn * mask
#             mask_gans_trn = mask_gans_trn * mask_sar
#             img_source = minmaxnormalization(sar, mask_gans_trn)
#             num_rows, num_cols, bands = sar.shape
#             np.save(output_folder + self.dataset_name + '_sar', sar)
#             io.savemat(output_folder + self.dataset_name + '_sar' + '.mat', {"sar":sar})
#             np.save(output_folder + self.dataset_name + '_opt', opt)
#         elif args.experiment_type is 'case_04':
#             print 'Case 04 Multiresolution ...'
#             mask_path = '/mnt/Data/DataBases/RS/SAR/Campo Verde/New_Masks/TrainTestMasks/TrainTestMask_50_50_Dec.tif'
#             sar_path = self.sar_root_patch + '13_07Jul_2016.npy'
#             opt_path = self.opt_root_patch + '20160708/'
#             # La imagen opt_path1 es la imagen a reconstruir
#             opt, _ = load_landsat(opt_path)
#             opt[np.isnan(opt)] = 0.0
#             opt = np.float32(opt)
#             sar = np.load(sar_path)
#             sar = np.rollaxis(sar, 0, 3)
#             mask = load_tiff_image(mask_path)

#             sar[sar > 1.0] = 1.0
#             mask_sar = sar[:, :, 0].copy()
#             mask_sar[sar[:, :, 0] < 1] = 1
#             mask_sar[sar[:, :, 0] == 1] = 0

#             mask_gan = np.load('mask_gan_original.npy')
#             mask_gan[mask == 0] = 0
#             mask_gan[mask_gan != 0] = 2
#             mask_gan[(mask != 0) * (mask_gan == 0) ] = 1

#             mask_gans_trn = mask_gan

#             img_source = minmaxnormalization(sar, mask_sar)
# #            mask_opt = resampler(mask_sar)
# #            opt = minmaxnormalization(opt, mask_opt)
# #
# #            img_source = np.concatenate((sar1, sar2, opt_source), axis=2)
# #            img_source = minmaxnormalization(img_source, args.image_region)
# #            opt_target = minmaxnormalization_mask50(opt_target)
#             num_rows, num_cols, num_bands = img_source.shape
#         elif args.experiment_type is 'case_05':
#             print 'do something'

# #        print self.input_c_dim,  self.output_size
#         img_source = img_source.reshape(1, num_rows, num_cols, num_bands)
#         fake_opt = np.zeros((int(round(num_rows/3)), int(num_cols/3), self.output_c_dim),
#                             dtype='float32')
#         s = 3*112
#         self.image_size_o = self.image_size
#         self.image_size = 3*self.image_size
#         stride = self.image_size-2*s
#         for row in range(0, num_rows, stride):
#             for col in range(0, num_cols, stride):
#                 if (row+self.image_size <= num_rows) and (col+self.image_size <= num_cols):

#                     print row + s, row + self.image_size - s
#                     sample_image = img_source[:, row:row+self.image_size, col:col+self.image_size]
#                     sample = self.sess.run(self.fake_B_sample,
#                                            feed_dict={self.real_A: sample_image}
#                                            )
#                     print sample.shape
#                     fake_opt[int((row+s)/3):int((row+self.image_size-s)/3), int((col+s)/3):int((col+self.image_size-s)/3)] = sample[0, int(s/3):self.image_size_o-int(s/3), int(s/3):self.image_size_o-int(s/3)]
#                 elif col+self.image_size <= num_cols:
#                     sample_image = img_source[:, num_rows-self.image_size:num_rows, col:col+self.image_size]
#                     print(sample_image.shape)
#                     sample = self.sess.run(self.fake_B_sample,
#                                            feed_dict={self.real_A: sample_image}
#                                            )
#                     print sample.shape
#                     fake_opt[int((row+s)/3):int(round(num_rows/3)), int((col+s)/3):int((col+self.image_size-s)/3)] = sample[0, int((self.image_size-num_rows+row+s)/3):int(self.image_size/3), int(s/3):int((self.image_size-s)/3)]
#                 elif row+self.image_size <= num_rows:
#                     print col
#                     sample_image = img_source[:, row:row+self.image_size, num_cols-self.image_size:num_cols]
#                     sample = self.sess.run(self.fake_B_sample,
#                                            feed_dict={self.real_A: sample_image}
#                                            )
#                     fake_opt[int((row+s)/3):int((row+self.image_size-s)/3), int((col+s)/3):int(num_cols/3)] = sample[0, int(s/3):int((self.image_size-s)/3), int((self.image_size-num_cols+col+s)/3):int(self.image_size/3)]

#         np.save(output_folder + self.dataset_name + '_fake_opt_new', fake_opt)

#        SAR = np.zeros((args.batch_size, num_rows, num_cols, self.input_c_dim + self.output_c_dim), dtype='float32')
#        img_source = img_source.reshape(1, num_rows, num_cols, bands)
##        img_source = np.repeat(img_source, args.batch_size, axis=0)
#        SAR[:, :, :, :self.input_c_dim] = img_source
#        fake_opt = np.zeros((num_rows, num_cols, self.output_c_dim),

#                            dtype='float32')
#        fake_opt = self.sess.run(
#                    self.fake_B_sample,
#                    feed_dict={self.real_data: SAR}
#                    )
#        np.save(output_folder + self.dataset_name + '_fake_opt_new', fake_opt)

#
        # Save weigths !
#        e1 = self.sess.graph.get_tensor_by_name('generator/g_e1_conv/w:0')
#        eb1 = self.sess.graph.get_tensor_by_name('generator/g_e1_conv/biases:0')
#        print e1.eval(), eb1.eval()
#        save_weights(self.sess)
#        print "weigths saved...."

#        print self.input_c_dim,  self.output_size
#        SAR = np.zeros((args.batch_size, num_rows, num_cols, self.input_c_dim + self.output_c_dim), dtype='float32')
#        img_source = img_source.reshape(1, num_rows, num_cols, bands)
##        img_source = np.repeat(img_source, args.batch_size, axis=0)
#        SAR[:, :, :, :self.input_c_dim] = img_source
#        fake_opt = np.zeros((num_rows, num_cols, self.output_c_dim),
#                            dtype='float32')
#        avg_img = np.zeros_like(fake_opt).astype('float32')
#        stride = int(self.image_size/1)
#        for row in range(0, num_rows, stride):
#            for col in range(0, num_cols, stride):
#                if row+self.image_size <= num_rows and col+self.image_size <= num_cols:
#                    sample_image = SAR[:, row:row+self.image_size, col:col+self.image_size]
#                    print(sample_image.shape)
#
#                    sample = self.sess.run(
#                            self.fake_B_sample,
#                            feed_dict={self.real_data: sample_image}
#                            )
#                    print sample.shape
##                    fake_opt[row:row+256, col:col+256] = sample[0].reshape(256, 256, self.output_c_dim)
#                    fake_opt[row:row+self.image_size, col:col+self.image_size] += sample[0]
#                    avg_img[row:row+self.image_size, col:col+self.image_size] += np.ones_like(sample[0])
##                    fake_opt[row+stride:row+self.image_size-stride, col+stride:col+self.image_size-stride] += sample[0, stride:self.image_size-stride, stride:self.image_size-stride]
##                    avg_img[row+stride:row+self.image_size-stride, col+stride:col+self.image_size-stride] += np.ones_like(sample[0, stride:self.image_size-stride, stride:self.image_size-stride])
##        plt.figure()
##        plt.imshow(fake_opt)
##        plt.show()
#        avg_img[avg_img == 0] = 1
#        fake_opt = fake_opt/avg_img
#        fake_opt[np.isnan(fake_opt)] = 0
#        np.save(output_folder + '_fake_opt', fake_opt)
##        np.save(output_folder + self.dataset_name + '_fake_opt', fake_opt)
##        np.save(output_folder + self.dataset_name + '_fake_opt', fake_opt)
##        np.save(output_folder + 'real_opt_'+self.dataset_name, opt_target)
#
##        plt.figure()
##        plt.imshow(avg_img[:, :, 0])
##        plt.show()


    def create_dataset(self, args):
        sar_t0 = '10_08May_2016.npy'
        opt_t0 = '20160505/'
        sar_t1 = '20170520.npy'
        opt_t1 = '20170524/'
        # print sar_img_name, opt_img_name
        create_dataset_multitemporal_multiresolution_CV(
            ksize=256,
            dataset=self.dataset_name,
            mask_path=None,
            sar_path_t0=self.sar_root_patch + sar_t0,
            opt_path_t0=self.opt_root_patch + opt_t0,
            sar_path_t1=self.sar_root_patch + sar_t1,
            opt_path_t1=self.opt_root_patch + opt_t1,
            )
        return 0