"""Filesystem tools, confined to a root.

Paths are resolved and checked against the root before anything is opened. A
local model will try to read /etc/shadow or wander up with ../../.., not out of
malice but because it pattern-matched a tutorial.
"""

from __future__ import annotations

import os
from pathlib import Path

from payload.tools.base import Tool, ToolError

MAX_READ = 40_000


class Sandbox:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"sandbox root {self.root} is not a directory")

    def resolve(self, candidate: str) -> Path:
        """Resolve `candidate` inside the root, or refuse.

        The check is on the resolved form, which handles both `..` traversal
        and symlinks pointing outward.
        """
        target = (self.root / candidate).resolve() if not Path(candidate).is_absolute() \
            else Path(candidate).resolve()

        if target != self.root and self.root not in target.parents:
            raise ToolError(
                f"{candidate!r} resolves outside the permitted root "
                f"({self.root}). Only paths under that root can be read."
            )
        return target


def register(registry, sandbox: Sandbox) -> None:

    def read_file(path: str, start: int = 1, lines: int = 400) -> str:
        target = sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file that exists")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ToolError(f"cannot read {path!r}: {exc}") from exc

        all_lines = content.splitlines()
        window = all_lines[max(0, start - 1):max(0, start - 1) + lines]
        numbered = "\n".join(
            f"{start + i:5d}  {line}" for i, line in enumerate(window)
        )
        if len(numbered) > MAX_READ:
            numbered = numbered[:MAX_READ] + "\n[truncated - request fewer lines]"

        header = (f"{target.relative_to(sandbox.root) if target != sandbox.root else target}"
                  f"  lines {start}-{start + len(window) - 1} of {len(all_lines)}")
        return header + "\n" + numbered

    def list_dir(path: str = ".") -> str:
        target = sandbox.resolve(path)
        if not target.is_dir():
            raise ToolError(f"{path!r} is not a directory")

        entries = []
        for item in sorted(target.iterdir()):
            kind = "dir " if item.is_dir() else "file"
            size = "" if item.is_dir() else f"  {item.stat().st_size:>9d} bytes"
            entries.append(f"  {kind}  {item.name}{size}")
        return f"{path}\n" + ("\n".join(entries) or "  (empty)")

    def grep(pattern: str, path: str = ".", max_results: int = 80) -> str:
        import re
        target = sandbox.resolve(path)
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regular expression: {exc}") from exc

        files = [target] if target.is_file() else [
            p for p in target.rglob("*") if p.is_file()
        ]

        hits: list[str] = []
        for file in files:
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    rel = file.relative_to(sandbox.root)
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        return "\n".join(hits) + f"\n[stopped at {max_results} matches]"

        return "\n".join(hits) if hits else f"no matches for {pattern!r}"

    registry.add(Tool(
        name="read_file",
        description="Read a text file, with line numbers. Paths are confined to the engagement root.",
        risk="read",
        handler=read_file,
        parameters={
            "path": {"type": "string"},
            "start": {"type": "integer", "minimum": 1},
            "lines": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        required=("path",),
    ))

    registry.add(Tool(
        name="list_dir",
        description="List a directory.",
        risk="read",
        handler=list_dir,
        parameters={"path": {"type": "string"}},
    ))

    registry.add(Tool(
        name="grep",
        description="Search files under a path for a regular expression.",
        risk="read",
        handler=grep,
        parameters={
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        required=("pattern",),
    ))
