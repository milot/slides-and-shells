"""Binary analysis tools.

Uses radare2 when it is there, since its analysis and pseudo-decompiler give a
model much better material than raw disassembly. Falls back to objdump, nm,
strings and otool, which ship on both Arch and macOS.

Gotcha: `objdump --file-headers` fails on Mach-O under Xcode's LLVM objdump,
which is why header inspection goes through otool on Darwin. `objdump -d` and
`--section-headers` are fine on both.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

from payload.tools.base import Tool, ToolError

# Output handed back to a model has to be bounded. A full disassembly of even
# a small binary will evict everything else from a local model's context.
MAX_OUTPUT = 24_000

IS_DARWIN = platform.system() == "Darwin"


def have_r2() -> bool:
    return shutil.which("r2") is not None or shutil.which("radare2") is not None


def _run(argv: list[str], timeout: int = 120) -> str:
    if shutil.which(argv[0]) is None:
        raise ToolError(
            f"{argv[0]!r} is not installed. See docs/INSTALL.md; the binary "
            f"tools degrade to objdump/nm/strings when radare2 is absent."
        )
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"{argv[0]} timed out after {timeout}s") from None

    out = proc.stdout or ""
    if not out.strip() and proc.stderr.strip():
        raise ToolError(f"{argv[0]} failed: {proc.stderr.strip()[:500]}")
    return _truncate(out)


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return (
        text[:MAX_OUTPUT]
        + f"\n\n[output truncated at {MAX_OUTPUT} characters. Narrow the "
        f"request - ask for a specific function or address range.]"
    )


def _check_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise ToolError(f"{path!r} is not a file that exists")
    return p


def _r2_cmd(path: Path, command: str, analyse: bool = True) -> str:
    """Run one r2 command in batch mode.

    `-e scr.color=0` because escape codes waste a model's context, and
    `-N` skips user config so an operator's own radare2rc cannot change what
    the model sees between runs.
    """
    prefix = "aaa;" if analyse else ""
    binary = shutil.which("r2") or shutil.which("radare2")
    return _run([binary, "-q", "-N", "-e", "scr.color=0",
                 "-c", prefix + command, str(path)], timeout=300)


# --------------------------------------------------------------------------
# handlers


def overview(path: str) -> str:
    """File type, architecture, sections and linked libraries."""
    target = _check_path(path)
    parts: list[str] = []

    if have_r2():
        parts.append("== r2 info ==\n" + _r2_cmd(target, "i", analyse=False))
        parts.append("== sections ==\n" + _r2_cmd(target, "iS", analyse=False))
        parts.append("== imports ==\n" + _r2_cmd(target, "ii", analyse=False))
        return "\n\n".join(parts)

    parts.append("== file ==\n" + _run(["file", str(target)]))
    parts.append("== sections ==\n"
                 + _run(["objdump", "--section-headers", str(target)]))
    if IS_DARWIN:
        # objdump --file-headers rejects Mach-O under Xcode's LLVM objdump.
        parts.append("== mach header ==\n" + _run(["otool", "-hv", str(target)]))
        parts.append("== linked libraries ==\n"
                     + _run(["otool", "-L", str(target)]))
    else:
        parts.append("== elf header ==\n" + _run(["readelf", "-h", str(target)]))
        parts.append("== dynamic ==\n" + _run(["readelf", "-d", str(target)]))
    return "\n\n".join(parts)


def symbols(path: str) -> str:
    """Symbol table. On a stripped binary this is mostly dynamic imports."""
    target = _check_path(path)
    if have_r2():
        return _r2_cmd(target, "is", analyse=False)
    out = _run(["nm", str(target)])
    if not out.strip():
        return ("no symbols. The binary is stripped - work from the "
                "disassembly and the imports instead.")
    return out


def list_strings(path: str, min_length: int = 5) -> str:
    """Printable strings. Obfuscated constants will not show up here."""
    target = _check_path(path)
    return _run(["strings", "-n", str(min_length), str(target)])


def functions(path: str) -> str:
    """Functions discovered by analysis.

    Without radare2 there is no function discovery, so this reports entry
    points from the disassembly instead of pretending to a capability it
    does not have.
    """
    target = _check_path(path)
    if have_r2():
        return _r2_cmd(target, "afl")

    out = _run(["objdump", "-d", str(target)])
    labels = re.findall(r"^([0-9a-f]+)\s+<([^>]+)>:", out, re.M)
    if not labels:
        return ("no function labels found. radare2 is not installed, so there "
                "is no function discovery. Use binary_disassemble on the "
                "whole text section and identify boundaries yourself.")
    lines = [f"{addr}  {name}" for addr, name in labels]
    return (f"{len(lines)} labelled entry point(s) from objdump. radare2 is "
            f"not installed, so unlabelled functions in a stripped binary "
            f"will not appear here:\n" + "\n".join(lines))


def disassemble(path: str, symbol: str = "", address: str = "",
                count: int = 80) -> str:
    """Disassemble a function by name, or an address range."""
    target = _check_path(path)

    if have_r2():
        if symbol:
            return _r2_cmd(target, f"s {symbol}; pdf")
        if address:
            return _r2_cmd(target, f"s {address}; pd {count}")
        return _r2_cmd(target, f"s main; pdf")

    out = _run(["objdump", "-d", str(target)])

    if not symbol and not address:
        return out

    needle = symbol or address
    lines = out.splitlines()
    for index, line in enumerate(lines):
        if needle.lstrip("0x") in line or needle in line:
            window = lines[index:index + count]
            return "\n".join(window)

    raise ToolError(
        f"could not locate {needle!r} in the disassembly. On a stripped "
        f"binary, symbol names are gone - pass an address instead, which you "
        f"can find with binary_overview or binary_disassemble with no arguments."
    )


# TODO: wire up Ghidra's analyzeHeadless as a second decompiler. Its output is
# better than pdc and the docs used to claim this existed, which it never did.
# Needs a cache step in provision.sh so the JVM start is not on the hot path.
def decompile(path: str, symbol: str = "main") -> str:
    """Pseudo-decompiled C for one function. Requires radare2."""
    target = _check_path(path)
    if not have_r2():
        raise ToolError(
            "decompilation needs radare2 (`pdc`), which is not installed. "
            "Use binary_disassemble instead, or install radare2 - see "
            "docs/INSTALL.md."
        )
    return _r2_cmd(target, f"s {symbol}; pdc")


_HEX_LINE = re.compile(r"^\s*([0-9a-f]{6,16})\s+((?:[0-9a-f]{2,8}\s+){1,4})")


def section_bytes(path: str, section: str) -> str:
    """Raw bytes of one section, as hex plus a printable rendering.

    Needed for obfuscated constants: an XOR-encoded string is invisible to
    `strings` but sits in plain sight in a data section. This returns the
    bytes so the model can work the encoding out instead of guessing.
    """
    target = _check_path(path)
    raw = _run(["objdump", "-s", "-j", section, str(target)])

    blob = bytearray()
    for line in raw.splitlines():
        match = _HEX_LINE.match(line)
        if match:
            blob += bytes.fromhex(match.group(2).replace(" ", ""))

    if not blob:
        raise ToolError(
            f"no byte content found for section {section!r}. Check the exact "
            f"section name with binary_overview; names differ between Mach-O "
            f"(__const, __cstring) and ELF (.rodata, .data)."
        )

    printable = "".join(
        chr(b) if 32 <= b <= 126 else "." for b in blob
    )
    hex_rows = []
    for offset in range(0, len(blob), 16):
        chunk = blob[offset:offset + 16]
        hex_rows.append(
            f"  +{offset:04x}  {chunk.hex(' '):<47}  "
            + "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        )

    return (
        f"section {section}: {len(blob)} bytes\n"
        + "\n".join(hex_rows)
        + f"\n\nas printable text: {printable}"
    )


# --------------------------------------------------------------------------
# registration

def register(registry) -> None:
    registry.add(Tool(
        name="binary_overview",
        description=(
            "File type, architecture, sections, and linked libraries for a "
            "binary. Start here when analysing an unfamiliar executable."
        ),
        risk="analyse",
        handler=overview,
        parameters={"path": {"type": "string",
                             "description": "path to the binary"}},
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_symbols",
        description=(
            "Symbol table of a binary. On a stripped binary this shows only "
            "dynamically linked imports, which still reveals which library "
            "functions are used."
        ),
        risk="analyse",
        handler=symbols,
        parameters={"path": {"type": "string"}},
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_strings",
        description=(
            "Printable strings in a binary. Note that obfuscated or encoded "
            "constants will NOT appear here - absence of a string is not "
            "evidence it is not in the binary."
        ),
        risk="analyse",
        handler=list_strings,
        parameters={
            "path": {"type": "string"},
            "min_length": {"type": "integer", "minimum": 1, "maximum": 64,
                           "description": "minimum string length, default 5"},
        },
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_functions",
        description="List functions discovered in a binary.",
        risk="analyse",
        handler=functions,
        parameters={"path": {"type": "string"}},
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_disassemble",
        description=(
            "Disassemble a function by symbol name, or `count` instructions "
            "from an address. With neither, returns the whole text section."
        ),
        risk="analyse",
        handler=disassemble,
        parameters={
            "path": {"type": "string"},
            "symbol": {"type": "string",
                       "description": "function name, if symbols exist"},
            "address": {"type": "string",
                        "description": "hex address, e.g. 0x100000548"},
            "count": {"type": "integer", "minimum": 1, "maximum": 400},
        },
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_decompile",
        description=(
            "Pseudo-decompiled C for one function. Requires radare2; returns "
            "an error explaining the fallback if it is not installed."
        ),
        risk="analyse",
        handler=decompile,
        parameters={
            "path": {"type": "string"},
            "symbol": {"type": "string",
                       "description": "function name or address"},
        },
        required=("path",),
    ))

    registry.add(Tool(
        name="binary_section_bytes",
        description=(
            "Raw bytes of a named section as hex and printable text. Use this "
            "when you suspect an encoded or obfuscated constant that `strings` "
            "will not reveal. Mach-O sections are named like __const and "
            "__cstring; ELF sections like .rodata and .data."
        ),
        risk="analyse",
        handler=section_bytes,
        parameters={
            "path": {"type": "string"},
            "section": {"type": "string"},
        },
        required=("path", "section"),
    ))
