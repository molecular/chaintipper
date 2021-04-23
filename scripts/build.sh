#!/bin/bash
cd $(dirname $0)/..

pyrcc5 qresources.qrc > qresources.py
