#!/bin/sh
./quantize.py trained/eyes.pth.tar trained/eyes_q.pth.tar --device MAX78000 -v "$@"