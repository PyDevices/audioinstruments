# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Tonewheel3 compiled to a graph sounds the rack's Tonewheel3.

Every module of the Tonewheel3 (the voice, the manual's percussion, the scanner
vibrato, the expression pedal and the rotary speaker) has a graph fragment, so
``create()`` compiles it where audiodsp has ``audiograph``. The rack's tone and
vibrato each run 256 frames late (two ``ChunkedBridge`` objects), and the graph
has no such latency, so each part is held to the rack on a small rack of its
own, lined up as that part needs:

* **Drawbars.** ``WAVETABLE`` plays the drawbar table through the contacts,
  and the rack's synth starts its table 256 frames in (the bridge's priming
  pull), which the fragment copies. With the rack read 256 frames on, the two
  agree to a count (rounding) on every key, as long as a key's pitch changes on
  a chunk boundary, as the rack's synth can only retune once every 256 frames.
* **Vibrato and chorus.** The sweep is the same ``FeedbackDelay`` and the same
  table; the rack's sweep and the graph's agree to 2 counts in all six modes.
* **Expression pedal.** Within a count and a half.
* **Rotary.** ``ROTARY`` against ``RotarySpeakerCore``, 5 counts at worst.
* **Percussion.** The sine's phase is the rack's accident (it starts 256 frames
  ahead of the contacts that gate it), so the envelope is compared: the rms of
  each 480 frames follows the rack's within 12%, which is mostly that same 256
  frames on the fall.
* **Key click.** The rack plays one fixed table of band-limited noise; the graph
  makes new noise under the same envelope, so what is compared is the energy
  of sixty clicks, down and up, within 20%.

The whole instrument is held to the rack on level, since the sweep of the
vibrato and the rotor are free-running and the two engines differ in the
latency in front of them.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.rotary_speaker import RotarySpeaker
from audioinstruments._rack.modules.tonewheel3.expression import Tonewheel3Expression
from audioinstruments._rack.modules.tonewheel3.percussion import Tonewheel3Percussion
from audioinstruments._rack.modules.tonewheel3.vibrato import Tonewheel3Vibrato
from audioinstruments._rack.modules.tonewheel3.voice import Tonewheel3Voice

ag = pytest.importorskip("audiograph")

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BLOCK = 128
RATE = 48000
NO_DRAWBARS = {
    "db16": 0,
    "db5_13": 0,
    "db8": 0,
    "db4": 0,
    "db2_23": 0,
    "db2": 0,
    "db1_35": 0,
    "db1_13": 0,
    "db1": 0,
}

#: counts, worst and rms, of the drawbars against the rack
TONE_BOUND = (1.0, 0.1)
#: counts, worst, of the scanner against the rack
VIBRATO_BOUND = 3.0
EXPRESSION_BOUND = 1.5
ROTARY_BOUND = 5.0
#: the percussion's envelope, relative error of the rms of each 480 frames
PERCUSSION_BOUND = 0.12
#: the click's energy against the rack's, a ratio within these
CLICK_BOUND = (0.8, 1.25)


# -- a rack of one module, fed a signal ------------------------------------------------


class Source(Module):
    """A tone with a period of 256 frames, so a 256-frame delay changes nothing."""

    NAME = "TWSource"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.n = 0

    def process(self, block_size):
        t = np.arange(self.n, self.n + block_size)
        x = sum(a * np.sin(2 * np.pi * k * t / 256.0) for k, a in ((1, 1.0), (2, 0.6), (3, 0.3)))
        self.out.buffer[:] = x * 0.1
        self.n += block_size


def part_rack(cls, params, stereo=False):
    rack = Rack(block_size=BLOCK)
    src = rack.add_module(Source("src"))
    module = rack.add_module(cls("m", sample_rate=RATE, block_size=BLOCK))
    for name, value in params.items():
        module.set_param(name, value)
    rack.connect(src.out, module.audio_in)
    if stereo:
        rack.connect(module.left_out, rack.master_left_in)
        rack.connect(module.right_out, rack.master_right_in)
    else:
        rack.connect(module.audio_out, rack.master_left_in)
    return rack, module


