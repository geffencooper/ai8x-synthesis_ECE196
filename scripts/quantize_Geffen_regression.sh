#!/bin/sh
./quantize.py trained/mini_vgg_net_bb.pth.tar trained/mini_vgg_net_bb_q.pth.tar --device MAX78000 -v "$@"
