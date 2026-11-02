# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Hold a compiled voice to one rule: a value written only when it moved still arrives.

    micropython tools/block_phrase.py poly106
    python tools/block_phrase.py poly106 pump

The ``before_run`` hooks of the MIDI module, the mix and some voices compare what they would
write with what they last wrote, and skip the writing. A comparison that misses something
leaves a stale value in a control, which is a wrong note and no error. So this plays one phrase
twice, moving everything those hooks carry: a bend and its range, the wheels and pedals,
pressure, a glide, a retriggered key, steals, a patch change, a recompile, the pool switched
to mono and back, the level, a reset, a step of the rack, and the voice's own knobs. In the
second playing the hooks' memory is wiped before every block, so they write everything the long
way. The two must come out the same bytes.
``check`` also reads the controls after the hooks and works out from the module's state what
each should hold, which catches what both playings would get wrong alike. A run prints
``ok <voice> <mode> <sha256>``, or raises.
"""

import hashlib
import sys

# No os.path on MicroPython: the script's own path says where lib/ is.
_parts = (sys.argv[0] if sys.argv and sys.argv[0] else "tools/block_phrase.py").split("/")
ROOT = "/".join(_parts[:-2]) or "."
if ROOT + "/lib" not in sys.path:
    sys.path.insert(0, ROOT + "/lib")

import audiocore  # noqa: E402
import audioinstruments._rack.adapter as adapter  # noqa: E402

SAMPLE_RATE = 48000
BUFFER = 256
BLOCK = 128
BUFFERS = 240
CHORD = (48, 55, 60, 64, 67, 72)

#: The knobs a voice's own hook remembers, moved under the chord: (buffer, name, value).
KNOBS = {
    "polya6": (
        (3, "post_f1_lp", 100),  # so Filter 1 is heard
        (3, "f1_freq", 500.0),
        (4, "osc_lfo1", 20),
        (4, "lfo1_trigger", "voice"),
        (4, "lfo1_delay", 0.1),
        (5, "f1_lfo2", 60),
        (6, "f1_sh", 40),
        (6, "sh_rate", 40.0),
        (7, "lfo2_delay", 0.1),
        (12, "lfo1_rate", 3.0),
        (15, "f1_res", 70),
        (17, "sh_rate", 15.0),
        (19, "f1_sh", 0),
        (21, "f1_lfo2", 0),
        (22, "f1_env2", 40),
        (23, "filter_bypass", True),
        (25, "filter_bypass", False),
        (27, "f1_env2", 0),
        (29, "f1_keytrack", 30),
        (33, "f1_freq", 1000.0),
        (36, "f1_keytrack", 0),
        (36, "osc_lfo1", 0),
        (37, "slop", 50),
        (41, "osc1_semi", 7),
        (42, "osc2_cents", 13.0),
        (42, "mix_sub1", 30),
        (43, "osc1_bend", False),
        (45, "slop", 0),
        (47, "slop", 10),
        (49, "osc1_tri", True),
        (50, "osc1_sine", True),
        (51, "osc2_square", True),
        (53, "osc1_square", True),
        (53, "osc1_pwm", 30),
        (60, "osc1_pwm", 0),
    ),
    "west_coast_synth": (
        (3, "func1_rise", 0.02),
        (3, "func1_fall", 0.08),
        (3, "func2_fall", 0.15),
        (12, "fm_index", 0.8),
        (33, "func1_fall", 0.5),
        (40, "func2_rise", 0.3),
    ),
    "state_variable_mono": (
        (3, "env1_decay", 0.05),
        (6, "env1_sustain", 0.8),
        (12, "vcf_cutoff", 0.7),
        (15, "vcf_env1_depth", 0.2),
        (22, "vcf_lfo_depth", 0.4),
        (27, "lfo_rate", 9.0),
        (32, "vcf_lfo_depth", 0.0),
        (41, "env1_sustain", 0.0),
        (47, "vcf_cutoff", 0.3),
    ),
    "poly80": (
        (3, "ch1_init_bril", 0.8),
        (3, "ch1_init_level", 0.5),
        (3, "touch_bend", 0.5),
        (3, "ring_mod", 0.6),
        (3, "ring_depth", 0.5),
        (3, "ring_decay", 0.2),
        (5, "trem", "chorus"),
        (6, "sub_vcf", 0.5),
        (8, "slop", 0.5),
        (12, "sub_vcf", 0.0),
        (15, "detune", 0.3),
        (17, "sub_vca", 0.4),
        (22, "sub_vca", 0.0),
        (25, "wheel_wah", 0.5),
        (27, "touch_speed", 0.7),
        (32, "resonance", 0.5),
        (33, "ch1_feet", "4"),
        (36, "sub_wave", "square"),
        (37, "ring_speed", 0.8),
        (41, "sustain_mode", "II"),
        (42, "trem", "off"),
        (43, "ch2_lpf", 0.2),
        (45, "slop", 0.0),
        (47, "slop", 0.2),
        (49, "ring_mod", 0.0),
    ),
    "poly8": (
        (3, "portamento", 0.4),
        (3, "env1_key_follow", 1.0),
        (15, "env1_key_follow", 0.0),
        (17, "env2_key_follow", 1.0),
        (22, "portamento", 0.0),
        (25, "slop", 0.0),
        (27, "slop", 5.0),
        (30, "vco1_range", 1),
        (32, "vco2_fine", 0.3),
        (36, "hpf_cutoff", 0.5),
        (41, "hpf_cutoff", 0.0),
        (43, "portamento", 0.3),
        (47, "env2_key_follow", 0.0),
        (49, "portamento", 0.0),
    ),
}


def _param(inst, name, value):
    if name in inst._midi.params:
        inst._midi.set_param(name, value)


def _mono(inst, on):
    if hasattr(inst._midi, "mono"):
        inst._midi.mono = on


def _recompile(inst, carry):
    compiled = inst._compiled
    if not compiled.pumped:
        groups = [voice.members for voice in inst._pool.voices]
        inst._compiled = compiled.recompile(groups=groups, carry=carry)


def _rack_step(inst):
    """A step of the rack between graph blocks, which moves what both paths share."""
    if not inst._compiled.pumped:
        inst.rack.step()


def _level(inst, value):
    inst._pool.mix.set_param("level", value)


def _knob(inst, name, value):
    """A knob on every voice that has it, as a patch's voice parameter is set."""
    for f in inst._compiled.fragments:
        if name in f.module.params:
            f.module.set_param(name, value)


