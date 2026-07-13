# Vendored quick-start snippets

These files are a **committed, drift-checked copy** of the per-framework
"govern your first agent" snippets produced by the `ai-agent-assembly/examples`
repo (`scripts/extract_snippets.py`, AAASM-4512 / PR examples#267). Each `.py`
file is the `region: quickstart` slice — `init_assembly()` plus that framework's
adapter wiring — cut verbatim from the matching runnable example's entrypoint.

## Why vendored, not fetched at build time

`examples` is a **separate repository**; the MkDocs build here must not reach
across repos at render time. Vendoring keeps the docs build hermetic while the
snippets stay honest: `scripts/generate_quickstart_tabs.py` turns them into the
`pymdownx.tabbed` block in `docs/quick-start.md` §3, and a CI drift check
(`.github/workflows/quickstart-tabs-check.yml`) fails if the committed doc no
longer matches these inputs.

## Refreshing after the examples change

When the upstream examples' quick-start regions change, re-copy the Python
snippet files and the `python` slice of `examples/snippets/manifest.json` into
this directory (`manifest.json` here keeps only the `python` entries), then run:

```bash
python scripts/generate_quickstart_tabs.py
```

and commit the regenerated `docs/quick-start.md` alongside the updated snippets.

`manifest.json` is the data-driven tab index: `frameworks[]` ordered as the tab
list should render, each with `framework_id` (also the `<framework_id>.py`
filename), `label` (tab text), `status`, `lang`, and `source_example`
(provenance in the examples repo).