def part_worst(cls, params, blocks=120, stereo=False, skip=2000):
    """Worst counts between the rack and the graph of one module, from ``skip`` frames on."""
    rack, _ = part_rack(cls, params, stereo)
    want = []
    for _ in range(blocks):
        rack.step()
        left = np.array(rack.output_buffer_left, dtype=np.float64) * UNIT
        right = np.array(rack.output_buffer_right, dtype=np.float64) * UNIT
        want.append(np.stack([left, right], 1))
    want = np.concatenate(want)
    graph, _ = part_rack(cls, params, stereo)
    compiled = compile_rack(graph, scale=1.0, channel_count=2)
    assert [m.NAME for m in compiled.rack_side] == ["TWSource"]
    raw = bytearray(BLOCK * 4 * blocks)
    for k in range(blocks):
        compiled.step(raw, k)
    got = np.frombuffer(raw, dtype=np.int16).astype(np.float64).reshape(-1, 2)
    diff = (want - got)[skip:]
    if not stereo:
        diff = diff[:, 0]
    return float(np.abs(diff).max())


def vibrato_worst():
    return max(
        part_worst(Tonewheel3Vibrato, {"vibrato": 1.0, "vibrato_mode": mode})
        for mode in (0, 1, 2, 3, 4, 5)
    )


def expression_worst():
    return max(part_worst(Tonewheel3Expression, {"expression": p}) for p in (10.0, 6.0, 2.5, 0.0))


def rotary_worst():
    return max(
        part_worst(RotarySpeaker, {"rotary": mode, "drive": drive, "volume": 7.0}, 200, True, 0)
        for mode, drive in ((0.0, 0.0), (1.0, 2.0), (2.0, 7.0))
    )


# -- the voice and the manual's percussion, keyed ------------------------------------


