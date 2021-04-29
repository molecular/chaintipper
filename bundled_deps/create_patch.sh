#!/bin/bash
find ../websocket ../praw*/ websocket praw* -name __pycache__ | xargs rm -rf
rm *.patch
diff -Naur praw ../praw > patch_praw_relative_imports.patch
