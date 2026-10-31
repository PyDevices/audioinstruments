# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Import a package's public names on first use.

A package keeps a table of name -> submodule path and defines a module-level
``__getattr__`` that calls :func:`load`. The first ``pkg.Name`` imports only the
submodule that holds ``Name`` and stores the result in the package's globals,
so every later access is a plain attribute read.
"""


def load(pkg, table, name, namespace):
    path = table.get(name)
    if path is None:
        raise AttributeError("module '%s' has no attribute '%s'" % (pkg, name))
    value = getattr(__import__(pkg + "." + path, None, None, (name,)), name)
    namespace[name] = value
    return value
