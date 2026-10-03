"""Configuration.

Resolved from a TOML file with environment overrides. No network, no remote
config fetch, no defaults that point anywhere off this machine.

Roles, not model names. The local-weights landscape moves monthly, and a
file that hardcodes a model name is stale before anyone reads it. Roles
stay stable; what is pinned behind them is a provisioning decision.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"

# A capability, not a model. On 16GB these collapse onto one chat model plus
# an embedder, and swapping costs seconds.
ROLES = ("plan", "code", "embed")


@dataclass
class RoleConfig:
    model: str
    endpoint: str = DEFAULT_ENDPOINT
    temperature: float = 0.2
    max_tokens: int = 4096
    # Seconds. Local inference on a cold model can genuinely take this long.
    timeout: int = 600


@dataclass
class Config:
    roles: dict[str, RoleConfig] = field(default_factory=dict)
    db_path: Path = Path("corpus/corpus.db")
    transcript_path: Path = Path("runs/transcript.jsonl")
    artifact_dir: Path = Path("runs/artifacts")
    # Deny by default. Nothing that touches a target runs unapproved.
    auto_approve: tuple[str, ...] = ()
    max_steps: int = 24

    def role(self, name: str) -> RoleConfig:
        if name not in self.roles:
            raise KeyError(
                f"role {name!r} is not configured. Configured roles: "
                f"{sorted(self.roles) or 'none'}"
            )
        return self.roles[name]

    def role_or_fallback(self, name: str) -> RoleConfig:
        """Return `name`, else the `plan` role.

        Lets a single-model setup satisfy every chat role without special
        casing. An absent `embed` role is a real error and not covered here,
        because silently embedding with a chat model produces a corpus that
        retrieves badly in ways nobody notices until it matters.
        """
        if name in self.roles:
            return self.roles[name]
        if name == "embed":
            raise KeyError(
                "no 'embed' role configured. Retrieval needs a real embedding "
                "model; falling back to a chat model would build a corpus that "
                "retrieves badly without obviously failing."
            )
        return self.role("plan")


def _config_search_path(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    env = os.environ.get("PAYLOAD_CONFIG")
    if env:
        return [Path(env)]
    return [
        Path.cwd() / "payload.toml",
        Path.cwd().parent / "payload.toml",
        Path.home() / ".config" / "payload" / "payload.toml",
    ]


def load(path: str | None = None) -> Config:
    """Load configuration, applying environment overrides.

    Missing config is not fatal: a default single-role setup pointed at a
    local Ollama is enough to get a first run working, which matters when an
    someone is trying this for the first time.
    """
    cfg = Config()
    data: dict = {}

    for candidate in _config_search_path(path):
        if candidate.is_file():
            with candidate.open("rb") as fh:
                data = tomllib.load(fh)
            cfg.note_source = candidate  # type: ignore[attr-defined]
            break

    paths = data.get("paths", {})
    cfg.db_path = Path(paths.get("db", cfg.db_path))
    cfg.transcript_path = Path(paths.get("transcript", cfg.transcript_path))
    cfg.artifact_dir = Path(paths.get("artifacts", cfg.artifact_dir))

    agent = data.get("agent", {})
    cfg.max_steps = int(agent.get("max_steps", cfg.max_steps))
    cfg.auto_approve = tuple(agent.get("auto_approve", cfg.auto_approve))

    default_endpoint = os.environ.get(
        "PAYLOAD_ENDPOINT", data.get("endpoint", DEFAULT_ENDPOINT)
    )

    for role in ROLES:
        section = data.get("roles", {}).get(role)
        env_model = os.environ.get(f"PAYLOAD_MODEL_{role.upper()}")
        if section is None and env_model is None:
            continue
        section = section or {}
        cfg.roles[role] = RoleConfig(
            model=env_model or section["model"],
            endpoint=section.get("endpoint", default_endpoint),
            temperature=float(section.get("temperature", 0.2)),
            max_tokens=int(section.get("max_tokens", 4096)),
            timeout=int(section.get("timeout", 600)),
        )

    return cfg
