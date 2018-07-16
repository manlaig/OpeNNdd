from __future__ import division
import math
from opeNNdd_dataset import OpeNNdd_Dataset as open_data#class for the OpeNNdd dataset
from collections import OrderedDict #dictionary for holding network
import matplotlib.pyplot as plt
import tensorflow as tf #import tensorflow
import numpy as np
import sys #for unit tests
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2' #disables AVX/FMA warning
from tqdm import tqdm #progress bar
from pathlib import Path #for getting home folder
import random
from datetime import datetime
random.seed(datetime.now())

class OpeNNdd_Model:
    """
        Class to easily declare network models of different architectures and hyperparameters
        for the OpeNNdd_Dataset.
    """

    def __init__(self,
        hdf5_file = None, #complete file path to the hdf5 file where the data is stored
        batch_size = None, #number of images to use for train, val and test batches
        channels = None, #num of channel for each image
        conv_layers = None, #must provide a shape that each dim will specify features per layer.. ex. [32,64,64] -> 3 layers, filters of 32, 64, and 64 features
        conv_kernels = None, #must provide a shape that will specify kernel dim per layer.. ex. [3,5,5] -> 3x3x3 5x5x5 and 5x5x5 filters.. must have same num of dimenions as conv_layers
        fire_layers = None,
        pool_layers = None, #must provide a shape that each dim will specify filter size.. ex. [2,2,2] -> 3 pool layers, 2x2x2 filters and stride of 2 is always
        dropout_layers = None, #must be a shape where each dimension is the probability a neuron stays on or gets turned off... must check... ex. [.4,.4,.4] -> 3 layers with keep probability of 0.4
        fc_layers = None, #must provide a shape that each dim will specify units per connected layer.. ex. [1024,256,1] -> 3 layers, 1024 units, 256, units and 1 unit... last fully connected is the logits layer
        loss_function = None, #must be a tensorflow loss function
        optimizer = None, #must be a tensorflow optimizing function with a learning rate already... see unit tests example below
        ordering = None, #must be a string representing ordering of layers by the standard of this class... ex. "cpcpff" -> conv, max_pool, conv1, max_pool, fully connected, fully connected.. and the num of characters must match the sum of all of the dimensions provided in the layers variables
        storage_folder = None, #complete path to an existing directory you would like model data stored
        gpu_mode = False #booling for whether or not to enable gpu mode
    ):
        assert (len(conv_layers) + len(pool_layers) + len(dropout_layers) + len(fc_layers) == len(ordering)), "Number of layers does not equal number of entries in the ordering list."
        None if os.path.isdir(storage_folder) else os.makedirs(storage_folder) #create dir if need be
        self.id = random.randint(100000, 999999)
        self.storage_folder = storage_folder
        self.model_folder = os.path.join(storage_folder, 'tmp', str(self.id)) #append / onto model_folder if need be
        self.log_folder = os.path.join(storage_folder, 'logs', str(self.id))
        self.db = open_data(hdf5_file, batch_size, channels) #handle for the OpeNNdd dataset
        self.conv_layers = conv_layers
        self.conv_kernels = conv_kernels
        self.fire_layers = fire_layers
        self.pool_layers = pool_layers
        self.dropout_layers = dropout_layers
        self.fc_layers = fc_layers
        self.loss_function = loss_function
        self.optimizer = optimizer
        self.ordering = ordering.lower() #convert all to lowercase for simplicity
        self.gpu_mode = gpu_mode
        self.flattened = False #flag to know if we have already flattened the data once we come to fully connected layers
        self.network_built = False #flag to see if we have already built the network
        self.epochs = 0 #number of epochs we have currently completed successfully with increasing validation accuracy
        self.stop_threshold = 5
        self.min_epochs = 25

        self.train_mse_arr = np.zeros([1], dtype=float)
        self.train_rmse_arr = np.zeros([1], dtype=float)
        self.train_mape_arr = np.zeros([1], dtype=float)
        self.train_avg_mse_arr = np.zeros([1], dtype=float)
        self.train_avg_rmse_arr = np.zeros([1], dtype=float)
        self.train_avg_mape_arr = np.zeros([1], dtype=float)

        self.val_mse_arr = np.zeros([0], dtype=float)
        self.val_rmse_arr = np.zeros([0], dtype=float)
        self.val_mape_arr = np.zeros([0], dtype=float)
        self.val_avg_mse_arr = np.zeros([1], dtype=float)
        self.val_avg_rmse_arr = np.zeros([1], dtype=float)
        self.val_avg_mape_arr = np.zeros([1], dtype=float)

        self.test_mse_arr = np.zeros([0], dtype=float)
        self.test_rmse_arr = np.zeros([0], dtype=float)
        self.test_mape_arr = np.zeros([0], dtype=float)
        self.test_avg_mse_arr = 0
        self.test_avg_rmse_arr = 0
        self.test_avg_mape_arr = 0



        #Changes to Train/Val/Test parameters to test logging functionality
        #self.min_epochs = 5
        #self.db.total_train_steps = 10
        #self.db.total_val_steps = 10
        #self.db.total_test_steps = 10
        #self.stop_threshold = 0


    #3d conv with relu activation
    def conv_3d(self, inputs, filters, kernel_size, name=None):
        out = tf.layers.conv3d(inputs, filters=filters, kernel_size=kernel_size,
                                 padding='same', activation=tf.nn.relu,
                                 name=None)
        return out

    def fire_3d(self, inputs, filters, expand_filters, kernel_size, name=None):
        out = tf.layers.conv3d(inputs, filters=filters, kernel_size=kernel_size,
                                 padding='same', activation=tf.nn.relu,
                                 name=None)

        expand1 = tf.layers.conv3d(out, filters=expand_filters, kernel_size= (1,1,1),
                                 padding='same', activation=tf.nn.relu,
                                 name=None)

        expand2 = tf.layers.conv3d(inputs, filters=expand_filters, kernel_size= (1,1,1),
                                 padding='same', activation=tf.nn.relu,
                                 name=None)

        out = tf.concat([expand1, expand2], 3)

        return out

    def avg_pool3d(self, inputs, pool_size, name=None):
        out = tf.layers.average_pooling3d(inputs, pool_size=pool_size, strides=(2,2,2),
                                        padding='same', name=name)
        return out

    #max pooling with strides of 2 and same padding
    def max_pool3d(self, inputs, pool_size, name=None):
        out = tf.layers.max_pooling3d(inputs, pool_size=pool_size, strides=(2,2,2),
                                        padding='same', name=name)
        return out

    #n-dimensions to 1-dimension
    def flatten(self, inputs):
        out = tf.contrib.layers.flatten(inputs)
        return out

    #fully connected layer with relu activation
    def dense_relu(self, inputs, units, name=None):
        out = tf.layers.dense(inputs, units, activation=tf.nn.relu,
                                name=name)
        return out

    #fully connected no relu, or logits layer
    def dense(self, inputs, units, name=None):
        out = tf.layers.dense(inputs, units,
                                name=name)
        return out

    #dynamicall build the network
    def build_network(self):
        self.network = OrderedDict({'labels': tf.placeholder(tf.float32, [None, open_data.classes])}) #start a dictionary with first element as placeholder for the labels
        self.network.update({'inputs': tf.placeholder(tf.float32, [None, open_data.grid_dim, open_data.grid_dim, open_data.grid_dim, self.db.channels])}) #append placeholder for the inputs
        c_layer, p_layer, d_layer, f_layer, h_layer, a_layer = 0, 0, 0, 0, 0, 0 #counters for which of each type of layer we are on

        #append layers as desired
        for command in self.ordering: #for each layer in network
            if command == 'c': #convolution
                shape = (self.conv_kernels[c_layer], self.conv_kernels[c_layer], self.conv_kernels[c_layer]) #convert dim provided into a tuple
                self.network.update({'conv'+str(c_layer): self.conv_3d(self.network[next(reversed(self.network))], self.conv_layers[c_layer], shape, 'conv'+str(c_layer))}) #append the desired conv layer
                c_layer += 1
            elif command == 'p': #max_pooling
                shape = (self.pool_layers[p_layer], self.pool_layers[p_layer], self.pool_layers[p_layer])
                self.network.update({'max_pool'+str(p_layer): self.max_pool3d(self.network[next(reversed(self.network))], shape, 'max_pool'+str(p_layer))})
                p_layer += 1
            elif command == 'd': #dropout
                self.network.update({'dropout'+str(d_layer): tf.nn.dropout(self.network[next(reversed(self.network))], self.dropout_layers[d_layer])})
                d_layer += 1
            elif command == 'f':
                shape = (self.conv_kernels[c_layer], self.conv_kernels[c_layer], self.conv_kernels[c_layer]) #convert dim provided into a tuple
                self.network.update({'fire'+str(c_layer): self.fire_3d(self.network[next(reversed(self.network))], self.conv_layers[c_layer], self.fire_layers[f_layer], shape, 'fire'+str(c_layer))})
                c_layer += 1
                f_layer += 1
            elif command == 'a':
                shape = (self.pool_layers[a_layer], self.pool_layers[a_layer], self.pool_layers[a_layer])
                self.network.update({'avg_pool'+str(a_layer): self.max_pool3d(self.network[next(reversed(self.network))], shape, 'avg_pool'+str(a_layer))})
            elif command == 'h': #fully connected
                if h_layer == self.ordering.count('h') - 1: #we are appending the last fully connected layer.. so use dense no relu
                    if self.flattened:
                        self.network.update({'logits': self.dense(self.network[next(reversed(self.network))], self.fc_layers[h_layer], 'logits')})
                    else:
                        self.network.update({'logits': self.dense(self.flatten(self.network[next(reversed(self.network))]), self.fc_layers[h_layer], 'logits')})
                        self.flattened = True
                else: #dense with relu
                    if self.flattened:
                        self.network.update({'fc'+str(h_layer): self.dense_relu(self.network[next(reversed(self.network))], self.fc_layers[h_layer], 'fc'+str(h_layer))})
                    else:
                        self.network.update({'fc'+str(h_layer): self.dense_relu(self.flatten(self.network[next(reversed(self.network))]), self.fc_layers[h_layer], 'fc'+str(h_layer))})
                        self.flattened = True
                h_layer += 1
        self.network_built = True

        #append loss function and then optimizer
        self.network.update({'loss': tf.reduce_mean(self.loss_function(labels = self.network['labels'], predictions = self.network['logits']), name="quadratic_cost")})
        tf.summary.histogram("quadratic_cost", self.network['loss'])
        self.network.update({'optimizer': self.optimizer.minimize(self.network['loss'])})
        self.optimal_epochs = 0


    def mean_absolute_percentage_error(self, target, prediction):
        err = 0
        batch_size = target.shape[0]
        for i in range(batch_size):
            err += abs(target[i][0]-prediction[i][0])/abs(target[i][0])
        err *= 100/batch_size
        return err

    def plot_val_err(self, err_type, metric_type = ''):
        plt.clf()
        plt.cla()
        plt.close()
        delay = 1
        self.val_avg_mse_arr[delay] = 0
        self.train_avg_mse_arr[delay] = 0
        self.val_avg_rmse_arr[delay] = 0
        self.train_avg_rmse_arr[delay] = 0
        self.val_avg_mape_arr[delay] = 0
        self.train_avg_mape_arr[delay] = 0

        if err_type.lower() == 'mse':
            err_phrase, err_key, units = 'Mean Squared Error', 'mse', '(kCal/Mol)^2'
            if metric_type.lower() == 'average' or metric_type.lower() == 'avg':
                plt.plot(self.val_avg_mse_arr, 'b-', label='val')
                plt.plot(self.train_avg_mse_arr, 'y-', label='train')
                plt.legend(loc='upper right')
                plt.xlim(xmin=2)
                metric_phrase, metric_key, metric_iter = 'Average ', 'avg_', 'Epochs'
            else:
                plt.plot(self.val_mse_arr)
                plt.xlim(xmin=1)
                metric_phrase, metric_key, metric_iter = '', '', 'Batches'
        elif err_type.lower() == 'rmse':
            err_phrase, err_key, units = 'Root Mean Squared Error', 'rmse', '(kCal/Mol)'
            if metric_type.lower() == 'average' or metric_type.lower() == 'avg':
                plt.plot(self.val_avg_rmse_arr, 'b-', label='val')
                plt.plot(self.train_avg_rmse_arr, 'y-', label='train')
                plt.legend(loc='upper right')
                plt.xlim(xmin=2)
                metric_phrase, metric_key, metric_iter = 'Average ', 'avg_', 'Epochs'
            else:
                plt.plot(self.val_rmse_arr)
                plt.xlim(xmin=1)
                metric_phrase, metric_key, metric_iter = '', '', 'Batches'
        elif err_type.lower() == 'mape':
            err_phrase, err_key, units = 'Mean Absolute Percentage Error', 'mape', '(%)'
            if metric_type.lower() == 'average' or metric_type.lower() == 'avg':
                plt.plot(self.val_avg_mape_arr, 'b-', label='val')
                plt.plot(self.train_avg_mape_arr, 'y-', label='train')
                plt.legend(loc='upper right')
                plt.xlim(xmin=2)
                metric_phrase, metric_key, metric_iter = 'Average ', 'avg_', 'Epochs'
            else:
                plt.plot(self.val_mape_arr)
                plt.xlim(xmin=1)
                metric_phrase, metric_key, metric_iter = '', '', 'Batches'
        else:
            return
        plt.title('Validation - ' + metric_phrase + err_phrase)
        plt.xlabel('Number of ' + metric_iter)
        plt.ylabel(metric_phrase + err_phrase + ' ' + units)
        folder = os.path.join(self.log_folder, 'metrics', 'val', err_key)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        plt.savefig(os.path.join(folder, 'val_' + metric_key + err_key + '_'+ str(self.id)+'.png'))

    def plot_test_err(self, err_type):
        plt.clf()
        plt.cla()
        plt.close()
        if err_type.lower() == 'mse':
            err_phrase, err_key, units = 'Mean Squared Error', 'mse', '(kCal/Mol)^2'
            plt.plot(self.test_mse_arr)
            plt.xlim(xmin=1)
        elif err_type.lower() == 'rmse':
            err_phrase, err_key, units = 'Root Mean Squared Error', 'rmse', '(kCal/Mol)'
            plt.plot(self.test_rmse_arr)
            plt.xlim(xmin=1)
        elif err_type.lower() == 'mape':
            err_phrase, err_key, units = 'Mean Absolute Percentage Error', 'mape', '(%)'
            plt.plot(self.test_mape_arr)
            plt.xlim(xmin=1)
        else:
            return
        plt.title('Testing - ' + err_phrase)
        plt.xlabel('Number of Testing Batches')
        plt.ylabel(err_phrase + ' ' + units)
        folder = os.path.join(self.log_folder, 'metrics', 'test', err_key)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        plt.savefig(os.path.join(folder, 'test_' +err_key + '_'+ str(self.id)+'.png'))

    def record_model_metrics(self, mode):
        folder = os.path.join(self.log_folder, 'metrics')
        file = os.path.join(folder, 'metrics.txt')
        if not os.path.isdir(folder):
            os.makedirs(folder)
        if not os.path.exists(file):
            metrics_file = open(file, 'w')
            metrics_file.write("Model ID: " + str(self.id))
            metrics_file.write("\nModel Folder: " + self.model_folder)
            metrics_file.write("\nLogging Folder: " + self.log_folder)
            metrics_file.write("\n\nModel Structure: \n")
            conv_count, pool_count, fc_count, drop_count = 0,0,0,0
            metrics_file.write("Input Layer: Dimensions = %dx%dx%d, Number of Channels = %d\n"%(self.db.grid_dim, self.db.grid_dim, self.db.grid_dim, self.db.channels))
            for layer in list(self.network.keys()):
                if (layer.find('conv') != -1):
                    metrics_file.write('Convolutional Layer %d: Number of Filters = %d, Kernel Size = %dx%dx%d\n' % (conv_count+1, self.conv_layers[conv_count], self.conv_kernels[conv_count], self.conv_kernels[conv_count], self.conv_kernels[conv_count]))
                    conv_count+=1
                if (layer.find('pool') != -1):
                    metrics_file.write('Pooling Layer %d: Pool Size = %dx%dx%d, Stride = %d\n'%(pool_count+1, self.pool_layers[pool_count], self.pool_layers[pool_count], self.pool_layers[pool_count], self.pool_layers[pool_count]))
                    pool_count+=1
                if (layer.find('fc') != -1):
                    metrics_file.write('Fully Connected Layer %d: Number of Nodes = %d\n' % (fc_count+1, self.fc_layers[fc_count]))
                    fc_count+=1
                if (layer.find('dropout') != -1):
                    metrics_file.write('Dropout Layer %d: Rate = %f\n'%(drop_count+1, self.dropout_layers[drop_count]))
                    drop_count+=1

            metrics_file.write("Output Layer: Number of Outputs = %d\n"%(self.db.classes))
            metrics_file.write("\nLoss Function: " + str(self.loss_function))
            metrics_file.write("\nOptimizer: " + str(self.optimizer))

            metrics_file.write("\n\nTraining Epochs for Saved Model: " + str(self.optimal_epochs))
            metrics_file.write("\nTotal Training Epochs: " + str(self.epochs))
        else:
            metrics_file = open(file, "a")
        if mode.lower() == 'validation' or mode.lower() == 'val':
            metrics_file.write("\nValidation - Average Mean Squared Error: %f kCal^2/Mol^2\n" % (self.val_avg_mse_arr[-self.stop_threshold]))
            metrics_file.write("Validation - Average Root Mean Squared Error: %f kCal/Mol\n" % (self.val_avg_rmse_arr[-self.stop_threshold]))
            metrics_file.write("Validation - Average Mean Absolute Percentage Error:  {:0.2f}%\n".format(self.val_avg_mape_arr[-self.stop_threshold]))

        if mode.lower() == 'testing' or mode.lower() == 'test':
            metrics_file.write("\nTesting - Average Mean Squared Error: %f kCal^2/Mol^2\n" % (self.test_avg_mse_arr))
            metrics_file.write("Testing - Average Root Mean Squared Error: %f kCal/Mol\n" % (self.test_avg_rmse_arr))
            metrics_file.write("Testing - Average Mean Absolute Percentage Error:  {:0.2f}%".format(self.test_avg_mape_arr))

        metrics_file.close()

    #train the model...includes validation
    def train(self):
        None if self.network_built else self.build_network() #Dynamically build the network if need be
        config = tf.ConfigProto()
        if self.gpu_mode == True: # set gpu configurations if specified
            config.gpu_options.allow_growth = True

        saver = tf.train.Saver() #ops to save the model
        with tf.Session(config=config) as sess:
            sess.run(tf.global_variables_initializer()) #initialize tf variables
            print("initialized")
            stop_count = 0
            prev_error = float('inf')
            #prev_error = 0
            while True: #we are going to fing the number of epochs
                self.db.shuffle_train_data() #shuffle training data between epochs
                total_mse, total_rmse, total_mape = 0.0, 0.0, 0.0
                for step in tqdm(range(self.db.total_train_steps), desc = "Training Model - Epoch " + str(self.epochs+1)):
                    train_ligands, train_labels = self.db.next_train_batch() #get next training batch
                    train_op, mse, targets, outputs = sess.run([self.network['optimizer'], self.network['loss'], self.network['labels'], self.network['logits']], feed_dict={self.network['inputs']: train_ligands, self.network['labels']: train_labels}) #train and return predictions with target values
                    rmse, mape = math.sqrt(mse), self.mean_absolute_percentage_error(targets, outputs)
                    total_mse += mse
                    total_rmse += rmse
                    total_mape += mape

                #if (self.epochs > 0 and self.epochs % self.stop_threshold == 0):
                self.train_avg_mse_arr = np.append(self.train_avg_mse_arr, total_mse / self.db.total_train_steps)
                self.train_avg_rmse_arr = np.append(self.train_avg_rmse_arr, total_rmse / self.db.total_train_steps)
                self.train_avg_mape_arr = np.append(self.train_avg_mape_arr, total_mape / self.db.total_train_steps)
                error = self.validate(sess)

                if prev_error > error: #right now this early stopping only works for errors that will get less, but not accuracies that will become more
                    prev_error = error
                    saver.save(sess, os.path.join(self.model_folder, str(self.id)))
                    self.optimal_epochs = self.epochs
                    stop_count = 0
                else:
                    stop_count += 1

                #else: #stop training becuase model did not improve with another pass thru the train set, self.epochs is the appropriate num of epochs..might need to change later
                if (self.epochs > self.min_epochs and stop_count > self.stop_threshold):
                    self.plot_val_err('mse')
                    self.plot_val_err('mse', 'avg')
                    self.plot_val_err('rmse')
                    self.plot_val_err('rmse', 'avg')
                    self.plot_val_err('mape')
                    self.plot_val_err('mape', 'avg')
                    self.record_model_metrics('val')
                    #saver.save(sess, os.path.join(self.model_folder, str(self.id)))
                    return

                self.epochs += 1

    def validate(self, sess):
        self.db.shuffle_val_data()
        mse_arr = np.zeros([self.db.total_val_steps], dtype=float)
        rmse_arr = np.zeros([self.db.total_val_steps], dtype=float)
        mape_arr = np.zeros([self.db.total_val_steps], dtype=float)
        total_mse, total_rmse, total_mape = 0.0, 0.0, 0.0
        for step in tqdm(range(self.db.total_val_steps), desc = "Validating Model..."):
            val_ligands, val_labels = self.db.next_val_batch()
            outputs, targets, mse = sess.run([self.network['logits'], self.network['labels'], self.network['loss']], feed_dict={self.network['inputs']: val_ligands, self.network['labels']: val_labels}) #train and return predictions with target values
            rmse, mape = math.sqrt(mse), self.mean_absolute_percentage_error(targets, outputs)
            mse_arr[step], rmse_arr[step], mape_arr[step] = mse, rmse, mape
            total_mse += mse
            total_rmse += rmse
            total_mape += mape

        self.val_mse_arr = np.append(self.val_mse_arr, mse_arr)
        self.val_rmse_arr = np.append(self.val_rmse_arr, rmse_arr)
        self.val_mape_arr = np.append(self.val_mape_arr, mape_arr)


        self.val_avg_mse_arr = np.append(self.val_avg_mse_arr, total_mse / self.db.total_val_steps)
        self.val_avg_rmse_arr = np.append(self.val_avg_rmse_arr, total_rmse / self.db.total_val_steps)
        self.val_avg_mape_arr = np.append(self.val_avg_mape_arr, total_mape / self.db.total_val_steps)

        return total_mse / self.db.total_val_steps #return the avg error

    #restore the model and test
    def test(self):
        None if self.network_built else self.build_network() #Dynamically build the network if need be
        mse_arr = np.empty([self.db.total_val_steps], dtype=float)
        rmse_arr = np.empty([self.db.total_val_steps], dtype=float)
        mape_arr = np.empty([self.db.total_val_steps], dtype=float)
        total_mse, total_rmse, total_mape = 0.0, 0.0, 0.0

        config = tf.ConfigProto()
        if self.gpu_mode == True: # set gpu configurations if specified
            config.gpu_options.allow_growth = True

        saver = tf.train.Saver()
        with tf.Session(config=config) as sess:
            #sess.run(tf.global_variables_initializer()) #initialize tf variables
            saver.restore(sess, os.path.join(self.model_folder, str(self.id)))
            self.db.shuffle_test_data() #shuffle training data between epochs
            for step in tqdm(range(self.db.total_test_steps), desc = "Testing Model..."):
                test_ligands, test_labels = self.db.next_test_batch() #get next training batch
                outputs, targets, mse = sess.run([self.network['logits'], self.network['labels'], self.network['loss']], feed_dict={self.network['inputs']: test_ligands, self.network['labels']: test_labels}) #train and return predictions with target values
                rmse, mape = math.sqrt(mse), self.mean_absolute_percentage_error(targets, outputs)
                mse_arr[step], rmse_arr[step], mape_arr[step] = mse, rmse, mape
                total_mse += mse
                total_rmse += rmse
                total_mape += mape

            self.test_mse_arr = np.append(self.test_mse_arr, mse_arr)
            self.test_rmse_arr = np.append(self.test_rmse_arr, rmse_arr)
            self.test_mape_arr = np.append(self.test_mape_arr, mape_arr)
            self.test_avg_mse_arr = total_mse / self.db.total_test_steps
            self.test_avg_rmse_arr = total_rmse / self.db.total_test_steps
            self.test_avg_mape_arr = total_mape / self.db.total_test_steps

            self.plot_test_err('mse')
            self.plot_test_err('rmse')
            self.plot_test_err('mape')
            self.record_model_metrics('test')




"""
    Unit tests for OpeNNdd 2 channel dataset.
"""


if __name__ == '__main__':
    #Constants
    BATCH_SIZE = 9 #images per batch
    CHANNELS = 2
    HDF5_DATA_FILE = str(sys.argv[1]) #path to hdf5 data file
    MODEL1_STORAGE_DIR = str(sys.argv[2])  #path to where we would like our model stored

    if str(sys.argv[3]).lower() == "cpu":
        model = OpeNNdd_Model(HDF5_DATA_FILE, BATCH_SIZE, CHANNELS,
                                [32], [5,5], [32], [2], [0.4],
                                [1024, 1], tf.losses.mean_squared_error,
                                tf.train.AdamOptimizer(1e-4), 'FPDHH',
                                MODEL1_STORAGE_DIR)
    else:
        model = OpeNNdd_Model(HDF5_DATA_FILE, BATCH_SIZE, CHANNELS,
                                [16], [5,5], [16], [2], [0.4],
                                [1], tf.losses.mean_squared_error,
                                tf.train.AdamOptimizer(1e-4), 'FPDH',
                                MODEL1_STORAGE_DIR, True)

    model.train() #train the model
    model.test() #test the model and get the error
