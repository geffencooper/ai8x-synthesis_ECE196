###################################################################################################
# Copyright (C) Maxim Integrated Products, Inc. All Rights Reserved.
#
# Maxim Integrated Products, Inc. Default Copyright Notice:
# https://www.maximintegrated.com/en/aboutus/legal/copyrights.html
###################################################################################################
"""
Unload AI8X HWC memory into standard representation.
"""
from . import toplevel
from . import tornadocnn as tc
from .eprint import eprint, wprint
from .utils import ffs, popcount


def unload(
        memfile,
        apb_base,
        processor_map,
        input_shape,
        out_offset,
        out_expand,
        out_expand_thresh,
        output_width=8,
        mlator=False,
        blocklevel=False,
):
    """
    Unload HWC memory from hardware, writing C code to the `memfile` handle.
    The generated C code is specific to the network configuration passed in in `processor_map`,
    and `input_shape`. Additionally, the generated addresses are offset by `apb_base` and
    `out_offset`. The C code function takes a pointer to a memory array, and the depth of
    the array does not matter (flattened or not flattened) as long as the size is correct.
    When `mlator` is set, use the hardware mechanism to rearrange 4-channel data into single
    channels.
    """
    assert not blocklevel or not mlator

    memfile.write('// Custom unload for this network: '
                  f'{output_width}-bit data, shape: {input_shape}\n')
    toplevel.function_header(memfile, function='unload',
                             arguments=f'uint32_t *out_buf{"32" if output_width != 32 else ""}')
    memfile.write('  volatile uint32_t *addr;\n')
    if output_width != 32:
        memfile.write(f'  uint{output_width}_t *out_buf = (uint{output_width}_t *) out_buf32;\n')
        if input_shape[1] * input_shape[2] == 1:
            memfile.write('  uint32_t val;\n\n')
        else:
            memfile.write('  uint32_t val, offs;\n\n')

    coffs_start = ffs(processor_map) & ~(tc.dev.P_SHARED-1)
    coffs = coffs_start
    poffs = coffs_start
    next_layer_map_init = processor_map >> coffs
    next_layer_map = next_layer_map_init

    # Output expansion for channels and/or wide output
    out_size = output_width // 8
    width = out_expand * out_size

    read_addr = None
    write_addr = None
    mlat_addr = None
    c = 0
    while c < input_shape[0]:
        if c % out_expand_thresh == 0:
            poffs = coffs_start
            next_layer_map = next_layer_map_init

        expand = c // out_expand_thresh  # Channels 64+ handled by processors 0+
        proc = poffs & ~(tc.dev.P_SHARED-1)

        if not mlator or out_size > 1:
            for doffs in range(input_shape[1] * input_shape[2]):
                row, col = divmod(doffs, input_shape[2])
                this_map = next_layer_map
                this_c = c

                # Get four bytes from memory array
                offs = out_offset + \
                    (((proc % tc.dev.P_NUMPRO) * tc.dev.INSTANCE_SIZE |
                      (proc // tc.dev.P_NUMPRO) * tc.dev.C_GROUP_OFFS // 4) +
                     doffs * width + expand * out_size) * 4

                if offs != read_addr:
                    memfile.write('  addr = (volatile uint32_t *) '
                                  f'0x{apb_base + tc.dev.C_SRAM_BASE + offs:08x};\n')
                if out_size != 4:
                    memfile.write('  val = *addr++;\n')
                    read_addr = offs + 4
                else:
                    read_addr = offs

                # Singulate bytes, ignoring unused processors
                for shift in range(4):
                    addr = this_c * input_shape[1] * input_shape[2] + row * input_shape[1] + col
                    if (shift == 0 or out_size > 1) \
                       and out_size != 4 and input_shape[1] * input_shape[2] != 1:
                        if addr != write_addr:
                            memfile.write(f'  offs = 0x{addr:04x};\n')
                        else:
                            memfile.write('  offs++;\n')
                        write_addr = addr + 1
                    if this_map & 1:
                        if out_size != 4:
                            if input_shape[1] * input_shape[2] != 1:
                                memfile.write('  out_buf[offs')
                                if shift > 0:
                                    memfile.write(f'+0x{0x10 * shift:02x}')
                                memfile.write('] = ')
                            else:
                                memfile.write('  *out_buf++ = ')
                            if shift == 0:
                                memfile.write('val')
                            else:
                                memfile.write(f'(val >> {shift * 8})')
                            if out_size == 1:
                                memfile.write(' & 0xff;\n')
                            else:
                                memfile.write(';\n')
                        else:  # out_size == 4
                            memfile.write('  *out_buf++ = *addr++;\n')
                            write_addr = addr + 4
                            read_addr += 4

                        this_c += 1
                    this_map >>= 1
        else:  # mlator
            assert out_size == 1
            this_map = next_layer_map
            mlat = tc.ctl_addr(proc // tc.dev.P_NUMPRO, tc.dev.REG_MLAT)
            ctrl = tc.ctl_addr(proc // tc.dev.P_NUMPRO, tc.dev.REG_CTL)
            if mlat_addr != mlat:
                mlat_addr = mlat
                memfile.write(f'  ctrl = (volatile uint32_t *) 0x{ctrl:08x};\n')
                memfile.write(f'  mlat = (volatile uint32_t *) 0x{mlat:08x};\n')

            this_c = c
            for shift in range(4):
                if this_map & 1:
                    memfile.write(f'  // Channel {this_c}\n')

                    for doffs in range(0, input_shape[1] * input_shape[2], 4):
                        row, col = divmod(doffs, input_shape[2])

                        # Get four bytes from memory
                        source = out_offset + \
                            (((proc % tc.dev.P_NUMPRO) * tc.dev.INSTANCE_SIZE |
                              (proc // tc.dev.P_NUMPRO) * tc.dev.C_GROUP_OFFS // 4) +
                             (doffs >> 2) * width + expand * out_size) * 4
                        target = this_c * input_shape[1] * input_shape[2] \
                            + row * input_shape[1] + col
                        assert target & 3 == 0

                        if target != write_addr:
                            memfile.write(f'  offs = 0x{target >> 2:04x};\n')
                        if source != read_addr:
                            if doffs != 0:
                                memfile.write(f'  *ctrl = 0x{tc.dev.READY_SEL << 1 | 1 << 3:08x}; '
                                              '// Disable mlator\n')
                            # Set wptr to start address
                            val = tc.lreg_addr(proc // tc.dev.P_NUMPRO, tc.dev.LREG_WPTR_BASE)
                            memfile.write(f'  *((volatile uint32_t *) 0x{val:08x}) = '
                                          f'0x{doffs:08x}; // Set SRAM address\n')
                            # Set wptr_inc to set increment value (default: 1)
                            val = tc.lreg_addr(proc // tc.dev.P_NUMPRO, tc.dev.LREG_LCTL2)
                            memfile.write(f'  *((volatile uint32_t *) 0x{val:08x}) = '
                                          f'0x{expand:08x}; // Set pointer increment\n')
                            # Set mlatorld enable bit to load write ptr; select byte 0..3
                            val = tc.dev.READY_SEL << 1 | 1 << 16 | shift << 17 | 1 << 3
                            memfile.write(f'  *ctrl = 0x{val:08x}; '
                                          f'// Enable mlator, byte {shift}\n')
                            # memfile.write('  val = *mlat; // Prime\n')
                            memfile.write('  asm volatile ("" : "=m" (*mlat) : "r" (*mlat));'
                                          ' // Prime\n')

                        # FIXME: Do not write more than `num_bytes = min(4, input_shape[2] - col)`
                        memfile.write(f'  out_buf{"32" if out_size != 32 else ""}[offs++] = *mlat;'
                                      f' // {this_c},{row},{col}-{col+3}\n')
                        read_addr = source + 4
                        write_addr = target + 4

                    # Disable mlator
                    memfile.write(f'  *ctrl = 0x{tc.dev.READY_SEL << 1 | 1 << 3:08x}; '
                                  '// Disable mlator\n')
                this_c += 1

                this_map >>= 1

        coffs += 4
        poffs += 4
        c += popcount(next_layer_map & 0x0f)
        next_layer_map >>= 4

    toplevel.function_footer(memfile)  # unload()


def verify(
        verify_fn,
        ll,
        in_map,
        out_map,
        out_buf,
        processor_map,
        input_shape,
        out_offset,
        out_expand,
        out_expand_thresh,
        output_width=8,
        overwrite_ok=False,
        no_error_stop=False,
        mlator=False,
        apb_base=0,
        stream=None,
        max_count=None,
        write_gap=0,
        final_layer=0,
):
    """
    Verify HWC memory from AI8X, writing C or mem code using the `verify_fn` function.
    The generated code is specific to the network configuration passed in in `processor_map`,
    and `input_shape`. Additionally, the generated addresses are offset by
    `out_offset`. The function takes a pointer to a memory array, and the depth of
    the array does not matter (flattened or not flattened) as long as the size is correct.
    `in_map` and `out_map` are used to optionally prevent overwriting data
    (controlled by `overwrite_ok` and `no_error_stop`).
    When `mlator` is set, use the hardware mechanism to rearrange 4-channel data into single
    channels.
    """
    count = 0

    def check_overwrite(
            p,
            target_offs,
            in_map,
            out_map,
            c,
            row,
            col,
    ):
        # If using single layer, make sure we're not overwriting the input
        if (not overwrite_ok) and in_map[target_offs >> 2] is not None:
            old_ll, old_c, old_row, old_col, _ = in_map[target_offs >> 2]
            old_layer = f'layer {old_ll}' if old_ll >= 0 else 'the input loader'
            eprint(f'Processor {p}: '
                   f'Layer {ll} output for CHW={c},{row},{col} is overwriting '
                   f'input at offset 0x{target_offs:08x} that was created by '
                   f'{old_layer}, CHW={old_c},{old_row},{old_col}.',
                   error=not no_error_stop)
        # Check we're not overflowing the data memory
        if (not overwrite_ok) and out_map is not None and out_map[target_offs >> 2] is not None:
            old_ll, old_c, old_row, old_col, old_val = out_map[target_offs >> 2]
            eprint(f'Processor {p}: '
                   f'Layer {ll} output for CHW={c},{row},{col} is overwriting '
                   f'offset 0x{target_offs:08x}. Previous write by '
                   f'layer {old_ll},CHW={old_c},{old_row},{old_col} with value 0x{old_val:08x}.',
                   error=not no_error_stop)

    # Start at the instance of the first active output processor/channel
    coffs_start = ffs(processor_map) & ~(tc.dev.P_SHARED-1)
    next_layer_map = processor_map >> coffs_start
    # Output expansion for channels and/or wide output
    out_size = output_width // 8
    width = out_expand * out_size

    if not mlator or out_size > 1:
        if mlator:
            wprint('ignoring --mlator for 32-bit output.')

        for doffs in range(input_shape[1] * input_shape[2]):
            row, col = divmod(doffs, input_shape[2])
            this_map = next_layer_map
            coffs = coffs_start
            poffs = coffs_start
            c = 0
            while c < input_shape[0]:
                if c % out_expand_thresh == 0:
                    poffs = coffs_start
                    this_map = next_layer_map  # Wrap around for AI85 channel expansion

                this_c = c
                expand = c // out_expand_thresh  # Channels 64+ handled by processors 0+
                # Physical offset into instance and group
                proc = poffs & ~(tc.dev.P_SHARED-1)

                # Get four bytes or words either from output or zeros and construct HWC word
                no_data = True
                if out_size == 1:
                    val = 0
                    for _ in range(4):
                        val >>= 8
                        if this_map & 1:
                            no_data = False
                            if c < input_shape[0]:
                                val |= (out_buf[c][row][col] & 0xff) << 24
                            c += 1
                        this_map >>= 1
                else:
                    val = [0] * 4
                    for i in range(4):
                        if this_map & 1:
                            no_data = False
                            if c < input_shape[0]:
                                val[i] = out_buf[c][row][col] & 0xffffffff
                            c += 1
                        this_map >>= 1

                # Get the offset of the first output byte/word of 4
                offs = tc.dev.C_SRAM_BASE + out_offset + \
                    (((proc % tc.dev.P_NUMPRO) * tc.dev.INSTANCE_SIZE |
                      (proc // tc.dev.P_NUMPRO) * tc.dev.C_GROUP_OFFS // 4) +
                     (doffs * width + expand * out_size) * (write_gap + 1)) * 4

                if not no_data:
                    num_bytes = min(c - this_c, input_shape[0] - this_c)
                    if out_size == 1:
                        check_overwrite(
                            proc,
                            offs,
                            in_map,
                            out_map,
                            this_c,
                            row,
                            col,
                        )
                        if out_map is not None:
                            out_map[offs >> 2] = (ll, this_c, row, col, val)
                        if max_count is None or count < max_count:
                            verify_fn(
                                offs,
                                val,
                                rv=False,
                                comment=f' // {row},{col},{this_c}-{this_c+num_bytes-1}',
                                num_bytes=num_bytes,
                                first_proc=ffs(processor_map >> proc) % 4,
                                data=ll == final_layer,
                            )
                    else:
                        for i in range(min(num_bytes, out_size)):
                            check_overwrite(
                                proc,
                                offs,
                                in_map,
                                out_map,
                                this_c,
                                row,
                                col,
                            )
                            if out_map is not None:
                                out_map[offs >> 2] = (ll, this_c, row, col, val[i])
                            if max_count is None or count < max_count:
                                verify_fn(
                                    offs,
                                    val[i],
                                    rv=False,
                                    comment=f' // {row},{col},{this_c+i}',
                                    data=ll == final_layer,
                                )
                            offs += out_size
                    count += 1
                    if count == max_count and stream is not None:
                        stream.write('  // Truncated further checks...\n')

                coffs += 4
                poffs += 4
    else:  # mlator == True
        assert out_size == 1
        c = 0
        poffs = coffs_start
        this_map = next_layer_map
        read_addr = None

        while c < input_shape[0]:
            if c % out_expand_thresh == 0:
                poffs = coffs_start  # Wrap around for AI85 channel expansion
                this_map = next_layer_map

            expand = c // out_expand_thresh  # Channels 64+ handled by processors 0+
            # Physical offset into instance and group
            proc = poffs & ~(tc.dev.P_SHARED-1)

            mlat = tc.ctl_addr(proc // tc.dev.P_NUMPRO, tc.dev.REG_MLAT)
            ctrl = tc.ctl_addr(proc // tc.dev.P_NUMPRO, tc.dev.REG_CTL)

            for shift in range(4):
                if this_map & 1:
                    for doffs in range(0, input_shape[1] * input_shape[2], 4):
                        row, col = divmod(doffs, input_shape[2])

                        # Get four bytes or words either from output or zeros and
                        # construct HWC word
                        val = 0
                        for i in range(4):
                            val >>= 8
                            if col+i < input_shape[2]:
                                val |= (out_buf[c][row][col+i] & 0xff) << 24

                        # Get the offset of the first output byte/word of 4
                        source = out_offset + \
                            (((proc % tc.dev.P_NUMPRO) * tc.dev.INSTANCE_SIZE |
                              (proc // tc.dev.P_NUMPRO) * tc.dev.C_GROUP_OFFS // 4) +
                             (doffs >> 2) * width) * 4

                        if source != read_addr:
                            if doffs != 0:
                                stream.write(f'  *((volatile uint32_t *) '
                                             f'0x{apb_base + ctrl:08x}) = '
                                             f'0x{tc.dev.READY_SEL << 1 | 1 << 3:08x}; '
                                             '// Disable mlator\n')
                            # Set wptr to start address
                            w = apb_base + tc.lreg_addr(proc // tc.dev.P_NUMPRO,
                                                        tc.dev.LREG_WPTR_BASE)
                            stream.write(f'  *((volatile uint32_t *) 0x{w:08x}) = '
                                         f'0x{source >> 2:08x}; // Set SRAM address\n')
                            # Set wptr_inc to set increment value (default: 1)
                            w = apb_base + tc.lreg_addr(proc // tc.dev.P_NUMPRO,
                                                        tc.dev.LREG_LCTL2)
                            stream.write(f'  *((volatile uint32_t *) 0x{w:08x}) = '
                                         f'0x{expand:08x}; // Set pointer increment\n')
                            # Set mlatorld enable bit to load write ptr; select byte 0..3
                            w = tc.dev.READY_SEL << 1 | 1 << 16 | shift << 17 | 1 << 3
                            stream.write(f'  *((volatile uint32_t *) 0x{apb_base + ctrl:08x}) ='
                                         f' 0x{w:08x}; '
                                         f'// Enable mlator, byte {shift}\n')
                            stream.write('  asm volatile ("" : "=m" (*((volatile uint32_t *) '
                                         f'0x{apb_base + mlat:08x})) : "r" '
                                         f'(*((volatile uint32_t *) 0x{apb_base + mlat:08x})));'
                                         ' // Prime\n')

                        num_bytes = min(4, input_shape[2] - col)
                        check_overwrite(
                            proc,
                            tc.dev.C_SRAM_BASE + source,
                            in_map,
                            out_map,
                            c,
                            row,
                            col,
                        )
                        if out_map is not None:
                            out_map[source >> 2] = (ll, c, row, col, val)
                        verify_fn(
                            mlat,
                            val,
                            rv=False,
                            comment=f' // {row},{col}-{col+num_bytes-1},{c}',
                            num_bytes=num_bytes,
                            data=ll == final_layer,
                        )

                        read_addr = source + 4
                    # Disable mlator
                    stream.write(f'  *((volatile uint32_t *) '
                                 f'0x{apb_base + ctrl:08x}) = '
                                 f'0x{tc.dev.READY_SEL << 1 | 1 << 3:08x}; '
                                 '// Disable mlator\n')

                this_map >>= 1
                c += 1

            poffs += 4
