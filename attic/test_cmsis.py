#!/usr/bin/env python3
###################################################################################################
# Copyright (C) 2019 Maxim Integrated Products, Inc. All Rights Reserved.
#
# Maxim Integrated Products, Inc. Default Copyright Notice:
# https://www.maximintegrated.com/en/aboutus/legal/copyrights.html
#
# Written by RM
###################################################################################################
"""
Test the CMSIS NN network generator.
"""
import os
import sys

import numpy as np

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import izer.cmsisnn as cmsisnn  # noqa: E402 pylint: disable=wrong-import-position, import-error
import izer.devices as devices  # noqa: E402 pylint: disable=wrong-import-position, import-error
import izer.op as op  # noqa: E402 pylint: disable=wrong-import-position, import-error
import izer.tornadocnn as tc  # noqa: E402 pylint: disable=wrong-import-position, import-error


@pytest.mark.parametrize('test_no', [0, 1, 2, 3, 4])
def test_cmsis(test_no):
    """Main program to test cmsisnn.create_net."""

    tc.dev = tc.get_device(devices.CMSISNN)

    weight = []
    bias = []
    layers = 1
    padding = [[1, 1]]
    dilation = [[1, 1]]
    stride = [[1, 1]]
    kernel_size = [[3, 3]]
    quantization = [8]
    pool = [[1, 1]]
    pool_stride = [[1, 1]]
    pool_average = [False]
    activate = [None]
    bias = [None]
    output_width = [8]
    convolution = [op.CONV2D]
    operands = [1]
    eltwise = [None]
    pool_first = [False]
    in_sequences = [None]
    conv_groups = [1]

    assert 0 <= test_no <= 4
    if test_no == 0:  # Passes
        input_chan = [2]
        output_chan = [3]
        input_size = [2, 4, 4]

        w = np.array(
            [-16, 26, 35, -6, -40, -31, -27, -54, -51, -84, -69, -65,
             -8, -8, -13, -16, -3, 33, 48, 39, 27, 56, 50, 57, 31, 35,
             2, 8, 16, 28, 13, -18, 8, -6, 32, 20, -3, 4, 42, 41, 3, 23,
             67, 74, 8, -12, 33, 28, -25, -14, 1, 14, -3, 2], dtype=np.int64)
        w = w.reshape((input_chan[0] * output_chan[0], kernel_size[0][0], kernel_size[0][1]))
        print(w.flatten())
        weight.append(w)

        data = np.array(
            [[[85, 112, 69, 78],
              [69, 81, 51, 65],
              [45, 24, 0, 20],
              [34, 0, 15, 30]],
             [[0, 0, 3, 8],
              [0, 0, 12, 47],
              [0, 0, 0, 8],
              [0, 2, 0, 0]]],
            dtype=np.int64)
    elif test_no == 1:  # Passes
        input_chan = [1]
        output_chan = [1]
        input_size = [1, 2, 2]

        w = np.array(
            [-16, 26, 35, -6, -40, -31, -27, -54, -51], dtype=np.int64)
        w = w.reshape((input_chan[0] * output_chan[0], kernel_size[0][0], kernel_size[0][1]))
        weight.append(w)

        data = np.array(
            [[[85, 112],
              [69, 81]]],
            dtype=np.int64)
    elif test_no == 2:  # Passes
        input_chan = [1]
        output_chan = [3]
        input_size = [1, 2, 2]

        w = np.array(
            [-16, 26, 35, -6, -40, -31, -27, -54, -51,
             -84, -69, -65, -8, -8, -13, -16, -3, 33,
             48, 39, 27, 56, 50, 57, 31, 35, 2], dtype=np.int64)
        w = w.reshape((input_chan[0] * output_chan[0], kernel_size[0][0], kernel_size[0][1]))
        weight.append(w)

        data = np.array(
            [[[85, 112],
              [69, 81]]],
            dtype=np.int64)
    elif test_no == 3:  # Passes
        input_chan = [2]
        output_chan = [1]
        input_size = [2, 2, 2]

        w = np.array(
            [-16, 26, 35, -6, -40, -31, -27, -54, -51,
             -84, -69, -65, -8, -8, -13, -16, -3, 33], dtype=np.int64)
        w = w.reshape((input_chan[0] * output_chan[0], kernel_size[0][0], kernel_size[0][1]))
        weight.append(w)

        data = np.array(
            [[[85, 112],
              [69, 81]],
             [[51, -65],
              [-45, 65]]],
            dtype=np.int64)
    elif test_no == 4:
        input_chan = [2]
        output_chan = [2]
        input_size = [2, 2, 2]

        w = np.array(
            [-16, 26, 35, -6, -40, -31, -27, -54, -51,
             -84, -69, -65, -8, -8, -13, -16, -3, 33,
             48, 39, 27, 56, 50, 57, 31, 35, 2, 8,
             16, 28, 13, -18, 8, -6, 32, 20], dtype=np.int64)
        w = w.reshape((input_chan[0] * output_chan[0], kernel_size[0][0], kernel_size[0][1]))
        weight.append(w)

        data = np.array(
            [[[85, 112],
              [69, 81]],
             [[51, -65],
              [-45, 65]]],
            dtype=np.int64)

    assert data.size == input_size[0]*input_size[1]*input_size[2]
    assert input_chan[0] == input_size[0]
    assert w.size == input_chan[0]*kernel_size[0][0]*kernel_size[0][1]*output_chan[0]

    input_dim = [[input_size[1], input_size[2]]]
    pooled_dim = input_dim
    output_dim = [[data.shape[1], data.shape[2]]]
    flatten = [False]
    output_shift = [0]

    cmsisnn.create_net(
        'test_cmsis',  # prefix
        True,  # verbose
        False,  # verbose_all
        False,  # debug
        True,  # log
        layers,
        convolution,
        input_dim,  # auto_input_dim
        input_dim,
        pooled_dim,
        output_dim,
        kernel_size,
        quantization,
        output_shift,
        input_chan,
        output_chan,
        conv_groups,
        output_width,
        padding,
        dilation,
        stride,
        pool,
        pool_stride,
        pool_average,
        activate,
        data,
        weight,
        bias,
        flatten,
        operands,
        eltwise,
        pool_first,
        in_sequences,
        'main',  # c_filename,
        'tests',  # base_directory
        'log.txt',  # log_filename
        'weights.h',  # weight_filename
        'sampledata.h',  # sample_filename,
        False,  # avg_pool_rounding
        False,  # legacy_test
    )


if __name__ == '__main__':
    for i in range(5):
        test_cmsis(i)
