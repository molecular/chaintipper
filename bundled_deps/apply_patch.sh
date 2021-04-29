#!/bin/sh
cd $(dirname $0)

# apply patches
echo "patching praw to use relative imports and include praw.ini contets as string...."
patch -p1 < patch_praw_relative_imports.patch 

# for running as internal plugin:
#cp -r praw prawcore websocket ..
