# Contributing

NemoFold welcomes focused issues and pull requests that preserve its local-first,
evidence-first trust boundary.

## Development setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
python -m pytest -q
```

Before opening a pull request, run:

```powershell
python -m ruff check src tests
python -m mypy src
python -m pytest -q
python -m compileall -q src tests
node --check src/nemofold/web/app.js
python -m build
git diff --check
```

Use synthetic fixtures only. Never commit API keys, `.env` files, private documents,
absolute host paths, generated run reports, SQLite indexes, or real personal data.
Changes to file actions, external transfer, verification, or cost controls need a
regression test for the fail-closed path.
