---
name: fcis-python-tdd
description: >
  Use this skill for any Python project involving clean architecture, functional core /
  imperative shell (FCIS), TDD, monorepo layout, or research project structure. Trigger on:
  "pure functions", "separate logic from I/O", "Red-Green-Refactor", "write tests first",
  "research project", "reusable experiments", or scaffolding a multi-package Python repo.
  Never produce .ipynb files — always plain .py in explore/. When in doubt, use this skill.
---

# FCIS · TDD · Research Monorepo — Python

## Two zones, one rule

| Zone | Contract | Folder |
|------|----------|--------|
| **Core** | Pure functions. No I/O. Data in → data out. | `packages/core/` |
| **Shell** | All I/O: DB, network, clock, random. Calls core. | `packages/shell/` |

Shell is thin and dumb. Core is fat and smart. Core tests need zero mocks.

## Folder structure

```
{project}/
├── pyproject.toml            ← uv workspace root
├── .gitignore                ← includes explore/scratch/
├── packages/
│   ├── core/                 ← pure logic, full test coverage
│   │   ├── src/core/
│   │   │   ├── transforms/   ← pure functions
│   │   │   ├── metrics/      ← pure functions
│   │   │   └── domain.py
│   │   └── tests/            ← unit tests, zero mocks, < 1s total
│   ├── datasets/             ← loaders, validators, schemas
│   │   ├── src/datasets/
│   │   └── tests/
│   └── shell/                ← all I/O lives here
│       ├── src/shell/
│       │   ├── storage/
│       │   └── runner.py     ← thin orchestration, calls core
│       └── tests/            ← integration tests, fixtures OK
├── experiments/              ← append-only, never edit old ones
│   └── YYYY-MM-{name}/
│       ├── config.yaml       ← all params here, not in code
│       ├── run.py            ← thin script, imports packages
│       ├── results/          ← commit outputs
│       └── README.md         ← what changed, what the number was
├── tests/
│   └── test_all.py           ← single entry point: runs every test in the repo
├── explore/                  ← plain .py only — NO .ipynb ever
│   ├── eda_something.py      ← run: uv run python explore/eda_something.py
│   └── scratch/              ← gitignored
├── pipelines/                ← production data / training pipelines
│   ├── data/
│   └── training/
└── apps/                     ← deployed services (API, CLI, dashboard)
```

## Graduation path

```
explore/ → packages/core/ → experiments/ → pipelines/ → apps/
(try it)    (test it)        (validate)     (productionise) (deploy)
```

## Hard rules

1. `core/` never imports I/O libs (`requests`, `boto3`, `psycopg2`, `subprocess`, `open`).
2. `datetime.now()` and `random` belong in shell — pass them as params to core.
3. Core tests need no mocks. If you reach for `unittest.mock` in a core test, the function belongs in shell.
4. Experiments are append-only. Clone folder, bump date, change config only.
5. `explore/` scripts call packages — never define logic. Useful function? Graduate to `core/` + write a test.
6. Never produce `.ipynb`. Use plain `.py` in `explore/`. Interactive: `uv run python -i explore/file.py` or `marimo`.
7. Every new test module must be imported in `tests/test_all.py`. One file to run them all: `uv run pytest tests/test_all.py -v`.

## Decision table

| Does this … | Then … |
|-------------|--------|
| Touch external state (DB, network, file, clock)? | → `shell/` |
| Test need a mock? | → shell test |
| `core/` import I/O lib? | Hard stop — move to shell |
| Test take > 100ms? | Probably hitting I/O — move to shell tests |
| File end in `.ipynb`? | Hard stop — use `.py` in `explore/` |
| Exploration function prove useful? | Graduate to `core/` + test |

## Reference files

Read these when you need code examples or setup commands:

- `references/monorepo-setup.md` — uv workspace init, inter-package deps, pytest commands, `test_all.py` template
- `references/patterns.md` — core/shell code templates, TDD cycle examples, Result types, async shell
