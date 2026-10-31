# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Four-pole ladder filters with a saturating feedback loop.

One core, several characters. Each ladder is four one-pole stages (TPT
integrators) with the fourth (or third) stage fed back to the input through
a nonlinearity. The presets differ in where the saturation sits, how hard
the feedback is scaled, and which stage is the output:

- ``transistor``: tanh in every stage and at the input (Modular55's low-pass and its relatives).
- ``clean``: fast tanh at the input only, with an optional one-pole
  high-pass before the ladder (the Patch2600 and Modular100 filters).
- ``cem3320``: tanh on the feedback, passband compensation so bass survives
  resonance, tanh at the output (Curtis-style).
- ``diode``: softer diode-shaped feedback, output taken from the third
  stage (an 18 dB per octave slope, as in PinMatrix3).

The four run on audiodsp's ``audioladder.Ladder`` at the rack's block size
when audiodsp has it (0.6.8 and later): ``NodeLadderCore`` maps each preset
onto the node's feedback, output tap and passband compensation, and puts the
``clean`` preset's high-pass in front as a biquad. When the node has a cutoff
input (``Ladder.modulate``, after audiodsp 0.6.8) the cutoff CV goes into it
and the node reads it every sample, so audio-rate filter FM stays clean;
an older node moves its cutoff once a block, from the CV at the middle of the
block, which buzzes at the block rate under audio-rate FM. Without the node,
``PythonLadderCore`` runs them per sample, reading the cutoff CV at the
block's ends and interpolating the coefficient between them.

Every ladder takes its output from the fourth stage (the third for ``diode``)
unless ``render`` is given ``poles=``: 1 to 4, the stage the output is taken
from, which is 6 to 24 dB per octave. ``poles=2`` is the 12 dB slope, and it can
change from block to block. The feedback still comes from the fourth stage at
every setting, so resonance is the same loop whatever the slope: the filter
rings and self-oscillates at the cutoff from 12 dB too, only louder, about 6 dB
above its 24 dB level, because the tone is larger two stages earlier in the
loop. A linear two-pole feedback would not self-oscillate at all.

The acid filter stays in Python: its feedback is high-passed inside the
loop, which the node has no place for.
"""

import array
import math

import audiocore

from ..core.bridge import NODE_MAX_FRAMES, NodeBridge, effect_kwargs, node_kwargs, sized_node
from ..core.signal import (
    DEFAULT_SAMPLE_RATE,
    INT16_DTYPE,
    create_buffer,
    np,
    pitch_to_frequency,
    to_int16,
)

try:
    import audioladder
except ImportError:
    audioladder = None


def fast_tanh(x):
    """Rational approximation of tanh, within 0.05 everywhere and exact beyond ±3."""
    if x < -3.0:
        return -1.0
    if x > 3.0:
        return 1.0
    x2 = x * x
    return x * (27.0 + x2) / (27.0 + 9.0 * x2)


def _diode(x):
    return math.tanh(x * 1.2) / 1.2


PRESETS = {
    # k_scale, min_hz, stage_tanh, in_fn, fb_fn, comp_per_res, tap, out_fn
    "transistor": (4.0, 5.0, True, math.tanh, None, 0.0, 4, None),
    "clean": (4.0, 10.0, False, fast_tanh, None, 0.0, 4, None),
    "cem3320": (4.15, 20.0, False, None, math.tanh, 0.45, 4, math.tanh),
    "diode": (4.4, 20.0, False, None, _diode, 0.0, 3, lambda x: math.tanh(x * 1.2)),
}


def _check_poles(poles):
    if poles not in (1, 2, 3, 4):
        raise ValueError("poles must be 1, 2, 3 or 4, not %r" % (poles,))
    return poles


class PythonLadderCore:
    """A 24 dB/oct (or 18 dB for ``diode``) resonant low-pass with one of the presets above.

    ``render(poles=2)`` takes the output two stages in: 12 dB per octave.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, model="transistor"):
        self.sample_rate = sample_rate
        self.model = model
        (
            self._k_scale,
            self._min_hz,
            self._stage_tanh,
            self._in_fn,
            self._fb_fn,
            self._comp,
            self._tap,
            self._out_fn,
        ) = PRESETS[model]
        self.s0 = self.s1 = self.s2 = self.s3 = 0.0
        self.hp_x1 = self.hp_y1 = 0.0

    def reset(self):
        self.s0 = self.s1 = self.s2 = self.s3 = 0.0
        self.hp_x1 = self.hp_y1 = 0.0

    def render(
        self,
        block_size,
        src,
        dst,
        cutoff_hz=1000.0,
        cutoff_cv=None,
        mod_depth=1.0,
        resonance=0.0,
        drive=1.0,
        hp_cutoff_hz=0.0,
        poles=None,
    ):
        """Filter one block. ``resonance`` 0..1 self-oscillates near the top.

        ``poles`` is the stage the output is taken from, 1 to 4 (6 to 24 dB per
        octave); None is the preset's own, 4 or 3 for ``diode``.
        """
        sr = float(self.sample_rate)
        inv_sr = 1.0 / sr
        s0, s1, s2, s3 = self.s0, self.s1, self.s2, self.s3
        k = resonance * self._k_scale
        comp = 1.0 + resonance * self._comp
        stage_tanh = self._stage_tanh
        in_fn = self._in_fn
        fb_fn = self._fb_fn
        out_fn = self._out_fn
        tap = self._tap if poles is None else _check_poles(poles)
        top = sr * 0.45
        lo = self._min_hz

        # cutoff coefficient at both block ends, interpolated between. The transistor
        # preset integrates its saturated stages forward (Euler) with g; the
        # others are trapezoidal (TPT) with h = g / (1 + g).
        c0 = cutoff_cv[0] if cutoff_cv is not None else 0.0
        c1 = cutoff_cv[block_size - 1] if cutoff_cv is not None else 0.0
        fc0 = max(lo, min(pitch_to_frequency(c0 * mod_depth, base_freq=cutoff_hz), top))
        if stage_tanh:
            h = min(2.0 * math.pi * fc0 * inv_sr, 0.95)
        else:
            g = min(math.tan(math.pi * fc0 * inv_sr), 0.95)
            h = g / (1.0 + g)
        if c0 != c1:
            fc1 = max(lo, min(pitch_to_frequency(c1 * mod_depth, base_freq=cutoff_hz), top))
            if stage_tanh:
                h1 = min(2.0 * math.pi * fc1 * inv_sr, 0.95)
            else:
                g1 = min(math.tan(math.pi * fc1 * inv_sr), 0.95)
                h1 = g1 / (1.0 + g1)
            h_step = (h1 - h) / float(block_size)
        else:
            h_step = 0.0

        hp_x1 = self.hp_x1
        hp_y1 = self.hp_y1
        if hp_cutoff_hz > 5.0:
            rc = 1.0 / (2.0 * math.pi * hp_cutoff_hz)
            hp_alpha = rc / (rc + inv_sr)
        else:
            hp_alpha = 0.0

        for i in range(block_size):
            x = (src[i] if src is not None else 0.0) * drive
            if h_step != 0.0:
                h += h_step
            if hp_alpha > 0.0:
                y = hp_alpha * (hp_y1 + x - hp_x1)
                hp_x1 = x
                hp_y1 = y
                x = y

            fb = s3 * k
            if fb_fn is not None:
                fb = fb_fn(fb)
            u = x * comp - fb
            if in_fn is not None:
                u = in_fn(u)

            if stage_tanh:
                s0 += h * (u - math.tanh(s0))
                s1 += h * (math.tanh(s0) - math.tanh(s1))
                s2 += h * (math.tanh(s1) - math.tanh(s2))
                s3 += h * (math.tanh(s2) - math.tanh(s3))
                y0 = s0
                y1 = s1
                y2 = s2
                y3 = s3
            else:
                v0 = (u - s0) * h
                y0 = v0 + s0
                s0 = y0 + v0
                v1 = (y0 - s1) * h
                y1 = v1 + s1
                s1 = y1 + v1
                v2 = (y1 - s2) * h
                y2 = v2 + s2
                s2 = y2 + v2
                v3 = (y2 - s3) * h
                y3 = v3 + s3
                s3 = y3 + v3

            if tap == 4:
                out = y3
            elif tap == 3:
                out = y2
            elif tap == 2:
                out = y1
            else:
                out = y0
            if out_fn is not None:
                out = out_fn(out)
            dst[i] = out

        self.s0, self.s1, self.s2, self.s3 = s0, s1, s2, s3
        self.hp_x1 = hp_x1
        self.hp_y1 = hp_y1


