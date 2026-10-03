"""Embedding helpers.

Batched: a local embedding server is much faster with a list than with the
same texts one at a time.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

Embedder = Callable[[list[str]], list[list[float]]]


def batched(items: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


def embed_all(embedder: Embedder, texts: Sequence[str], batch_size: int = 32,
              progress: Callable[[int, int], None] | None = None
              ) -> list[list[float]]:
    out: list[list[float]] = []
    for chunk in batched(texts, batch_size):
        out.extend(embedder(chunk))
        if progress:
            progress(len(out), len(texts))
    return out
