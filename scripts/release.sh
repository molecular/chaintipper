cd $(dirname $0)/..
version=$(cat manifest.json | jq -r '.version')
zipfile="ChainTipper-${version}.zip"

# prepare git (should be on develop branch)
git push 
git push github

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

# zip release folder
echo -ne "\n\ncreating .zip file..."
cd release
t=$(date +%s)
#find . -exec touch -t ${t} {} + 
zip -q -X -r ../${zipfile} *
cd ..

# sha256sums
echo -ne "\n\ncreating checksums..."
sha256sum ChainTipper*.zip > "SHA256.ChainTipper.txt"

# create lastest_release.json
echo -ne "\n\ncreating latest_version.json...."
sha256=$(sha256sum ${zipfile} | cut -f 1 -d " ")
uri='http://criptolayer.net/Pk4p2VyxVtOAkWzq/'${zipfile}

echo -ne "\n\nwill call ../scripts/sign.sh. open the wallet, then hit <anykey>"
read
sig=$(scripts/sign.sh $version,$uri,$sha256)
sig_of_sha256=$(scripts/sign.sh $sha256)

echo -ne '{
	"version": "'${version}'",
	"uri": "'${uri}'",
	"sha256": "'${sha256}'",
	"sig_ca": "molecular#123",
	"sig_addr": "bitcoincash:qzz3zl6sl7zahh00dnzw0vrs0f3rxral9uedywqlfw",
	"sig": "'${sig}'",
	"sig_of_sha256": "'${sig_of_sha256}'"
}
' > update_checker/latest_version.json

# update version tag 
git tag -d ${version}
git tag ${version}
for repo in origin github; do
	git push ${repo}
	git push --delete ${repo} ${version}
	git push ${repo} ${version}
done

# run any post-release copying 
if [ -e "scripts/local_release.sh" ]; then
	echo -ne "\n\nrunning scripts/local_release.sh..."
	scripts/local_release.sh ${zipfile}
fi

# deploy to distribution location
if [ -e "scripts/deploy.sh" ]; then
	echo -ne "\n\nrunning scripts/deploy.sh..."
	#scripts/deploy.sh ${zipfile}
fi

echo "as a last step, to activate update_checker, merge develop -> release"
