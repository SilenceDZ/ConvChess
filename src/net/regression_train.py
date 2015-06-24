from __future__ import division, absolute_import
from __future__ import print_function, unicode_literals

import time
import numpy as np
import sklearn.datasets
import sklearn.cross_validation
import sklearn.metrics
import theano
import theano.tensor as T
import lasagne

# ############################### prepare data ###############################
import h5py as h5
dataset = h5.File("/data/ConvChess/data/CvC_regression_h5/X_0_8000.h5")
# theano has a constant float type that it uses (float32 for GPU)
# also rescaling to [0, 1] instead of [0, 255]
X = dataset['data']
y = dataset['label']
X_train = X[0:700000]
X_valid = X[700001:800000]
y_train=y[0:700000]
y_valid = y[700001:800000]
#sklearn.cross_validation.train_test_split(
#    X, y, random_state=42, train_size=500000, test_size=100000)
# need to reshape arrays into images, and add in a channel dimension
# there is only 1 channel in this case because the images are gray scale
#X_train = X_train.reshape(-1, 1, 28, 28)
#X_valid = X_valid.reshape(-1, 1, 28, 28)

# ############################## prepare model ##############################
# architecture:
# - 5x5 conv, 32 filters
# - ReLU
# - 2x2 maxpool
# - 5x5 conv, 32 filters
# - ReLU
# - 2x2 maxpool
# - fully connected layer - 256 units
# - 50% dropout
# - fully connected layer- 10 units
# - softmax

# - conv layers take in 4-tensors with the following dimensions:
#   (batch size, number of channels, image dim 1, image dim 2)
# - the batch size can be provided as `None` to make the network
#   work for multiple different batch sizes
l_in = lasagne.layers.InputLayer(
    shape=(None, 6, 8,  8),
)

# - GlorotUniform is an intelligent initialization for conv layers
#   that people like to use (: named after Xavier Glorot
# - by default, a "valid" convolution
# - note that ReLUs are specified in the nonlinearity
l_conv1 = lasagne.layers.Conv2DLayer(
    l_in,
    num_filters=96,
    filter_size=(3, 3),
    nonlinearity=lasagne.nonlinearities.rectify,
    W=lasagne.init.GlorotUniform(),
)
l_conv2 = lasagne.layers.Conv2DLayer(
    l_conv1,
    num_filters=256,
    filter_size=(3, 3),
    nonlinearity=lasagne.nonlinearities.rectify,
    W=lasagne.init.GlorotUniform(),
)
l_conv3 = lasagne.layers.Conv2DLayer(
    l_conv2,
    num_filters=384,
    filter_size=(3, 3),
    nonlinearity=lasagne.nonlinearities.rectify,
    W=lasagne.init.GlorotUniform(),
)
l_hidden1 = lasagne.layers.DenseLayer(
    l_conv3,
    num_units=256,
    nonlinearity=lasagne.nonlinearities.rectify,
    W=lasagne.init.GlorotUniform(),
)

l_hidden1_dropout = lasagne.layers.DropoutLayer(l_hidden1, p=0.5)

# - applies the softmax after computing the final layer units
# - note that there is no ReLU
l_out = lasagne.layers.DenseLayer(
    l_hidden1_dropout,
    num_units=1,
    nonlinearity=lasagne.nonlinearities.tanh,
    W=lasagne.init.GlorotUniform(),
)

# ############################### network loss ###############################

# int32 vector
target_vector = T.vector('y')


def loss_fn(output):
    return T.mean(lasagne.objectives.squared_error(output, target_vector))

stochastic_out = lasagne.layers.get_output(l_out)
# - every layer is passed the deterministic=True flag, but in this
#   case, only the dropout layer actually uses it
deterministic_out = lasagne.layers.get_output(l_out, deterministic=True)

# - theano variable for non-deterministic loss (ie. with dropout)
stochastic_loss = loss_fn(stochastic_out)
# - theano variable for deterministic (ie. without dropout)
deterministic_loss = loss_fn(deterministic_out)

# ######################## compiling theano functions ########################

print("Compiling theano functions")

# - takes out all weight tensors from the network, in order to compute
#   how the weights should be updated
all_params = lasagne.layers.get_all_params(l_out)

# - calculate how the parameters should be updated
# - theano keeps a graph of operations, so that gradients w.r.t.
#   the loss can be calculated
updates = lasagne.updates.nesterov_momentum(
    loss_or_grads=stochastic_loss,
    params=all_params,
    learning_rate=0.1,
    momentum=0.9)

# - create a function that also updates the weights
# - this function takes in 2 arguments: the input batch of images and a
#   target vector (the y's) and returns a list with a single scalar
#   element (the loss)
train_fn = theano.function(inputs=[l_in.input_var, target_vector],
                           outputs=[stochastic_loss],
                           updates=updates)

# - create a function that does not update the weights, and doesn't
#   use dropout
# - same interface as previous the previous function, but now the
#   output is a list where the first element is the loss, and the
#   second element is the actual predicted probabilities for the
#   input data
valid_fn = theano.function(inputs=[l_in.input_var, target_vector],
                           outputs=[deterministic_loss, deterministic_out])

# ################################# training #################################

print("Starting training...")

num_epochs = 25
batch_size = 600
for epoch_num in range(num_epochs):
    start_time = time.time()
    # iterate over training minibatches and update the weights
    num_batches_train = int(np.ceil(len(X_train) / batch_size))
    train_losses = []
    for batch_num in range(num_batches_train):
        batch_slice = slice(batch_size * batch_num,
                            batch_size * (batch_num + 1))
        X_batch = T.shared(X_train[batch_slice])
        y_batch = T.shared(y_train[batch_slice])

        loss, = train_fn(X_batch, y_batch)
        train_losses.append(loss)
    # aggregate training losses for each minibatch into scalar
    train_loss = np.mean(train_losses)

    # calculate validation loss
    num_batches_valid = int(np.ceil(len(X_valid) / batch_size))
    valid_losses = []
    list_of_probabilities_batch = []
    for batch_num in range(num_batches_valid):
        batch_slice = slice(batch_size * batch_num,
                            batch_size * (batch_num + 1))
        X_batch = X_valid[batch_slice]
        y_batch = y_valid[batch_slice]

        loss, probabilities_batch = valid_fn(X_batch, y_batch)
        valid_losses.append(loss)
        list_of_probabilities_batch.append(probabilities_batch)
    valid_loss = np.mean(valid_losses)
    # concatenate probabilities for each batch into a matrix
    probabilities = np.concatenate(list_of_probabilities_batch)
    # calculate classes from the probabilities
    predicted_classes = np.argmax(probabilities, axis=1)
    # calculate accuracy for this epoch
    accuracy = sklearn.metrics.accuracy_score(y_valid, predicted_classes)

    total_time = time.time() - start_time
    print("Epoch: %d, train_loss=%f, valid_loss=%f, valid_accuracy=%f, time=%fs"
          % (epoch_num + 1, train_loss, valid_loss, accuracy, total_time))