cd $(dirname $0)/..
source scripts/vars.sh

echo "version: ${version}"

# precompile to pyc files
echo -ne "\n\ncompiling python files..."
python -m compileall . > /dev/null

echo -ne "\n\npreparing release files..."

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

# zip release folder (unforunately not dependable, zip will be different each time)
echo -ne "\n\ncreating .zip file..."
cd release
t=$(date +%s)
#find . -exec touch -t ${t} {} + 
zip -q -X -r ../${zipfile} *
cd ..

# sha256sums
echo -e "\n\ncreating checksums..."
sha256sum ChainTipper*.zip > "SHA256.ChainTipper.txt"

echo -e "\n--- created ${zipfile} ---\n"

# run any post-packaging actions (like copy to test machine) 
sh="packaged_local.sh"
if [ -e "scripts/${sh}" ]; then
	echo -ne "\n\nrunning scripts/${sh}..."
	scripts/${sh}
fi
