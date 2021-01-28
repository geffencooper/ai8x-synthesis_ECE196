###################################################################################################
# Copyright (C) Maxim Integrated Products, Inc. All Rights Reserved.
#
# Maxim Integrated Products, Inc. Default Copyright Notice:
# https://www.maximintegrated.com/en/aboutus/legal/copyrights.html
###################################################################################################
"""
Simulate a single CNN layer
"""
import os

import numpy as np

from . import op, stats
from . import tornadocnn as tc
from .compute import conv1d, conv2d, eltwise, linear, pool1d, pool2d


def print_data(
        verbose_data,
        header,
        data,
        input_size,
        expand,
        expand_thresh,
):
    """
    Print `data` of dimensions `input_size` with `expand` and `expand_thresh`,
    prefixed by `header`.
    """
    int8_format = '{0:4}' if np.any(data < 0) else '{0:3}'

    print(header, end='')
    if verbose_data:
        print(':')
        with np.printoptions(formatter={'int': int8_format.format}):
            if input_size[1] == input_size[2] == 1:
                for i in range(0, input_size[0], expand_thresh):
                    last = min(i + expand_thresh, input_size[0])
                    if last - 1 > i:
                        print(f'Channels #{i} to #{last-1}', end='')
                    else:
                        print(f'Channel #{i}', end='')
                    if expand and expand > 1:
                        print(f' (expansion: {(i // expand_thresh) + 1} of {expand})')
                    else:
                        print('')
                    print(np.squeeze(data[i:last]))
            else:
                for i in range(input_size[0]):
                    print(f'Channel #{i}', end='')
                    if expand and expand > 1:
                        print(f' (expansion: {(i // expand_thresh) + 1} of {expand})')
                    else:
                        print('')
                    print(data[i])
    print('')


def conv2d_layer(
        layer,  # pylint: disable=unused-argument
        verbose,
        verbose_data,
        input_size,
        kernel_size,
        output_shift,
        output_channels,
        padding,
        dilation,
        stride,
        activation,
        kernel,
        bias,
        data,
        bits=8,
        output_width=8,
        groups=1,
        debug=False,
        bypass=False,
):
    """
    Perform 2D convolution for one layer.
    """
    if verbose:
        print(f"{kernel_size[0]}x{kernel_size[1]} KERNEL(S)", end='')
        if bypass:
            print(' (BYPASS)')
        if verbose_data and not bypass:
            print(":")
            with np.printoptions(formatter={'int': '{0:4}'.format}):
                for i in range(output_channels):
                    print(f'Output channel #{i}')
                    if kernel_size[0] == kernel_size[1] == 1:
                        print(np.squeeze(kernel[i]))
                    else:
                        print(kernel[i])
        if verbose_data:
            print(f"BIAS: {bias}\n")
        elif bias is not None:
            print(f"\nBIAS SIZE: {len(bias)}")
        else:
            print('')

    out_size = [output_channels,
                (input_size[1] - dilation[0] * (kernel_size[0] - 1) - 1 +
                 2 * padding[0]) // stride[0] + 1,
                (input_size[2] - dilation[1] * (kernel_size[1] - 1) - 1 +
                 2 * padding[1]) // stride[1] + 1]

    if bias is not None:
        bias = bias * tc.dev.BIAS_DIV

    out_buf = conv2d(
        data=data,
        weight=kernel,
        bias=bias,
        input_size=input_size,
        output_size=out_size,
        kernel_size=kernel_size,
        stride=stride,
        pad=padding,
        dilation=dilation,
        fractional_stride=[1, 1],
        output_pad=[0, 0],
        groups=groups,
        debug=debug,
    )

    if verbose and verbose_data:
        print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} FULL-RES OUTPUT:")
        if out_size[1] == out_size[2] == 1:
            print(np.squeeze(out_buf))
        else:
            print(out_buf)
        print('')

    stats.macc += (input_size[0] // groups) * kernel_size[0] * kernel_size[1] * out_size[0] \
        * out_size[1] * out_size[2]

    if output_width != 32:
        out_buf = np.floor(0.5 + out_buf / (128 / 2.0**output_shift)).astype(np.int64). \
            clip(-(2**(bits-1)), 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} OUTPUT "
                  f"{'BEFORE ACTIVATION' if activation is not None else '(NO ACTIVATION)'}:")
            if out_size[1] == out_size[2] == 1:
                print(np.squeeze(out_buf))
            else:
                print(out_buf)
            print('')

    if activation is not None:
        if activation == op.ACT_RELU:
            np.clip(out_buf, 0, 2**(bits-1)-1, out_buf)
        elif activation == op.ACT_ABS:
            out_buf = np.abs(out_buf).clip(0, 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} ACTIVATED OUTPUT"
                  f" ({op.act_string(activation).upper()}):")
            if out_size[1] == out_size[2] == 1:
                print(np.squeeze(out_buf))
            else:
                print(out_buf)
            print('')

        stats.comp += out_size[0] * out_size[1] * out_size[2]

    if verbose and not verbose_data:
        print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} OUTPUT"
              f" ({op.act_string(activation).upper()})\n")

    return out_buf, out_size


