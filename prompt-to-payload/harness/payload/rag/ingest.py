"""Corpus ingestion.

Chunking is paragraph-aware with overlap. Pentest reference material is dense
and heavily structured - a command and the sentence explaining what it does are
often adjacent, and splitting them produces chunks that retrieve well and help
nobody. Overlap is cheap insurance against that.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# Characters, not tokens. An exact count would mean a tokenizer per model, and
# this does not need to be exact.
CHUNK_CHARS = 1400
OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 80

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc"}


@dataclass
class Chunk:
    source: str
    title: str
    text: str


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def chunk_text(text: str, source: str, title: str = "") -> list[Chunk]:
    paragraphs = _split_paragraphs(text)
    chunks: list[Chunk] = []
    buffer = ""

    for paragraph in paragraphs:
        # A paragraph longer than the budget gets hard-split instead of
        # dropped; long fenced code blocks are common in this material.
        if len(paragraph) > CHUNK_CHARS:
            if buffer:
                chunks.append(Chunk(source, title, buffer.strip()))
                buffer = ""
            for start in range(0, len(paragraph), CHUNK_CHARS - OVERLAP_CHARS):
                piece = paragraph[start:start + CHUNK_CHARS]
                if len(piece) >= MIN_CHUNK_CHARS:
                    chunks.append(Chunk(source, title, piece.strip()))
            continue

        if len(buffer) + len(paragraph) + 2 > CHUNK_CHARS:
            chunks.append(Chunk(source, title, buffer.strip()))
            tail = buffer[-OVERLAP_CHARS:] if OVERLAP_CHARS else ""
            buffer = tail + "\n\n" + paragraph
        else:
            buffer = (buffer + "\n\n" + paragraph) if buffer else paragraph

    if len(buffer.strip()) >= MIN_CHUNK_CHARS:
        chunks.append(Chunk(source, title, buffer.strip()))

    return chunks


def _title_for(path: Path, text: str) -> str:
    """Prefer the document's own first heading over its filename."""
    for line in text.splitlines()[:40]:
        heading = re.match(r"^#{1,3}\s+(.+)", line.strip())
        if heading:
            return heading.group(1).strip()[:120]
    return path.stem.replace("-", " ").replace("_", " ")


def collect(root: Path, source: str) -> list[Chunk]:
    """Chunk every text document under `root`."""
    chunks: list[Chunk] = []
    if root.is_file():
        files = [root]
    else:
        files = sorted(
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
        )

    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text.strip()) < MIN_CHUNK_CHARS:
            continue
        chunks.extend(chunk_text(text, source, _title_for(file, text)))

    return chunks


def fingerprint(chunks: list[Chunk]) -> str:
    """Stable digest of a chunk set, so a rebuild can be detected as a no-op."""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()[:16]
