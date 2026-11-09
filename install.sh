#!/usr/bin/env bash
# Compatibility entry point; everyday commands live in the Makefile.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec make setup-browser build-web