class Keys(Module):
    """One key: its pitch, note and gate, set from Python a block at a time."""

    NAME = "TWKeys"

    def _build(self):
        self.pitch = self.add_output("pitch", signal_type=SignalType.CV)
        self.note = self.add_output("note", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.key = 60
        self.held = 0.0

    def process(self, block_size):
        fill(self.pitch.buffer, (self.key - 60) / 120.0)
        fill(self.note.buffer, (self.key - 60) / 120.0)
        fill(self.gate.buffer, self.held)

    def fragment(self, f):
        self._controls = [f.control(jack, 0.0) for jack in (self.pitch, self.note, self.gate)]
        f.before_run(self._block)

    def _block(self):
        value = (self.key - 60) / 120.0
        self._controls[0].set(value)
        self._controls[1].set(value)
        self._controls[2].set(self.held)


def voice_rack(voice_params, perc_params):
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    perc = rack.add_module(Tonewheel3Percussion("perc", sample_rate=RATE, block_size=BLOCK))
    voice = rack.add_module(Tonewheel3Voice("voice", sample_rate=RATE, block_size=BLOCK))
    rack.connect(keys.gate, perc.gate_in)
    rack.connect(keys.pitch, voice.pitch_in)
    rack.connect(keys.note, voice.note_in)
    rack.connect(keys.gate, voice.gate_in)
    rack.connect(perc.env_out, voice.perc_env_in)
    rack.connect(voice.audio_out, rack.master_left_in)
    for name, value in voice_params.items():
        voice.set_param(name, value)
    for name, value in perc_params.items():
        perc.set_param(name, value)
    return rack, keys


def voice_render(voice_params, plan, blocks, perc_params=None):
    """The rack's and the graph's left channel for ``plan``: {block: (key, held)}."""
    rack, keys = voice_rack(voice_params, perc_params or {})
    want = []
    for b in range(blocks):
        if b in plan:
            keys.key, keys.held = plan[b]
        rack.step()
        want.append(np.array(rack.output_buffer_left, dtype=np.float64) * UNIT)
    graph, keys = voice_rack(voice_params, perc_params or {})
    compiled = compile_rack(graph, scale=1.0, channel_count=2)
    raw = bytearray(BLOCK * 4 * blocks)
    for b in range(blocks):
        if b in plan:
            keys.key, keys.held = plan[b]
        compiled.step(raw, b)
    got = np.frombuffer(raw, dtype=np.int16).astype(np.float64).reshape(-1, 2)[:, 0]
    return np.concatenate(want), got


#: Every change of key is on an even block: the rack's synth retunes once a 256-frame chunk.
TONES = {
    60: (10, 80),
    36: (10, 70),
    96: (10, 70),
}


def tone_stats(voice_params):
    """(worst, rms) counts of the graph against the rack, read 256 frames on."""
    plan = {10: (60, 1.0), 70: (60, 0.0), 80: (36, 1.0), 120: (36, 0.0), 130: (96, 1.0)}
    plan.update({170: (96, 0.0), 180: (64, 1.0), 200: (67, 1.0), 240: (64, 0.0), 250: (67, 0.0)})
    want, got = voice_render(voice_params, plan, 280)
    assert np.abs(want).max() > 100.0
    diff = want[256:] - got[:-256]
    return float(np.abs(diff).max()), float(np.sqrt(np.mean(diff**2)))


def tone_stats_all_drawbars():
    return tone_stats(
        {
            "percussion": 0.0,
            "click": 0.0,
            "db16": 8,
            "db5_13": 5,
            "db8": 7,
            "db4": 3,
            "db2_23": 8,
            "db2": 2,
            "db1_35": 6,
            "db1_13": 1,
            "db1": 4,
        }
    )


def tone_stats_default():
    return tone_stats({"percussion": 0.0, "click": 0.0})


DRAWBAR_NAMES = tuple(NO_DRAWBARS)


def tone_stats_one_drawbar(name):
    """The tone with only drawbar ``name`` out, at 6: its own footage and trim."""
    return tone_stats(dict(NO_DRAWBARS, percussion=0.0, click=0.0, **{name: 6}))


def drawbars_one_at_a_time_ok():
    for name in DRAWBAR_NAMES:
        worst, rms = tone_stats_one_drawbar(name)
        if worst > TONE_BOUND[0] or rms > TONE_BOUND[1]:
            return False
    return True


def percussion_peak_hz(harmonic, key=60):
    """The graph's percussion frequency (the FFT peak) and the one the rack plays."""
    params = dict(NO_DRAWBARS, percussion=1.0, click=0.0, perc_harmonic=harmonic)
    want, got = voice_render(params, {10: (key, 1.0), 90: (key, 0.0)}, 170)
    peaks = []
    for series in (want[256:], got):
        seg = series[1700 : 1700 + 4096]
        spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        peaks.append(float(np.argmax(spectrum)) * RATE / len(seg))
    return peaks[1], peaks[0]


def percussion_pitch_ok():
    for harmonic in (0.0, 1.0):
        got, want = percussion_peak_hz(harmonic)
        if abs(got - want) > 2 * RATE / 4096:
            return False
    # and the two settings are different notes (second 4', third 2 2/3')
    return abs(percussion_peak_hz(1.0)[0] / percussion_peak_hz(0.0)[0] - 1.5) < 0.05


def windows(a, size=480):
    n = len(a) // size
    return np.sqrt(np.mean(a[: n * size].reshape(n, size) ** 2, axis=1))


def percussion_error(harmonic, volume, decay):
    """The worst relative error of the percussion's rms, 480 frames at a time."""
    params = dict(
        NO_DRAWBARS, percussion=1.0, click=0.0, perc_harmonic=harmonic, perc_volume=volume
    )
    plan = {10: (60, 1.0), 90: (60, 0.0)}
    want, got = voice_render(params, plan, 170, {"perc_decay": decay})
    r = windows(want[256:])[4:22]
    g = windows(got[:-256])[4:22]
    assert r.min() > 20.0
    return float(np.max(np.abs(r - g) / r))


def percussion_worst():
    return max(
        percussion_error(1.0, 1.0, 1.0),
        percussion_error(0.0, 0.0, 1.0),
        percussion_error(1.0, 1.0, 0.0),
    )


def click_ratios(keys=40):
    """(down, up): the graph's click energy over the rack's, summed over ``keys`` keys."""
    params = dict(NO_DRAWBARS, percussion=0.0, click=10.0)
    plan = {}
    for i in range(keys):
        plan[10 + i * 20] = (60, 1.0)
        plan[20 + i * 20] = (60, 0.0)
    want, got = voice_render(params, plan, 20 * keys + 30)
    out = []
    for first in (10, 20):
        energy = []
        for series, offset in ((want, 256), (got, 0)):
            total = 0.0
            for i in range(keys):
                s = (first + i * 20) * BLOCK + offset
                total += float(np.sum(series[s : s + 250] ** 2))
            energy.append(total)
        out.append(energy[1] / energy[0])
    return tuple(out)


def within(value, bound):
    return bound[0] <= value <= bound[1]


# -- the engine -------------------------------------------------------------------------


def test_the_tonewheel3_compiles_every_module():
    inst = adapter.create(48000, voice="tonewheel3", output="pull")
    try:
        assert inst.engine == "graph" and inst.latency_samples == 0
        assert inst._compiled.rack_side == []
    finally:
        inst.deinit()
    rack = adapter.create(48000, voice="tonewheel3", engine="rack", output="pull")
    try:
        assert rack.engine == "rack" and rack.latency_samples == 512
    finally:
        rack.deinit()


def test_create_picks_the_graph():
    import audioinstruments

    inst = audioinstruments.create("tonewheel3", 48000)
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
    finally:
        inst.deinit()


# -- the parts against the rack -----------------------------------------------------------


def test_the_drawbars_play_the_rack_tone():
    for stats in (tone_stats_default(), tone_stats_all_drawbars()):
        assert stats[0] <= TONE_BOUND[0] and stats[1] <= TONE_BOUND[1], stats


@pytest.mark.parametrize("name", DRAWBAR_NAMES)
def test_each_drawbar_alone_plays_the_rack_tone(name):
    worst, rms = tone_stats_one_drawbar(name)
    assert worst <= TONE_BOUND[0] and rms <= TONE_BOUND[1], (name, worst, rms)


def test_the_percussion_sounds_the_rack_pitch():
    assert percussion_pitch_ok()


def test_the_scanner_vibrato_and_chorus_sweep_as_the_rack_does():
    assert vibrato_worst() <= VIBRATO_BOUND


def test_the_expression_pedal_swells_as_the_rack_does():
    assert expression_worst() <= EXPRESSION_BOUND


def test_the_rotary_speaker_turns_as_the_rack_does():
    assert rotary_worst() <= ROTARY_BOUND


def test_the_percussion_follows_the_rack_envelope():
    assert percussion_worst() <= PERCUSSION_BOUND


def test_the_key_click_carries_the_rack_energy():
    down, up = click_ratios()
    assert within(down, CLICK_BOUND) and within(up, CLICK_BOUND), (down, up)


def test_the_percussion_is_single_trigger_and_silent_when_off():
    params = dict(NO_DRAWBARS, percussion=1.0, click=0.0)
    plan = {10: (60, 1.0), 40: (64, 1.0), 120: (60, 0.0), 122: (64, 0.0)}
    want, got = voice_render(params, plan, 160)
    # the second key (legato) gets no new strike: no jump in the envelope at its block
    g = windows(got, 128)
    assert g[40] < 1.1 * g[39] and g[41] < 1.1 * g[40]
    off = dict(NO_DRAWBARS, percussion=0.0, click=0.0)
    want, got = voice_render(off, plan, 160)
    assert np.abs(want).max() == 0.0 and np.abs(got).max() == 0.0


# -- the whole instrument -----------------------------------------------------------------


def instrument_render(engine, patch, shift):
    inst = adapter.create(
        48000, voice="tonewheel3", engine=engine, output="pull", buffer_frames=BLOCK
    )
    try:
        inst.program_change(patch)
        events = [(10 * BLOCK + shift, 1, k, 100) for k in (48, 55, 64, 72)]
        events += [(120 * BLOCK + shift, 0, k, 0) for k in (48, 55, 64, 72)]
        out, k = [], 0
        for b in range(220):
            start = b * BLOCK
            while k < len(events) and events[k][0] < start + BLOCK:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).astype(np.float64).copy())
        return np.concatenate(out).reshape(-1, 2)
    finally:
        inst.deinit()


