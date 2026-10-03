"""Corpus retrieval exposed as a tool.

The model decides when it wants reference material. Forcing retrieval into
every turn burns context on chunks nobody asked for, and on a small window that
is the difference between finishing and running out of room.
"""

from __future__ import annotations

from payload.tools.base import Tool, ToolError


def register(registry, store, embedder) -> None:

    def corpus_search(query: str, k: int = 5, source: str = "") -> str:
        if store is None:
            raise ToolError(
                "no corpus is configured. Run provisioning to build one, or "
                "proceed without retrieval."
            )
        if store.count() == 0:
            raise ToolError(
                "the corpus is empty. Run `make corpus` to build it."
            )

        try:
            vector = embedder([query])[0]
        except Exception as exc:  # surfaced to the model, not fatal
            raise ToolError(f"could not embed the query: {exc}") from exc

        hits = store.search(vector, k=k, source=source or None)
        if not hits:
            return f"no corpus matches for {query!r}"

        blocks = []
        for rank, hit in enumerate(hits, 1):
            blocks.append(
                f"[{rank}] {hit.source} - {hit.title}  (similarity {hit.score:.3f})\n"
                f"{hit.text}"
            )
        return "\n\n".join(blocks)

    registry.add(Tool(
        name="corpus_search",
        description=(
            "Search the local offline pentest reference corpus. Use this for "
            "technique details, tool syntax and command references instead of "
            "recalling them from memory, which is where a local model is most "
            "likely to invent a plausible but wrong flag."
        ),
        risk="read",
        handler=corpus_search,
        parameters={
            "query": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 20},
            "source": {"type": "string",
                       "description": "restrict to one corpus source"},
        },
        required=("query",),
    ))
