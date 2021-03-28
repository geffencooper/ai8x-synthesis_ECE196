#!/bin/sh
./quantize.py trained/simplemnist.pth.tar trained/simplemnist_q.pth.tar --device MAX78000 -v "$@"
