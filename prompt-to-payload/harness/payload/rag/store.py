"""Vector store over plain sqlite.

Embeddings are float32 BLOBs in an ordinary table. Retrieval is brute-force
cosine, with numpy if it happens to be installed and pure Python if not.

A corpus of personal notes is tens of thousands of chunks at most, where brute force
costs milliseconds. A vector database would mean a service to run or an
extension to load, and then the offline story depends on a package manager
having worked. One file, no daemon.
"""

from __future__ import annotations

import math
import sqlite3
from array import array
from dataclasses import dataclass
from pathlib import Path

try:  # optional accelerator
    import numpy as _np
except ImportError:  # pragma: no cover - absence is the supported path
    _np = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY,
    source    TEXT NOT NULL,
    title     TEXT NOT NULL DEFAULT '',
    text      TEXT NOT NULL,
    dim       INTEGER NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Hit:
    score: float
    source: str
    title: str
    text: str


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array:
    out = array("f")
    out.frombytes(blob)
    return out


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ write

    def add(self, source: str, title: str, text: str,
            embedding: list[float]) -> None:
        self.db.execute(
            "INSERT INTO chunks (source, title, text, dim, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, title, text, len(embedding), pack(embedding)),
        )

    def commit(self) -> None:
        self.db.commit()

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def clear_source(self, source: str) -> int:
        cur = self.db.execute("DELETE FROM chunks WHERE source = ?", (source,))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------------- read

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def sources(self) -> list[tuple[str, int]]:
        return list(self.db.execute(
            "SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY 2 DESC"
        ))

    def search(self, query: list[float], k: int = 5,
               source: str | None = None) -> list[Hit]:
        sql = "SELECT source, title, text, embedding FROM chunks"
        params: tuple = ()
        if source:
            sql += " WHERE source = ?"
            params = (source,)

        rows = self.db.execute(sql, params).fetchall()
        if not rows:
            return []

        if _np is not None:
            return self._search_numpy(query, rows, k)
        return self._search_python(query, rows, k)

    # NOTE: this path is untested. I have only ever run the pure-Python one,
    # because numpy is not installed on the machine I built this on.
    def _search_numpy(self, query, rows, k) -> list[Hit]:
        q = _np.asarray(query, dtype=_np.float32)
        q_norm = float(_np.linalg.norm(q)) or 1.0

        matrix = _np.frombuffer(
            b"".join(row[3] for row in rows), dtype=_np.float32
        ).reshape(len(rows), -1)

        norms = _np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        scores = (matrix @ q) / (norms * q_norm)

        order = _np.argsort(-scores)[:k]
        return [
            Hit(float(scores[i]), rows[i][0], rows[i][1], rows[i][2])
            for i in order
        ]

    def _search_python(self, query, rows, k) -> list[Hit]:
        q_norm = math.sqrt(sum(x * x for x in query)) or 1.0

        scored: list[Hit] = []
        for source, title, text, blob in rows:
            vec = unpack(blob)
            if len(vec) != len(query):
                # A corpus embedded with one model and queried with another.
                # Silently scoring these would return confident nonsense.
                raise ValueError(
                    f"embedding dimension mismatch: corpus has {len(vec)}, "
                    f"query has {len(query)}. The corpus was built with a "
                    f"different embedding model - re-run provisioning."
                )
            dot = sum(a * b for a, b in zip(vec, query))
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            scored.append(Hit(dot / (norm * q_norm), source, title, text))

        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]
