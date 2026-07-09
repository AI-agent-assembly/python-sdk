{% raw %}
# Shared metadata macros in the docs

The Python SDK docs use [`mkdocs-macros-plugin`](https://mkdocs-macros-plugin.readthedocs.io/)
so that drift-prone factual values — the current package version, the PyPI /
repo / docs URLs, the import name, the CLI name, and canonical install
commands — live in **one source of truth** instead of being hand-copied across
Markdown pages.

This page is the maintainer contract for that macro layer. Read it before
adding a new shared value or before editing `docs_macros.py`.

## Where the values come from

Every macro variable exposed to Markdown pages is registered in
[`docs_macros.py`](https://github.com/ai-agent-assembly/python-sdk/blob/master/docs_macros.py)
at the repo root and is available in Markdown as the top-level `aa` object.

The layout is:

| Section | What lives here | Source |
| --- | --- | --- |
| `aa.python_sdk` | Package version, package name, `requires-python`, import name, CLI name | `pyproject.toml` (via `tomllib`) for version / name / `requires-python`; string literals in `docs_macros.py` for the import and CLI names |
| `aa.urls` | Canonical docs, repo, and PyPI URLs | String literals in `docs_macros.py` |
| `aa.commands` | Install snippets (`pip install …`, `uv add …`, runtime extra) | String literals in `docs_macros.py` |

The **package version is never hand-maintained in Markdown**. It is read from
`[project].version` in `pyproject.toml` at every docs build, so a release bump
to `pyproject.toml` automatically updates every page that references
`{{ aa.python_sdk.version }}`.

## Adding a new shared value

1. Open `docs_macros.py` at the repo root.
2. Add the value under the appropriate section of the `aa` dict inside
   `define_env`:
      - `python_sdk` — package-authoritative facts (prefer sourcing from
        `pyproject.toml` where possible).
      - `urls` — canonical URLs (docs, repo, PyPI, related sites).
      - `commands` — install and CLI snippets.

    If none of these fit, add a new section rather than overloading an
    existing one.
3. Reference it from any Markdown page as `{{ aa.<section>.<key> }}`.
4. Run `uv run mkdocs build --strict` locally. Because `mkdocs.yml` sets
   `on_undefined: strict` and `on_error_fail: true`, a typo in the variable
   path fails the build immediately instead of silently rendering an empty
   string.

Example — adding a new URL:

```python
# docs_macros.py
aa = {
    ...
    "urls": {
        "docs": "https://docs.agent-assembly.com/python-sdk/",
        "repo": "https://github.com/ai-agent-assembly/python-sdk",
        "pypi": "https://pypi.org/project/agent-assembly/",
        # new value:
        "issues": "https://github.com/ai-agent-assembly/python-sdk/issues",
    },
    ...
}
```

```markdown
<!-- in any Markdown page -->
Report bugs on the [issue tracker]({{ aa.urls.issues }}).
```

## What NOT to template

- **Historical release notes and per-release adapter tables** — a line like
  ``| `agent-assembly` | `>=0.0.1rc3` (the release that ships the Haystack
  adapter) |`` is a **historical fact** about which version first shipped a
  feature. It must remain a literal so future readers can still see when that
  feature landed.
- **Version-range examples** (e.g. `agent-assembly==0.0.x`) that illustrate a
  pinning pattern rather than the current version.
- **One-off framework-composed install commands** where the readability cost
  of `{{ aa.commands.install_pip }} langchain` exceeds the drift risk of
  `pip install --pre agent-assembly langchain`. Templating everything is not the
  goal; the goal is to keep the **current-state, high-drift** values in sync.

If in doubt, ask: *"When we cut the next release, will this line become
wrong if left alone?"* If yes, template it. If no, leave it literal.

## Fail-fast behavior

The plugin is configured in `mkdocs.yml` as:

```yaml
- macros:
    module_name: docs_macros
    on_error_fail: true
    on_undefined: strict
```

Combined with the CI job that runs `uv run mkdocs build --strict` in
`.github/workflows/documentation.yaml`, this means:

- A typo like `{{ aa.python_sdk.versio }}` **fails the docs build** rather
  than rendering as an empty string.
- A missing macro function or Python-side exception in `docs_macros.py`
  **fails the docs build** rather than being logged and skipped.

So CI is the safety net: if a macro reference is broken, the PR cannot merge
with a green docs check.

## Related files

- `docs_macros.py` — the macros module.
- `mkdocs.yml` — enables the plugin (search for `- macros:`).
- `pyproject.toml` — the version / package-name / `requires-python` source of
  truth read by `docs_macros.py`.
- `.github/workflows/documentation.yaml` — the CI job that runs
  `mkdocs build --strict`.
{% endraw %}
