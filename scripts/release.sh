cd $(dirname $0)/..
version=$(cat manifest.json | jq -r '.version')
zipfile="ChainTipper-${version}.zip"

# precompile to pyc files
python -m compileall .

# remove old files 
rm ${zipfile}
rm -rf release

# gather stuff in release folder
mkdir -p release/chaintipper
cp *.py release/chaintipper

for module in praw prawcore websocket iterators; do
	cp -ar bundled_deps/patched/${module} release/chaintipper
done

cp manifest.json release

# zip release folder
cd release
t=$(date +%s)
find . -exec touch -t ${t} {} +
zip -X -r ../${zipfile} *
cd ..

sha256sum ChainTipper*.zip > "SHA256.ChainTipper.txt"

# run any post-release copying 
if [ -e "scripts/local_release.sh" ]; then
	scripts/local_release.sh ${zipfile}
fi
