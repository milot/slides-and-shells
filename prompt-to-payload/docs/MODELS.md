# Models

## Why I do not name a model here

Weights move faster than documentation. Anything I called "the one to use" would be
wrong within a couple of months, and a stale recommendation stated confidently
is worse than no recommendation, because people act on it.

So the harness is built around roles, and you decide what fills them when you
provision, against whatever is current.

`plan` does the reasoning, picks tools, and writes findings. It wants
instruction-following and reliable tool calling more than it wants raw
knowledge.

`code` reads decompiled C and reviews source. A smaller code-trained model
usually beats a larger generalist here.

`embed` turns the corpus and your queries into vectors. This has to be a real
embedding model. A chat model will produce something, and it will retrieve
badly in ways you will not notice for a while.

### Picking one

Tool calling is the binding constraint, not size. A model that emits malformed
tool calls is useless here no matter how well it reasons. Test that first: run
`payload re` against the lab binary and watch the calls. The harness copes with
three dialects of tool-call arguments and will tell you when it is getting none
of them.

Context length matters more than you would think for RE work. Disassembly is
enormous, and a small window gets spent on one function.

Below about 4-bit, quantisation degrades reasoning while leaving fluency
intact. For this work that is the worst possible trade, because the output
still reads fine.

The honest answer to "which model" is to look at what people are running this
month and test two of them.

---

## Memory tiers

Sizing by total usable memory: unified memory on Apple Silicon, VRAM plus
spillover on a discrete GPU, system RAM on CPU-only.

| Memory | Realistic setup | What it feels like |
|---|---|---|
| **8 GB** | One small model, ~3–4B class, 4-bit. Roles collapse to one. | Works for recon triage and syntax translation. RE is a stretch; expect to do the structural thinking yourself. |
| **16 GB** | One ~7–8B class model at 4-bit, plus a small embedder resident. | The floor for useful RE work, and the stated prerequisite. Swapping between a chat and code model costs seconds. |
| **32 GB** | ~14B class at 4-bit, or 7B at 8-bit, plus embedder. | Comfortable. Noticeably better at holding a multi-step analysis together. |
| **64 GB** | ~30B class, or a mid-size MoE. Two models resident. | Genuine role separation: `plan` and `code` both stay loaded. |
| **128 GB+** | ~70B class at 4-bit, or a large MoE. All three roles resident. | Everything stays in memory and routing is free. |

### About the machine I measured on

I run 128 GB of unified memory, well above the 16 GB floor in the
prerequisites. Same three bugs and the same ground-truth source at every size,
so you can see what actually degrades between a large model and a small one.

What I have seen. Check it, do not take my word:

The stack overflow gets found at every size. It is pattern matching and models
are good at that.

The auth bypass starts getting missed as models shrink, and the miss is silent.
A smaller model does not flag it as uncertain, it just never mentions it.

The off-by-one is wrong at every size I have tried, including the largest.
Scale does not fix it. It produces a better-written wrong answer.

That last one is the most useful thing in this file.

---

## A concrete starting point

Checked against the Ollama library on **2026-10-03**. Dated because it will go stale, which is
the thing this file opens by warning about. Check it before you rely on it:

```bash
ollama list                      # what you already have
curl -s https://ollama.com/library | grep -o 'library/[a-z0-9.-]*' | sort -u
```

### On 128 GB unified memory, all three roles resident

```bash
ollama pull gpt-oss:120b              # 65 GB   plan
ollama pull qwen3.6:27b-coding        # 18 GB   code
ollama pull qwen3-embedding:8b        # 4.7 GB  embed
```

About 88 GB resident. macOS caps GPU-wired memory at roughly 75% of RAM by
default, which is ~96 GB here, so that fits but without much room. If you hit
swapping, either raise the cap for the session or drop the plan role to
`qwen3.6:35b` (23 GB):

```bash
sudo sysctl iogpu.wired_limit_mb=114688    # 112 GB, resets on reboot
```

### Lighter, and still does the job

```bash
ollama pull qwen3.6:35b               # 23 GB   plan
ollama pull qwen3.6:27b-coding        # 18 GB   code
ollama pull qwen3-embedding:8b        # 4.7 GB  embed
```

About 46 GB, leaving plenty of headroom for context. Worth starting here and
only going bigger if scoring says it helps.

### Then wire it up

```toml
# harness/payload.toml
endpoint = "http://127.0.0.1:11434/v1"

[roles.plan]
model = "gpt-oss:120b"

[roles.code]
model = "qwen3.6:27b-coding"

[roles.embed]
model = "qwen3-embedding:8b"
```

```bash
cd harness && python3 -m payload doctor
```

### Do not take the above on trust

I checked the sizes and names. I did not check tool-calling quality, which is
the thing that actually decides whether a model works here and cannot be read
off a model card. Pull two and score them against the lab binary:

```bash
cd harness
PAYLOAD_MODEL_PLAN=gpt-oss:120b python3 -m payload re ../lab/re-target/dist/vulnbox
PAYLOAD_MODEL_PLAN=qwen3.6:35b  python3 -m payload re ../lab/re-target/dist/vulnbox
```

Then read both against `lab/re-target/SPOILERS.md`. See which found the auth
bypass and whether either got the off-by-one right. Twenty minutes, and it
beats any recommendation including mine.

---

## Collapsing roles on a small machine

With limited memory, point every chat role at one model:

```toml
endpoint = "http://127.0.0.1:11434/v1"

[roles.plan]
model = "your-chat-model"

[roles.embed]
model = "your-embedding-model"
```

Omit `[roles.code]` entirely. The harness falls back to `plan` for any missing
chat role, but it will **not** fall back for `embed`, because embedding with a
chat model produces a corpus that retrieves badly in ways nobody notices until
it matters.

---

## Pinning

Once a corpus is built, the embedding model is fixed. Change it and every
stored vector is meaningless. The store raises a dimension-mismatch error
instead of quietly returning nonsense ranked by distances that mean nothing.

Record what you used:

```bash
cd harness && python3 -m payload corpus stats
```

For a reproducible bundle, pin by digest, not by tag. Tags get moved; a
model that silently changed underneath you is indistinguishable from a model
that got worse.
