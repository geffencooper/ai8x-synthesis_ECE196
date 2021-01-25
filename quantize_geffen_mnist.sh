#!/bin/sh
./quantize.py trained/geffen_mnist.pth.tar trained/geffen_mnist.pth.tar --device MAX78000 -v -c networks/mnist-chw-ai85.yaml --scale 0.85 "$@"
