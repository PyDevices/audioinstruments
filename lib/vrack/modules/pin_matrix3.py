# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PinMatrix3, a synthesizer with a 16 x 16 pin matrix, inspired by the EMS VCS3.

Three oscillators, a diode ladder filter, a ring modulator, noise, a
trapezoid envelope shaper, a joystick and a spring reverb, routed by pins.
Sources are matrix rows, destinations are columns; ``set_pin(row, col,
weight)`` places a pin. The default pins send oscillators 1 and 2 to the
filter and the filter to both outputs.

Rows: 0 osc1 sine, 1 osc1 saw, 2 osc2 square, 3 osc2 triangle, 4 osc3
square, 5 osc3 ramp, 6 noise, 7 filter out, 8 trapezoid, 9 ring mod,
10 reverb out, 11 joystick X, 12 joystick Y, 13 ext in 1, 14 ext in 2,
15 keyboard CV. Columns: 0 osc1 pitch, 1 osc2 pitch, 2 osc3 pitch,
3 filter in, 4 filter CV, 9 reverb in, 10 output 1, 11 output 2.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import (
    BASE_FREQ_C4,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SAMPLE_RATE,
    add_scaled,
    copy_into,
    mix_into,
)
from ..dsp.function_generator import FunctionGeneratorCore
from ..dsp.ladder import LadderCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.reverb import ReverbCore
from ..dsp.utility import ring_mod_into
from ._util import jack_signal, knob_hz

ROWS = 16
COLS = 16
COL_OSC1, COL_OSC2, COL_OSC3, COL_FILTER_IN, COL_FILTER_CV, COL_REVERB_IN, COL_OUT1, COL_OUT2 = (
    0,
    1,
    2,
    3,
    4,
    9,
    10,
    11,
)


