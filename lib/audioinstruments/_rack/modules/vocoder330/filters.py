# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A helper for the Vocoder330's band-pass filters.

``clear_filter`` wipes a filter's state, for a filter that has been idle.
"""

import audiocore


def clear_filter(biquad_filter):
    """Zero a ``BiquadFilter``'s state, which ``BiquadFilter.reset()`` leaves alone."""
    biquad_filter.reset()
    audiocore.reset_buffer(biquad_filter.bridge.tail)
