version=$(cat manifest.json | jq -r '.version')
zipfile="ChainTipper-${version}.zip"
repos="origin github"