class PinMatrix3(Module):
    NAME = "PinMatrix3"
    DISPLAY_NAME = "PinMatrix3"
    HP = 34

    MACRO_LABELS = (
        "filter_freq",
        "filter_res",
        "trap_attack",
        "trap_decay",
        "reverb_mix",
        "joy_x",
        "joy_y",
        "volume",
    )

    def __init__(self, id_tag=None, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.matrix = [[0.0] * COLS for _ in range(ROWS)]
        super().__init__(id_tag=id_tag, sample_rate=sample_rate, block_size=block_size)

    def set_pin(self, source_row, dest_col, weight=1.0):
        if 0 <= source_row < ROWS and 0 <= dest_col < COLS:
            self.matrix[source_row][dest_col] = float(weight)

    def clear_pin(self, source_row, dest_col):
        self.set_pin(source_row, dest_col, 0.0)

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.osc3 = OscillatorCore(sr)
        self.filter = LadderCore(sr, "diode")
        self.noise = NoiseGenerator()
        self.reverb = ReverbCore(sr, n, roomsize=0.7, damp=0.55)
        self.trapezoid = FunctionGeneratorCore(sr, n)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.ext_in1 = self.add_input("ext_in1", "Ext In 1", audio)
        self.ext_in2 = self.add_input("ext_in2", "Ext In 2", audio)
        self.out_left = self.add_output("out_left", "Output Channel 1", audio)
        self.out_right = self.add_output("out_right", "Output Channel 2", audio)
        self.filter_out = self.add_output("filter_out", "Filter Out", audio)
        self.trapezoid_out = self.add_output("trapezoid_out", "Trapezoid Out", cv)
        self.joystick_x_out = self.add_output("joy_x", "Joystick X Out", cv)
        self.joystick_y_out = self.add_output("joy_y", "Joystick Y Out", cv)

        self.set_pin(0, COL_FILTER_IN, 0.7)
        self.set_pin(2, COL_FILTER_IN, 0.7)
        self.set_pin(7, COL_OUT1, 1.0)
        self.set_pin(7, COL_OUT2, 1.0)

        self.add_param(
            "osc1_freq", "Osc 1 Pitch Offset (octaves)", default=0.0, min_val=-3.0, max_val=3.0
        )
        self.add_param(
            "osc2_freq", "Osc 2 Pitch Offset (octaves)", default=0.02, min_val=-3.0, max_val=3.0
        )
        self.add_param(
            "osc3_freq", "Osc 3 Pitch Offset (octaves)", default=-2.0, min_val=-5.0, max_val=2.0
        )
        self.add_param("filter_freq", "Filter Cutoff", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param("filter_res", "Filter Response", default=0.40, min_val=0.0, max_val=1.0)
        self.add_param(
            "trap_attack", "Trapezoid Attack (s)", default=0.02, min_val=0.002, max_val=5.0
        )
        self.add_param("trap_on", "Trapezoid On (s)", default=0.15, min_val=0.0, max_val=5.0)
        self.add_param("trap_decay", "Trapezoid Decay (s)", default=0.35, min_val=0.01, max_val=5.0)
        self.add_param(
            "trap_off",
            "Trapezoid Off / repeat (s); 0 = gated only",
            default=0.0,
            min_val=0.0,
            max_val=5.0,
        )
        self.add_param("reverb_mix", "Spring Reverb Mix", default=0.25, min_val=0.0, max_val=1.0)
        self.add_param("joy_x", "Joystick X", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("joy_y", "Joystick Y", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("volume", "Master Output Level", default=1.0, min_val=0.0, max_val=1.5)

        # one block per matrix row, plus column sums
        self._sources = [None] * ROWS
        for r in range(ROWS):
            self._sources[r] = self.add_scratch("_row%d" % r)
        self._sources[8] = self.trapezoid_out.buffer
        self._sources[7] = self.filter_out.buffer
        for name in ("_cv1", "_cv2", "_cv3", "_filt_in", "_filt_cv", "_rev_in", "_wet", "_tmp"):
            self.add_scratch(name)
        self._weights = [0.0] * ROWS
        self._column_srcs = [None] * ROWS

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        for r in range(ROWS):
            self._sources[r] = getattr(self, "_row%d" % r)
        self._sources[8] = self.trapezoid_out.buffer
        self._sources[7] = self.filter_out.buffer
        self.reverb = ReverbCore(self.sample_rate, block_size, roomsize=0.7, damp=0.55)
        self.trapezoid.set_block_size(block_size)

    def reset(self):
        for core in (
            self.osc1,
            self.osc2,
            self.osc3,
            self.filter,
            self.noise,
            self.reverb,
            self.trapezoid,
        ):
            core.reset()

    def _column(self, col, dst):
        """dst = sum of pinned rows into a column. Returns True when any pin is set."""
        srcs = self._column_srcs
        weights = self._weights
        any_pin = False
        for r in range(ROWS):
            w = self.matrix[r][col]
            if w != 0.0:
                srcs[r] = self._sources[r]
                weights[r] = w
                any_pin = True
            else:
                srcs[r] = None
                weights[r] = 0.0
        mix_into(dst, self._tmp, srcs, weights)
        return any_pin

    def process(self, block_size):
        p = self.params
        n = block_size
        self.joystick_x_out.buffer[:] = p["joy_x"] * 0.5
        self.joystick_y_out.buffer[:] = p["joy_y"] * 0.5

        gate = jack_signal(self.kybd_gate_in)
        self.trapezoid.render(
            gate,
            self.trapezoid_out.buffer,
            p["trap_attack"],
            p["trap_decay"],
            cycle=p["trap_off"] > 0.005 and gate is None,
            hold_sec=p["trap_on"],
        )
        self.noise.white(self._row6)
        copy_into(self._row11, self.joystick_x_out.buffer)
        copy_into(self._row12, self.joystick_y_out.buffer)
        ext1 = jack_signal(self.ext_in1)
        ext2 = jack_signal(self.ext_in2)
        if ext1 is not None:
            copy_into(self._row13, ext1)
        else:
            self._row13[:] = 0.0
        if ext2 is not None:
            copy_into(self._row14, ext2)
        else:
            self._row14[:] = 0.0
        kybd = jack_signal(self.kybd_cv_in)
        if kybd is not None:
            copy_into(self._row15, kybd)
        else:
            self._row15[:] = 0.0

        # oscillator pitch columns; with no pin the keyboard drives oscillators 1 and 2
        if not self._column(COL_OSC1, self._cv1) and kybd is not None:
            copy_into(self._cv1, kybd)
        if not self._column(COL_OSC2, self._cv2) and kybd is not None:
            copy_into(self._cv2, kybd)
        self._column(COL_OSC3, self._cv3)
        self.osc1.render(
            n, BASE_FREQ_C4 * (2.0 ** p["osc1_freq"]), self._cv1, saw=self._row1, sine=self._row0
        )
        self.osc2.render(
            n, BASE_FREQ_C4 * (2.0 ** p["osc2_freq"]), self._cv2, pulse=self._row2, tri=self._row3
        )
        self.osc3.render(
            n, BASE_FREQ_C4 * (2.0 ** p["osc3_freq"]), self._cv3, saw=self._row5, pulse=self._row4
        )
        ring_mod_into(self._row9, self._row0, self._row2)

        self._column(COL_FILTER_IN, self._filt_in)
        self._column(COL_FILTER_CV, self._filt_cv)
        self.filter.render(
            n,
            self._filt_in,
            self.filter_out.buffer,
            cutoff_hz=knob_hz(p["filter_freq"], 40.0, 12000.0),
            cutoff_cv=self._filt_cv,
            resonance=p["filter_res"],
        )

        # reverb: wet from the column, dry/wet by the mix knob
        if self._column(COL_REVERB_IN, self._rev_in):
            self.reverb.render_wet(self._rev_in, self._wet)
            row10 = self._row10
            copy_into(row10, self._rev_in)
            row10 *= 1.0 - p["reverb_mix"]
            add_scaled(row10, self._wet, p["reverb_mix"], self._tmp)
        else:
            self._row10[:] = 0.0

        self._column(COL_OUT1, self.out_left.buffer)
        self._column(COL_OUT2, self.out_right.buffer)
        if p["volume"] != 1.0:
            self.out_left.buffer *= p["volume"]
            self.out_right.buffer *= p["volume"]
