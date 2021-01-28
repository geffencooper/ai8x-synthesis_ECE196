###################################################################################################
# Copyright (C) Maxim Integrated Products, Inc. All Rights Reserved.
#
# Maxim Integrated Products, Inc. Default Copyright Notice:
# https://www.maximintegrated.com/en/aboutus/legal/copyrights.html
###################################################################################################
"""
Bias related functions
"""
import numpy as np

from . import tornadocnn as tc
from .eprint import eprint, wprint
from .utils import argmin, ffs, fls, popcount

_INVALID_VALUE = -(2**63)


def load(
        verbose,  # pylint: disable=unused-argument
        embedded_code,
        apb,
        start_layer,
        layers,
        bias,
        group_map,
        output_chan,
        streaming,
        conv_groups,
        broadcast_mode,
        processor_map,
        output_processor_map,
        out_expand,
        debug,  # pylint: disable=unused-argument
):
    """
    Write `bias` values for the network to C code.
    """
    # Bias: Each group has one bias memory (size BIAS_SIZE bytes). Use only the bias memory in
    # one selected group for the layer, and only if the layer uses a bias. Keep track of the
    # offsets so they can be programmed into the mask count register later.

    if embedded_code:
        bias_values = np.zeros((tc.dev.P_NUMGROUPS, tc.dev.BIAS_SIZE), dtype=np.int64)

    if not embedded_code:
        apb.function_header(function='load_bias')

    group_bias_max = [0] * tc.dev.P_NUMGROUPS
    bias_offs = [[None] * tc.dev.P_NUMGROUPS for _ in range(layers)]
    bias_group = [None] * layers
    for ll in range(start_layer, layers):
        if bias[ll] is None or group_map[ll] is None:
            continue
        if len(bias[ll]) != output_chan[ll]:
            eprint(f'Layer {ll}: output channel count {output_chan[ll]} does not match the number '
                   f'of bias values {len(bias[ll])}.')
        if not np.any(bias[ll] != 0):
            wprint(f'Layer {ll}: All bias values are zero. Ignoring the input.')
            continue

        # Round up the divided length of bias values
        target_offs = ffs(output_processor_map[ll]) % tc.dev.P_SHARED * out_expand[ll]
        bias_len = output_chan[ll] + target_offs

        if ll == 0 and streaming[ll] and not tc.dev.SUPPORT_STREAM_BIAS:
            # Work around a problem on AI85
            bias_len += 1
        if streaming[ll] and not tc.dev.SUPPORT_STREAM_BIAS:
            wprint(f'Layer {ll} uses streaming and a bias. '
                   'THIS COMBINATION MIGHT NOT BE FUNCTIONING CORRECTLY!!!')

        if conv_groups[ll] == 1:
            # Pick the group with the least amount of data in it
            group = argmin(group_bias_max[t] for t in group_map[ll])
            if group_bias_max[group] + bias_len > tc.dev.BIAS_SIZE:
                eprint(f'Layer {ll}: bias memory capacity exceeded - available groups: '
                       f'{group_map[ll]}, used so far: {group_bias_max}, needed: {bias_len}.')
            bias_group[ll] = group
            for i in range(tc.dev.P_NUMGROUPS):
                bias_offs[ll][i] = group_bias_max[group]
            # Each layer has output_channel number of bias values
            i = 0
            if ll == 0 and streaming[ll] and not tc.dev.SUPPORT_STREAM_BIAS:
                # Work around a problem on AI85
                if not embedded_code:
                    apb.write_bias(group, bias_offs[ll][group], 0)
                else:
                    # Store for later
                    bias_values[group][bias_offs[ll][group]] = 0
                target_offs += 1
            while i < output_chan[ll]:
                if not embedded_code:
                    apb.write_bias(group, bias_offs[ll][group] + target_offs, bias[ll][i] & 0xff)
                else:
                    # Store for later
                    bias_values[group][bias_offs[ll][group] + target_offs] = bias[ll][i] & 0xff
                i += 1
                target_offs += 1
            group_bias_max[group] += bias_len
        else:
            # Each group needs to have 'its own' bias values
            bias_group[ll] = 'all'

            def bias_add_byte(layer, group, val):
                """
                Add a single bias byte `val` to the memory in `group`.
                """
                assert 0 <= group < tc.dev.P_NUMGROUPS_ALL
                if group_bias_max[group] >= tc.dev.BIAS_SIZE:
                    eprint(f'Layer {layer}: bias memory capacity for group {group} exceeded, '
                           f'used so far: {group_bias_max[group]}.')

                if val is not None and val != _INVALID_VALUE:  # else just consume the space
                    if not embedded_code:
                        apb.write_bias(group, group_bias_max[group], val & 0xff)
                    else:
                        # Store for later
                        bias_values[group][group_bias_max[group]] = val & 0xff
                group_bias_max[group] += 1

            used_groups = 0
            for group in range(tc.dev.P_NUMGROUPS):
                if processor_map[ll] >> group * tc.dev.P_NUMPRO & (2**tc.dev.P_NUMPRO - 1):
                    if broadcast_mode[ll]:  # Round up so we can use all groups in parallel
                        group_bias_max[group] = (group_bias_max[group] + 3) & ~3
                    bias_offs[ll][group] = group_bias_max[group]
                    used_groups += 1
                else:
                    bias_offs[ll][group] = None

            map_used = processor_map[ll]
            if not broadcast_mode[ll]:
                # The first gap is 'moved' to the end of the group
                start_proc = ffs(map_used)
                first_group = start_proc // tc.dev.P_NUMPRO
                map_used &= ~((2**tc.dev.P_NUMPRO - 1) << first_group * tc.dev.P_NUMPRO)
                map_used |= (processor_map[ll] & (((2**tc.dev.P_NUMPRO - 1) <<
                             (first_group * tc.dev.P_NUMPRO)))) >> start_proc % tc.dev.P_NUMPRO

            start_proc = ffs(map_used)
            if broadcast_mode[ll] or used_groups > 1:
                # Pad out to allow for parallel read from the 8-bit memories
                start_proc &= ~(2**tc.dev.P_NUMPRO - 1)
            last_proc = fls(map_used)

            # Break bias into multiple passes
            bias_pad = bias[ll].copy()
            leftover = (out_expand[ll] - len(bias_pad) % out_expand[ll]) % out_expand[ll]
            if leftover != 0:
                # Odd length with leftover unused values
                bias_pad = np.append(bias_pad, np.array([_INVALID_VALUE] * leftover))
            bias_pad = bias_pad.reshape(out_expand[ll], -1)

            assert bias_pad.shape[1] == popcount(processor_map[ll])

            # Insert 'None' elements where processors are not used. This is not needed at the end,
            # and additionally, not needed at the start but only when only one group is used and
            # when not in broadcast mode.

            # Start inserting from the left so the `proc` index will match the bias array
            # Skip last_proc since we already know it is used (do not skip start since it could be
            # unused)
            for proc in range(start_proc, last_proc):
                if map_used >> proc & 1 == 0:
                    bias_pad = np.insert(bias_pad, proc,
                                         np.array([_INVALID_VALUE] * out_expand[ll]), axis=1)

            for expand in range(out_expand[ll]):
                for p in range(start_proc, last_proc + 1):
                    group = p // tc.dev.P_NUMPRO
                    src = (p & ~0x0f) + (p % 4) * 4 + (p % 16) // 4 if broadcast_mode[ll] else p
                    val = bias_pad[expand][src - start_proc] \
                        if src - start_proc < bias_pad.shape[1] else None
                    # Add value, even if it's None (except the very tail end)
                    if expand < out_expand[ll] - 1 or p <= last_proc - leftover:
                        bias_add_byte(ll, group, val)

    if embedded_code:
        if max(group_bias_max) > 0:
            # At least one bias value exists, output defines
            for group in range(tc.dev.P_NUMGROUPS):
                if group_bias_max[group] == 0:
                    continue  # but not for this group
                apb.output_define(bias_values[group][:group_bias_max[group]], f'BIAS_{group}',
                                  '0x%02x', 16)
            # Output variables
            for group in range(tc.dev.P_NUMGROUPS):
                if group_bias_max[group] == 0:
                    continue
                apb.output(f'static const uint8_t bias_{group}[] = BIAS_{group};\n', embedded_code)
            apb.output('\n', embedded_code)

            # Finally, create function and do memcpy()
            apb.function_header(prefix='', function='memcpy_8to32', return_type='static void',
                                arguments='uint32_t *dst, const uint8_t *src, int n')
            apb.output('  while (n-- > 0) {\n    *dst++ = *src++;\n  }\n', embedded_code)
            apb.function_footer(return_value='void')

            apb.function_header(function='load_bias')
            for group in range(tc.dev.P_NUMGROUPS):
                if group_bias_max[group] == 0:
                    continue
                addr = apb.apb_base + tc.dev.C_GROUP_OFFS*group + tc.dev.C_BRAM_BASE
                apb.output(f'  memcpy_8to32((uint32_t *) 0x{addr:08x}, bias_{group}, '
                           f'sizeof(uint8_t) * {group_bias_max[group]});\n', embedded_code)
        else:
            apb.function_header(function='load_bias')
            apb.output('  // Not used in this network', embedded_code)

    apb.function_footer()  # load_bias()

    return bias_offs, bias_group, group_bias_max
