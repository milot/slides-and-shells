# Install

Two platforms, both first-class: Arch (and Arch-derived, including Omarchy)
and macOS. Every command below is meant to be pasted.

The harness itself needs **Python 3.11 or newer and nothing else**. Everything
in this document beyond that is either a model runtime or an analysis tool that
makes the harness more useful.

---

## 1. Base requirements

### Arch

```bash
sudo pacman -S --needed python base-devel git
```

`base-devel` provides the C compiler used by the lab target and the egress
interposer.

### macOS

```bash
xcode-select --install          # compiler and the binutils used below
brew install python git
```

Check:

```bash
python3 -c 'import sys; print(sys.version)'   # must be 3.11+
cc --version
```

Python 3.11 is the floor because the config loader uses `tomllib`, which
entered the standard library in that release. Using it instead of a TOML
package is what keeps the dependency count at zero.

---

## 2. A model runtime

You need something that serves an OpenAI-compatible API on loopback. Any of
these work; the harness does not care which.

### Ollama: simplest

```bash
# Arch
sudo pacman -S ollama
systemctl --user enable --now ollama

# macOS
brew install ollama
brew services start ollama
```

Serves `http://127.0.0.1:11434/v1`. That is the harness default, so no config
change is needed.

### llama.cpp: most control

```bash
# Arch
sudo pacman -S llama.cpp        # or build from source for a specific backend

# macOS
brew install llama.cpp
```

```bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8080 -ngl 999
```

Then set `endpoint = "http://127.0.0.1:8080/v1"` in `payload.toml`.

`-ngl 999` offloads every layer it can to the GPU. On Apple Silicon that is
Metal and it matters enormously; on a CPU-only box, drop it.

### MLX: Apple Silicon only, usually fastest there

```bash
pip install mlx-lm
mlx_lm.server --host 127.0.0.1 --port 8080
```

Benchmark it against llama.cpp on your own hardware. Which one wins changes
with the release, so do not take anyone's word for it, including mine.

### LM Studio

Enable the local server in its UI. It serves an OpenAI-compatible API, usually
on port 1234.

---

## 3. Analysis tooling

All optional. The harness degrades to tools that ship with both operating
systems, and says so when a capability is missing instead of failing opaquely.

### radare2: recommended

Gives real function discovery and a pseudo-decompiler. Without it, the binary
tools fall back to `objdump`, `nm` and `strings`, which still work but give the
model noticeably worse material.

```bash
# Arch
sudo pacman -S radare2

# macOS
brew install radare2
```

### Ghidra: optional, best decompiler

```bash
# Arch
sudo pacman -S ghidra            # or: yay -S ghidra-bin

# macOS
brew install --cask ghidra
```

Not wired in yet. Nothing in the harness calls Ghidra; `binary_decompile` uses
radare2's `pdc`. Install it if you want to run `analyzeHeadless` by hand, and
see the TODO in `payload/tools/binary.py` if you want to add it.

### Scanners

```bash
# Arch
sudo pacman -S nmap
# macOS
brew install nmap
```

Only needed if you want to produce fresh recon output. The harness parses
*saved* scanner output, which needs nothing installed at all.

---

## 4. The harness

```bash
git clone <this repo> prompt-to-payload
cd prompt-to-payload
./provision/provision.sh
```

Provisioning builds the lab target, verifies its bugs are reachable, builds the
egress interposer, and creates `harness/payload.toml` from the example.

Then choose your models (see [MODELS.md](MODELS.md)), pull them, and edit
`harness/payload.toml` to replace the `REPLACE-ME` placeholders.

Check everything:

```bash
cd harness
python3 -m payload doctor
```

`doctor` reports Python version, offline lock state, which analysis tools it
found, corpus contents, and whether each configured role actually answers.

---

## 5. Confirm it works

Before any weights are downloaded, you can exercise the whole loop against a
stub model:

```bash
# terminal 1
python3 harness/tests/stub_server.py 11455

# terminal 2
cd harness
PAYLOAD_MODEL_PLAN=stub PAYLOAD_ENDPOINT=http://127.0.0.1:11455/v1 \
  python3 -m payload re ../lab/re-target/dist/vulnbox --yes
```

If that completes, your install is sound and the only remaining variable is
the model.

Then the real thing:

```bash
cd harness
python3 -m payload re ../lab/re-target/dist/vulnbox
```

And the tests, which need neither model nor network:

```bash
python3 harness/tests/test_agent.py
python3 harness/tests/test_egress.py
./lab/re-target/verify.sh
./scripts/egress-test.sh
```

---

## Troubleshooting

**`cannot reach http://127.0.0.1:11434/v1`**: the model server is not
running. `systemctl --user status ollama`, or start `llama-server` by hand.

**`refusing to contact ... the harness is locked offline`**: working as
designed. Your endpoint is not loopback. Either correct it, or if you
genuinely intend to reach a remote model, `PAYLOAD_OFFLINE=0`, understanding
that this is the thing the whole project exists to avoid.

**`no 'embed' role configured`**: retrieval needs a real embedding model.
The harness refuses to substitute a chat model because the resulting corpus
retrieves badly without ever obviously failing.

**`embedding dimension mismatch`**: the corpus was built with a different
embedding model than the one now configured. Rebuild it:
`python3 -m payload corpus build <dir>`.

**radare2 missing**: expected, and fine. `binary_decompile` returns an
explanatory error; everything else falls back to `objdump` and friends.

**macOS: egress-test says the interposer is not active.** Your `python3` is
hardened or SIP-protected, so `DYLD_INSERT_LIBRARIES` is ignored. Use a
Homebrew or python.org interpreter. The test detects this and refuses to
report a false pass.
