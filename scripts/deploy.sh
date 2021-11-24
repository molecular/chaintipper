#!/bin/bash
pushd $(pwd)
cd $(dirname $0)/..
source scripts/vars.sh
source scripts/secrets.sh # exports GITHUB_TOKEN

bin="/home/nick/go/bin/github-release"
args="--user "${github_user}" --repo "${github_repo}" --tag "${version}

echo "checking for existing github release..."
${bin} info ${args} | grep ${version} > /dev/null
if [ $? -eq 0 ]; then
	echo "detected existing release, deleting..."
	${bin} delete ${args} | grep ${version} > /dev/null
fi

echo "creating github release..."
cat CHANGES | grep -B 10000 "+++" | head -n -1 | ${bin} release ${args} --name "ChainTipper Release ${version}" --description - --pre-release

${bin} upload ${args} --name ${zipfile} --file ${zipfile}
		
${bin} upload ${args} --name SHA256.ChainTipper.txt --file SHA256.ChainTipper.txt


# echo "creating and copying manual html"
# cd doc/manual
# grip --export manual.md
# cd ..

popd
