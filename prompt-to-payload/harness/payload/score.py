"""Score a model's findings against known ground truth.

The point of this module: before you trust a local model with client work, find
out what it gets right on a target where the answer is already known. The lab
binary has three planted bugs of graded difficulty and its source ships with
it, so a model's output can be checked instead of admired.

What this is: keyword matching over the model's free-text answer, driven by
patterns in `truth.toml`. It distinguishes "found it" from "never mentioned it"
from "described it backwards".

What this is not: a grader. It cannot tell you whether the reasoning was sound,
and it will not catch a finding phrased in a way the patterns miss. Read the
model's actual output as well. The score is a filter, not a verdict.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

FOUND = "found"
MISSED = "missed"
INVERTED = "inverted"
# The model looked at the code and declared it sound. Worse than silence: it
# arrives as a cleared finding, so you stop looking.
CLEARED = "cleared"


@dataclass
class BugResult:
    id: str
    title: str
    severity: str
    verdict: str
    expected: str
    matched: list[str] = field(default_factory=list)


@dataclass
class Scorecard:
    results: list[BugResult]
    addresses_cited: int
    answer_chars: int

    @property
    def found(self) -> int:
        return sum(1 for r in self.results if r.verdict == FOUND)

    @property
    def inverted(self) -> int:
        return sum(1 for r in self.results if r.verdict == INVERTED)

    @property
    def cleared(self) -> int:
        return sum(1 for r in self.results if r.verdict == CLEARED)

    @property
    def missed(self) -> int:
        return sum(1 for r in self.results if r.verdict == MISSED)


def normalise(text: str) -> str:
    """Fold the unicode a model emits into something patterns can match.

    Models produce U+2010/U+2011 inside words like "stack-buffer" and U+2264
    for <=, often enough that naive matching misses real findings.
    """
    text = unicodedata.normalize("NFKC", text)
    for ch in "‐‑‒–—−":
        text = text.replace(ch, "-")
    text = text.replace("≤", "<=").replace("≥", ">=")
    return re.sub(r"\s+", " ", text)


def load_truth(path: str | Path) -> dict:
    with Path(path).open("rb") as fh:
        return tomllib.load(fh)


def _any(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.I)]


def score(answer: str, truth: dict) -> Scorecard:
    text = normalise(answer)
    results: list[BugResult] = []

    for bug in truth.get("bug", []):
        inverted_hits = _any(bug.get("inverted", []), text)
        evidence_hits = _any(bug.get("evidence", []), text)
        cleared_hits = _any(bug.get("cleared", []), text)

        # Precedence: a specific, correct identification wins over everything
        # else. A long answer can describe the bug accurately in one place and
        # phrase something sloppily in another, and the find is what counts.
        if evidence_hits:
            verdict, matched = FOUND, evidence_hits
        elif inverted_hits:
            verdict, matched = INVERTED, inverted_hits
        elif cleared_hits:
            verdict, matched = CLEARED, cleared_hits
        else:
            verdict, matched = MISSED, []

        results.append(BugResult(
            id=bug["id"],
            title=bug["title"],
            severity=bug.get("severity", "?"),
            verdict=verdict,
            expected=bug.get("expected", ""),
            matched=matched[:4],
        ))

    return Scorecard(
        results=results,
        # A claim with an address behind it can be checked. One without cannot.
        addresses_cited=len(set(re.findall(r"0x[0-9a-fA-F]{6,}", text))),
        answer_chars=len(answer),
    )


def render(card: Scorecard, model: str = "") -> str:
    mark = {FOUND: "found   ", INVERTED: "INVERTED", CLEARED: "CLEARED ",
            MISSED: "missed  "}
    lines = []
    if model:
        lines.append(f"model: {model}")
    lines.append("")
    for r in card.results:
        lines.append(f"  {mark[r.verdict]}  {r.title}")
        lines.append(f"            severity {r.severity}, typically {r.expected}")
        if r.matched:
            lines.append(f"            matched {', '.join(repr(m) for m in r.matched)}")
    lines.append("")
    lines.append(f"  {card.found} found, {card.inverted} inverted, "
                 f"{card.cleared} cleared, {card.missed} missed"
                 f"   ({card.addresses_cited} distinct addresses cited)")
    if card.inverted:
        lines.append("")
        lines.append("  An inverted finding is worse than a miss: the model named the")
        lines.append("  right code and described its behaviour backwards.")
    if card.cleared:
        lines.append("")
        lines.append("  A cleared finding is worse still. The model read the code and")
        lines.append("  reported it sound, so you stop looking.")
    return "\n".join(lines)
