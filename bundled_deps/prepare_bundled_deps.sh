#!/bin/bash
cd $(dirname $0)

# download dependency packages (got links from pypy.org)

rm -rf praw*gz websocket_client*gz
wget "https://files.pythonhosted.org/packages/63/f6/8bbd6893922c388ee53247529c66154fe4f3662d4fba9c26a78d7915cd51/praw-7.2.0.tar.gz"
wget "https://files.pythonhosted.org/packages/23/08/e2f19da55b7a74652f9ad66fc9f8ef1ebae234e56e5e6fe10b62517da7d1/prawcore-2.0.0.tar.gz"
wget "https://files.pythonhosted.org/packages/4a/df/112c278ba1ead96786d24d973429ce1e1a2c86b9843183d9f8ef8c6330d7/websocket_client-0.58.0.tar.gz"

# verify sha256 sums of downloaded files

sha256sum *.tar.gz > actual_sums.txt
if not diff actual_sums.txt target_sums.txt; then
	echo "ERROR checksum mismatch or download failed."
	exit 1
fi
echo "checksums match, unpacking..."

# unpack packages and get the library code from the packages

tar -xzf praw-7.2.0.tar.gz praw-7.2.0/praw 
rm -rf praw
mv praw-7.2.0/praw .
rm -rf praw-7.2.0

tar -xzf prawcore-2.0.0.tar.gz prawcore-2.0.0/prawcore 
rm -rf prawcore
mv prawcore-2.0.0/prawcore .
rm -rf prawcore-2.0.0

tar -xzf websocket_client-0.58.0.tar.gz websocket_client-0.58.0/websocket
rm -rf websocket
mv websocket_client-0.58.0/websocket .
rm -rf websocket_client-0.58.0

# apply patches

echo "patching praw to use relative imports and include praw.ini contets as string...."
patch -p1 < patch_praw_relative_imports.patch 

# for running as internal plugin:
#cp -r praw prawcore websocket ..
