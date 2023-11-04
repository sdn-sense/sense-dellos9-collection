#!/bin/sh
for fname in `git diff --name-only HEAD HEAD~1`; do
  if test -f "$fname" && [[ $fname == *.py ]]; then
    black $fname;
    isort $fname;
    pylint $fname --rcfile standarts/pylintrc
  fi
done
