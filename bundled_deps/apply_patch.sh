#!/bin/sh
pushd $(pwd)
cd $(dirname $0)

# create copy of libs in "patched" folder
rm -rf patched
mkdir -p patched
cp -ar praw prawcore websocket iterators patched


# patch the copy in "patched" folder
echo "patching praw to use relative imports and include praw.ini contets as string...."
cd patched
patch -p1 < ../patch_praw_relative_imports.patch 

# for running as internal plugin copy the libs to main code folder
#cp -r praw prawcore websocket iterators ../..

popd