def phrase(inst, voice=None):
    """{buffer: [(function, args)]}."""
    events = {}

    def at(buffer, fn, *args):
        events.setdefault(buffer, []).append((fn, args))

    for note in CHORD:
        at(2, inst.note_on, note, 100)
    for buffer, name, value in KNOBS.get(voice, ()):
        at(buffer, _knob, inst, name, value)
    at(10, inst.pitch_bend, 12000)
    at(14, inst.pitch_bend, 8192)
    at(16, inst.control_change, 1, 90)
    at(18, inst.control_change, 1, 0)
    at(20, inst.channel_pressure, 80)
    at(24, inst.channel_pressure, 0)
    at(26, inst.poly_pressure, 60, 100)
    at(28, inst.channel_pressure, 40)
    at(29, inst.poly_pressure, 60, 0)
    at(30, inst.control_change, 11, 60)
    at(31, inst.control_change, 4, 40)
    at(33, _rack_step, inst)  # with a chord held
    at(34, inst.note_on, 60, 60)  # a held key again, softer
    at(35, inst.note_on, 67, 127, 0.3)
    at(38, inst.control_change, 64, 127)
    at(39, inst.note_off, 48)
    at(40, inst.note_off, 55)
    at(44, inst.control_change, 64, 0)
    at(46, inst.pitch_bend, 3000)
    at(48, _param, inst, "bend_range", 12.0)  # the same wheel, a new range
    at(52, _param, inst, "bend_range", 2.0)
    at(54, inst.pitch_bend, 8192)
    at(56, _param, inst, "glide", 0.2)
    at(57, inst.note_on, 50, 90)
    at(58, inst.pitch_bend, 5000)
    at(62, inst.note_off, 50)
    at(63, _param, inst, "glide", 0.0)
    at(64, inst.pitch_bend, 8192)
    at(66, inst.program_change, 1)  # a patch change under held notes
    at(70, inst.set_macro, 0, 100)
    for i, note in enumerate((41, 43, 45, 47, 49, 51, 53, 57, 59)):
        at(72 + i, inst.note_on, note, 70 + i)  # steals, on the smaller pools
    at(84, inst.pitch_bend, 10000)
    at(86, _recompile, inst, True)  # state carried, under a bend
    at(88, inst.pitch_bend, 8192)
    at(90, _recompile, inst, False)  # and starting fresh
    at(91, inst.note_on, 62, 80)
    at(91, _rack_step, inst)  # the rack sees the gate first
    at(100, _rack_step, inst)  # and at rest
    at(94, inst.all_notes_off)
    at(120, inst.program_change, 2)
    at(124, inst.note_on, 60, 110)
    at(125, inst.note_on, 72, 90)
    at(128, inst.pitch_bend, 12000)  # a bend the fading voices take as the mode changes
    at(128, _mono, inst, True)
    at(129, inst.note_on, 64, 90)
    at(130, inst.note_on, 67, 90)
    at(132, inst.pitch_bend, 11000)
    at(134, inst.note_off, 67)
    at(136, inst.channel_pressure, 60)
    at(138, inst.pitch_bend, 8192)
    at(140, inst.channel_pressure, 0)
    at(142, _mono, inst, False)
    at(146, inst.note_on, 69, 100)
    at(150, inst.pitch_bend, 6000)
    at(152, inst.all_notes_off)
    at(170, _level, inst, 0.5)
    at(172, inst.note_on, 60, 100)
    at(178, _level, inst, 1.0)
    at(180, inst.reset)
    at(182, inst.note_on, 62, 100)
    at(184, inst.pitch_bend, 9000)
    at(190, inst.note_off, 62)
    return events


