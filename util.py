#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small vehicle-independent helpers shared across the project.

Nothing here knows about a particular car. It exists so the generic layers
(the transport, the reader, the web app) stop reaching into `leaf_decoders`
for things that were never Leaf-specific in the first place — the temperature
formatter was, until 2026-09, imported into the vehicle-agnostic reader from a
module named after one car. `leaf_decoders` re-exports both temperature
helpers, so its long-standing callers are unaffected.
"""

import os


ENV_PREFIX = "VEHICLETAP_"
OLD_ENV_PREFIX = "HAKAKE_"      # the project's name until 2026-11; still read, see env()


def env(name, *aliases, default=None):
    """Environment variable, with backward-compatible older names.

    Names are tried in this order, and the first non-empty one wins:

    1. ``name`` itself.
    2. If ``name`` starts with ``VEHICLETAP_``, the same name with the ``HAKAKE_`` prefix the project used
       before it was renamed, so an existing setup keeps working with no call site carrying an alias for it.
    3. The explicit ``aliases``, such as the ``LEAF_*`` names from when it was a one-car tool. Those still
       work too, silently, because they are documented in the README and in use on the owner's machine.

    Empty is treated as unset, so ``VEHICLETAP_X= HAKAKE_X=abc`` still finds ``abc``.
    """
    names = [name]
    if name.startswith(ENV_PREFIX):
        names.append(OLD_ENV_PREFIX + name[len(ENV_PREFIX):])
    for n in (*names, *aliases):
        v = os.environ.get(n)
        if v:
            return v
    return default


def c_to_f(c):
    """Celsius → Fahrenheit, rounded to 0.1."""
    return None if c is None else round(c * 9.0 / 5.0 + 32.0, 1)


def fmt_temp(c):
    """'34 °C / 93 °F' — the project's standard temperature string."""
    if c is None:
        return "--"
    return f"{c:.0f} °C / {c_to_f(c):.0f} °F" if float(c).is_integer() else f"{c:.1f} °C / {c_to_f(c):.1f} °F"

