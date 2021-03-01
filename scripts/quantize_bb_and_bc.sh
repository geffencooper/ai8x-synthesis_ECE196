#!/bin/sh
./quantize.py trained/bb_and_bc.pth.tar trained/bb_and_bc_q.pth.tar --device MAX78000 -v "$@"