# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Sphinx configuration for the audioinstruments documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from pydevices-docs.
"""

from pydevices_docs import configure

settings = configure(
    "audioinstruments", __file__,
    repo="PyDevices/audioinstruments", edit_path="docs",
    source_dirs=["../lib"], api_packages=["audioinstruments"],
    use_module_all=True,
    # audiodsp's native modules are not installable on Read the Docs.
    mock_imports=[
        "audiobiquad", "audiocore", "audioconvolve", "audiodelays",
        "audiodsp_util", "audiodynamics", "audioecho", "audiofilters",
        "audiograph", "audioladder", "audiomath", "audiomixer",
        "audiomodal", "audiopump", "audioroute", "audiosampler",
        "audioshaper", "audioverb", "audiospeed", "audiofreeverb",
        "audiomp3", "audiovorbis", "synthio",
    ],
    version_file="../VERSION",
)
globals().update(settings)

# instruments.md links to level-4 headings ("The Mono101 graph form").
myst_heading_anchors = 4
