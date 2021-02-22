#!/bin/sh
./quantize.py trained/mini_vgg_net.pth.tar trained/mini_vgg_net_q.pth.tar --device MAX78000 -v "$@"