def _wipe(compiled):
    """A hook that makes every other hook behind it write the long way."""
    fragments = compiled.fragments

    def wipe():
        for f in fragments:
            module = f.module
            if hasattr(module, "_w_pitch"):  # the MIDI module
                module._forget_written()
                module._forget_jacks()
                module._g_bend = None
            if hasattr(module, "_seen_level"):  # the mix
                module._seen_level = None
            name = type(module).__name__
            if name == "StringEnsembleVoice":
                module._g_gain_set = None
            elif name == "PolyA6Voice":
                module._k_moved = True
                module._dirty = True
                module._seen = None
                module._lfo_rate[:] = (None, None)
                module._lfo_level[:] = (None, None)
                module._f1_hz = None
            elif name == "Poly8Voice":
                module._pending.update(module._FLUSH)
                module._step_blocks = None
            elif name == "WestCoastSynth":
                module._scanned = module._still = None
            elif name == "StateVariableMono":
                module._scanned = module._still_state = module._set_cv = None
            elif name == "Poly80Voice":
                module._moved = True
                module._pulse_scanned = module._step_blocks = None
            elif name == "Poly80Output":
                module._moved = True
                module._scanned = None
            elif name == "Poly80Mod":
                module._moved = module._keys_moved = True

    return wipe


def _close(a, b):
    return a == b or abs(a - b) < 1e-9


