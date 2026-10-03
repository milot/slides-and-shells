#!/usr/bin/env bash
#
# Phase 1: provision. This is the only step that needs a network.
#
# After this completes, everything runs offline forever. Nothing in the run
# phase resolves a name, opens a socket to anything but loopback, or consults
# a package index.
#
#   ./provision/provision.sh            full provision
#   ./provision/provision.sh --lab-only just build the lab target
#
# You pull the models yourself. Picking weights is a judgement call
# that depends on your memory budget and changes month to month; see
# docs/MODELS.md for the tier matrix. This script verifies what you chose
# instead of choosing for you.

set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

LAB_ONLY=0
[ "${1:-}" = "--lab-only" ] && LAB_ONLY=1

say()  { printf '\n\033[36m==\033[0m %s\n' "$1"; }
ok()   { printf '   \033[32mok\033[0m    %s\n' "$1"; }
warn() { printf '   \033[33mnote\033[0m  %s\n' "$1"; }
die()  { printf '   \033[31mfail\033[0m  %s\n' "$1"; exit 1; }

# ---------------------------------------------------------------- prerequisites

say "checking prerequisites"

command -v python3 >/dev/null || die "python3 not found"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
    || die "python 3.11+ required (tomllib); found $PYV"
ok "python $PYV"

command -v cc >/dev/null || command -v gcc >/dev/null || command -v clang >/dev/null \
    || die "no C compiler found. Arch: pacman -S base-devel. macOS: xcode-select --install"
ok "C compiler present"

for opt in r2 nmap; do
    if command -v "$opt" >/dev/null; then
        ok "$opt present"
    else
        warn "$opt not installed (optional; see docs/INSTALL.md)"
    fi
done

# ------------------------------------------------------------------- lab target

say "building the lab target"
make -C lab/re-target clean >/dev/null 2>&1
if make -C lab/re-target all >/dev/null 2>&1; then
    ok "vulnbox built and stripped"
else
    die "lab target failed to build; run 'make -C lab/re-target all' to see why"
fi

if ./lab/re-target/verify.sh >/dev/null 2>&1; then
    ok "all three bugs verified reachable"
else
    die "lab verification failed; run ./lab/re-target/verify.sh for detail"
fi

# Cache the function list so the first analysis pass is not paid for twice.
if command -v r2 >/dev/null; then
    mkdir -p runs/cache
    r2 -q -N -e scr.color=0 -c 'aaa; afl' lab/re-target/dist/vulnbox \
        > runs/cache/vulnbox.functions.txt 2>/dev/null \
        && ok "cached r2 function list"
fi

[ "$LAB_ONLY" -eq 1 ] && { say "lab built. Stopping here as asked."; exit 0; }

# ---------------------------------------------------------------- egress guard

say "building the egress interposer"
if make -C scripts/noegress >/dev/null 2>&1; then
    ok "interposer built"
else
    warn "interposer failed to build; scripts/egress-test.sh will not run"
fi

# ---------------------------------------------------------------------- models

say "models"

if [ ! -f harness/payload.toml ]; then
    cp harness/payload.toml.example harness/payload.toml
    warn "created harness/payload.toml from the example"
fi

SKIP_CORPUS=0

if grep -q 'REPLACE-ME' harness/payload.toml 2>/dev/null; then
    warn "harness/payload.toml still has REPLACE-ME placeholders."
    warn "Choose your weights (docs/MODELS.md), pull them, then edit that file."
    SKIP_CORPUS=1
else
    ok "payload.toml has no placeholders left"
fi

# The corpus is optional. Checking for the
# role here instead of assuming it: an absent embed role used to get
# as far as the embedding call and surface as a traceback.
if ! grep -qE '^[[:space:]]*\[roles\.embed\]' harness/payload.toml 2>/dev/null; then
    warn "no [roles.embed] in harness/payload.toml, so there is nothing to"
    warn "embed with. Skipping the corpus; it is optional and the"
    warn "binary analysis does not use it."
    warn "To add one later:  ollama pull qwen3-embedding:8b"
    SKIP_CORPUS=1
elif [ "$SKIP_CORPUS" -eq 0 ]; then
    ok "embed role configured"
fi

# ---------------------------------------------------------------------- corpus

if [ "${SKIP_CORPUS:-0}" -eq 0 ]; then
    say "building the corpus"
    mkdir -p corpus/notes

    # The run phase is locked; provisioning is the one place egress is allowed,
    # and only for the model server, which is local anyway.
    if ( cd harness && PAYLOAD_OFFLINE=1 python3 -m payload corpus build \
            ../corpus/notes --name local-notes ); then
        ok "corpus built from corpus/notes"
    else
        warn "corpus build failed; check that the embed role is reachable"
    fi
fi

# ----------------------------------------------------------------------- done

say "verifying the result"
( cd harness && python3 -m payload doctor ) || true

cat <<'EOF'

provisioning done.

From here nothing needs a network:

    cd harness
    python3 -m payload re ../lab/re-target/dist/vulnbox

To check that claim instead of taking it on faith:

    ./scripts/egress-test.sh

To carry this onto an air-gapped host:

    ./provision/bundle.sh

EOF