def convtranspose2d_layer(
        layer,  # pylint: disable=unused-argument
        verbose,
        verbose_data,
        input_size,
        kernel_size,
        output_shift,
        output_channels,
        padding,
        dilation,
        fractional_stride,
        output_padding,
        activation,
        kernel,
        bias,
        data,
        bits=8,
        output_width=8,
        groups=1,
        debug=False,
        bypass=False,
):
    """
    Perform a fractionally strided 2D convolution for one layer.
    """
    if verbose:
        print(f"{kernel_size[0]}x{kernel_size[1]} KERNEL(S)", end='')
        if bypass:
            print(' (BYPASS)')
        if verbose_data and not bypass:
            print(':')
            with np.printoptions(formatter={'int': '{0:4}'.format}):
                for i in range(output_channels):
                    print(f'Output channel #{i}')
                    if kernel_size[0] == kernel_size[1] == 1:
                        print(np.squeeze(kernel[i]))
                    else:
                        print(kernel[i])
        if verbose_data:
            print(f"BIAS: {bias}\n")
        elif bias is not None:
            print(f"\nBIAS SIZE: {len(bias)}")
        else:
            print('')

    out_size = [output_channels,
                (input_size[1] - 1) * fractional_stride[0] - 2 * padding[0]
                + dilation[0] * (kernel_size[0] - 1)
                + output_padding[0] + 1,
                (input_size[2] - 1) * fractional_stride[1] - 2 * padding[1]
                + dilation[1] * (kernel_size[1] - 1)
                + output_padding[1] + 1]

    if bias is not None:
        bias = bias * tc.dev.BIAS_DIV

    out_buf = conv2d(
        data=data,
        weight=kernel,
        bias=bias,
        input_size=input_size,
        output_size=out_size,
        kernel_size=kernel_size,
        stride=[1, 1],
        pad=padding,
        dilation=dilation,
        fractional_stride=fractional_stride,
        output_pad=output_padding,
        groups=groups,
        debug=debug,
    )

    if verbose and verbose_data:
        print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} FULL-RES OUTPUT:")
        if out_size[1] == out_size[2] == 1:
            print(np.squeeze(out_buf))
        else:
            print(out_buf)
        print('')

    stats.macc += (input_size[0] // groups) * kernel_size[0] * kernel_size[1] * out_size[0] \
        * out_size[1] * out_size[2]

    if output_width != 32:
        out_buf = np.floor(0.5 + out_buf / (128 / 2.0**output_shift)).astype(np.int64). \
            clip(-(2**(bits-1)), 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} OUTPUT "
                  f"{'BEFORE ACTIVATION' if activation is not None else '(NO ACTIVATION)'}:")
            if out_size[1] == out_size[2] == 1:
                print(np.squeeze(out_buf))
            else:
                print(out_buf)
            print('')

    if activation is not None:
        if activation == op.ACT_RELU:
            np.clip(out_buf, 0, 2**(bits-1)-1, out_buf)
        elif activation == op.ACT_ABS:
            out_buf = np.abs(out_buf).clip(0, 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} ACTIVATED OUTPUT"
                  f" ({op.act_string(activation).upper()}):")
            if out_size[1] == out_size[2] == 1:
                print(np.squeeze(out_buf))
            else:
                print(out_buf)
            print('')

        stats.comp += out_size[0] * out_size[1] * out_size[2]

    if verbose and not verbose_data:
        print(f"{out_size[0]}x{out_size[1]}x{out_size[2]} OUTPUT"
              f" ({op.act_string(activation).upper()})\n")

    return out_buf, out_size


