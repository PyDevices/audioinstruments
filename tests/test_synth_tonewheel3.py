# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3: the instrument plays, and each control does what its name says."""

import math

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Rack
from audioinstruments._rack.core.signal import create_buffer
from audioinstruments._rack.dsp.organ import (
    DRAWBAR_LEVELS,
    DrawbarToneCore,
    ScannerVibratoCore,
    SwellPedalCore,
    tonewheel_harmonics,
)
from audioinstruments._rack.dsp.rotary import RotarySpeakerCore
from audioinstruments._rack.instruments import tonewheel3
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.tonewheel3.percussion import Tonewheel3Percussion
from audioinstruments._rack.modules.tonewheel3.voice import DRAWBARS, Tonewheel3Voice

SR = 48000
CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(SR, voice="tonewheel3", output="pull", engine="rack", **options)
    inst.program_change(patch)
    return inst


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=60, velocity=100):
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def set_control(inst, name, value):
    inst.patch.set_control(inst.voice_pool, name, value)


def plain(patch=5, **controls):
    """A patch with the effects out of the way: no vibrato, rotor stopped, clean amplifier."""
    inst = make(patch)
    for name, value in (("vibrato", False), ("rotary", "stop"), ("drive", 0.0)):
        set_control(inst, name, value)
    for name, value in controls.items():
        set_control(inst, name, value)
    return inst


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def amp_at(x, f):
    t = np.arange(len(x)) / SR
    return abs(np.sum(x * np.hanning(len(x)) * np.exp(-2j * np.pi * f * t))) * 4 / len(x)


def peak_freq(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(freqs[int(np.argmax(mag))])


def inst_cents(x, f0):
    """Instantaneous pitch of ``x`` against ``f0``, in cents: the phase of the analytic
    signal of the band within 20 % of ``f0`` (an FFT Hilbert transform)."""
    n = len(x)
    freqs = np.fft.fftfreq(n, 1.0 / SR)
    h = np.where((freqs > 0.8 * f0) & (freqs < 1.2 * f0), 2.0, 0.0)
    phase = np.unwrap(np.angle(np.fft.ifft(np.fft.fft(x) * h)))
    f = np.diff(phase) * SR / (2 * np.pi)
    return 1200 * np.log2(np.clip(f[500:-500], 1, None) / f0)


def swing(cents, low=1, high=99):
    return float(np.percentile(cents, high) - np.percentile(cents, low))


def hz(note):
    return 440.0 * 2 ** ((note - 69) / 12)


# --- one voice on a small rack --------------------------------------------------------------


def voice_rack(bs=64, **params):
    rack = Rack(block_size=bs)
    midi = rack.add_module(MidiCVModule("midi", block_size=bs))
    perc = rack.add_module(Tonewheel3Percussion("perc", block_size=bs))
    v = rack.add_module(Tonewheel3Voice("voice", block_size=bs))
    rack.connect(midi.gate_out, perc.gate_in)
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(perc.env_out, v.perc_env_in)
    for name, value in params.items():
        for m in (v, perc):
            if name in m.params:
                m.set_param(name, value)
    return rack, midi, perc, v


def run(rack, v, blocks, perc=None):
    out, env = [], []
    for _ in range(blocks):
        rack.step()
        out.append(np.array(v.audio_out.buffer, dtype=float))
        if perc is not None:
            env.append(np.array(perc.env_out.buffer, dtype=float))
    o = np.concatenate(out)
    return (o, np.concatenate(env)) if perc is not None else o


NO_TONE = {"db16": 0.0, "db5_13": 0.0, "db8": 0.0}


# --- the instrument's shape -----------------------------------------------------------------


def test_sixteen_voices_eight_patches_and_latency():
    inst = make()
    assert inst.voices == 16 and inst.voice_pool.max_voice_count == 16
    assert len(inst.patches) == 8 and inst.patches[0][0] == "Full Gospel"
    assert inst.latency_samples == 512
    assert len(inst.macro_labels) == 9
    inst.voices = 8
    assert inst.voices == 8
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "tonewheel3" in adapter.ALL


def test_a_note_arrives_as_late_as_latency_says():
    inst = plain(click=0.0)
    inst.note_on(72, 100)
    x = np.abs(pull(inst, 8)[:, 0])
    first = int(np.nonzero(x > 30)[0][0])
    assert 500 <= first <= 560, "the note began at frame %d, not about 512" % first


@pytest.mark.parametrize("patch", range(8), ids=lambda i: tonewheel3.PRESETS[i][0])
def test_every_patch_plays_a_chord_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (48, 55, 60, 64, 67), buffers=80, velocity=100)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(1)  # Jazz Trio: db5_13 is 8, percussion on, vibrato on
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["db16"] == 8.0
    assert voice.params["db5_13"] == 8.0
    assert voice.params["db4"] == 0.0
    assert inst.patch.percussion.params["percussion"] == 1.0
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    assert abs(inst.patch.rotary.params["drive"] - 1.0) < 0.05

    inst.program_change(5)  # Flutes: 8' only, percussion off, V2, slow, drive 0
    assert voice.params["db16"] == 0.0 and voice.params["db8"] == 8.0
    assert voice.params["db5_13"] == 0.0
    assert inst.patch.percussion.params["percussion"] == 0.0
    assert inst.patch.vibrato.params["vibrato_mode"] == 1.0  # V2
    assert inst.patch.rotary.params["drive"] == 0.0


