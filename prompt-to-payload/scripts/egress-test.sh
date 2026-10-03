#!/usr/bin/env bash
#
# Proves the harness sends nothing off this machine.
#
# Runs a full agent loop - real HTTP, real tool dispatch, real binary analysis -
# with every network operation intercepted at the libc boundary and logged.
# Then runs a positive control that really does attempt egress, to show the
# test is capable of detecting it.
#
# A test that cannot fail is not evidence. The control is the point.

set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
PORT="${PORT:-11457}"
EVIDENCE="${EVIDENCE:-$ROOT/runs/egress}"
PASS=0; FAIL=0

ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
info(){ printf '        %s\n' "$1"; }

case "$(uname -s)" in
  Darwin) LIB="$ROOT/scripts/noegress/libnoegress.dylib"; VAR=DYLD_INSERT_LIBRARIES ;;
  Linux)  LIB="$ROOT/scripts/noegress/libnoegress.so";    VAR=LD_PRELOAD ;;
  *) echo "unsupported platform: $(uname -s)" >&2; exit 2 ;;
esac

mkdir -p "$EVIDENCE"

echo "egress verification"
echo

# -------------------------------------------------------------- build + setup

make -C scripts/noegress >/dev/null 2>&1
if [ ! -f "$LIB" ]; then
    echo "could not build the interposer. Is a C compiler installed?" >&2
    exit 1
fi
ok "interposer built for $(uname -s)"

# Confirm the interposer actually takes effect before trusting any result from
# it. On macOS a hardened or SIP-protected interpreter silently ignores
# DYLD_INSERT_LIBRARIES, which would make everything below a false pass.
probe_log="$EVIDENCE/probe.tsv"
: > "$probe_log"
env "$VAR=$LIB" NOEGRESS_LOG="$probe_log" python3 - <<'PY' >/dev/null 2>&1
import socket
try:
    socket.create_connection(("192.0.2.1", 80), timeout=2)
except OSError:
    pass
PY
if grep -q BLOCK "$probe_log" 2>/dev/null; then
    ok "interposer is active and intercepting (self-check)"
else
    bad "interposer is NOT active - every result below would be meaningless"
    info "on macOS this means the python3 in use is hardened or SIP-protected."
    info "try a Homebrew or python.org interpreter, or use the Linux netns mode."
    echo; printf '%d passed, %d failed\n' "$PASS" "$FAIL"; exit 1
fi

# ------------------------------------------------------- the actual agent run

python3 harness/tests/stub_server.py "$PORT" >"$EVIDENCE/stub.log" 2>&1 &
STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 1.5

if ! kill -0 "$STUB" 2>/dev/null; then
    bad "stub model server failed to start; see $EVIDENCE/stub.log"
    echo; printf '%d passed, %d failed\n' "$PASS" "$FAIL"; exit 1
fi

RUN_LOG="$EVIDENCE/agent-run.tsv"
: > "$RUN_LOG"

( cd harness && env "$VAR=$LIB" NOEGRESS_LOG="$RUN_LOG" \
    PAYLOAD_OFFLINE=1 \
    PAYLOAD_MODEL_PLAN=stub \
    PAYLOAD_ENDPOINT="http://127.0.0.1:$PORT/v1" \
    python3 -m payload re ../lab/re-target/dist/vulnbox --yes \
) >"$EVIDENCE/agent-stdout.txt" 2>"$EVIDENCE/agent-stderr.txt"
rc=$?

if [ "$rc" -eq 0 ]; then
    ok "full agent loop completed (model call, tool dispatch, answer)"
else
    bad "agent loop exited $rc; see $EVIDENCE/agent-stderr.txt"
fi

allowed=$(grep -c ALLOW "$RUN_LOG" 2>/dev/null || true)
blocked=$(grep -c BLOCK "$RUN_LOG" 2>/dev/null || true)

if [ "${allowed:-0}" -gt 0 ]; then
    ok "$allowed loopback operation(s) observed - the loop really ran"
else
    bad "no network operations logged at all; the run did not exercise HTTP"
fi

if [ "${blocked:-0}" -eq 0 ]; then
    ok "zero non-loopback operations attempted"
else
    bad "$blocked non-loopback operation(s) attempted:"
    grep BLOCK "$RUN_LOG" | sed 's/^/        /'
fi

# --------------------------------------------------------- positive control

# Actually attempt egress, with the harness unlocked so its own guard stands
# aside. No BLOCK here means the test above measured nothing.
CTRL_LOG="$EVIDENCE/control.tsv"
: > "$CTRL_LOG"
( cd harness && env "$VAR=$LIB" NOEGRESS_LOG="$CTRL_LOG" \
    PAYLOAD_OFFLINE=0 \
    PAYLOAD_MODEL_PLAN=stub \
    PAYLOAD_ENDPOINT="http://198.51.100.7:443/v1" \
    python3 -m payload ask "hello" --yes \
) >/dev/null 2>&1

if grep -q BLOCK "$CTRL_LOG" 2>/dev/null; then
    ok "control: a real egress attempt WAS detected and blocked"
    info "$(grep BLOCK "$CTRL_LOG" | head -1)"
else
    bad "control: real egress was not detected - this test proves nothing"
fi

# And with the lock on, the harness refuses before libc is ever reached.
GUARD_LOG="$EVIDENCE/guard.tsv"
: > "$GUARD_LOG"
( cd harness && env "$VAR=$LIB" NOEGRESS_LOG="$GUARD_LOG" \
    PAYLOAD_OFFLINE=1 \
    PAYLOAD_MODEL_PLAN=stub \
    PAYLOAD_ENDPOINT="http://198.51.100.7:443/v1" \
    python3 -m payload ask "hello" --yes \
) >/dev/null 2>&1

if [ ! -s "$GUARD_LOG" ]; then
    ok "with the lock on, no connection is even attempted"
    info "the harness refuses in egress.py before a socket is opened"
else
    bad "a connection was attempted despite the offline lock:"
    sed 's/^/        /' "$GUARD_LOG"
fi

echo
echo "evidence written to ${EVIDENCE#$ROOT/}/"
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
