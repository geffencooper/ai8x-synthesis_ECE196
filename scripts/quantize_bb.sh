#!/bin/sh
./quantize.py trained/bb.pth.tar trained/bb_q.pth.tar --device MAX78000 -v "$@"