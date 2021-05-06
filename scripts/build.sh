#!/bin/bash
pushd $(pwd)
cd $(dirname $0)/..

pyrcc5 qresources.qrc > qresources.py

bundled_deps/download_check_unpack_bundled_deps.sh
bundled_deps/applay_patch.sh # results in patched deps in bundled_deps/patched/

popd