# --- drawbars and wheels --------------------------------------------------------------------


def test_drawbar_steps_are_about_three_db():
    assert DRAWBAR_LEVELS[0] == 0.0 and DRAWBAR_LEVELS[8] == 1.0
    for i in range(2, 9):
        step = 20 * math.log10(DRAWBAR_LEVELS[i] / DRAWBAR_LEVELS[i - 1])
        assert 2.0 < step < 4.0


@pytest.mark.parametrize("footage", range(9), ids=lambda i: DRAWBARS[i])
def test_each_footage_sounds_its_harmonic(footage):
    """Each drawbar alone plays its harmonic of the 16' pitch, on a key with no foldback."""
    core = DrawbarToneCore(SR, 128)
    levels = [0.0] * 9
    levels[footage] = 1.0
    core.set_levels(levels, tonewheel_harmonics(60, [0] * 9))
    out = create_buffer(128)
    x = []
    for _ in range(200):
        core.render(hz(60), 1.0, out)
        x.append(np.array(out))
    x = np.concatenate(x)[8192:]
    want = hz(60) * 0.5 * (1, 3, 2, 4, 6, 8, 10, 12, 16)[footage]
    assert abs(peak_freq(x) - want) < 0.01 * want + 6


def test_drawbars_change_harmonic_content():
    x16 = play(plain(db16=8, db8=0), (60,), buffers=60)[6000:, 0]
    x8 = play(plain(db16=0, db8=8), (60,), buffers=60)[6000:, 0]
    assert band(x16, 110, 150) > 10 * band(x8, 110, 150)
    assert band(x8, 240, 280) > 5 * band(x16, 240, 280)


def test_sub_third_sits_under_the_unison():
    """The 5 1/3' wheels are a few dB under the 8' at the same drawbar."""
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0, db16=0.0, db8=8.0, db5_13=8.0)
    midi.note_on(60, 100)
    x = run(rack, v, 200)[4096:]
    ratio = 20 * math.log10(amp_at(x, 1.5 * hz(60)) / amp_at(x, hz(60)))
    assert -10.0 < ratio < -6.0


def test_foldback_at_both_ends():
    # the 1' stops at the top wheel and plays an octave lower above it
    assert tonewheel_harmonics(72, [0] * 9)[8] == 16
    assert tonewheel_harmonics(84, [0] * 9)[8] == 8
    assert tonewheel_harmonics(96, [0] * 9)[8] == 4  # twice, to the top C's folded 2'
    assert tonewheel_harmonics(84, [0] * 9)[5] == 8  # the 2' still has its wheel
    assert tonewheel_harmonics(96, [0] * 9)[5] == 4  # and on the top C it has none
    # the 16' folds up an octave on the bottom twelve keys
    assert tonewheel_harmonics(47, [0] * 9)[0] == 2
    assert tonewheel_harmonics(48, [0] * 9)[0] == 1


def test_foldback_is_heard():
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0, db1=8.0, **NO_TONE)
    midi.note_on(90, 100)
    x = run(rack, v, 200)[4096:]
    assert abs(peak_freq(x) - 4 * hz(90)) < 20  # the 2' wheel, an octave under the 1'


def test_velocity_changes_nothing():
    levels = []
    for velocity in (20, 64, 127):
        rack, midi, perc, v = voice_rack(click=0.0)
        midi.note_on(60, velocity)
        levels.append(rms(run(rack, v, 200)))
    assert max(levels) - min(levels) < 1e-6