#: Per preset on the node: output tap, and passband compensation (the node
#: scales it by its own 0..4 feedback, so the Python preset's per-resonance
#: figure is divided by k_scale).
NODE_PRESETS = {
    "transistor": (4, 0.0),
    "clean": (4, 0.0),
    "cem3320": (4, 0.45 / 4.15),
    "diode": (3, 0.0),
}


class NodeLadderCore:
    """``PythonLadderCore``'s interface on an audioladder node.

    On the int16 wire vrack's +-0.5 (+-5 V) is a quarter of full scale, while
    the node's saturator is scaled to full scale. So the drive into the loop
    is doubled, which puts the saturator where the Python preset has it, and
    the output halved on the way back.

    The cutoff CV goes onto the same wire, into the node's cutoff input:
    1.0 is half of full scale and 0.1 is an octave, so full scale is twenty
    octaves, times ``mod_depth``. The node clamps the cutoff it reaches to
    1 Hz up to just under the oversampled Nyquist rather than to the preset's
    floor and 0.45 of the sample rate; both ends are outside what a ladder
    lets through anyway.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, model="transistor"):
        self.sample_rate = sample_rate
        self.model = model
        self._k_scale = PRESETS[model][0]
        self._min_hz = PRESETS[model][1]
        self._tap, self._comp = NODE_PRESETS[model]
        self._bridge = None
        self._python = None
        self._node = None
        self._hp = None
        self._fc = self._res = self._drive = self._poles = None
        self._octaves = None
        self._hp_hz = None
        self._per_sample = False
        self._wired = False

    def _build(self, block_size):
        import audiofilters
        import synthio

        sr = self.sample_rate
        self._node = audioladder.Ladder(
            poles=self._tap, passband_comp=self._comp, **node_kwargs(block_size, sr)
        )
        self._bridge = NodeBridge(block_size, sr)
        if self.model == "clean":
            self._biquad = synthio.Biquad(synthio.FilterMode.HIGH_PASS, 20.0, Q=0.5)
            self._hp = audiofilters.Filter(filter=None, **effect_kwargs(block_size, sr))
            self._bridge.chain(self._hp, self._node, direct=True)
        else:
            self._bridge.chain(self._node, direct=True)
        self._fc = self._res = self._drive = self._poles = None
        self._octaves = None
        self._hp_hz = None
        # The cutoff CV's own int16 block, handed to the node by a looping
        # RawSample, as OscillatorBridge feeds an Oscillator's inputs.
        self._per_sample = hasattr(self._node, "modulate")
        self._wired = False
        if self._per_sample:
            self._cv = array.array("h", bytes(block_size * 2))
            self._cv_view = np.frombuffer(self._cv, dtype=INT16_DTYPE)
            self._cv_tmp = create_buffer(block_size)
            self._cv_raw = audiocore.RawSample(self._cv, channel_count=1, sample_rate=sr)

    def reset(self):
        if self._node is not None:
            self._node.clear()
        if self._python is not None:
            self._python.reset()

    def render(
        self,
        block_size,
        src,
        dst,
        cutoff_hz=1000.0,
        cutoff_cv=None,
        mod_depth=1.0,
        resonance=0.0,
        drive=1.0,
        hp_cutoff_hz=0.0,
        poles=None,
    ):
        """Filter one block. ``resonance`` 0..1 self-oscillates near the top.

        ``poles`` is as on ``PythonLadderCore.render``.
        """
        tap = self._tap if poles is None else _check_poles(poles)
        if block_size > NODE_MAX_FRAMES:
            # a block larger than a node hands out: the Python core
            if self._python is None:
                self._python = PythonLadderCore(self.sample_rate, self.model)
            self._python.render(
                block_size,
                src,
                dst,
                cutoff_hz,
                cutoff_cv,
                mod_depth,
                resonance,
                drive,
                hp_cutoff_hz,
                tap,
            )
            return
        if self._bridge is None or self._bridge.block_size != block_size:
            self._build(block_size)
        res = resonance * self._k_scale
        if self._per_sample:
            wired = cutoff_cv is not None
            if wired:
                to_int16(self._cv_view, cutoff_cv, self._cv_tmp)
            if wired != self._wired:
                self._wired = wired
                self._node.modulate(cutoff=self._cv_raw if wired else None)
            fc = max(self._min_hz, min(cutoff_hz, self.sample_rate * 0.45))
            octaves = 20.0 * mod_depth
            if (
                fc != self._fc
                or res != self._res
                or drive != self._drive
                or octaves != self._octaves
                or tap != self._poles
            ):
                self._fc = fc
                self._res = res
                self._drive = drive
                self._octaves = octaves
                self._poles = tap
                self._node.set(
                    cutoff_hz=fc,
                    resonance=res,
                    drive=drive * 2.0,
                    cutoff_octaves=octaves,
                    poles=tap,
                )
        else:
            c = cutoff_cv[block_size // 2] if cutoff_cv is not None else 0.0
            fc = pitch_to_frequency(c * mod_depth, base_freq=cutoff_hz)
            fc = max(self._min_hz, min(fc, self.sample_rate * 0.45))
            if fc != self._fc or res != self._res or drive != self._drive or tap != self._poles:
                self._fc = fc
                self._res = res
                self._drive = drive
                self._poles = tap
                self._node.set(cutoff_hz=fc, resonance=res, drive=drive * 2.0, poles=tap)
        if self._hp is not None and hp_cutoff_hz != self._hp_hz:
            self._hp_hz = hp_cutoff_hz
            if hp_cutoff_hz > 5.0:
                self._biquad.frequency = hp_cutoff_hz
                self._hp.filter = self._biquad
            else:
                self._hp.filter = None
        if src is None:
            dst[:] = 0.0
            src = dst
        self._bridge.process(src, dst)
        dst *= 0.5


#: The ladder the modules use: the node when audiodsp has one that runs at the
#: rack's block size, Python otherwise.
if audioladder is not None and sized_node(audioladder, "Ladder"):
    LadderCore = NodeLadderCore
else:
    LadderCore = PythonLadderCore


class AcidFilterCore:
    """Acid303's diode ladder with its accent circuit.

    Four one-pole stages; the feedback is high-passed so bass thins as
    resonance rises, and an accent capacitor pushes cutoff and drive for a
    short burst. The cutoff coefficient is refreshed every four samples.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.inv_sr = 1.0 / sample_rate
        self.s0 = self.s1 = self.s2 = self.s3 = 0.0
        self.hp_state = 0.0
        self.accent_env = 0.0
        self.slide_pitch = 0.0

    def reset(self):
        self.s0 = self.s1 = self.s2 = self.s3 = 0.0
        self.hp_state = 0.0
        self.accent_env = 0.0
        self.slide_pitch = 0.0

    def slide(self, target_pitch, active):
        """Advance the slide circuit one block toward target_pitch (about 60 ms) and return it."""
        if active:
            alpha = 1.0 - math.exp(-self.inv_sr / 0.060)
            self.slide_pitch += alpha * (target_pitch - self.slide_pitch)
        else:
            self.slide_pitch = target_pitch
        return self.slide_pitch

    def render(self, block_size, src, dst, cutoff_hz, resonance, env_mod, env, accent):
        decay = math.exp(-self.inv_sr / 0.15)
        s0, s1, s2, s3 = self.s0, self.s1, self.s2, self.s3
        hp = self.hp_state
        acc_env = self.accent_env
        res_gain = resonance * 4.2
        g = 0.5
        for i in range(block_size):
            x = src[i] if src is not None else 0.0
            e = env[i] if env is not None else 0.0
            acc = accent[i] if accent is not None else 0.0
            if acc > 0.3:
                acc_env = 1.0
            else:
                acc_env *= decay
            if (i & 3) == 0:
                total_env = e + acc_env * 0.4
                f = max(30.0, min(14000.0, cutoff_hz * (2.0 ** (total_env * env_mod * 4.0))))
                g = max(0.001, min(0.95, math.tan(math.pi * f * self.inv_sr)))
            res_hp = s3 - hp
            hp += 0.95 * res_hp
            u = math.tanh(x - math.tanh(res_hp * res_gain))
            s0 += g * (u - s0)
            s1 += g * (s0 - s1)
            s2 += g * (s1 - s2)
            s3 += g * (s2 - s3)
            y = s3
            if acc_env > 0.01:
                y = math.tanh(y * (1.0 + acc_env * 1.5))
            dst[i] = y
        self.s0, self.s1, self.s2, self.s3 = s0, s1, s2, s3
        self.hp_state = hp
        self.accent_env = acc_env
