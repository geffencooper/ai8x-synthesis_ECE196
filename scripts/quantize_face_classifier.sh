#!/bin/sh
./quantize.py trained/test.pth.tar trained/test_q.pth.tar --device MAX78000 -v "$@"
