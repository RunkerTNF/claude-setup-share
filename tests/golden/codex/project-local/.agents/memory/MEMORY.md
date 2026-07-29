# Project Memory Index

Project-scoped notes live flat under `.agents/memory/`. Index every note here
with a one-line retrieval hook. Each note records its type in frontmatter; do
not create a second type-based directory layer.

When `.agents/memory/IMPORTED.md` exists, use it as the provenance index for
notes imported from legacy agent setups.

Rules that must always apply belong in `.agents/RULES.md`, not only in memory.