@pytest.mark.parametrize("patch", range(8))
def test_every_patch_plays_at_the_rack_level(patch):
    """A chord held: the level of each side within 10% of the rack's, and silent once let go."""
    rack = instrument_render("rack", patch, 0)
    graph = instrument_render("graph", patch, 512)
    held = slice(40 * BLOCK, 118 * BLOCK)
    for side in (0, 1):
        r = np.sqrt(np.mean(rack[held, side] ** 2))
        g = np.sqrt(np.mean(graph[held, side] ** 2))
        assert r > 100.0
        assert abs(g / r - 1.0) < 0.10, (patch, side, r, g)
    # the percussion and the click are gone and the rotary has rung out
    assert np.abs(graph[-20 * BLOCK :]).max() < 40.0


# -- planted faults ----------------------------------------------------------------------
#
# One value in each fragment, doubled after its own parameter method runs. The
# clean render must pass the check and the faulted one must fail it.


def _wrap(monkeypatch, cls, name, after):
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _double(get_node, index):
    def after(self):
        node = get_node(self)
        f = self._fragment
        f.set(node, index, 2.0 * f.get(node, index))

    return after


def _tone_ok():
    worst, rms = tone_stats_default()
    return worst <= TONE_BOUND[0] and rms <= TONE_BOUND[1]


