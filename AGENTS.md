# AGENTS.md

- Tests: to check a branch, run `python tools/ci_scope.py --base origin/main --get pytest` and pass that selection to `.venv/bin/python -m pytest -q` (CPython, audiodsp from TestPyPI). The full suite is for changes the tool marks full. Also `micropython tests/mpy/run.py`. Lint: `ruff check lib tests examples` and `ruff format`.
- The MicroPython tests need a build with ulab and the audiodsp modules (`help('modules')` lists `audiofilters`, `audioladder`, `audiomodal`, `audiopump`). A stale build fails the tests on its own; rebuild before you blame the code.
- No audio targets: never add a check that says "this should sound like X". Trait files (`tests/traits/`) compare an instrument with itself; accept with `python tools/traits.py <name> --accept`.
- Nothing allocates in a block path; `tests/test_allocation.py` enforces it.
- Everything else is in [CONTRIBUTING.md](CONTRIBUTING.md).
