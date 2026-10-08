#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec sudo /usr/bin/python3 install.py "$@"
