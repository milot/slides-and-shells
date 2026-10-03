"""Command line interface.

    payload doctor                 check the environment
    payload re <binary>            reverse engineer a binary
    payload triage <artifact>      triage saved recon output
    payload ask "<question>"       general question, with tools
    payload corpus build <dir>     embed a directory into the corpus
    payload corpus stats           what is in the corpus
    payload corpus search "<q>"    query the corpus directly, no model
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from payload import __version__, config as config_mod, egress, prompts
from payload.agent import Agent
from payload.approval import auto_approver, interactive_approver
from payload.models import ModelClient, ModelError
from payload.tools import build as build_registry
from payload.transcript import Transcript


def _require_plan_role(cfg) -> bool:
    """Every agent command needs a `plan` role. Say so instead of crashing.

    Without this, running the installed console script from a directory with
    no payload.toml in the search path raises a KeyError from deep inside the
    model client.
    """
    if "plan" in cfg.roles:
        return True

    source = getattr(cfg, "note_source", None)
    print("no 'plan' role is configured, so there is no model to run.",
          file=sys.stderr)
    print(file=sys.stderr)
    if source:
        print(f"  config read from {source}", file=sys.stderr)
    else:
        print("  no payload.toml was found. Looked in the working directory,",
              file=sys.stderr)
        print("  its parent, and ~/.config/payload/payload.toml.",
              file=sys.stderr)
    print("  Point at one with --config, or set PAYLOAD_CONFIG.",
          file=sys.stderr)
    print("  To start from scratch, copy harness/payload.toml.example.",
          file=sys.stderr)
    return False


def _store_and_embedder(cfg, client):
    """Open the corpus if one exists. Absent is a normal state, not an error."""
    from payload.rag.store import Store

    if not Path(cfg.db_path).is_file():
        return None, None
    store = Store(cfg.db_path)
    if store.count() == 0:
        return None, None
    return store, (lambda texts: client.embed(texts))


def _run_agent(cfg, task: str, system: str, root: Path, yes: bool) -> int:
    if not _require_plan_role(cfg):
        return 2
    client = ModelClient(cfg)
    store, embedder = _store_and_embedder(cfg, client)
    registry = build_registry(root, store=store, embedder=embedder)
    transcript = Transcript(cfg.transcript_path)

    approver = (auto_approver(cfg.auto_approve) if yes
                else interactive_approver(cfg.auto_approve))

    agent = Agent(cfg, registry, client, transcript, approver)

    print(f"  tools     {len(registry)} registered", file=sys.stderr)
    print(f"  corpus    {store.count() if store else 0} chunks", file=sys.stderr)
    print(f"  transcript {transcript.path}", file=sys.stderr)
    print(f"  offline   {'locked' if egress.is_locked() else 'UNLOCKED'}",
          file=sys.stderr)
    print(file=sys.stderr)

    try:
        result = agent.run(task, system)
    except ModelError as exc:
        print(f"model error: {exc}", file=sys.stderr)
        return 1

    print(result.answer)

    if result.stopped_early:
        print(f"\n[stopped at the {cfg.max_steps}-step budget. The answer above "
              f"is the last thing the model said, not a conclusion.]",
              file=sys.stderr)
    if result.denied:
        print(f"\n[denied during this run: {', '.join(sorted(set(result.denied)))}]",
              file=sys.stderr)
    return 0


# ------------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    cfg = config_mod.load(args.config)

    print(f"payload {__version__}\n")

    print("environment")
    print(f"  python          {sys.version.split()[0]}")
    print(f"  offline lock    {'on' if egress.is_locked() else 'OFF'}")
    print(f"  config source   {getattr(cfg, 'note_source', '(defaults)')}")

    print("\nroles")
    if not cfg.roles:
        print("  none configured. Copy payload.toml.example to payload.toml.")
    for name, role in cfg.roles.items():
        print(f"  {name:6} {role.model}  -> {role.endpoint}")

    print("\nanalysis tooling")
    for tool, note in [
        ("r2", "radare2: better analysis and a pseudo-decompiler"),
        ("objdump", "fallback disassembly"),
        ("nm", "symbol table"),
        ("strings", "string extraction"),
        ("otool", "Mach-O headers (macOS)"),
        ("readelf", "ELF headers (Linux)"),
        ("nmap", "scanning (optional)"),
    ]:
        found = shutil.which(tool)
        mark = "yes" if found else "no "
        print(f"  {mark}  {tool:9} {note}")

    print("\ncorpus")
    db = Path(cfg.db_path)
    if db.is_file():
        from payload.rag.store import Store
        store = Store(db)
        print(f"  {store.count()} chunks at {db}")
        for source, count in store.sources():
            print(f"    {count:6d}  {source}")
        model = store.get_meta("embed_model")
        if model:
            print(f"  embedded with {model}")
    else:
        print(f"  no corpus at {db}. Retrieval will be unavailable.")

    print("\nmodel reachability")
    if not cfg.roles:
        print("  skipped: no roles configured")
        return 0

    client = ModelClient(cfg)
    ok = True
    for name, role in cfg.roles.items():
        # A raw 404 for "REPLACE-ME-reasoning" is a confusing first run.
        if "REPLACE-ME" in role.model:
            ok = False
            print(f"  no   {name}: still a placeholder. Pick a model "
                  f"(docs/MODELS.md), pull it, and edit payload.toml.")
            continue
        try:
            if name == "embed":
                client.embed(["probe"])
            else:
                client.chat(name, [{"role": "user", "content": "say ok"}],
                            retries=0)
            print(f"  yes  {name}")
        except Exception as exc:
            ok = False
            print(f"  no   {name}: {str(exc)[:140]}")

    return 0 if ok else 1


# ------------------------------------------------------------------ commands

def cmd_re(args) -> int:
    cfg = config_mod.load(args.config)
    binary = Path(args.binary).expanduser().resolve()
    if not binary.is_file():
        print(f"no such binary: {binary}", file=sys.stderr)
        return 2

    task = (
        f"Reverse engineer the stripped binary at {binary}.\n\n"
        f"Identify its functionality and any memory-safety or logic "
        f"vulnerabilities. Report each finding with the address, the evidence "
        f"you based it on, and your confidence."
    )
    if args.task:
        task = args.task + f"\n\nThe binary is at {binary}."

    return _run_agent(cfg, task, prompts.RE_ANALYST, binary.parent, args.yes)


def _find_lab() -> Path | None:
    """Locate the bundled lab target by walking up from this package.

    The default used to be a path relative to the working directory, which
    only worked from inside harness/. `payload` is an installed console
    script, so it has to work from anywhere.
    """
    for base in Path(__file__).resolve().parents:
        candidate = base / "lab" / "re-target"
        if (candidate / "truth.toml").is_file():
            return candidate
    return None


def cmd_score(args) -> int:
    """Run a model against a target with known bugs and score what it found."""
    from payload.score import load_truth, render, score

    cfg = config_mod.load(args.config)
    lab = _find_lab()

    if args.binary:
        binary = Path(args.binary).expanduser().resolve()
    elif lab:
        binary = lab / "dist" / "vulnbox"
    else:
        print("could not find the bundled lab target. Pass a binary path.",
              file=sys.stderr)
        return 2

    if args.truth:
        truth_path = Path(args.truth)
    elif (binary.parent.parent / "truth.toml").is_file():
        truth_path = binary.parent.parent / "truth.toml"
    elif lab:
        truth_path = lab / "truth.toml"
    else:
        truth_path = Path("truth.toml")

    if not truth_path.is_file():
        print(f"no ground truth at {truth_path}.", file=sys.stderr)
        print("Pass --truth, or run from a checkout that has "
              "lab/re-target/truth.toml.", file=sys.stderr)
        return 2
    truth = load_truth(truth_path)

    if args.answer:
        # Score a saved answer without running anything.
        card = score(Path(args.answer).read_text(), truth)
        print(render(card, f"saved answer: {args.answer}"))
        return 0

    if not binary.is_file():
        print(f"no such binary: {binary}", file=sys.stderr)
        if lab:
            print(f"build it first: make -C {lab} all", file=sys.stderr)
        return 2

    model = cfg.roles["plan"].model if "plan" in cfg.roles else "?"
    task = (
        f"Reverse engineer the stripped binary at {binary}.\n\n"
        f"Identify its functionality and any memory-safety or logic "
        f"vulnerabilities. Report each finding with the address, the evidence "
        f"you based it on, and your confidence."
    )

    cards = []
    for run in range(1, args.runs + 1):
        if args.runs > 1:
            print(f"run {run} of {args.runs}", file=sys.stderr)
        answer = _capture_answer(cfg, task, prompts.RE_ANALYST, binary.parent)
        if answer is None:
            return 1
        card = score(answer, truth)
        cards.append(card)
        if args.save:
            out = Path(args.save).with_suffix(f".{run}.txt")
            out.write_text(answer)
            print(f"  answer saved to {out}", file=sys.stderr)
        print()
        print(render(card, f"{model}  (run {run})"))

    if len(cards) > 1:
        print()
        print("across runs:")
        for bug_index, result in enumerate(cards[0].results):
            verdicts = [c.results[bug_index].verdict for c in cards]
            tally = ", ".join(f"{v}x{verdicts.count(v)}"
                              for v in sorted(set(verdicts)))
            print(f"  {result.id:12} {tally}")
        print()
        print("  These models are not deterministic. One run is an anecdote.")

    return 0


def _capture_answer(cfg, task: str, system: str, root: Path) -> str | None:
    """Run the agent and return just its final answer."""
    if not _require_plan_role(cfg):
        return None
    client = ModelClient(cfg)
    store, embedder = _store_and_embedder(cfg, client)
    registry = build_registry(root, store=store, embedder=embedder)
    transcript = Transcript(cfg.transcript_path)
    agent = Agent(cfg, registry, client, transcript,
                  auto_approver(cfg.auto_approve))
    try:
        return agent.run(task, system).answer
    except ModelError as exc:
        print(f"model error: {exc}", file=sys.stderr)
        return None


def cmd_triage(args) -> int:
    cfg = config_mod.load(args.config)
    artifact = Path(args.artifact).expanduser().resolve()
    if not artifact.is_file():
        print(f"no such file: {artifact}", file=sys.stderr)
        return 2

    task = (
        f"Triage the reconnaissance output at {artifact}. Parse it, then give "
        f"me a prioritised list of what is worth investigating, with your "
        f"reasoning. Say what is missing or unscanned."
    )
    return _run_agent(cfg, task, prompts.RECON_TRIAGE, artifact.parent, args.yes)


def cmd_ask(args) -> int:
    cfg = config_mod.load(args.config)
    root = Path(args.root).expanduser().resolve()
    return _run_agent(cfg, args.question, prompts.GENERAL, root, args.yes)


# -------------------------------------------------------------------- corpus

def cmd_corpus_build(args) -> int:
    cfg = config_mod.load(args.config)
    from payload.rag.ingest import collect
    from payload.rag.store import Store

    source_dir = Path(args.path).expanduser().resolve()
    if not source_dir.exists():
        print(f"no such path: {source_dir}", file=sys.stderr)
        return 2

    # Check before touching the store, or a failed build leaves an empty db
    # behind and doctor then reports "0 chunks".
    if "embed" not in cfg.roles:
        print("no [roles.embed] is configured, so there is nothing to embed "
              "with.", file=sys.stderr)
        print(file=sys.stderr)
        print("  The corpus is optional. Binary analysis does not use it.",
              file=sys.stderr)
        print("  To add one:", file=sys.stderr)
        print("      ollama pull qwen3-embedding:8b", file=sys.stderr)
        print("  then add to harness/payload.toml:", file=sys.stderr)
        print("      [roles.embed]", file=sys.stderr)
        print('      model = "qwen3-embedding:8b"', file=sys.stderr)
        return 1

    name = args.name or source_dir.name
    chunks = collect(source_dir, name)
    if not chunks:
        print(f"no text documents found under {source_dir}", file=sys.stderr)
        print("recognised suffixes: .md .markdown .txt .rst .adoc",
              file=sys.stderr)
        return 1

    print(f"{len(chunks)} chunks from {source_dir}")

    client = ModelClient(cfg)
    store = Store(cfg.db_path)

    removed = store.clear_source(name)
    if removed:
        print(f"replaced {removed} existing chunks for source {name!r}")

    from payload.rag.embed import embed_all

    def progress(done: int, total: int) -> None:
        print(f"\r  embedding {done}/{total}", end="", file=sys.stderr)

    try:
        vectors = embed_all(
            lambda texts: client.embed(texts),
            [c.text for c in chunks],
            batch_size=args.batch,
            progress=progress,
        )
    except ModelError as exc:
        print(f"\nembedding failed: {exc}", file=sys.stderr)
        return 1
    print(file=sys.stderr)

    for chunk, vector in zip(chunks, vectors):
        store.add(chunk.source, chunk.title, chunk.text, vector)
    store.commit()
    store.set_meta("embed_model", cfg.role("embed").model)
    store.set_meta("embed_dim", str(len(vectors[0])))

    print(f"corpus now holds {store.count()} chunks at {cfg.db_path}")
    return 0


def cmd_corpus_stats(args) -> int:
    cfg = config_mod.load(args.config)
    from payload.rag.store import Store

    db = Path(cfg.db_path)
    if not db.is_file():
        print(f"no corpus at {db}")
        return 1
    store = Store(db)
    print(f"{store.count()} chunks at {db}")
    print(f"embedded with {store.get_meta('embed_model', 'unknown')} "
          f"({store.get_meta('embed_dim', '?')} dimensions)")
    for source, count in store.sources():
        print(f"  {count:6d}  {source}")
    return 0


def cmd_corpus_search(args) -> int:
    cfg = config_mod.load(args.config)
    from payload.rag.store import Store

    db = Path(cfg.db_path)
    if not db.is_file():
        print(f"no corpus at {db}", file=sys.stderr)
        return 1

    client = ModelClient(cfg)
    store = Store(db)
    try:
        vector = client.embed([args.query])[0]
    except ModelError as exc:
        print(f"embedding failed: {exc}", file=sys.stderr)
        return 1

    hits = store.search(vector, k=args.k)
    for rank, hit in enumerate(hits, 1):
        print(f"\n[{rank}] {hit.source} - {hit.title}   similarity {hit.score:.4f}")
        print(hit.text[:600])
    return 0


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="payload",
        description="An offensive AI harness that runs on local hardware.",
    )
    parser.add_argument("--config", help="path to payload.toml")
    parser.add_argument("--version", action="version",
                        version=f"payload {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--yes", action="store_true",
                       help="do not prompt for approval; pre-approved tools "
                            "only, everything else is still denied")

    p = sub.add_parser("doctor", help="check the environment")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("re", help="reverse engineer a binary")
    p.add_argument("binary")
    p.add_argument("--task", help="override the default instruction")
    add_common(p)
    p.set_defaults(func=cmd_re)

    p = sub.add_parser("score",
                       help="score a model against a target with known bugs")
    p.add_argument("binary", nargs="?",
                   help="defaults to the bundled lab target")
    p.add_argument("--truth", help="path to truth.toml")
    p.add_argument("--runs", type=int, default=1,
                   help="repeat N times; these models are not deterministic")
    p.add_argument("--answer", help="score a saved answer instead of running")
    p.add_argument("--save", help="write each answer to <path>.N.txt")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("triage", help="triage saved recon output")
    p.add_argument("artifact")
    add_common(p)
    p.set_defaults(func=cmd_triage)

    p = sub.add_parser("ask", help="ask a question with tools available")
    p.add_argument("question")
    p.add_argument("--root", default=".", help="filesystem root for tools")
    add_common(p)
    p.set_defaults(func=cmd_ask)

    corpus = sub.add_parser("corpus", help="manage the retrieval corpus")
    csub = corpus.add_subparsers(dest="corpus_command", required=True)

    c = csub.add_parser("build", help="embed a directory into the corpus")
    c.add_argument("path")
    c.add_argument("--name", help="source label, defaults to the directory name")
    c.add_argument("--batch", type=int, default=32)
    c.set_defaults(func=cmd_corpus_build)

    c = csub.add_parser("stats", help="what is in the corpus")
    c.set_defaults(func=cmd_corpus_stats)

    c = csub.add_parser("search", help="query the corpus without a model")
    c.add_argument("query")
    c.add_argument("-k", type=int, default=5)
    c.set_defaults(func=cmd_corpus_search)

    args = parser.parse_args(argv)
    return args.func(args)
