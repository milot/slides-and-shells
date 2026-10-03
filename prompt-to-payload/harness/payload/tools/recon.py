"""Recon artifact parsing.

Reads output real tooling already produced. Parsing a saved file is risk class
`read` and needs no approval; running a scanner contacts the target and does.

Most engagement time goes on triage, not scanning. This half also works on a
plane.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from payload import egress
from payload.tools.base import Tool, ToolError


def parse_nmap(path: str) -> str:
    """Flatten nmap XML into something compact enough for a small context."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise ToolError(f"{path!r} is not a file that exists")

    try:
        root = ET.parse(target).getroot()
    except ET.ParseError as exc:
        raise ToolError(
            f"{path!r} is not valid XML ({exc}). nmap writes XML with -oX; "
            f"a .nmap or .gnmap file will not parse here."
        ) from exc

    lines: list[str] = []
    host_count = 0

    for host in root.iter("host"):
        state = host.find("status")
        if state is not None and state.get("state") != "up":
            continue
        host_count += 1

        addrs = [a.get("addr") for a in host.iter("address") if a.get("addr")]
        names = [n.get("name") for n in host.iter("hostname") if n.get("name")]
        label = addrs[0] if addrs else "unknown"
        if names:
            label += f" ({', '.join(names)})"
        lines.append(f"host {label}")

        for port in host.iter("port"):
            port_state = port.find("state")
            if port_state is None or port_state.get("state") != "open":
                continue
            service = port.find("service")
            bits = [
                f"  {port.get('portid')}/{port.get('protocol')}",
            ]
            if service is not None:
                name = service.get("name") or "?"
                product = service.get("product") or ""
                version = service.get("version") or ""
                extra = " ".join(x for x in (product, version) if x)
                bits.append(f"{name}" + (f"  {extra}" if extra else ""))
            lines.append("  ".join(bits))

            for script in port.iter("script"):
                output = (script.get("output") or "").strip()
                if output:
                    first = output.splitlines()[0][:160]
                    lines.append(f"      [{script.get('id')}] {first}")

    if not host_count:
        return "no hosts recorded as up in this scan"

    header = (f"{host_count} host(s) up. Service and version strings below are "
              f"claims made by the target, not verified facts.\n")
    return header + "\n".join(lines)


def parse_ffuf(path: str, min_status: int = 200, max_status: int = 499) -> str:
    """Summarise ffuf JSON output, grouped by status code."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise ToolError(f"{path!r} is not a file that exists")

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"{path!r} is not valid JSON ({exc}). ffuf writes "
                        f"JSON with -of json -o <file>.") from exc

    results = data.get("results") or []
    if not results:
        return "ffuf recorded no results"

    buckets: dict[int, list[str]] = {}
    for item in results:
        status = int(item.get("status", 0))
        if not (min_status <= status <= max_status):
            continue
        buckets.setdefault(status, []).append(
            f"  {item.get('url', '?')}  {item.get('length', '?')} bytes"
        )

    if not buckets:
        return (f"no results with status between {min_status} and {max_status}. "
                f"Statuses present: "
                f"{sorted({int(r.get('status', 0)) for r in results})}")

    out = [f"{len(results)} total result(s)"]
    for status in sorted(buckets):
        out.append(f"\nstatus {status}  ({len(buckets[status])} hit(s))")
        out.extend(buckets[status][:40])
        if len(buckets[status]) > 40:
            out.append(f"  [... {len(buckets[status]) - 40} more]")
    return "\n".join(out)


# Hostname, IPv4, or CIDR. Anything else is refused before nmap is invoked.
# Arguments go to subprocess as a list so there is no shell to inject into,
# but a target that does not look like a target is still worth rejecting.
_TARGET = re.compile(r"^[A-Za-z0-9._:-]+(/\d{1,3})?$")

# Flags the model may ask for. An allowlist, because the alternative is letting
# a language model compose arbitrary nmap invocations against a client network.
_PROFILES = {
    "quick": ["-T3", "--top-ports", "100"],
    "full": ["-T3", "-p-"],
    "service": ["-T3", "-sV", "--top-ports", "100"],
    "ping": ["-sn"],
}


def run_nmap(target: str, profile: str = "quick", output: str = "") -> str:
    """Scan a target. Contacts it, so it needs approval and respects the lock."""
    if not _TARGET.match(target):
        raise ToolError(
            f"{target!r} does not look like a hostname, address or CIDR block."
        )

    if shutil.which("nmap") is None:
        raise ToolError("nmap is not installed")

    # Scanning is egress. The offline lock governs it the same as a model call,
    # so a locked harness will only scan loopback.
    try:
        egress.check(f"http://{target.split('/')[0]}")
    except egress.EgressBlocked as exc:
        raise ToolError(f"refusing to scan: {exc}") from exc

    out_path = Path(output) if output else Path(
        tempfile.mkdtemp(prefix="payload-nmap-")) / "scan.xml"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    argv = ["nmap", *_PROFILES[profile], "-oX", str(out_path), target]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=900, check=False)
    except subprocess.TimeoutExpired:
        raise ToolError("nmap timed out after 15 minutes") from None

    if not out_path.is_file():
        raise ToolError(f"nmap produced no XML: {proc.stderr.strip()[:400]}")

    return (f"scan written to {out_path}\n\n" + parse_nmap(str(out_path)))


def register(registry) -> None:
    registry.add(Tool(
        name="run_nmap",
        description=(
            "Scan a target with nmap and return the parsed result. This "
            "CONTACTS the target and is observable by anyone watching the "
            "network. Profiles: quick, full, service, ping."
        ),
        risk="touch",
        handler=run_nmap,
        parameters={
            "target": {"type": "string",
                       "description": "hostname, address or CIDR block"},
            "profile": {"type": "string",
                        "enum": ["quick", "full", "service", "ping"]},
            "output": {"type": "string",
                       "description": "where to write the XML report"},
        },
        required=("target",),
    ))

    registry.add(Tool(
        name="parse_nmap",
        description=(
            "Parse an nmap XML report (-oX) into a compact summary of up hosts "
            "and open ports. Reads a saved file; does not scan anything."
        ),
        risk="read",
        handler=parse_nmap,
        parameters={"path": {"type": "string"}},
        required=("path",),
    ))

    registry.add(Tool(
        name="parse_ffuf",
        description=(
            "Parse ffuf JSON output into results grouped by status code. "
            "Reads a saved file; does not request anything."
        ),
        risk="read",
        handler=parse_ffuf,
        parameters={
            "path": {"type": "string"},
            "min_status": {"type": "integer", "minimum": 100, "maximum": 599},
            "max_status": {"type": "integer", "minimum": 100, "maximum": 599},
        },
        required=("path",),
    ))