# --- the note, start and end ----------------------------------------------------------------


@pytest.mark.parametrize("offset", range(4))
def test_a_note_begins_on_its_own_pitch(offset):
    """A voice that played a low note starts a high one without a burst of the old pitch,
    whichever block of the bridge's chunk the key lands in."""
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0, db16=0.0, db5_13=0.0)
    midi.note_on(48, 100)
    run(rack, v, 40)
    midi.note_off(48)
    run(rack, v, 40 + offset)
    midi.note_on(72, 100)
    x = run(rack, v, 12)
    onset = int(np.nonzero(np.abs(x) > 1e-4)[0][0])
    seg = x[onset : onset + 512]
    assert amp_at(seg, hz(48)) < 0.1 * amp_at(seg, hz(72))


def test_contacts_ramp_in_a_few_ms():
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0)
    midi.note_on(60, 100)
    x = np.abs(run(rack, v, 40))
    onset = int(np.nonzero(x > 1e-4)[0][0])
    env = np.maximum.accumulate(x[onset:])
    rise = int(np.nonzero(env > 0.9 * env[2000])[0][0])
    assert rise < 480  # under 10 ms


@pytest.mark.parametrize("held", (37, 38, 39, 40))
def test_key_up_and_key_down_do_not_step(held):
    """The contacts ramp: no sample jumps further than the held tone's own steepest step."""
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0, db16=0.0, db5_13=0.0)
    midi.note_on(72, 100)
    x = run(rack, v, held)
    steady = np.max(np.abs(np.diff(x[-1024:])))
    midi.note_off(72)
    x = np.concatenate([x, run(rack, v, 20)])
    assert np.max(np.abs(np.diff(x))) < 1.5 * steady


def test_key_click_is_quieter_at_key_up():
    rack, midi, perc, v = voice_rack(percussion=0.0, click=10.0, **NO_TONE)
    midi.note_on(60, 100)
    down = np.max(np.abs(run(rack, v, 40)))
    midi.note_off(60)
    up = np.max(np.abs(run(rack, v, 40)))
    assert down > 0.005
    assert up < 0.7 * down
    rack, midi, perc, v = voice_rack(percussion=0.0, click=0.0, **NO_TONE)
    midi.note_on(60, 100)
    assert np.max(np.abs(run(rack, v, 40))) < 1e-6


# --- percussion -----------------------------------------------------------------------------


def test_percussion_single_trigger():
    rack, midi, perc, v = voice_rack()
    midi.note_on(60, 100)
    _, e1 = run(rack, v, 40, perc)
    assert e1.max() > 0.9
    midi.note_on(64, 100)  # legato: the first key is still down
    _, e2 = run(rack, v, 40, perc)
    assert e2.max() <= e1[-1] + 1e-6, "a legato key retriggered the percussion"
    midi.note_off(60)
    midi.note_off(64)
    run(rack, v, 20, perc)
    midi.note_on(67, 100)  # detached: it fires again
    _, e3 = run(rack, v, 40, perc)
    assert e3.max() > 0.9


def test_percussion_single_trigger_through_the_pool():
    inst = plain(click=0.0, percussion=True)
    env = inst.patch.percussion.env_out.buffer

    def struck(*notes):
        for note in notes:
            inst.note_on(note, 100)
        pull(inst, 1)
        return float(np.max(env))

    assert struck(60) > 0.9
    pull(inst, 150)  # fast percussion has died away
    assert struck(67) < 0.01, "a legato key retriggered the percussion"
    inst.note_off(60)
    inst.note_off(67)
    pull(inst, 20)
    assert struck(64) > 0.9, "a detached key did not fire the percussion"


@pytest.mark.parametrize("fast,low,high", ((1.0, 0.3, 1.2), (0.0, 1.2, 4.0)))
def test_percussion_decay_time(fast, low, high):
    rack, midi, perc, v = voice_rack(perc_decay=fast)
    midi.note_on(60, 100)
    _, env = run(rack, v, int(5.0 * SR / 64), perc)
    to_60db = np.nonzero(env < 0.001)[0][0] / SR
    assert low < to_60db < high


