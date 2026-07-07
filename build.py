#!/usr/bin/env python3

import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "answer_aura"
RUNTIME = ["__init__.py", "config.json", "tuner.html", "manifest.json"]
OPTIONAL = ["config.md"]


def main():
    # required files must exist
    for f in RUNTIME:
        if not os.path.exists(os.path.join(ROOT, f)):
            sys.exit(f"missing required file: {f}")

    for f in ("config.json", "manifest.json"):
        with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
            json.load(fh)

    files = list(RUNTIME) + [f for f in OPTIONAL if os.path.exists(os.path.join(ROOT, f))]

    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, f"{NAME}.ankiaddon")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(ROOT, f), f)  # store at archive root

    print(f"Built {out} ({os.path.getsize(out)} bytes)")
    print("Contents:")
    with zipfile.ZipFile(out) as z:
        for n in z.namelist():
            print("  ", n)


if __name__ == "__main__":
    main()
