# Offline

The claim is that after one provisioning step, nothing leaves this machine.

Here is how that is arranged, how to check it yourself, and what it does not
cover.

---

## Two phases

The split is structural. It is not a convention you can forget to follow.

### Phase 1: provision. Needs network. Run once.

```bash
./provision/provision.sh
```

- Pull model weights into your runtime's store.
- Build the lab target and verify its bugs are reachable.
- Build the egress interposer.
- Fetch and embed corpus sources.

This is the only moment a network is required, or permitted.

### Phase 2: run. Needs nothing.

```bash
cd harness
python3 -m payload re ../lab/re-target/dist/vulnbox
```

A model server on loopback and a sqlite file. No resolver, no package index, no
update check, no telemetry, no licence call-home.

This phase is why the harness has no required Python dependencies. A
dependency means a package manager, and a package manager means the offline
story depends on something having worked earlier. Standard library only, and
that whole class of problem goes away.

---

## Two guards

### In code

`payload/egress.py` resolves the host of every endpoint before a socket opens
and refuses anything that is not loopback while the harness is locked. Locked
is the default: `PAYLOAD_OFFLINE` must be explicitly set to `0` to unlock, and
only provisioning should ever do that.

It fails **closed**. A host that cannot be resolved, which is the normal state on
an air-gapped box, is refused, not attempted.

It also refuses without resolving. A DNS query is traffic leaving the machine,
and on a segmented network a lookup for a client's hostname is exactly the
packet I am trying not to send. Address literals get judged arithmetically,
`localhost` resolves because that comes from `/etc/hosts` and not a nameserver,
and every other name is refused unresolved. There is a test for it that swaps
`getaddrinfo` for a tripwire and asserts the guard never reaches it.

### Outside the code

`scripts/noegress/` builds a small shared library that intercepts `connect`,
`sendto` and `sendmsg` at the libc boundary, logs every call, and refuses
anything non-loopback. Loaded with `DYLD_INSERT_LIBRARIES` on macOS and
`LD_PRELOAD` on Linux.

Two guards, because they answer different questions. You rely on the code
guard day to day. The interposer is for convincing someone who does not trust
the code guard, which is the right attitude to have about software you are
about to point at a client's network.

---

## Verifying it

```bash
./scripts/egress-test.sh
```

This runs a **complete agent loop**: real HTTP to a loopback model server,
real tool dispatch, real binary analysis, with every network operation
intercepted and logged. It then asserts:

- the loop genuinely ran (loopback operations were observed);
- zero non-loopback operations were attempted;
- **a real egress attempt IS detected**, the positive control;
- with the lock on, no connection is attempted at all.

The control matters more than the rest of it. Without it, "zero packets left"
is equally consistent with "the test measured nothing."

Evidence lands in `runs/egress/` as tab-separated logs. Commit them if you want
someone who has not run it to be able to check.

### Stronger, on Linux

A network namespace with only loopback is a harder guarantee than libc
interposition, because it cannot be bypassed by a static binary or a raw
syscall:

```bash
sudo unshare -n bash -c '
    ip link set lo up
    cd harness && python3 -m payload re ../lab/re-target/dist/vulnbox
'
```

The catch: inside a fresh namespace, your model server on the host's loopback
is unreachable, because the namespace has its own. Either run the model server
inside the namespace too, or accept that this verifies the harness and not
the whole system.

---

## What this does not cover

Overstating any of this would defeat the point, so:

- **It intercepts libc.** A statically linked binary or one issuing raw
  syscalls would bypass the interposer. The harness is Python on system libc,
  so it holds for the thing under test, but it is not a sandbox.
- **It does not police your model runtime.** Ollama, llama.cpp and LM Studio
  are separate processes with their own update checks and telemetry. Audit
  them separately. The harness only governs itself.
- **macOS hardened binaries ignore `DYLD_INSERT_LIBRARIES`.** The test detects
  this and reports a failure instead of a false pass, but it means you need a
  Homebrew or python.org interpreter for the verification to mean anything.
- **It is not a defence against malicious code in this repo.** It only checks
  that the code does what it says. Read it. That is why it is short.

---

## Carrying it onto an air-gapped host

```bash
./provision/bundle.sh --tar
```

Produces `dist/payload-bundle/` and a tarball containing the harness, the
built corpus, the lab target, the egress guard, the docs, and a manifest
recording which models the bundle expects.

Weights are not copied by default, because they are large and live in your runtime's
own store. `--with-models DIR` includes them if you want one artifact.

`runs/` is excluded. A transcript can contain client data and must never
travel by accident.

On the receiving host:

```bash
cd payload-bundle/harness
python3 -m payload doctor
../scripts/egress-test.sh
```

Nothing there needs a package manager.
