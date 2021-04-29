#!/bin/bash
pushd $(pwd)
cd $(dirname $0)/..

pyrcc5 qresources.qrc > qresources.py

bundled_deps/prepare_bundled_deps.sh

popd
