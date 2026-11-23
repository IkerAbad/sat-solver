#!/usr/bin/env bash
# Build the pinned drat-trim proof checker from source.
set -euo pipefail

rev="${DRAT_TRIM_REV:-2e3b2dc0ecf938addbd779d42877b6ed69d9a985}"
dest="${1:-$PWD/.drat-trim}"

if [ ! -d "$dest/.git" ]; then
  git clone https://github.com/marijnheule/drat-trim.git "$dest"
fi
git -C "$dest" fetch --quiet origin "$rev"
git -C "$dest" checkout --quiet "$rev"

# drat-trim uses getc_unlocked, which is not exposed by strict C99. Mapping it
# to getc keeps the build portable across glibc and MSYS2 UCRT.
gcc -std=c99 -O2 -Dgetc_unlocked=getc "$dest/drat-trim.c" -o "$dest/drat-trim"

if [ -f "$dest/drat-trim.exe" ]; then
  echo "$dest/drat-trim.exe"
else
  echo "$dest/drat-trim"
fi
