cd $(dirname $0)/..
source scripts/vars.sh

echo "make sure you're on develop branch, everything commited and hit key"
read
git checkout develop || die

# push to git (should be on develop branch)
for repo in ${repos}; do
	git push ${repo} || die
done

# package
scripts/package.sh

# create lastest_release.json
echo -ne "\n\ncreating latest_version.json...."
sha256=$(sha256sum ${zipfile} | cut -f 1 -d " ")
uri='https://github.com/molecular/chaintipper/releases/tag/'${version}

echo -ne "\n\nwill call ../scripts/sign.sh. open the wallet, then hit <anykey>"
read
sig=$(scripts/sign.sh $version,$uri,$sha256)
sig_of_sha256=$(scripts/sign.sh $sha256)

if [ "$sig" == "" ]; then
	echo "signing failed: sig is empty"
	exit 1
fi

echo -ne '{
	"version": "'${version}'",
	"uri": "'${uri}'",
	"zip_filename": "'${zipfile}'",
	"sha256": "'${sha256}'",
	"sig_ca": "molecular#123",
	"sig_addr": "bitcoincash:qzz3zl6sl7zahh00dnzw0vrs0f3rxral9uedywqlfw",
	"sig": "'${sig}'",
	"sig_of_sha256": "'${sig_of_sha256}'"
}
' > update_checker/latest_version.json

# add and commit latest_version and sha sums
git add update_checker/latest_version.json
git add SHA256.ChainTipper.txt
git commit -m "release.sh (version $version) committing latest_version.json and SHA256sums"

# update version tag and push everything
git tag -d ${version}
git tag ${version}
for repo in ${repos}; do
	git push ${repo}
	git push --delete ${repo} ${version}
	git push ${repo} ${version}
done

# deploy to distribution location
sh="deploy.sh"
if [ -e "scripts/${sh}" ]; then
	echo -ne "\n\nrunning scripts/${sh}..."
	scripts/${sh}
fi

cat SHA256.ChainTipper.txt | tail -n 1

echo "as a last step, to activate update_checker, merge develop -> release, then push"
echo "and finally bump version in manifest.json, adjust CHANGES and checkout develop branch again"
