# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CI checks only what a change can reach, so the reach has to be right.

``tools/ci_scope.py`` reads the code and says which tests and which
instruments' traits a change could move. A reach that is too short lets a
change through unchecked; the first test here is the one that matters, and
compares the reach of every instrument with what the interpreter loads.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from tools import ci_scope

ROOT = ci_scope.ROOT

_LOADED = """
import json, os, sys
sys.path.insert(0, os.path.join(%(root)r, "lib"))
import vrack.adapter as adapter

out = {}
for name in adapter.ALL:
    for key in [k for k in sys.modules if k == "vrack" or k.startswith("vrack.")]:
        del sys.modules[key]
    import vrack.adapter as adapter
    try:
        adapter.create(48000, voice=name)
    except Exception as e:  # a sampler with no SoundFont bank (CI has none) still imported its files
        print("%%s: %%s" %% (name, e), file=sys.stderr)
    out[name] = sorted(
        os.path.relpath(m.__file__, %(root)r).replace(os.sep, "/")
        for k, m in sys.modules.items()
        if (k == "vrack" or k.startswith("vrack.")) and getattr(m, "__file__", None)
    )
print(json.dumps(out))
"""


def test_every_instrument_reaches_what_it_loads():
    ran = subprocess.run(
        [sys.executable, "-c", _LOADED % {"root": ROOT}],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(ran.stdout.strip().splitlines()[-1])
    # Importing a package loads everything its __init__ imports. That is
    # not the importer's business, so the reach CI uses drops it; but the
    # interpreter's loading must still be within the reach with it kept, or an
    # import went unseen (inside a function, by name).
    graph = ci_scope.Graph(ROOT)
    reach = graph.instruments(through_inits=True)
    assert sorted(loaded) == sorted(reach)
    for name, files in loaded.items():
        missing = sorted(set(files) - reach[name])
        assert not missing, "%s loads %s, which CI would not check it against" % (name, missing)


def _tree(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return str(tmp_path)


@pytest.fixture
def repo(tmp_path):
    return _tree(
        tmp_path,
        {
            "lib/vrack/__init__.py": "from . import modules\n__all__ = ['Alpha', 'BVoice']\n",
            "lib/vrack/adapter.py": """
                from .core.x import x
                _MODULE_VOICES = {"a": ("Alpha", "k", "g", "o")}
                _PATCH_VOICES = {"b": ("b", "B")}
            """,
            "lib/vrack/core/__init__.py": "",
            "lib/vrack/core/x.py": "x = 1\n",
            "lib/vrack/modules/__init__.py": """
                _REGISTRY = (("Alpha", "Alpha", "alpha"), ("BVoice", "BVoice", "b.voice"))
            """,
            "lib/vrack/modules/alpha.py": "from ..dsp.d1 import f\n",
            "lib/vrack/modules/b/__init__.py": "",
            "lib/vrack/modules/b/voice.py": "from ...dsp.d2 import f\n",
            "lib/vrack/dsp/__init__.py": "",
            "lib/vrack/dsp/d1.py": "def f(): pass\n",
            "lib/vrack/dsp/d2.py": "def f(): pass\n",
            "lib/vrack/dsp/d3.py": "def f(): pass\n",
            "lib/vrack/instruments/__init__.py": "",
            "lib/vrack/instruments/b.py": """
                class B:
                    def build(self):
                        from ..modules.b.voice import f
            """,
            "tools/traits.py": "SPECS = {'a': {}, 'b': {}}\n",
            "tests/traits/a.json": "{}",
            "tests/traits/b.json": "{}",
            "tests/conftest.py": "import vrack\n",
            "tests/test_traits.py": "from tools import traits\nimport vrack.adapter\n",
            "tests/test_sweep.py": "import vrack.adapter as adapter\nadapter.ALL\n",
            "tests/test_alpha.py": "from vrack.modules.alpha import f\n",
            "tests/test_plain.py": "def test_x(): pass\n",
        },
    )


def test_a_dsp_file_one_instrument_uses_checks_that_instrument(repo):
    out = ci_scope.scope(repo, ["lib/vrack/dsp/d2.py"])
    assert out["instruments"] == ["b"]
    assert "tests/test_traits.py::test_traits_hold[b]" in out["pytest"]
    assert "tests/test_traits.py::test_traits_hold[a]" not in out["pytest"]
    assert "tests/test_traits.py" not in out["pytest"]
    assert out["lint"] == ["lib/vrack/dsp/d2.py"]
    assert not out["full"]


def test_a_module_voice_is_reached_through_the_registry_class(repo):
    out = ci_scope.scope(repo, ["lib/vrack/dsp/d1.py"])
    assert out["instruments"] == ["a"]
    assert "tests/test_alpha.py" in out["pytest"]


def test_a_core_change_checks_every_instrument(repo):
    out = ci_scope.scope(repo, ["lib/vrack/core/x.py"])
    assert out["instruments"] == ["a", "b"]
    assert out["pytest"] == ["tests"]
    assert not out["full"] and out["reasons"]


def test_a_new_core_in_a_package_is_only_its_importers_business(repo, tmp_path):
    (tmp_path / "lib/vrack/dsp/__init__.py").write_text(
        "from .d1 import f\nfrom .d2 import f as g\n"
    )
    (tmp_path / "lib/vrack/modules/alpha.py").write_text("from ..dsp import f\n")
    (tmp_path / "lib/vrack/modules/b/voice.py").write_text("from ...dsp import g\n")
    assert ci_scope.scope(repo, ["lib/vrack/dsp/d1.py"])["instruments"] == ["a"]
    assert ci_scope.scope(repo, ["lib/vrack/dsp/d2.py"])["instruments"] == ["b"]


def test_the_package_init_does_not_make_every_module_reachable(repo):
    graph = ci_scope.Graph(repo)
    assert "lib/vrack/modules/b/voice.py" not in graph.instruments()["a"]


def test_an_unused_file_checks_no_instrument(repo):
    out = ci_scope.scope(repo, ["lib/vrack/dsp/d3.py"])
    assert out["instruments"] == []
    assert "tests/test_sweep.py" in out["pytest"]


def test_a_trait_file_checks_its_instrument(repo):
    out = ci_scope.scope(repo, ["tests/traits/a.json"])
    assert out["instruments"] == ["a"]
    assert "tests/test_traits.py::test_traits_hold[a]" in out["pytest"]


def test_the_traits_tool_checks_every_instrument(repo):
    out = ci_scope.scope(repo, ["tools/traits.py"])
    assert out["instruments"] == ["a", "b"]
    assert "tests/test_traits.py" in out["pytest"]


def test_docs_and_examples_check_little(repo):
    assert ci_scope.scope(repo, ["README.md", "docs/x.md", "ROADMAP.md"])["nothing"]
    out = ci_scope.scope(repo, ["examples/demo.py"])
    assert out["lint"] == ["examples/demo.py"]
    assert out["pytest"] == [] and out["instruments"] == []


@pytest.mark.parametrize(
    "changed,deleted",
    [
        (["pyproject.toml"], []),
        ([".github/workflows/ci.yml"], []),
        (["tools/ci_scope.py"], []),
        ([], ["lib/vrack/dsp/d3.py"]),
        (["lib/vrack/data.bin"], []),
    ],
)
def test_these_check_everything(repo, changed, deleted):
    out = ci_scope.scope(repo, changed, deleted)
    assert out["full"] and out["reasons"]
    assert out["pytest"] == ["tests"] and out["instruments"] == ["a", "b"]


def test_the_real_tree_parses_and_a_core_change_reaches_the_poly106():
    out = ci_scope.scope(ROOT, ["lib/vrack/core/rack.py"])
    assert "poly106" in out["instruments"]
    assert os.path.exists(os.path.join(ROOT, "tools", "ci_scope.py"))
