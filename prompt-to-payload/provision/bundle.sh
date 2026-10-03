#!/usr/bin/env bash
#
# Emit a portable bundle for an air-gapped host.
#
# Produces a directory (and optionally a tarball) containing the harness, the
# built corpus, the lab target and a manifest. Model weights are NOT copied by
# default - they are large and live in your runtime's own store - but the
# manifest records exactly which ones the bundle expects, so the receiving host
# can be checked instead of guessed at.
#
#   ./provision/bundle.sh                     build ./dist/payload-bundle
#   ./provision/bundle.sh --tar               also produce a .tar.gz
#   ./provision/bundle.sh --with-models DIR   copy weights from DIR as well

set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
OUT="$ROOT/dist/payload-bundle"

TAR=0
MODELS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --tar) TAR=1; shift ;;
        --with-models) MODELS="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\033[36m==\033[0m %s\n' "$1"; }

rm -rf "$OUT"
mkdir -p "$OUT"

say "copying the harness"
mkdir -p "$OUT/harness"
# Source and config only. Explicitly excluded: __pycache__, and runs/ - a
# transcript can contain client data and must never travel by accident.
( cd harness && tar --exclude='__pycache__' --exclude='runs' --exclude='*.pyc' \
    -cf - payload tests pyproject.toml payload.toml.example ) \
    | ( cd "$OUT/harness" && tar -xf - ) \
    || { echo "   failed to copy the harness" >&2; exit 1; }
[ -f harness/payload.toml ] && cp harness/payload.toml "$OUT/harness/"

say "copying the corpus"
if [ -f corpus/corpus.db ]; then
    mkdir -p "$OUT/corpus"
    cp corpus/corpus.db "$OUT/corpus/"
    SIZE=$(du -h corpus/corpus.db | cut -f1)
    echo "   corpus.db ($SIZE)"
else
    echo "   no corpus found; the bundle will have no retrieval"
fi

say "copying the lab target"
mkdir -p "$OUT/lab/re-target"
cp -R lab/re-target/src lab/re-target/Makefile lab/re-target/verify.sh \
      "$OUT/lab/re-target/" 2>/dev/null
[ -d lab/re-target/dist ] && cp -R lab/re-target/dist "$OUT/lab/re-target/"

say "copying the egress guard"
mkdir -p "$OUT/scripts"
cp -R scripts/noegress "$OUT/scripts/"
cp scripts/egress-test.sh "$OUT/scripts/"
rm -f "$OUT/scripts/noegress/"*.dylib "$OUT/scripts/noegress/"*.so

say "copying docs"
cp -R docs "$OUT/" 2>/dev/null
cp README.md "$OUT/" 2>/dev/null

if [ -n "$MODELS" ]; then
    say "copying model weights from $MODELS"
    mkdir -p "$OUT/models"
    cp -R "$MODELS"/. "$OUT/models/" && echo "   $(du -sh "$OUT/models" | cut -f1)"
fi

say "writing the manifest"
{
    echo "# payload bundle"
    echo
    echo "built:    $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "host os:  $(uname -srm)"
    echo "python:   $(python3 -V 2>&1)"
    echo
    echo "## expected models"
    echo
    if [ -f harness/payload.toml ]; then
        grep -E '^\s*model\s*=' harness/payload.toml | sed 's/^/    /'
    else
        echo "    (no payload.toml at bundle time)"
    fi
    echo
    echo "## corpus"
    echo
    if [ -f corpus/corpus.db ]; then
        ( cd harness && python3 -m payload corpus stats 2>/dev/null ) | sed 's/^/    /'
    else
        echo "    none"
    fi
    echo
    echo "## on the receiving host"
    echo
    echo "    1. Load the model weights into your local runtime."
    echo "    2. Confirm the role names in harness/payload.toml match them."
    echo "    3. cd harness && python3 -m payload doctor"
    echo "    4. ../scripts/egress-test.sh"
    echo
    echo "Nothing here needs a package manager. The harness imports only the"
    echo "standard library on Python 3.11 or newer."
} > "$OUT/MANIFEST.md"

if [ "$TAR" -eq 1 ]; then
    say "creating the tarball"
    ( cd "$ROOT/dist" && tar -czf payload-bundle.tar.gz payload-bundle )
    echo "   dist/payload-bundle.tar.gz ($(du -h "$ROOT/dist/payload-bundle.tar.gz" | cut -f1))"
fi

echo
say "bundle at ${OUT#$ROOT/}  ($(du -sh "$OUT" | cut -f1))"
echo "   read ${OUT#$ROOT/}/MANIFEST.md before carrying it anywhere."
