# Building

## Bundled Dependencies

As a plug it's not straight-forward to include external libraries not already used in electron-cash. To do so one must include the sources of those libs inside the plugin zip file and even fiddle with the library sources themselves to make imports work.

For ChainTipper the process of downloading sources of external libraries (currently praw, prawcore and websocket) and patching them with the necessary changes is automated by `bundled_deps/download_check_unpack_bundled_deps.sh` and `bundled_deps/apply_patch.sh`.

This is setup this way to make it easier for code reviewers to check those sources for malicious modifications.

Both the mentioned scripts are called from `scripts/build.sh`, which also compiles qt resources.

So all you need to prepare the bundled dependency sources and compile the qt resources is

```
#> scripts/build.sh
```

This only needs to be done once or in case qt resources change or a library is added.

## Packaging

There's a bash script to help create a plugin.zip file for distribution:

```
#> scripts/package.sh
```

## Running as internal plugin (when developing)

In presence of electron-cash source code one can symb olically link chaintipper into that code so that it appears as so-called "internal plugin".

```
#> ln -s path/to/chaintipper path/to/my_ec_sources/electroncash_plugins
```

# Reviewing

## Bundled Dependencies

I made it as easy as possible for reviewers to check for malicious code in the bundled dependencies that are being included in the distribution zip file. Please read section Bundled Dependencies above. Essentially reviewers can simply verify the download locations / hashes of the external library package files that are downloaded through `bundled_deps/download_check_unpack_bundled_deps.sh`, verify the patches applied by `bundled_deps/apply_patch.sh` (currently this is just one patch: `bundled_deps/patch_praw_relative_imports.path`) and then verify the result is identical to what is included in the reviewed plugin.zip.

## ZIP File integrity

I tried to setup a dependable build system (the bash-scripts mentioned above), but failed at telling ZIP to create exactly the same archive every time. So the ZIP file being reviewed will not be identical to the ZIP file built by reviewers bit by bit. So reviewers will need to unpack both and compare the contents instead.

# Wishlist for code reviews

Here are my ideas on who would be an adequate individual for a code review and what the code could be checked for.

## Reviewer

The ideal code reviewer...

 * is well-known in the Bitcoin Cash community and has a good reputation there 
 * is trusted by the community to have the technical skills to conduct a code review as described below
 * is able to sign messages with a key that can be publically attributed to him.

## Review scope

A review should do the following things

 * verify the contents of the distribution file(s) (identified by sha256 hash(es)) are identical to what is produced by using the sources and build scripts that are publically available
 * check bundled dependencies and chaintipper source code regarding
   * any type of intentional malicious code (like fund stealer, intentional corruption of local data, disruption or manupulation of host electron-cash operation)
   * any type of unnecessary leakage of information beyond what is necessary for operation (i.e. phone-home stuff)
   * (optionally) likelihood of unintentional bugs that could lead to loss of funds or disruption of host electron-cash operation (this could be done by judging architecture design and code quality)
 * (optionally) make a judgement of impact on users privacy implied by use of chaintipper
 * publish a signed messages (with a key attributable to the individual) with the findings

It would be ideal if the review could be incrementally updated periodically when chaintipper is updated.
