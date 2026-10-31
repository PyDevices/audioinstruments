# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The macros these modules took from the instruments they replaced move the parameters they name."""

import pytest
from vrack.modules import get_module_class

MERGED = {
    "Duo20": ("lpf_eg2_depth", "eg2_release", "volume"),
    "HybridMono": ("env_attack", "env_sustain"),
    "WestCoastSynth": ("func1_rise", "func1_fall", "volume"),
}


@pytest.mark.parametrize("module,name", [(m, n) for m, names in MERGED.items() for n in names])
def test_a_merged_macro_moves_its_parameter(module, name):
    mod = get_module_class(module)("m")
    index = mod.MACRO_LABELS.index(name)
    spec = mod._param_specs[name]
    mod.set_macro(index, 0.0)
    assert mod.get_param(name) == pytest.approx(spec["min"])
    mod.set_macro(index, 1.0)
    assert mod.get_param(name) == pytest.approx(spec["max"])
    assert mod.get_macro(index) == pytest.approx(1.0)


def test_acid303_has_a_volume_macro_that_scales_its_output():
    import numpy as np

    acid303 = get_module_class("Acid303")("t")
    index = acid303.MACRO_LABELS.index("volume")
    assert index == 8
    acid303.set_macro(index, 0.0)
    assert acid303.volume == 0.0
    acid303.set_macro(index, 1.0)
    assert acid303.volume == pytest.approx(1.5)
    assert np.isfinite(acid303.volume)