def test_percussion_volume_and_the_three_db_drop():
    def measure(**params):
        rack, midi, perc, v = voice_rack(click=0.0, **params)
        midi.note_on(60, 100)
        o = run(rack, v, 300)
        return amp_at(o[-8192:], hz(60)), float(np.max(np.abs(o[:4096])))

    full_footage, _ = measure(percussion=0.0)  # the 8' at drawbar 8
    normal, _ = measure(percussion=1.0, perc_volume=1.0)
    soft, _ = measure(percussion=1.0, perc_volume=0.0)
    assert abs(20 * math.log10(normal / full_footage) + 3.0) < 0.5
    assert abs(20 * math.log10(soft / full_footage)) < 0.5

    _, pk_normal = measure(percussion=1.0, perc_volume=1.0, **NO_TONE)
    _, pk_soft = measure(percussion=1.0, perc_volume=0.0, **NO_TONE)
    assert 1.4 * full_footage < pk_normal < 2.8 * full_footage
    assert abs(20 * math.log10(pk_normal / pk_soft) - 6.0) < 1.0


def test_percussion_harmonic_and_its_foldback():
    for third, ratio in ((1.0, 3), (0.0, 2)):
        rack, midi, perc, v = voice_rack(click=0.0, perc_harmonic=third, perc_decay=0.0, **NO_TONE)
        midi.note_on(60, 100)
        x = run(rack, v, 100)[1024:]
        assert abs(peak_freq(x) - ratio * hz(60)) < 15
    # at the top the third harmonic folds as the 2 2/3' does
    rack, midi, perc, v = voice_rack(click=0.0, perc_decay=0.0, **NO_TONE)
    midi.note_on(96, 100)
    x = run(rack, v, 100)[1024:]
    assert peak_freq(x) < 2 * hz(96)


def test_percussion_mutes_1_foot_drawbar():
    whistle_plain = make(7)  # Whistle: 16' and 1', percussion off
    whistle_perc = make(7)
    set_control(whistle_perc, "percussion", True)
    x_plain = play(whistle_plain, (60,), buffers=60)[6000:, 0]
    x_perc = play(whistle_perc, (60,), buffers=60)[6000:, 0]
    assert band(x_perc, 2000, 3000) < 0.02 * band(x_plain, 2000, 3000)


# --- vibrato and chorus ---------------------------------------------------------------------


def scanner(depth, chorus, f0=1000.0):
    core = ScannerVibratoCore(SR, 128)
    core.set(True, depth, chorus)
    src, dst = create_buffer(128), create_buffer(128)
    out = []
    for b in range(400):
        t = (np.arange(128) + b * 128) / SR
        src[:] = 0.5 * np.sin(2 * np.pi * f0 * t)
        core.render(src, dst)
        out.append(np.array(dst))
    return np.concatenate(out)[20000:]


@pytest.mark.parametrize("depth,low,high", ((1, 20, 50), (2, 45, 85), (3, 80, 130)))
def test_vibrato_depths(depth, low, high):
    x = scanner(depth, False)
    s = swing(inst_cents(x, 1000.0))
    assert low < s < high, "V%d swings %.0f cents" % (depth, s)
    assert abs(rms(x) - 0.5 / math.sqrt(2)) < 0.01  # vibrato is the swept signal alone


def test_chorus_mixes_the_dry_signal_in():
    # at 100 Hz the sweep is far shorter than a cycle: dry plus swept keeps the level and
    # swings much less than the vibrato alone
    v3 = scanner(3, False, f0=100.0)
    c3 = scanner(3, True, f0=100.0)
    assert swing(inst_cents(c3, 100.0)) < 0.7 * swing(inst_cents(v3, 100.0))
    assert abs(rms(c3) - rms(v3)) < 0.2 * rms(v3)


def test_vibrato_switch_reaches_the_sound():
    xd = play(plain(click=0.0), (72,), buffers=80)[10000:, 0]
    xw = play(plain(click=0.0, vibrato=True, vibrato_mode="V3"), (72,), buffers=80)[10000:, 0]
    assert swing(inst_cents(xd, hz(72)), 5, 95) < 20
    assert swing(inst_cents(xw, hz(72)), 5, 95) > 60


# --- rotary speaker -------------------------------------------------------------------------


def test_rotary_speaker_widens_stereo_field():
    x = play(make(0), (60, 64, 67), buffers=80)[8000:]  # Full Gospel: fast
    corr = np.corrcoef(x[:, 0], x[:, 1])[0, 1]
    assert corr < 0.95, "rotary speaker should provide stereo separation, got %.3f" % corr