def _check_controls(midi):
    """What a control holds, against what the module's state says it should."""
    pb = midi._pitch_bend
    bend = pb * (midi.params["bend_range"] / 12.0) * 0.1
    cur = midi._current_pitch
    assert midi._c_line_note.value == cur, "line note"
    assert _close(midi._c_line_pitch.value, cur + bend), "line pitch"
    assert midi._c_note_hi.value == midi._target_hi, "note hi"
    assert _close(midi._c_pitch_hi.value, midi._target_hi + bend), "pitch hi"
    assert midi._c_any_gate.value == (1.0 if midi._gate_active else 0.0), "gate"
    assert midi._c_any_vel.value == midi._velocity, "velocity"
    assert midi._c_any_press.value == midi._pressure(), "pressure"
    assert midi._c_legato.value == (1.0 if midi._legato else 0.0), "legato"
    assert midi._c_bend.value == pb * 0.5, "bend"
    assert midi._c_mod.value == midi._mod_wheel, "mod"
    assert midi._c_pedal.value == (1.0 if midi._sustain_pedal else 0.0), "pedal"
    assert midi._c_expr.value == midi._expr, "expression"
    assert midi._c_foot.value == midi._foot, "foot"
    assert _close(midi.press_out.buffer[0], midi._pressure()), "press jack"
    assert _close(midi.mod_out.buffer[0], midi._mod_wheel), "mod jack"
    assert _close(midi.expr_out.buffer[0], midi._expr), "expr jack"
    assert _close(midi.foot_out.buffer[0], midi._foot), "foot jack"
    if midi.mono:
        return
    for i in range(midi.max_voices):
        note = midi._v_pitch[i]
        assert midi._c_note[i].value == note, "voice note"
        assert _close(midi._c_pitch[i].value, note + bend), "voice pitch"
        assert midi._c_gate[i].value == (1.0 if midi._v_gate[i] else 0.0), "voice gate"
        assert midi._c_vel[i].value == midi._v_vel[i], "voice velocity"
        press = midi._v_press[i]
        if midi._chan_press > press:
            press = midi._chan_press
        assert midi._c_press[i].value == press, "voice pressure"


def _install(inst, wipe, check, done):
    """Put the wipe ahead of the hooks and the check behind them, once per compiled graph."""
    compiled = inst._compiled
    if compiled in done:
        return
    done.append(compiled)
    midi = inst._midi
    if wipe:
        compiled.before.insert(0, _wipe(compiled))
    if check and hasattr(midi, "_c_pitch"):
        compiled.before.append(lambda: _check_controls(midi))


def _loud(raw):
    """True when a sample's high byte says more than silence."""
    return any(raw[i] not in (0, 255) for i in range(1, len(raw), 32))


def render(voice, mode="pull", wipe=False, check=False):
    """The phrase on ``voice``; returns the sha256 of every byte, as hex digits."""
    pulled = mode == "pull"
    inst = adapter.create(
        SAMPLE_RATE,
        voice=voice,
        engine="graph",
        output="pull" if pulled else "graph",
        buffer_frames=BUFFER,
    )
    done = []
    h = hashlib.sha256()
    loud = False
    try:
        events = phrase(inst, voice)
        for b in range(BUFFERS):
            for fn, args in events.get(b, ()):
                fn(*args)
            _install(inst, wipe, check, done)
            if pulled:
                raw = inst._pull()
                h.update(raw)
                loud = loud or _loud(raw)
            else:
                for _ in range(BUFFER // BLOCK):
                    inst.fill()
                    raw = bytes(audiocore.get_buffer(inst.output)[1])
                    h.update(raw)
                    loud = loud or _loud(raw)
    finally:
        inst.deinit()
    assert loud, "%s played nothing" % voice
    return "".join("%02x" % x for x in h.digest())


def main(argv):
    voice = argv[0]
    mode = argv[1] if len(argv) > 1 else "pull"
    fast = render(voice, mode, check=True)
    slow = render(voice, mode, wipe=True)
    if fast != slow:
        raise AssertionError("%s %s: a stale value (%s, long way %s)" % (voice, mode, fast, slow))
    print("ok %s %s %s" % (voice, mode, fast))


if __name__ == "__main__":
    main(sys.argv[1:])
