"""Write the demonstration datasets into the repository's .data folder.

The datasets themselves live in :mod:`spwb.demo`, inside the package, so
that everyone who installs SPWB can create them - from the application's
**File > Create Demo Data ...**, or from a script. This script is the
developer's front door to the same function: it defaults to the checkout's
own ``.data/`` and reports what it wrote.

Usage::

    python tools/make_demo_data.py [output_folder]

Files are written in SPWB's native HDF5 format, so they open with
File > Open > SPWB / HDF5. Verify them afterwards with::

    python tools/verify_demo_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from spwb.demo import DATASET_COUNT, write_demo_data

# The repo's own untracked working folder, found relative to this script so
# it follows the checkout. Git ignores .data entirely: everything in it is
# generated from here, so a clean clone simply re-creates it.
DEFAULT_OUT = REPO / ".data"


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    print(f"writing {DATASET_COUNT} demo datasets to {out}\n")

    def report(done, total, path):
        print(f"   [{done:2d}/{total}] {path.name:52} "
              f"{path.stat().st_size / 1024:7.0f} KB")

    written = write_demo_data(out, progress=report)
    readme = out / "README.txt"
    print(f"\n   {readme.name:52} {readme.stat().st_size / 1024:7.1f} KB")
    print(f"\n{len(written)} data files + README written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