def test_rotors_reach_fast_at_their_own_pace():
    core = RotarySpeakerCore(SR, 128)
    src, left, right = create_buffer(128), create_buffer(128), create_buffer(128)
    core.set_mode("slow")
    for _ in range(2000):
        core.render(src, left, right)
    core.set_mode("fast")
    horn_t = drum_t = None
    for b in range(1, 3000):
        core.render(src, left, right)
        t = b * 128 / SR
        if horn_t is None and core.horn_speed > 0.8 + 0.9 * (6.8 - 0.8):
            horn_t = t
        if drum_t is None and core.drum_speed > 0.7 + 0.9 * (5.9 - 0.7):
            drum_t = t
    assert 0.4 < horn_t < 1.5, horn_t
    assert 2.0 < drum_t < 6.0, drum_t


def test_horn_has_doppler_but_not_a_warble():
    core = RotarySpeakerCore(SR, 128)
    core.set_mode("fast")
    core.horn_speed, core.drum_speed = 6.8, 5.9
    src, left, right = create_buffer(128), create_buffer(128), create_buffer(128)
    out = []
    for b in range(400):
        t = (np.arange(128) + b * 128) / SR
        src[:] = 0.3 * np.sin(2 * np.pi * 3000.0 * t)
        core.render(src, left, right, drive=0.0)
        out.append(np.array(left))
    s = swing(inst_cents(np.concatenate(out)[8000:], 3000.0), 5, 95)
    assert 20 < s < 120, s


def test_drive_is_clean_at_zero_and_dirty_when_up():
    def third(drive):
        core = RotarySpeakerCore(SR, 128)
        core.set_mode("stop")
        src, left, right = create_buffer(128), create_buffer(128), create_buffer(128)
        out = []
        for b in range(200):
            t = (np.arange(128) + b * 128) / SR
            src[:] = 0.5 * np.sin(2 * np.pi * 200.0 * t)
            core.render(src, left, right, drive=drive)
            out.append(np.array(left))
        x = np.concatenate(out)[4096:]
        return 20 * math.log10(amp_at(x, 600.0) / amp_at(x, 200.0))

    assert third(0.0) < -45
    assert third(7.0) > -30


# --- expression -----------------------------------------------------------------------------


def test_expression_lowers_the_level_and_a_little_bass():
    loud = plain(click=0.0, expression=10.0)
    quiet = plain(click=0.0, expression=4.0)
    xl = play(loud, (60,), buffers=60)[6000:, 0]
    xq = play(quiet, (60,), buffers=60)[6000:, 0]
    assert rms(xq) < 0.3 * rms(xl)

    def through(pedal):
        core = SwellPedalCore(SR, 128)
        src, dst = create_buffer(128), create_buffer(128)
        out = []
        for b in range(200):
            t = (np.arange(128) + b * 128) / SR
            src[:] = 0.2 * np.sin(2 * np.pi * 65.0 * t) + 0.2 * np.sin(2 * np.pi * 1000.0 * t)
            core.render(src, dst, pedal)
            out.append(np.array(dst))
        x = np.concatenate(out)[4096:]
        return amp_at(x, 65.0), amp_at(x, 1000.0)

    lo_open, hi_open = through(1.0)
    lo_closed, hi_closed = through(0.4)
    assert abs(hi_open - 0.2) < 0.01 and abs(lo_open - 0.2) < 0.01  # open is a wire
    assert lo_closed / hi_closed < 0.9


# --- the pool -------------------------------------------------------------------------------


def test_sixteen_voice_stealing_is_clean():
    inst = make()
    for i in range(16):
        inst.note_on(36 + i * 2, 100)
    pull(inst, 20)
    inst.note_on(70, 100)
    x = pull(inst, 20)
    assert np.all(np.isfinite(x))
    assert np.max(np.abs(x)) < CLIP
    assert inst.voice_pool.stolen >= 1


def test_steal_does_not_click():
    """Stealing a voice adds no sample-to-sample jump bigger than the held chord's own."""
    inst = plain(click=0.0, percussion=False)
    for i in range(16):
        inst.note_on(48 + i, 100)
    held = pull(inst, 40)[:, 0]
    inst.note_on(80, 100)
    x = pull(inst, 20)[:, 0]
    assert np.max(np.abs(np.diff(x))) < 1.5 * np.max(np.abs(np.diff(held))) + 200


def test_sustain_pedal_holds_notes():
    inst = make()
    inst.control_change(64, 127)
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)
    x = pull(inst, 40)
    assert rms(x) > 300
    inst.control_change(64, 0)
    pull(inst, 50)
    x_off = pull(inst, 20)
    assert rms(x_off) < 50.0
