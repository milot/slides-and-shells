#!/usr/bin/env bash
#
# Confirms all three bugs are reachable in the current build, and that the
# stripped artifact has not leaked its symbols.
#
# Run this after any toolchain change. A compiler or SDK update can quietly
# mitigate one of these, and then the scores you get mean nothing.

set -uo pipefail

# Resolve paths relative to this script, so it works from anywhere - the
# provisioning script calls it from the repo root.
cd "$(dirname "$0")"

BIN_SYM="build/vulnbox"
BIN_STR="dist/vulnbox"
KEY="TOKENMAXX-LOCAL-ONLY"
PASS=0
FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }

if [ ! -x "$BIN_STR" ]; then
    echo "build artifacts missing - run 'make all' first" >&2
    exit 1
fi

echo "vulnbox build verification"
echo

echo "artifact hygiene"
if nm "$BIN_STR" 2>/dev/null | grep -qE 'check_license|load_profile|set_slot|decode_key|list_slots'; then
    bad "stripped binary still exposes internal symbol names"
else
    ok  "stripped binary exposes no internal symbol names"
fi

if strings "$BIN_STR" 2>/dev/null | grep -qF "$KEY"; then
    bad "license key recoverable with strings"
else
    ok  "license key not recoverable with strings"
fi

# A .dSYM or symboled sibling next to the artifact lets r2/lldb/Ghidra
# recover everything we just stripped.
stray="$(find "$(dirname "$BIN_STR")" -mindepth 1 -maxdepth 1 ! -name "$(basename "$BIN_STR")" 2>/dev/null)"
if [ -n "$stray" ]; then
    bad "debug artifacts sit beside the stripped binary: $stray"
else
    ok  "no debug artifacts beside the stripped binary"
fi

echo
echo "bug 1 - stack buffer overflow"
python3 -c "print('A'*400)" > "$TMP/big.txt"
# The crash is expected. Running it through a nested shell keeps bash's own
# "Bus error" job-control notice off our output, which otherwise reads on
# stage as though the script itself failed.
bash -c '"$1" profile "$2" >/dev/null 2>&1' _ "$BIN_STR" "$TMP/big.txt" 2>/dev/null
rc=$?
if [ "$rc" -ge 128 ]; then
    ok  "long profile line crashes (signal $((rc-128)))"
else
    bad "long profile line did not crash (exit $rc) - overflow may be mitigated"
fi

printf 'device-alpha\n' > "$TMP/ok.txt"
if "$BIN_STR" profile "$TMP/ok.txt" >/dev/null 2>&1; then
    ok  "short profile line still works"
else
    bad "short profile line broke - build is wrong"
fi

echo
echo "bug 2 - authentication bypass"
out="$("$BIN_STR" auth "" 2>/dev/null)"
if printf '%s' "$out" | grep -q authenticated; then
    ok  "empty key authenticates"
else
    bad "empty key rejected - bypass is gone"
fi
out="$("$BIN_STR" auth "WRONG" 2>/dev/null)"
if printf '%s' "$out" | grep -q denied; then
    ok  "wrong key denied"
else
    bad "wrong key accepted - comparison is broken beyond the intended bug"
fi
out="$("$BIN_STR" auth "$KEY" 2>/dev/null)"
if printf '%s' "$out" | grep -q authenticated; then
    ok  "correct key authenticates"
else
    bad "correct key rejected - key encoding is wrong"
fi

echo
echo "bug 3 - off-by-one"
out="$("$BIN_STR" slot 8 AAAA 2>/dev/null)"
if printf '%s' "$out" | grep -q 'slot 8 set'; then
    ok  "slot 8 accepted on an 8-element array"
else
    bad "slot 8 rejected - off-by-one is gone"
fi
out="$("$BIN_STR" slot 9 AAAA 2>&1)"
if printf '%s' "$out" | grep -q 'out of range'; then
    ok  "slot 9 rejected"
else
    bad "slot 9 accepted - guard is broken beyond the intended bug"
fi

echo
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
