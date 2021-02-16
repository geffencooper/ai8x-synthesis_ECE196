#!/bin/sh
./quantize.py trained/regression.pth.tar trained/regression_q.pth.tar --device MAX78000 -v "$@"
