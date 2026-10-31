# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Say what CI has to check for a change, so a typical change costs a few minutes.

    python tools/ci_scope.py --base origin/main          # a branch against main
    python tools/ci_scope.py --files lib/vrack/dsp/chorus.py tests/test_x.py
    python tools/ci_scope.py --all                       # check everything
    python tools/ci_scope.py --base BASE --get pytest    # one item per line
    python tools/ci_scope.py --base BASE --out scope.json   # keep the answer
    python tools/ci_scope.py --from scope.json --get lint   # read it back

The answer is a JSON object: ``lint`` (python files for ruff), ``pytest``
(test files, and single trait checks), ``instruments`` (the instruments with
a trait file that the change reaches) and ``full`` (the whole repo, with the
reasons). It reads the code with ``ast`` and needs nothing installed, so a
change that touches no code finishes before anything is downloaded.

How a file is mapped:

- A python file reaches every file it imports, directly or through others,
  including imports inside functions. Importing a package runs its
  ``__init__``, but reaches only the files it re-exports under the names
  you import, so a new core in ``dsp/`` is not everyone's business. A name in a string that is a module's
  class (the registry in ``modules/__init__.py``), or a module's dotted name
  (a patch's graph form in ``GRAPH``), counts as an import of that
  module, and an instrument also reaches the adapter and the submodule its
  entry in ``_PATCH_VOICES``, ``_MODULE_VOICES`` or ``SAMPLERS`` names.
- A test runs when it, or anything it reaches, changed. A test that goes
  through every module or every instrument (it mentions ``ALL``,
  ``MODULE_TYPES``, ``get_module_class`` or the registry) reaches all of
  ``lib/``.
- An instrument is checked against its trait file when anything it reaches,
  or its trait file, changed. The adapter and the core are reached by every
  instrument, so a change there checks every instrument.
- A change to the shared core (``core/``, the adapter, the registry, the
  package ``__init__``, ``conftest.py``) runs every test and checks every
  instrument.
- Everything is checked when ``pyproject.toml``, the workflow or this tool
  changed, when a file under ``lib/`` or ``tools/`` or ``tests/`` was
  deleted, or when a file there that is not python or a trait file changed.
- ``tests/mpy/`` needs a MicroPython build with ulab and audiodsp, which CI
  does not have: run ``micropython tests/mpy/run.py`` before you merge.

``tests/test_ci_scope.py`` checks the reach of every instrument against what
the interpreter really imports.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Python is linted here. ``tests/mpy`` is read by MicroPython, not pytest.
LINT_DIRS = ("lib", "tests", "examples", "tools")
#: Source whose imports are followed.
GRAPH_DIRS = ("lib", "tests", "tools", "examples")
#: A change to any of these checks the whole repo.
FULL_FILES = ("pyproject.toml", "tools/ci_scope.py", "tests/test_ci_scope.py")
FULL_PREFIXES = (".github/",)
#: A change to any of these is a change to the shared core: every test runs
#: and every instrument is checked, whatever imports what.
SHARED_PREFIXES = ("lib/vrack/core/",)
SHARED_FILES = ("lib/vrack/__init__.py", "lib/vrack/_lazy.py", "tests/conftest.py")
#: A test that mentions one of these goes through every module or instrument.
SWEEP = re.compile(
    r"\b(ALL|MODULE_TYPES|get_module_class|_REGISTRY|_PATCH_VOICES|_MODULE_VOICES)\b"
)
#: Found by parsing, not importing, so the tool needs no dependencies.
ADAPTER = "lib/vrack/adapter.py"
REGISTRY = "lib/vrack/modules/__init__.py"
TRAITS_TOOL = "tools/traits.py"
TRAITS_DIR = "tests/traits"
TRAITS_TEST = "tests/test_traits.py"


def _is_mpy(path):
    return path.startswith("tests/mpy/")


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def _literal(root, rel, name):
    """The value of a module-level ``name = <literal>`` assignment in ``rel``."""
    tree = ast.parse(_read(root, rel))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def python_files(root):
    found = []
    for top in GRAPH_DIRS:
        for folder, dirs, names in os.walk(os.path.join(root, top)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in names:
                if name.endswith(".py"):
                    rel = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
                    if not _is_mpy(rel):
                        found.append(rel)
    return sorted(found)


class Graph:
    """What each python file imports, and what an instrument reaches."""

    def __init__(self, root):
        self.root = root
        self.files = python_files(root)
        self.known = set(self.files)
        registry = _literal(root, REGISTRY, "_REGISTRY") or ()
        #: Both a module's class name and its patch NAME lead to its submodule.
        self.by_name = {}
        for cls, name, sub in registry:
            self.by_name[cls] = self.by_name[name] = "vrack.modules." + sub
        self._exported = {}
        self.direct = {rel: self._imports(rel) for rel in self.files}
        self._reach = {}

    # -- imports ----------------------------------------------------------

    def dotted(self, rel):
        """The name a file is imported by, and whether it is a package."""
        base = rel[4:] if rel.startswith("lib/") else rel
        base = base[6:] if base.startswith("tests/") else base
        parts = base[:-3].split("/")
        if parts[-1] == "__init__":
            return ".".join(parts[:-1]), True
        return ".".join(parts), False

    def resolve(self, name):
        """The files that importing ``name`` runs: it and its parent packages."""
        out = set()
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            stem = "/".join(parts[:i])
            last = i == len(parts)
            for base in ("lib/", "tests/", ""):
                for cand in (base + stem + ".py", base + stem + "/__init__.py"):
                    if cand in self.known and (last or cand.endswith("__init__.py")):
                        out.add(cand)
        return out

    def _is_module(self, name):
        stem = name.replace(".", "/")
        return any(
            cand in self.known
            for base in ("lib/", "tests/", "")
            for cand in (base + stem + ".py", base + stem + "/__init__.py")
        )

    def _imports(self, rel):
        tree = ast.parse(_read(self.root, rel), filename=rel)
        here, is_pkg = self.dotted(rel)
        package = here if is_pkg else here.rpartition(".")[0]
        hits = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    hits |= self.resolve(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = self._base(node, package)
                for alias in node.names:
                    hits |= self.from_targets(base, alias.name)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in self.by_name
                # A registry class named in a string loads its module. A package's
                # __init__ lists every module in __all__ and the registry, and
                # the adapter lists every module voice, so they name none of
                # them for this purpose (an instrument is mapped on its own).
                and not rel.endswith("__init__.py")
                and rel != ADAPTER
            ):
                hits |= self.resolve(self.by_name[node.value])
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("vrack.")
                and self._is_module(node.value)
            ):
                # A module named by its dotted path in a string is loaded by
                # name: a patch's graph form (``VoicePatch.GRAPH``).
                hits |= self.resolve(node.value)
        hits.discard(rel)
        return hits

    @staticmethod
    def _base(node, package):
        """The dotted module a ``from`` statement names, relative ones resolved."""
        if not node.level:
            return node.module or ""
        up = package.split(".") if package else []
        up = up[: len(up) - (node.level - 1)]
        return ".".join(up + ([node.module] if node.module else []))

    def from_targets(self, base, name):
        """The files ``from base import name`` runs.

        The module itself and its parent packages (as nodes: a change to a
        package's ``__init__`` counts), and ``name`` as a submodule if it is
        one. If ``name`` is something the package's ``__init__`` re-exports,
        the file it comes from. The package's other re-exports are not
        reached: importing ``dsp.chorus`` runs ``dsp/__init__.py``, which
        imports every core in ``dsp``, but only the chorus is the importer's
        business.
        """
        out = set(self.resolve(base)) if base else set()
        if name == "*":
            for files in self._exports(base).values():
                out |= files
            return out
        full = base + "." + name if base else name
        if self._is_module(full):
            return out | self.resolve(full)
        return out | self._exports(base).get(name, set())

    def _exports(self, package):
        """Name -> files, for what a package's ``__init__`` imports at its top."""
        if package in self._exported:
            return self._exported[package]
        self._exported[package] = out = {}
        init = None
        for base in ("lib/", "tests/", ""):
            cand = base + package.replace(".", "/") + "/__init__.py"
            if cand in self.known:
                init = cand
        if init is not None:
            for node in ast.parse(_read(self.root, init)).body:
                if isinstance(node, ast.ImportFrom):
                    base = self._base(node, package)
                    for alias in node.names:
                        out.setdefault(alias.asname or alias.name, set()).update(
                            self.from_targets(base, alias.name) - {init}
                        )
        return out

    def reach(self, rel, through_inits=False):
        """Every file ``rel`` runs when it is imported, itself included.

        A package's ``__init__`` is a node, but unless ``through_inits`` its own
        imports are not followed, only the ones named in a ``from`` statement
        (see ``from_targets``). With it, this is everything the interpreter loads.
        """
        key = (rel, through_inits)
        if key not in self._reach:
            seen, todo = {rel}, [rel]
            while todo:
                here = todo.pop()
                if here.endswith("__init__.py") and here != rel and not through_inits:
                    continue
                for nxt in self.direct.get(here, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            self._reach[key] = seen
        return self._reach[key]

    # -- instruments ------------------------------------------------------

    def instruments(self, through_inits=False):
        """Instrument name -> the files that building and playing it reaches."""
        module_voices = _literal(self.root, ADAPTER, "_MODULE_VOICES") or {}
        patch_voices = _literal(self.root, ADAPTER, "_PATCH_VOICES") or {}
        samplers = _literal(self.root, ADAPTER, "SAMPLERS") or ()
        out = {}
        for name in samplers:  # a module of vrack that has its own create()
            out[name] = self._with_adapter(self.resolve("vrack." + name), through_inits)
        for name, entry in module_voices.items():
            entries = self.resolve(self.by_name.get(entry[0], "vrack.modules." + name))
            out[name] = self._with_adapter(entries, through_inits)
        for name, entry in patch_voices.items():
            out[name] = self._with_adapter(
                self.resolve("vrack.instruments." + entry[0]), through_inits
            )
        return out

    def _with_adapter(self, entries, through_inits):
        reached = set(self.reach(ADAPTER, through_inits))
        for rel in entries:
            reached |= self.reach(rel, through_inits)
        return reached

    def everything_in_lib(self):
        return {rel for rel in self.files if rel.startswith("lib/")}


def trait_names(root):
    """The instruments that have a trait file or a spec."""
    names = set()
    folder = os.path.join(root, TRAITS_DIR)
    if os.path.isdir(folder):
        names |= {n[:-5] for n in os.listdir(folder) if n.endswith(".json")}
    if os.path.exists(os.path.join(root, TRAITS_TOOL)):
        specs = _literal(root, TRAITS_TOOL, "SPECS")
        if specs:
            names |= set(specs)
    return sorted(names)


def scope(root, changed, deleted=(), force_full=False):
    """What to check for ``changed`` (existing files) and ``deleted`` ones."""
    changed = sorted(set(changed))
    deleted = sorted(set(deleted))
    reasons = []
    if force_full:
        reasons.append("everything was asked for")
    for rel in changed + deleted:
        if rel in FULL_FILES or rel.startswith(FULL_PREFIXES):
            reasons.append("%s changed" % rel)
    for rel in deleted:
        if rel.startswith(("lib/", "tests/", "tools/")) and not _is_mpy(rel):
            reasons.append("%s was deleted" % rel)
    for rel in changed:
        data = not rel.endswith(".py") and not rel.startswith(TRAITS_DIR + "/")
        if rel.startswith(("lib/", "tests/", "tools/")) and not _is_mpy(rel) and data:
            reasons.append("%s is data the tests may read" % rel)

    graph = Graph(root)
    every = trait_names(root)
    all_tests = [r for r in graph.files if re.match(r"tests/test_[^/]*\.py$", r)]

    if reasons:
        return {
            "full": True,
            "reasons": reasons,
            "nothing": False,
            "lint": list(LINT_DIRS),
            "pytest": ["tests"],
            "instruments": every,
        }

    code = {r for r in changed if r.endswith(".py") and not _is_mpy(r)}
    shared = sorted(
        r for r in code if r.startswith(SHARED_PREFIXES) or r in SHARED_FILES + (ADAPTER, REGISTRY)
    )
    lint = [
        r for r in changed if r.endswith(".py") and r.startswith(tuple(d + "/" for d in LINT_DIRS))
    ]
    reached_all = graph.everything_in_lib()

    tests = []
    for rel in all_tests:
        reach = set(graph.reach(rel))
        reach |= graph.reach("tests/conftest.py") if "tests/conftest.py" in graph.known else set()
        if SWEEP.search(_read(root, rel)):
            reach |= reached_all
        if reach & code:
            tests.append(rel)

    instruments = graph.instruments()
    named = {}
    for name in every:
        files = instruments.get(name, set())
        if files & code or "%s/%s.json" % (TRAITS_DIR, name) in changed:
            named[name] = True
    hit = sorted(named)

    pytest_args = list(tests)
    if shared:
        pytest_args, hit = ["tests"], list(every)
    elif TRAITS_TEST in tests:
        hit = list(every)
    elif hit:
        pytest_args.append(
            "%s::test_every_spec_has_a_trait_file_and_every_file_a_spec" % TRAITS_TEST
        )
        pytest_args += ["%s::test_traits_hold[%s]" % (TRAITS_TEST, n) for n in hit]

    return {
        "full": False,
        "reasons": ["the shared core changed (%s)" % ", ".join(shared)] if shared else [],
        "nothing": not lint and not pytest_args,
        "lint": lint,
        "pytest": pytest_args,
        "instruments": hit,
    }


def changed_between(root, base, head="HEAD"):
    """(existing, deleted) paths that differ between ``base`` and ``head``."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", "%s...%s" % (base, head)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    changed, deleted = [], []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        (deleted if status.startswith("D") else changed).append(path)
    return changed, deleted


def summary(result, changed):
    lines = ["### What CI checks", ""]
    if result["full"]:
        lines.append("Everything, because " + "; ".join(result["reasons"]) + ".")
    elif result["nothing"]:
        lines.append("Nothing: no code or test changed.")
    else:
        lines.append("%d file(s) changed." % len(changed))
        lines.append("- lint: %s" % (", ".join(result["lint"]) or "none"))
        lines.append("- pytest: %s" % (", ".join(result["pytest"]) or "none"))
        lines.append(
            "- instruments against their traits: %s" % (", ".join(result["instruments"]) or "none")
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="compare HEAD with this commit (merge-base)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--files", nargs="*", help="treat these as the changed files")
    ap.add_argument("--all", action="store_true", help="check everything")
    ap.add_argument("--out", help="also write the JSON answer to this file")
    ap.add_argument("--from", dest="source", help="read the answer from a file written by --out")
    ap.add_argument(
        "--get",
        choices=("lint", "pytest", "instruments", "reasons"),
        help="print one list, a line each",
    )
    ap.add_argument(
        "--github", action="store_true", help="write outputs and the step summary for Actions"
    )
    args = ap.parse_args(argv)

    if args.source:
        with open(args.source, encoding="utf-8") as f:
            print("\n".join(json.load(f)[args.get]))
        return 0

    changed, deleted = [], []
    if args.files is not None:
        changed = args.files
    elif args.base and not set(args.base) <= {"0"}:
        changed, deleted = changed_between(ROOT, args.base, args.head)
    else:
        args.all = True  # no base (a new branch, a manual run): check everything
    result = scope(ROOT, changed, deleted, force_full=args.all)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f)
    if args.get:
        print("\n".join(result[args.get]))
    else:
        print(json.dumps(result, indent=2))
    if args.github:
        text = summary(result, changed + deleted)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        path = os.environ.get("GITHUB_OUTPUT")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write("nothing=%s\n" % str(result["nothing"]).lower())
                f.write("lint=%s\n" % str(bool(result["lint"])).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
