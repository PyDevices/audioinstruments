# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The rack as an hmilink model, over the in-process transport.

pytest tests/test_hmi.py                         # CPython, with hmilink on the path
micropython tests/test_hmi.py                    # MicroPython, likewise
"""

import os
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "examples" not in sys.path:
    sys.path.insert(0, "examples")

try:
    import hmilink
    from hmilink import local
except ImportError:  # pragma: no cover - hmilink is a sibling package
    hmilink = None

if hmilink is None:
    import pytest

    pytest.skip("hmilink not on the path", allow_module_level=True)

import play_audio  # noqa: E402
from vrack.hmi import RackModel  # noqa: E402


def pump(device, panels, rounds=3):
    for _ in range(rounds):
        device.poll()
        for p in panels:
            p.poll()


def make():
    _name, rack, _events, _seconds = play_audio.build_movement(4)
    model = RackModel(rack, name="movement 4")
    device = hmilink.Device(model, telemetry_hz=1000)
    lst = device.add(local.serve())
    p1 = hmilink.Panel(local.connect(lst))
    p2 = hmilink.Panel(local.connect(lst))
    pump(device, (p1, p2))
    return rack, model, device, p1, p2


def test_document_and_description():
    rack, model, device, p1, p2 = make()
    assert p1.doc["modules"]["vco1"]["type"] == "Modular55VCO"
    assert p1.doc["cables"]["lpf.audio_in"]["source"] == "vco1.saw_out"
    assert "master_l" in p1.doc["cables"]
    desc = p1.desc
    assert desc["kind"] == "rack"
    vco = desc["modules"]["vco1"]
    names = [p["name"] for p in vco["params"]]
    assert "range" in names
    assert any(o["name"] == "saw_out" for o in vco["outputs"])
    assert "Modular55VCO" in desc["types"]
    assert desc["master"][0]["name"] == "master_l"


def test_knob_is_clipped_and_applied_to_the_module():
    rack, model, device, p1, p2 = make()
    lpf = rack.get_module("lpf")
    p1.set("/modules/lpf/params/regen", 5.0)
    pump(device, (p1, p2))
    assert lpf.params["regen"] == 1.0
    assert p1.doc["modules"]["lpf"]["params"]["regen"] == 1.0
    assert p2.doc["modules"]["lpf"]["params"]["regen"] == 1.0


def test_cables_plug_and_unplug_the_running_rack():
    rack, model, device, p1, p2 = make()
    lpf = rack.get_module("lpf")
    vco2 = rack.get_module("vco2")
    before = len(rack.cables)
    p1.set("/cables/lpf.audio_in", {"source": "vco2.saw_out"})
    pump(device, (p1, p2))
    assert lpf.audio_in.cable.source is vco2.saw_out
    assert len(rack.cables) == before  # replaced, not added
    assert p2.doc["cables"]["lpf.audio_in"]["source"] == "vco2.saw_out"
    assert p2.doc["cables"]["lpf.audio_in"]["color"]  # the device filled the color in
    assert rack._dirty is False  # scheduled at the boundary
    rack.step()
    p2.remove("/cables/lpf.audio_in")
    pump(device, (p1, p2))
    assert lpf.audio_in.cable is None
    assert "lpf.audio_in" not in p1.doc["cables"]
    rack.step()


def test_refused_op_is_undone_on_the_panel():
    rack, model, device, p1, p2 = make()
    errors = []
    p1.on_error = errors.append
    p1.set("/modules/vco1/params/nope", 1.0)
    pump(device, (p1, p2))
    assert errors and "no parameter" in errors[0]["msg"]
    assert "nope" not in p1.doc["modules"]["vco1"]["params"]
    p1.remove("/modules/lpf")
    pump(device, (p1, p2))
    assert "unplug" in errors[-1]["msg"]
    assert "lpf" in p1.doc["modules"]


def test_add_and_remove_a_module():
    rack, model, device, p1, p2 = make()
    events = []
    p2.on_event = events.append
    p1.set("/modules/lfo", {"type": "Modular100EnvLFO"})
    pump(device, (p1, p2))
    assert rack.get_module("lfo") is not None
    assert p2.doc["modules"]["lfo"]["type"] == "Modular100EnvLFO"
    assert any(e["name"] == "module" and e["id"] == "lfo" for e in events)
    rack.step()
    p2.remove("/modules/lfo")
    pump(device, (p1, p2))
    assert rack.get_module("lfo") is None
    assert "lfo" not in p1.doc["modules"]


def test_late_cable_event():
    rack, model, device, p1, p2 = make()
    events = []
    p1.on_event = events.append
    p2.set("/cables/vco1.freq_cv2", {"source": "lpf.audio_out"})  # a loop: lpf feeds vco1
    pump(device, (p1, p2))
    late = [e for e in events if e["name"] == "late"]
    assert late and late[-1]["cables"]
    rack.step()


def test_telemetry_levels():
    rack, model, device, p1, p2 = make()
    midi = rack.get_module("midi_cv")
    midi.note_on(48, 100)
    for _ in range(40):
        rack.step()
    tele = []
    p1.on_tele = tele.append
    device._tele_at -= 10000
    pump(device, (p1, p2))
    assert tele
    v = tele[-1]
    assert "vco1.saw_out" in v["levels"]
    assert v["levels"]["vco1.saw_out"] > 0.0
    assert len(v["master"]) == 2


def test_save_and_load(tmp_path=None):
    rack, model, device, p1, p2 = make()
    path = (str(tmp_path) if tmp_path else ".") + "/hmi_patch.json"
    events = []
    p2.on_event = events.append
    p1.set("/modules/lpf/params/regen", 0.25)
    pump(device, (p1, p2))
    p1.command("save", path=path)
    pump(device, (p1, p2))
    assert events[-1]["name"] == "saved"
    p1.set("/modules/lpf/params/regen", 0.75)
    pump(device, (p1, p2))
    docs = []
    p2.on_doc = lambda d, desc: docs.append(d)
    p1.command("load", path=path)
    pump(device, (p1, p2))
    assert rack.get_module("lpf").params["regen"] == 0.25
    assert docs and docs[-1]["modules"]["lpf"]["params"]["regen"] == 0.25
    assert p1.doc["modules"]["lpf"]["params"]["regen"] == 0.25
    os.remove(path)


def test_instrument_patch_and_macros_reach_every_panel():
    import vrack.adapter as adapter
    from vrack.hmi import InstrumentModel

    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        48000, voice="poly6", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    try:
        model = InstrumentModel(inst)
        device = hmilink.Device(model, telemetry_hz=1000)
        lst = device.add(local.serve())
        p1 = hmilink.Panel(local.connect(lst))
        p2 = hmilink.Panel(local.connect(lst))
        pump(device, (p1, p2))
        assert p1.desc["instrument"]["patches"][0] == "Init"
        assert "vcf_cutoff" in p1.desc["instrument"]["macros"]
        assert p1.doc["patch"] == 0 and "vcf_cutoff" in p1.doc["macros"]
        seen = []
        p2.on_op = seen.append
        p1.set("/patch", 1)
        pump(device, (p1, p2))
        assert inst.patch_index == 1
        inst.fill()  # a pull build renders when pulled; the macros apply at the next render
        device._tele_at -= 10000
        pump(device, (p1, p2))
        assert p2.doc["patch"] == 1
        synced = [o for o in seen if o.get("from") == 0]
        assert any(o["path"].startswith("/macros/") for o in synced), "macros followed the patch"
        p2.set("/macros/vcf_cutoff", 200)
        pump(device, (p1, p2))
        assert p1.doc["macros"]["vcf_cutoff"] == 127.0  # clipped to the instrument's scale
        device._tele_at -= 10000
        pump(device, (p1, p2))  # the sync after a macro move runs at the next telemetry
        errors = []
        p1.on_error = errors.append
        p1.set("/patch", 99)
        pump(device, (p1, p2))
        assert errors and "no patch" in errors[0]["msg"]
        # a moved macro makes the patch "edited" (None) on the instrument; the
        # refused op put the device's value back, whatever it is
        assert p1.doc["patch"] == model.doc["patch"] == inst.patch_index
    finally:
        inst.deinit()


def test_poll_cost_per_block():
    """Idle poll between blocks, as a number: must stay far under a block."""
    rack, model, device, p1, p2 = make()
    import time

    try:
        t0 = time.ticks_us()
        for _ in range(200):
            device.poll()
        dt = time.ticks_diff(time.ticks_us(), t0) / 200
    except AttributeError:
        t0 = time.monotonic_ns()
        for _ in range(200):
            device.poll()
        dt = (time.monotonic_ns() - t0) / 1000 / 200
    print("idle device.poll(): %.1f us" % dt)
    assert dt < 1000


if __name__ == "__main__":
    for name in sorted(k for k in dir() if k.startswith("test_")):
        print(name)
        globals()[name]()
    print("ok")
