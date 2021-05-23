version=$(cat manifest.json | jq -r '.version')
zipfile="ChainTipper-${version}.zip"
repos="origin github"
github_user="molecular"
github_repo="chaintipper"