def _vibrato_ok():
    return vibrato_worst() <= VIBRATO_BOUND


def _expression_ok():
    return expression_worst() <= EXPRESSION_BOUND


def _rotary_ok():
    return rotary_worst() <= ROTARY_BOUND


def _percussion_ok():
    return percussion_worst() <= PERCUSSION_BOUND


def _click_ok():
    down, up = click_ratios()
    return within(down, CLICK_BOUND) and within(up, CLICK_BOUND)


def _faults():
    return [
        (
            "the table's frequency",
            Tonewheel3Voice,
            "_graph_update",
            _double(lambda s: s._n_tone, ag.WAVETABLE_FREQUENCY),
            _tone_ok,
        ),
        (
            "the percussion sine's level",
            Tonewheel3Voice,
            "_graph_update",
            _double(lambda s: s._n_perc, ag.VCA_GAIN),
            _percussion_ok,
        ),
        (
            "the click's level",
            Tonewheel3Voice,
            "_graph_update",
            _double(lambda s: s._n_click, ag.VCA_GAIN),
            _click_ok,
        ),
        (
            "the percussion decay",
            Tonewheel3Percussion,
            "_graph_params",
            _double(lambda s: s._n_env, ag.DECAY_DECAY),
            _percussion_ok,
        ),
        (
            "the scanner's depth",
            Tonewheel3Vibrato,
            "_graph_params",
            _double(lambda s: s._n_line, ag.DELAY_WOW_DEPTH_MS),
            _vibrato_ok,
        ),
        (
            "the swell",
            Tonewheel3Expression,
            "_graph_params",
            _double(lambda s: s._n_sum, 0),
            _expression_ok,
        ),
        (
            "the rotary's drive",
            RotarySpeaker,
            "_graph_params",
            _double(lambda s: s._n_rotary, ag.ROTARY_DRIVE),
            _rotary_ok,
        ),
    ]


FAULT_IDS = ["tone", "percussion_level", "click", "percussion_decay", "vibrato", "swell", "rotary"]


@pytest.mark.parametrize("which", range(len(FAULT_IDS)), ids=FAULT_IDS)
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, which):
    name, cls, method, after, ok = _faults()[which]
    assert ok(), f"clean {name}"
    _wrap(monkeypatch, cls, method, _double_after(after))
    assert not ok(), f"fault not heard: {name}"


def _double_after(after):
    return after
