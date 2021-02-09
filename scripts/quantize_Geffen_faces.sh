#!/bin/sh
./quantize.py trained/geffen_classifier.pth.tar trained/geffen_classifier_q.pth.tar --device MAX78000 -v "$@"
