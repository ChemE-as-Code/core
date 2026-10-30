# Development

<!-- readme: ## Develop | body -->

<!-- readme: ## Build -->

<!-- readme: ## Design notes -->

## These docs

The site is built with MkDocs and the Material theme, pinned in `requirements-docs.txt` to the
versions ChemE-as-Code/core uses. Its pages include their sections from `REFERENCE.md` with
comments such as `<!-- readme: ## Build -->` (`docs/hooks/includes.py`, the same hook as core's),
so a section renamed or removed in REFERENCE.md fails the strict build:

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs serve           # http://127.0.0.1:8000
.venv/bin/mkdocs build --strict  # what CI runs (.github/workflows/viewer.yml); writes build/docs/
```

CI builds the site on every pull request. It is not deployed.
