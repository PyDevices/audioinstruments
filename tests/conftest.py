# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Shared test helpers."""

import pytest
from vrack.core import Module, SignalType


class Source(Module):
    """A module with one output whose block a test fills in by hand.

    Patch it into the jack under test instead of writing into an unfed
    input's silent buffer: a module only reads inputs that have a cable or a
    normal.
    """

    NAME = "Source"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def process(self, block_size):
        pass


@pytest.fixture
def source():
    return Source


def energy(buf):
    return sum(abs(float(x)) for x in buf)
