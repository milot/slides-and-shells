# Recon triage

Notes on turning scanner output into a decision about where to spend time.

## Version strings are claims

A banner is something the target said about itself. It can be stale, spoofed,
back-ported, or simply a distribution's patched build carrying an upstream
version number.

Treat a version as a lead that justifies a check, never as a conclusion that
justifies a finding. "Reported version X, which if accurate would be affected
by Y, unverified" is honest. "Vulnerable to Y" is not, until you looked.

## Prioritise by reachability, not by score

A critical-rated issue on a service you cannot reach matters less than a
medium-rated one on the host everybody authenticates through. CVSS describes a
vulnerability in the abstract; an engagement happens in a specific network.

Ordering questions worth asking:

1. Is it actually reachable from where I am?
2. Does exploiting it move me somewhere new, or just sideways?
3. What does it cost if it is noticed?

## Name what was not scanned

The most expensive recon mistake is a confident summary of an incomplete scan.
UDP almost never gets scanned properly. Top-1000 port scans miss services on
high ports. A host that did not respond is not a host that is not there.

Say what the scan did not cover, every time.

## Parsing saved output

Scanning contacts the target and is observable. Parsing a saved artifact is
not, and most triage time goes on the second.

```
nmap -oX scan.xml <targets>      # XML is the parseable form
ffuf -of json -o ffuf.json ...
```

Keep the raw artifacts. Re-triaging a saved scan costs nothing; re-running a
scan costs time and generates traffic somebody may be watching.

## Structuring a finding

What a client can act on:

- what it is, in one sentence, without jargon
- where exactly: host, port, path, parameter
- how you established it, so someone else can repeat it
- what an attacker gets from it, concretely
- what to do about it

What is not a finding: a scanner's output pasted in, a CVE number with no
evidence it applies here, or a severity rating with no reasoning behind it.
