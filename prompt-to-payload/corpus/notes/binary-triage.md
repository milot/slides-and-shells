# Binary triage

Working notes for approaching an unfamiliar executable. Written for retrieval,
so each section stands alone.

## First pass

Establish what you are holding before analysing anything.

```
file <binary>
objdump --section-headers <binary>
nm <binary>
strings -n 6 <binary>
```

On macOS, `objdump --file-headers` fails on Mach-O under the LLVM objdump that
Xcode ships. Use `otool -hv` and `otool -L` instead. `objdump -d` and
`--section-headers` work on both formats.

## Imports are evidence

The dynamic symbol table of a stripped binary still names every library
function it calls. That is a description of what the program does with input.

- `strcpy`, `strcat`, `sprintf`, `gets`: unbounded writes
- `strncpy`, `strncmp`, `memcpy`: bounded, but the bound is where bugs live
- `system`, `popen`, `execve`: command execution paths
- `fopen`, `open`, `read`: file-handling paths worth tracing

A binary importing `strcpy` is telling you something. A binary importing
`__strcpy_chk` is telling you it was built with fortification, and that the
overflow traps instead of corrupting.

## Absence of strings is not absence of data

`strings` finds printable runs. It does not find encoded, XOR-obfuscated,
packed or computed constants. If a program clearly compares against a secret
and `strings` shows nothing, the secret is in a data section in a form
`strings` cannot see.

```
objdump -s -j __const <binary>      # Mach-O
objdump -s -j .rodata <binary>      # ELF
```

Dump the bytes and look at them. A short run of high-entropy bytes adjacent to
a comparison routine is usually an obfuscated constant, and single-byte XOR is
the most common encoding by a wide margin.

## Comparison bugs

Length-bounded comparison functions are a recurring source of authentication
flaws. The question is always: *where does the length come from?*

```c
strncmp(supplied, expected, strlen(expected));  /* correct */
strncmp(supplied, expected, strlen(supplied));  /* bypass  */
```

When the length derives from attacker-controlled input, an empty string
compares zero bytes and matches. The same bug makes the comparison a prefix
oracle, which is often more useful than the bypass.

## Bounds checks

Read every bounds check twice, and prefer reading the array declaration over
reading the check.

```c
if (idx < 0 || idx > COUNT)    /* off by one: idx == COUNT is permitted */
if (idx < 0 || idx >= COUNT)   /* correct */
```

This is the single most common place for both human and model error. A guard
that looks careful is not the same as a guard that is correct.

## Stripped binaries

With no symbols, refer to functions by address and build your own map as you
go. Entry points to anchor from:

- the `main` symbol usually survives stripping on Mach-O
- string cross-references identify command dispatch
- the imports table identifies what each unnamed function is likely doing
