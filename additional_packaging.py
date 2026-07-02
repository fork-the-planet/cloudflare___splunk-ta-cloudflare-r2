# Copyright (c) 2026 Cloudflare, Inc.
# Licensed under the Apache 2.0 license.

"""
UCC post-build hook (invoked by `ucc-gen build`).

Two fixes applied to the generated output/<ta_name>/:

1. Architecture independence — remove compiled *.so files from lib/. The only
   binaries pulled in are charset_normalizer's optional mypyc speedups (via
   requests, which our stdlib R2 client does not even use); pure-Python
   fallbacks (md.py / cd.py) ship alongside them. Removing the *.so makes the
   add-on run on x86_64 AND aarch64 (Splunk Cloud / Graviton) and clears the
   AppInspect "AArch64-incompatible binary file" failure.

2. python.required — ucc-gen 5.52.0 emits only `python.version`, but current
   AppInspect flags stanzas that do not also define `python.required`. We add
   `python.required = 3.9, 3.13` to every stanza that has `python.version`
   (input + REST-handler admin_external stanzas). 3.9 is present on all
   supported Splunk releases (9.4-10.4); 3.13 is selected where available.
"""

import os

_PYTHON_REQUIRED = "python.required = 3.9, 3.13"
_CONF_FILES = ("inputs.conf", "restmap.conf")


def _strip_shared_objects(lib_dir):
    removed = []
    for dirpath, _dirs, files in os.walk(lib_dir):
        for name in files:
            if name.endswith(".so"):
                path = os.path.join(dirpath, name)
                os.remove(path)
                removed.append(os.path.relpath(path, lib_dir))
    return removed


def _ensure_python_required(conf_path):
    if not os.path.isfile(conf_path):
        return
    with open(conf_path, "r") as fh:
        text = fh.read()
    if "python.required" in text:
        return  # already present; nothing to do
    out_lines = []
    for line in text.splitlines():
        out_lines.append(line)
        if line.strip().startswith("python.version"):
            out_lines.append(_PYTHON_REQUIRED)
    with open(conf_path, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")


def additional_packaging(ta_name):
    root = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(root, "output", ta_name)

    removed = _strip_shared_objects(os.path.join(out, "lib"))
    print(
        "additional_packaging: removed {} compiled .so file(s) for "
        "architecture independence: {}".format(len(removed), removed)
    )

    for conf in _CONF_FILES:
        _ensure_python_required(os.path.join(out, "default", conf))
    print("additional_packaging: ensured python.required on python.version stanzas")
