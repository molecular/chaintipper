cd $(dirname $0)/..
version=$(cat manifest.json | jq -r '.version')
zipfile="chaintipper-${version}.zip"

# precompile to pyc files
python -m compileall .

# remove old files 
rm ${zipfile}
rm -rf release

# gather stuff in release folder
mkdir -p release/chaintipper
cp *.py release/chaintipper

for module in praw prawcore websocket; do
	cp -ar bundled_deps/${module} release/chaintipper
done

cp manifest.json release

# zip release folder
cd release
zip -r ../${zipfile} *
cd ..

scp ${zipfile} nick@blackbox:
