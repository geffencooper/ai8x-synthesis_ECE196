#!/bin/sh
./quantize.py trained/geffnet.pth.tar trained/geffnet_q.pth.tar --device MAX78000 -v "$@"
