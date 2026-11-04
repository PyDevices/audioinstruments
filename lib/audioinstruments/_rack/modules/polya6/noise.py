# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""PolyA6 noise generator: shared white and pink noise for every voice."""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.noise import NoiseGenerator

NOISE_SEED = 0x5EED

#: Kellet's pinking filter as the graph builds it: five one-poles (pole, gain)
#: on the white noise, each a sample-and-hold refreshed every sample with its
#: lag as the pole, so it settles to unity at DC and is scaled after. Kellet's
#: last three terms (a negative pole, a one-sample delay and the white noise
#: itself) are one more one-pole of pole 0.321 at gain 0.759: within 0.35 dB
#: of Kellet's magnitude from 20 Hz to Nyquist.
PINK_POLES = (
    (0.99886, 0.0555179),
    (0.99332, 0.0750759),
    (0.96900, 0.1538520),
    (0.86650, 0.3104856),
    (0.55000, 0.5329522),
)
PINK_TAIL = (0.321, 0.759)
PINK_SCALE = 0.15


class PolyA6Noise(Module):
    """Shared noise source for the PolyA6: white and pink noise.

    A single NoiseGenerator serves every voice, with white and pink
    outputs patched to each voice's noise inputs.
    """

    NAME = "PolyA6Noise"
    DISPLAY_NAME = "PolyA6 Noise"
    HP = 4

    def _build(self):
        self.noise = NoiseGenerator(seed=NOISE_SEED)
        audio = SignalType.AUDIO
        self.white_out = self.add_output("white", "White Noise", audio)
        self.pink_out = self.add_output("pink", "Pink Noise", audio)
        self._n_pink = ()
        self._pink_quiet = set()
        self._pink_on = True

    def reset(self):
        self.noise.reset()

    def fragment(self, f):
        """White noise from the graph's own generator, and Kellet's pink from it.

        The graph's noise is not the rack's (a numpy generator), so the two
        match in level and spectrum, not sample for sample.
        """
        import audiograph as ag

        from ...core.graph import UNIT

        self._ag = ag
        white = f.output(self.white_out)
        self._n_white = f.add(ag.NOISE, (), white)
        f.set(self._n_white, 0, 0.5 * UNIT)
        self._n_pink = []
        self._pink_gains = gains = []
        self._pink_poles = [pole for pole, _ in PINK_POLES + (PINK_TAIL,)]
        self._pink_quiet = set()
        self._pink_on = True
        stages = []
        for pole, gain in PINK_POLES + (PINK_TAIL,):
            b = f.buffer()
            node = f.add(ag.SAMPLE_HOLD, (white, None), b)
            f.set(node, ag.SH_RATE, float(self.sample_rate))
            f.set(node, ag.SH_LAG, pole)
            self._n_pink.append(node)
            stages.append(b)
            # a Kellet stage is gain / (1 - pole) times a unity one-pole; the tail
            # is fitted as a unity one-pole already
            gains.append(gain if (pole, gain) == PINK_TAIL else gain / (1.0 - pole))
        self._n_pink_mix = f.add(ag.MIX, tuple(stages), f.output(self.pink_out))
        for i, g in enumerate(gains):
            f.set(self._n_pink_mix, i, g * PINK_SCALE)
        f.on_reset(self._graph_reset)

    def graph_pink_read(self, voice, reads):
        """A voice says whether it reads the pink. With no reader left the stages stop: a
        stage at 0 Hz and no lag only copies what it holds."""
        quiet = self._pink_quiet
        if reads:
            quiet.discard(voice)
        else:
            quiet.add(voice)
        on = len(quiet) < len(self.pink_out.cables) or not quiet
        if on == self._pink_on:
            return
        self._pink_on = on
        f = self._fragment
        ag = self._ag
        for i, node in enumerate(self._n_pink):
            if on:
                # a stage that stopped kept a raw sample of the white: start it from nothing
                f.reset(node)
            f.set(node, ag.SH_RATE, float(self.sample_rate) if on else 0.0)
            f.set(node, ag.SH_LAG, self._pink_poles[i] if on else 0.0)
            f.set(self._n_pink_mix, i, self._pink_gains[i] * PINK_SCALE if on else 0.0)

    def _graph_reset(self):
        f = self._fragment
        for node in [self._n_white] + self._n_pink:
            f.reset(node)

    def process(self, block_size):
        if self.white_out.is_connected or self.pink_out.is_connected:
            white = self.white_out.buffer
            self.noise.white(white)
            if self.pink_out.is_connected:
                pink = self.pink_out.buffer
                self.noise.pink(white, pink)
