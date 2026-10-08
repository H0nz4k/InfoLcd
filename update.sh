#!/bin/sh
set -eu
cd "$(dirname "$0")"
git pull --ff-only
exec sh install.sh "$@"
