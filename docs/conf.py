# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""Sphinx configuration for the audioinstruments documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from omnipython-docs.
"""

from omnipython_docs import configure

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
# docs/dev is for contributors and is not part of the site.
settings["exclude_patterns"].append("dev")

globals().update(settings)

# The instrument pages link to one another's subsection headings.
myst_heading_anchors = 4
