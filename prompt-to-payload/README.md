# From Prompt to Payload

An offensive AI harness that runs on your own hardware. No API keys, no
telemetry, nothing leaves the machine once it is set up.

It wraps a local model around real tooling, keeps you in the approval loop,
and ships a calibration target so you can find out what your model actually
gets right before you trust it with anything.

## Why I built this

There are engagements where a hosted model is not on the table.

Sometimes it is the paperwork. The context I would need to paste in belongs to
a client, or sits under an NDA, or describes infrastructure I am not allowed to
discuss outside the engagement. Sometimes it is simpler than that: I am on a
segmented internal network with no egress, nothing gets out, and every packet I
generate is something a defender might notice.

The second case is not a cost argument. There is no price at which a hosted
model becomes reachable from that box.

Once inference is local, tokens cost nothing at the margin. There is no budget
to govern and no router to tune for price. What is left is capability, which is
the thing usage metrics never measured anyway. So the question I care about is
not how many tokens I burned, it is what the cheap model actually gets right.

This repo is my attempt to answer that with something you can re-run.

## Quick start

You need Python 3.11 or newer, a C compiler, and something serving an
OpenAI-compatible API on loopback. Ollama is the easiest. Full install for Arch
and macOS is in [docs/INSTALL.md](docs/INSTALL.md).

**1. Set up.** Builds the lab target, builds the egress guard, and writes a
starter config. This is the only step that needs a network.

```bash
./provision/provision.sh
```

**2. Choose a model and tell the harness about it.** Provisioning leaves
`harness/payload.toml` with `REPLACE-ME` placeholders, because which weights to
use is a decision that goes stale. [docs/MODELS.md](docs/MODELS.md) has sizing
by available memory and a dated starting point.

```bash
ollama pull <the model you picked>
$EDITOR harness/payload.toml      # replace the placeholders
```

Only the `plan` role is required. Leave `code` out and it falls back to `plan`;
leave `embed` out and you get everything except corpus retrieval.

**3. Check it.**

```bash
cd harness && python3 -m payload doctor
```

**4. Run it.**

```bash
python3 -m payload re ../lab/re-target/dist/vulnbox
```

### Before you have any models

The whole loop runs against a stub, so you can confirm the install while
weights are still downloading:

```bash
python3 harness/tests/stub_server.py 11455 &
cd harness
PAYLOAD_MODEL_PLAN=stub PAYLOAD_ENDPOINT=http://127.0.0.1:11455/v1 \
  python3 -m payload re ../lab/re-target/dist/vulnbox --yes
kill %1                           # stop the stub when you are done
```

The tests need neither a model nor a network at all:

```bash
make test
```

## Scoring a model before you trust it

`lab/re-target/` holds a small program with three planted bugs of graded
difficulty, and its source. Because the answers are known, a model's output can
be checked:

```bash
cd harness
python3 -m payload score --runs 3
```

Each bug comes back as **found**, **missed**, **inverted** (the model named the
right code and described it backwards) or **cleared** (it read the code and
declared it sound, which is the worst outcome, because you stop looking).

Ground truth lives in `lab/re-target/truth.toml`, so you can add targets of
your own.

Run it more than once. Across four runs of one model on the same prompt, the
off-by-one came back found twice, cleared once and missed once, and an earlier
run described it backwards. One run is an anecdote.

This is keyword matching over free text, not a grader. It tells you found from
missed from backwards, which is the distinction that matters when you are
deciding whether to let a model near client work.

## Layout

| Path | |
|---|---|
| `harness/` | The harness itself. About 2,400 lines, no required dependencies. |
| `lab/re-target/` | The calibration target: a vulnerable binary with its source and [answer key](lab/re-target/SPOILERS.md). |
| `corpus/` | Retrieval. Seed notes to replace with your own, see [corpus/README.md](corpus/README.md). |
| `provision/` | Setup, and the portable-bundle builder for air-gapped hosts. |
| `scripts/` | Egress verification and the libc interposer. |
| `docs/` | [Install](docs/INSTALL.md), [models](docs/MODELS.md), [offline](docs/OFFLINE.md), [where it breaks](docs/WHERE-IT-BREAKS.md). |
| `talk/` | The deck this came out of, see [talk/README.md](talk/README.md). |

## Choices I made

**No required dependencies.** The harness imports the standard library and
nothing else. A dependency means a package manager, and a package manager means
the offline story depends on something having worked earlier. `numpy` and
`r2pipe` are optional and change nothing about behaviour.

**Roles, not model names.** `plan`, `code`, `embed`. I do not name a model
anywhere in this repo because weights move faster than documentation does. See
[docs/MODELS.md](docs/MODELS.md) for sizing.

**Deny by default.** Tools carry a risk class. Anything that touches a target
is refused unless you approve it, and `auto_approve` ships empty.

**Two phases.** Provisioning needs a network once. Running needs nothing, ever.
`provision/bundle.sh` packs the whole thing up for an air-gapped host.

**Small enough to read.** This code gets pointed at client infrastructure. I
would rather it be boring and auditable than clever.

## Proving the offline claim

```bash
./scripts/egress-test.sh
```

Runs a full agent loop with every network operation intercepted at the libc
boundary, asserts nothing non-loopback was attempted, then tries
to leak on purpose to show the test can actually detect it. Without that control, "zero
packets left" is indistinguishable from "the test measured nothing."

Details and limits: [docs/OFFLINE.md](docs/OFFLINE.md).

## Where it falls apart

Local models are useful here, and they fail in repeatable ways. A wrong answer
arrives in the same confident prose as a right one, so you cannot tell them
apart without redoing the work.

The lab binary has three planted bugs. On one model across four runs, the stack
overflow was found every time, the authentication bypass was never mentioned
once, and the off-by-one was found twice, cleared once and missed once.

Run `payload score` against your own and find out, instead of taking my word
for it.

Full writeup: [docs/WHERE-IT-BREAKS.md](docs/WHERE-IT-BREAKS.md).

## Checking it yourself

```bash
make test      # no model, no network
make verify    # the above plus egress verification
```

## Background

This started as a talk, *From Prompt to Payload: Harnessing Local Models for
Offensive Work*, given at the Tokenmaxxing Village in 2026. The deck and a note
about it are in [talk/README.md](talk/README.md).

The repo is not a demo. Everything here is meant to be run, and the steps in
this README are the ones I would use on a real engagement.

## Prerequisites

Comfortable on the command line and with the usual offensive tooling. No ML
background needed. Python 3.11+, a C compiler, 16 GB of RAM to follow along.

## Licence

[MIT](../LICENSE). The corpus manifest points at third-party sources with their
own licences, so check those before redistributing a bundle built from them.
