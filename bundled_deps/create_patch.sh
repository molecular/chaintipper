#!/bin/bash
find ../praw/ -name __pycache__ | xargs rm -rf
diff -Naur praw ../praw > patch_praw_relative_imports.patch
