"""Human-in-the-loop gate. Deny by default.

A tool runs unattended only if it is read-only, or you listed it in
`auto_approve`.
"""

from __future__ import annotations

import sys
from typing import Protocol

# Risk classes, least to most consequential.
#   read    - reads local files or prior output. No target contact.
#   analyse - runs local analysis tooling. No target contact.
#   touch   - contacts the target. Observable by a defender.
#   mutate  - changes state on the target or the local system.
RISK_ORDER = ("read", "analyse", "touch", "mutate")
AUTO_OK = ("read", "analyse")


class Approver(Protocol):
    def __call__(self, name: str, args: dict, risk: str) -> tuple[bool, str]: ...


def auto_approver(allow: tuple[str, ...] = ()) -> Approver:
    """Non-interactive approver. Used by tests and by scripted demos."""

    def approve(name: str, args: dict, risk: str) -> tuple[bool, str]:
        if risk in AUTO_OK:
            return True, f"risk class {risk!r} is non-contacting"
        if name in allow:
            return True, "operator pre-approved this tool"
        return False, (
            f"{name!r} has risk class {risk!r} and was not pre-approved"
        )

    return approve


def interactive_approver(allow: tuple[str, ...] = ()) -> Approver:
    """Prompts the operator on anything that contacts or mutates."""

    def approve(name: str, args: dict, risk: str) -> tuple[bool, str]:
        if risk in AUTO_OK:
            return True, f"risk class {risk!r} is non-contacting"
        if name in allow:
            return True, "operator pre-approved this tool"

        print(f"\n  approval required", file=sys.stderr)
        print(f"    tool  {name}", file=sys.stderr)
        print(f"    risk  {risk}", file=sys.stderr)
        for key, value in args.items():
            rendered = str(value)
            if len(rendered) > 200:
                rendered = rendered[:200] + "..."
            print(f"    {key:5} {rendered}", file=sys.stderr)

        try:
            answer = input("  run it? [y/N] ").strip().lower()
        except EOFError:
            # No tty. Fail closed.
            return False, "no terminal available to approve on"

        if answer in ("y", "yes"):
            return True, "operator approved interactively"
        return False, "operator declined"

    return approve