def conv1d_layer(
        layer,  # pylint: disable=unused-argument
        verbose,
        verbose_data,
        input_size,
        kernel_size,
        output_shift,
        output_channels,
        padding,
        dilation,
        stride,
        activation,
        kernel,
        bias,
        data,
        bits=8,
        output_width=8,
        groups=1,
        debug=False,
        bypass=False,
):
    """
    Perform 1D convolution for one layer.
    """
    if verbose:
        print(f"KERNEL SIZE {kernel_size}", end='')
        if bypass:
            print(' (BYPASS)')
        if verbose_data and not bypass:
            print(':')
            print(kernel)
        if verbose_data:
            print(f"BIAS: {bias}\n")
        elif bias is not None:
            print(f"\nBIAS SIZE: {len(bias)}")
        else:
            print('')

    out_size = [output_channels,
                (input_size[1] - dilation * (kernel_size - 1) - 1 +
                 2 * padding) // stride + 1,
                1]

    if bias is not None:
        bias = bias * tc.dev.BIAS_DIV

    out_buf = conv1d(
        data=data,
        weight=kernel,
        bias=bias,
        input_size=input_size,
        output_size=out_size,
        out_channels=output_channels,
        kernel_size=kernel_size,
        stride=stride,
        pad=padding,
        dilation=dilation,
        groups=groups,
        debug=debug,
    )

    if verbose and verbose_data:
        print(f"{out_size[0]}x{out_size[1]} FULL-RES OUTPUT:")
        print(out_buf.squeeze(axis=-1))
        print('')

    stats.macc += (input_size[0] // groups) * kernel_size * out_size[0] \
        * out_size[1]

    if output_width != 32:
        out_buf = np.floor(0.5 + out_buf / (128 / 2.0**output_shift)).astype(np.int64). \
            clip(-(2**(bits-1)), 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]} OUTPUT "
                  f"{'BEFORE ACTIVATION' if activation is not None else '(NO ACTIVATION)'}:")
            print(out_buf.squeeze(axis=-1))
            print('')

    if activation is not None:
        if activation == op.ACT_RELU:
            np.clip(out_buf, 0, 2**(bits-1)-1, out_buf)
        elif activation == op.ACT_ABS:
            out_buf = np.abs(out_buf).clip(0, 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"{out_size[0]}x{out_size[1]} ACTIVATED OUTPUT"
                  f" ({op.act_string(activation).upper()}):")
            print(out_buf.squeeze(axis=-1))
            print('')

        stats.comp += out_size[0] * out_size[1]

    if verbose and not verbose_data:
        print(f"{out_size[0]}x{out_size[1]} OUTPUT"
              f" ({op.act_string(activation).upper()})\n")

    return out_buf, out_size


def linear_layer(
        verbose,
        verbose_data,
        activation,
        weight,
        bias,
        data,
        bits=16,
        debug=False,
):
    """
    Perform one software linear layer.
    """
    in_features = data.shape[0]
    out_features = weight.shape[0]

    if verbose:
        print("CLASSIFICATION LAYER (LINEAR)...\n")
        print(f"INPUT DATA (size {in_features})", end='')
        if verbose_data:
            print(':')
            print(data)
        print('')

        print(f"WEIGHTS (size {in_features * out_features})", end='')
        if verbose_data:
            print(':')
            print(weight)
            print(f"BIAS: {bias}\n")
        elif bias is not None:
            print(f"\nBIAS SIZE: {len(bias)}")
        else:
            print('')

    out_buf = linear(data=data, weight=weight, bias=bias,
                     in_features=in_features, out_features=out_features,
                     debug=debug)
    out_buf = np.floor(0.5 + out_buf / 128).astype(np.int64). \
        clip(-(2**(bits-1)), 2**(bits-1)-1)

    if verbose and verbose_data:
        print(f"OUTPUT (size {out_features}):")
        print(out_buf)
        print('')

    stats.sw_macc += in_features * out_features

    if activation is not None:
        if activation == op.ACT_RELU:
            np.clip(out_buf, 0, 2**(bits-1)-1, out_buf)
        elif activation == op.ACT_ABS:
            out_buf = np.abs(out_buf).clip(0, 2**(bits-1)-1)

        if verbose and verbose_data:
            print(f"ACTIVATED OUTPUT (size {out_features})"
                  f" ({op.act_string(activation).upper()}):")
            print(out_buf)
            print('')

        stats.sw_comp += out_features

    if verbose and not verbose_data:
        print(f"OUTPUT (size {out_features})"
              f" ({op.act_string(activation).upper()})\n")

    return out_buf, out_features


