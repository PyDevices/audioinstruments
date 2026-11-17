# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Refuse a release whose regenerated faces changed anything but their version.

    python .github/scripts/check_release_faces.py 0.5.2.dev7

Run after ``tools/make_faces.py``, from the repository root. The release PR's
VERSION is already committed, so what ``make_faces.py`` leaves in the working
tree should be the ``VERSION = "..."`` line of each face and nothing else.
A face, ``_names.py`` or ``catalog.json`` that changes in any other way means an
instrument changed on main without its faces being regenerated; that belongs in
its own change, not in a release.

Allowed: the ``VERSION`` line in ``lib/audioinstruments/<name>.py`` (the new
version on the new side, any ``VERSION = "..."`` on the old), and the ``VERSION``
file itself, only if it now says the new version. Everything else, including a
new, deleted or otherwise changed file, fails.
"""

import re
import subprocess
import sys

FACES = "lib/audioinstruments/"
LINE = re.compile(r'^VERSION = "[^"]*"$')


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def refusals(version):
    bad = []
    changed = [line for line in git("status", "--porcelain=v1", "-uall").splitlines() if line]
    for entry in changed:
        code, path = entry[:2], entry[3:]
        if path == "VERSION" and code.strip() == "M":
            with open(path, encoding="utf-8") as f:
                said = f.read().strip()
            if said != version:
                bad.append("VERSION does not say %s" % version)
            continue
        is_face = path.startswith(FACES) and path.endswith(".py") and "/" not in path[len(FACES) :]
        if code.strip() != "M" or not is_face:
            bad.append(
                "%s: %s, not a face's version line"
                % (path, "written" if code.strip() != "M" else "changed")
            )
            continue
        old = git("show", "HEAD:" + path).splitlines()
        with open(path, encoding="utf-8") as f:
            new = f.read().splitlines()
        if len(old) != len(new):
            bad.append("%s: %d lines became %d" % (path, len(old), len(new)))
            continue
        for number, (before, after) in enumerate(zip(old, new), 1):
            if before == after:
                continue
            if not (LINE.match(before) and after == 'VERSION = "%s"' % version):
                bad.append("%s:%d: %r became %r" % (path, number, before, after))
    return bad


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    bad = refusals(argv[0])
    if bad:
        print("The regenerated faces changed more than their version:")
        for line in bad:
            print("  " + line)
        print("Regenerate the faces on main in their own change, then prepare the release again.")
        return 1
    faces = git("diff", "--name-only", "--", FACES).splitlines()
    print("ok: %d faces changed, only their VERSION line" % len(faces))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
