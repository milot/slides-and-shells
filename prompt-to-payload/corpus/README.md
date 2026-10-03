# Corpus

Reference material the model can search while it works, embedded into a local
sqlite file. Retrieval is optional: without it everything works except the
`corpus_search` tool, which simply is not registered.

## What is in here

`notes/` holds three short notes I wrote on binary triage, recon triage, and
working with local models. They are seeds, not a library. **Replace them with
your own.** Your notes about the environments you actually work in are worth
more than anything general, because they are the one thing a model has never
seen.

## Building it

Needs an `embed` role in `harness/payload.toml` and an embedding model pulled.

```bash
make corpus                              # embeds corpus/notes
cd harness && python3 -m payload corpus stats
```

Add another directory:

```bash
cd harness
python3 -m payload corpus build /path/to/your/notes --name fieldnotes
```

Recognised file types: `.md`, `.markdown`, `.txt`, `.rst`, `.adoc`.

## Querying it without a model

The fastest way to find out whether the corpus actually has anything useful to
say about something:

```bash
cd harness
python3 -m payload corpus search "how do I spot an off-by-one in a bounds check"
```

## Third-party sources

`provision/manifest.toml` lists some public references you might want in here.
They are commented out, and I have not tested ingesting them. Read their
licences before redistributing a bundle built from them.

## A warning

The embedding model is fixed once you build. Change it and every stored vector
becomes meaningless; the store raises a dimension-mismatch error instead of
quietly returning nonsense. Rebuild after any change:

```bash
make corpus
```

`corpus/*.db` is gitignored. It is large and rebuildable.