def passthrough_layer(
        layer,  # pylint: disable=unused-argument
        verbose,  # pylint: disable=unused-argument
        verbose_data,  # pylint: disable=unused-argument
        input_size,
        data,
        debug=False,  # pylint: disable=unused-argument
):
    """
    2D passthrough for one layer.
    """

    return data, input_size


def eltwise_layer(
        operator,
        layer,  # pylint: disable=unused-argument
        verbose,
        verbose_data,
        input_size,
        output_shift,
        data,
        output_width=8,
        debug=False,
        operands=1,
):
    """
    Element-wise operators for one layer.
    """
    bits = 8
    assert operands == len(data)

    if verbose:
        print(f"{operands}-OPERAND {op.string(operator, elt=True).upper()}:\n")

    out_buf = eltwise(
        operator=operator,
        data=data,
        input_size=input_size,
        debug=debug,
    )

    if verbose and verbose_data:
        print(f"{input_size[0]}x{input_size[1]}x{input_size[2]} FULL-RES OUTPUT:")
        if input_size[1] == input_size[2] == 1:
            print(np.squeeze(out_buf))
        else:
            print(out_buf)
        print('')

    if operator in [op.ELTWISE_ADD, op.ELTWISE_SUB]:
        stats.add += (operands - 1) * out_buf.size
    elif operator == op.ELTWISE_MUL:
        stats.mul += (operands - 1) * out_buf.size
    elif operator in [op.ELTWISE_OR, op.ELTWISE_XOR]:
        stats.bitwise += (operands - 1) * out_buf.size

    if output_width != 32:
        if operator == op.ELTWISE_MUL:
            out_buf = np.floor(0.5 + out_buf / (128 / 2.0**output_shift)).astype(np.int64). \
                clip(-(2**(bits-1)), 2**(bits-1)-1)
        else:
            np.clip(out_buf, -(2**(bits-1)), 2**(bits-1)-1, out_buf)

        if verbose and verbose_data:
            print(f"{input_size[0]}x{input_size[1]}x{input_size[2]} OUTPUT:")
            if input_size[1] == input_size[2] == 1:
                print(np.squeeze(out_buf))
            else:
                print(out_buf)
            print('')

    if verbose and not verbose_data:
        print(f"{input_size[0]}x{input_size[1]}x{input_size[2]} OUTPUT")

    return out_buf, input_size


