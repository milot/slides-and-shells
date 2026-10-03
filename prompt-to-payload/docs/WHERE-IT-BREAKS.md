# Where it breaks

Local models are useful for offensive work. They are also wrong in specific,
repeatable ways, and not the ways people expect.

The trouble is not that the model is wrong. It is that a wrong answer looks
exactly like a right one. Both arrive in the same confident, well-structured
prose, and nothing in the output marks which is which. That is what costs you
time, and on an engagement it is what costs you credibility.

Everything below is reproducible against the lab binary in this repo:

```bash
cd harness && python3 -m payload score --runs 3
```

That runs your model against three planted bugs whose answers are known and
reports each as found, missed, inverted or cleared.

Run it more than once. Across four runs of one model on the same prompt the
off-by-one came back found twice, cleared once and missed once, and an earlier
run described it backwards. That spread is itself the most useful result in
this file: a single run tells you almost nothing.

## Boundary arithmetic

Off-by-one errors, bounds checks, index limits, loop termination. The model
reasons about these confidently and gets them wrong.

`set_slot()` guards with `idx > SLOT_COUNT` where it needed `idx >=`, so index
8 is accepted on an 8-element array. One model I tried found the right
function, then described the check as rejecting everything up to 8 and
accepting everything above it, which is backwards. It rated that High
confidence and invented a further finding on top of the mistake.

Bigger models do not fix this. They write a more convincing version of the same
wrong answer.

`payload score` separates two failure modes here that look the same in a
summary. **Inverted** is the model describing the guard backwards. **Cleared**
is worse: it reads the branch correctly, then reports the check sound, so you
stop looking.

Treat every boundary claim as unverified. If the model tells you a bounds check
is correct, that is the one to read yourself.

## Invented specifics

Function names, offsets, register values, flags, paths. Fluent, plausible, and
absent from the thing being analysed.

A stripped binary has no symbol names, so the model supplies them.
`check_license` is a reasonable guess for the function at `0x100000710`, but it
arrives in the same register as an observation.

The system prompt tells the model to cite addresses and to separate what it saw
from what it inferred. That helps. It does not fix it. Anything you plan to act
on should trace back to a tool call you can see:

```bash
python3 -c "
import json
for line in open('runs/transcript.jsonl'):
    r = json.loads(line)
    if r['kind'] == 'tool_call': print(r['tool'], r['args'])
"
```

Worth knowing: during one run the model garbled the binary's path twice,
turning `clients/personal` into `clients/p/personal`. The harness rejected both
calls with a usable error and it recovered. Long literal strings are not safe
in its hands either.

## Judgment on a live target

The model has no idea what a defender sees. It will suggest the loud option as
readily as the quiet one, and it does not weigh detection risk unless you make
it. It has no sense of blast radius either. "Try this against the domain
controller" and "try this against the test VM" are the same sentence to it.

That is why `approval.py` denies by default and why nothing with risk class
`touch` or `mutate` runs without a decision from you. Leave `auto_approve`
empty until you have watched a model work against something you do not mind
annoying.

The denials are useful on their own. A model that keeps reaching for a blocked
capability is telling you what its plan was.

## Confidence that means nothing

The strongest and weakest claims in a report arrive in the same tone. Ask for a
confidence rating and you get one, but it tracks how fluent the explanation was
more than how well-founded it is.

Do not ask how confident it is. Ask what evidence it has, and check whether
that evidence came from a tool. "I observed X at address Y" is checkable. "I am
highly confident" is not.

## Running out of context

A full disassembly will fill a local model's window and evict the instructions
along with everything else. You do not get an error. You get a model that
drifts, repeats a tool call it already made, or reaches a conclusion unrelated
to the evidence.

The binary tools truncate at 24,000 characters and say so. Work function by
function. If a run starts going in circles, `max_steps` ends it instead of
letting it burn an afternoon.

## Retrieval that agrees with you

A model that has already decided what it thinks will write a corpus query
shaped by that conclusion, retrieve something adjacent, and treat it as
agreement.

Check what came back. The transcript records it, and `payload corpus search`
runs the same query without a model in the loop, which is the fastest way to
find out whether the corpus had anything useful to say.

## What it is actually good at

Otherwise this reads as a reason not to bother.

Recon triage, turning scanner output into a prioritised list. You already ran
the scan; this is the hour afterwards, and it is real time saved.

Reading unfamiliar code, in a language or codebase you did not write, at the
speed of reading instead of the speed of learning.

Translating between tool syntaxes. Low risk, because you can see immediately
whether the output is right.

Turning raw output into prose a client can read, which is the part nobody
enjoys and everybody bills for.

The pattern: it is good at transformation, where the input is in front of it
and you can check the result. It is bad at judgment, where the input is partial
and the output is a decision. Keep it on the transformation side of that line
and it earns its keep.
