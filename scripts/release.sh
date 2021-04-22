version="0.1a"
zipfile="chaintipper-${version}.zip"

rm ${zipfile}
rm -rf release

mkdir -p release/chaintipper
cp *.py release/chaintipper

for module in praw prawcore websocket; do
	cp -ar ${module} release/chaintipper
done

cp manifest.json release
cd release
zip -r ../${zipfile} *
cd ..

scp ${zipfile} nick@blackbox:
