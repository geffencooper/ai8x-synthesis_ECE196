#!/bin/sh
./quantize.py trained/test2.pth.tar trained/test2_q.pth.tar --device MAX78000 -v "$@"