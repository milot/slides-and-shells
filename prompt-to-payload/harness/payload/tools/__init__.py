"""Tool registry assembly.

Everything the model can do is registered here and nowhere else, so there is
one file to read before you point this at a client's network.
"""

from __future__ import annotations

from pathlib import Path

from payload.tools.base import Registry, Tool, ToolError, validate

__all__ = ["Registry", "Tool", "ToolError", "validate", "build"]


def build(root: str | Path, store=None, embedder=None,
          include: tuple[str, ...] = ("fs", "binary", "recon", "rag")) -> Registry:
    """Assemble a registry.

    `root` confines all filesystem access. `store`/`embedder` enable retrieval;
    without them the corpus tool is simply not registered, instead of
    registered and failing at call time - a model shown a tool it cannot use
    will keep trying it.
    """
    from payload.tools import binary as binary_tools
    from payload.tools import fs as fs_tools
    from payload.tools import rag as rag_tools
    from payload.tools import recon as recon_tools

    registry = Registry()

    if "fs" in include:
        fs_tools.register(registry, fs_tools.Sandbox(root))
    if "binary" in include:
        binary_tools.register(registry)
    if "recon" in include:
        recon_tools.register(registry)
    if "rag" in include and store is not None and embedder is not None:
        rag_tools.register(registry, store, embedder)

    return registry