def pooling_layer(
        layer,
        verbose,
        verbose_data,
        input_size,
        pool,
        pool_stride,
        pool_average,
        data,
        debug=False,
        expand=None,
        expand_thresh=None,
        operation=None,
        operands=1,
        rounding=False,
        debug_data=None,
):
    """
    Perform pooling for one layer.
    """
    # Always apply stride
    if operation != op.CONV1D:
        pooled_size = [input_size[0],
                       (input_size[1] + pool_stride[0] - pool[0]) // pool_stride[0],
                       (input_size[2] + pool_stride[1] - pool[1]) // pool_stride[1]]
    else:
        pooled_size = [input_size[0],
                       (input_size[1] + pool_stride[0] - pool[0]) // pool_stride[0]]

    # Actual pooling operation?
    if pool[0] > 1 or pool[1] > 1:
        if operation != op.CONV1D:
            pooled = np.empty((operands, pooled_size[0], pooled_size[1], pooled_size[2]),
                              dtype=np.int64)
            for i in range(operands):
                if debug_data is not None:
                    for j in range(input_size[0]):
                        np.savetxt(os.path.join(debug_data, f"unpooled-{i}-L{layer}-ch{j}.csv"),
                                   data[i][j, :, :], delimiter=",")
                pooled[i] = pool2d(
                    data[i],
                    input_size,
                    pooled_size,
                    pool,
                    pool_stride,
                    pool_average,
                    floor=not rounding,
                    debug=debug
                )
                if verbose:
                    print_data(
                        verbose_data,
                        f"{pool[0]}x{pool[1]} {'AVERAGE' if pool_average else 'MAX'} "
                        f"POOLING, STRIDE {pool_stride[0]}/{pool_stride[1]} "
                        f"{input_size} -> {pooled_size}"
                        + (f", POOLED DATA {i}" if operands > 1 else ""),
                        pooled[i],
                        pooled_size,
                        expand,
                        expand_thresh,
                    )
                if debug_data is not None:
                    for j in range(pooled_size[0]):
                        np.savetxt(os.path.join(debug_data, f"pooled-{i}-L{layer}-ch{j}.csv"),
                                   pooled[i][j, :, :], delimiter=",")

            st = pool[0] * pool[1] * pooled_size[0] * pooled_size[1] * pooled_size[2] * operands
            if pool_average:
                stats.add += st
            else:
                stats.comp += st
        else:
            pooled = pool1d(
                data[0],
                input_size,
                pooled_size,
                pool[0],
                pool_stride[0],
                pool_average,
                floor=not rounding,
                debug=debug,
            )
            if verbose:
                print(f"{pool[0]} {'AVERAGE' if pool_average else 'MAX'} "
                      f"POOLING, STRIDE {pool_stride[0]} "
                      f"{input_size} -> {pooled_size}", end='')
                if verbose_data:
                    print(':')
                    print(pooled)
                print('')

            if pool_average:
                stats.add += pool[0] * pooled_size[0] * pooled_size[1]
            else:
                stats.comp += pool[0] * pooled_size[0] * pooled_size[1]

            pooled = np.expand_dims(pooled, axis=0)

    else:
        # Use pool_stride only
        if operation != op.CONV1D:
            pooled = data[:, :, ::pool_stride[0], ::pool_stride[1]]
            if pool_stride[0] > 1 or pool_stride[1] > 1:
                if verbose:
                    print(f"{pool[0]}x{pool[1]} {'AVERAGE' if pool_average else 'MAX'} "
                          f"POOLING, STRIDE {pool_stride[0]}/{pool_stride[1]} "
                          f"{input_size} -> {pooled_size}", end='')
                    if verbose_data:
                        print(':')
                        print(pooled)
                    print('')
        else:
            pooled = data[:, :, ::pool_stride[0]]
            if pool_stride[0] > 1:
                if verbose:
                    print(f"{pool[0]} {'AVERAGE' if pool_average else 'MAX'} "
                          f"POOLING, STRIDE {pool_stride[0]} "
                          f"{input_size} -> {pooled_size}", end='')
                    if verbose_data:
                        print(':')
                        print(pooled)
                    print('')

    return pooled, pooled_size


def show_data(
        layer,
        verbose,
        verbose_data,
        input_size,
        data,
        debug=False,  # pylint: disable=unused-argument
        expand=None,
        expand_thresh=None,
        operation=None,
        operands=1,
):
    """
    Show input data.
    """
    if verbose:
        if expand_thresh is None:
            expand_thresh = input_size[0]

        if operation != op.CONV1D:
            if operands == 1:
                op_string = f"LAYER {layer} ({op.string(operation).upper()})...\n"
            else:
                op_string = f"LAYER {layer} ({op.string(operation).upper()}, " \
                            f"{operands} OPERANDS)...\n"
            print(op_string)

            if operands == 1:
                print_data(verbose_data,
                           f"{data.shape[1]}x{data.shape[2]}x{data.shape[3]} INPUT DATA",
                           data[0],
                           [data.shape[1], data.shape[2], data.shape[3]],
                           expand,
                           expand_thresh)
            else:
                for i in range(operands):
                    print_data(verbose_data,
                               f"{data.shape[1]}x{data.shape[2]}x{data.shape[3]} INPUT DATA {i}",
                               data[i],
                               [data.shape[1], data.shape[2], data.shape[3]],
                               expand,
                               expand_thresh)
        else:
            print(f"LAYER {layer} ({op.string(operation).upper()})...\n")
            print(f"{input_size[1]}x{input_size[2]} INPUT DATA", end='')
            if verbose_data:
                print(':')
                print(np.squeeze(data))
            print('')
