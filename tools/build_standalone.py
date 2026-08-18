"""Build the standalone application locally, and check what came out.

    python tools/build_standalone.py

Double-clicking ``buildStandalone.cmd`` does the same thing on Windows.
The real builds are made by .github/workflows/build.yml, on all three
platforms at once - this is for trying a change to ``spwb.spec`` without
pushing, and it runs the same self-test CI runs, so a local build that
passes here is a build CI should also accept.

Nothing here decides *how* the application is bundled: that is entirely in
``spwb.spec``, so the two cannot drift apart.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP = "SPWB.app" if sys.platform == "darwin" else "SPWB"

#: what to run the self-test with, once the build is done
EXECUTABLE = {
    "win32": DIST / "SPWB" / "SPWB.exe",
    "darwin": DIST / "SPWB.app" / "Contents" / "MacOS" / "SPWB",
}.get(sys.platform, DIST / "SPWB" / "SPWB")


def folder_size(path: Path) -> str:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1e6:.0f} MB"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. From the repository root:\n\n"
              '    pip install ".[build]"\n', file=sys.stderr)
        return 1

    print(f"Building {APP} with Python {sys.version.split()[0]} ...\n")
    build = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "spwb.spec", "--noconfirm"],
        cwd=ROOT)
    if build.returncode != 0:
        return build.returncode

    target = DIST / APP
    print(f"\nBuilt {target} ({folder_size(target)})")

    # The build succeeding says nothing about whether the bundle is
    # complete - that is the whole reason --selftest exists.
    print("\nRunning the self-test against it ...\n")
    report = ROOT / "selftest.txt"
    check = subprocess.run([str(EXECUTABLE), "--selftest", str(report)])
    if report.is_file():
        print(report.read_text(encoding="utf8"))
    if check.returncode != 0:
        print("The build is INCOMPLETE - see the report above.", file=sys.stderr)
        return check.returncode

    # what CI uploads, so the thing you hand someone is the thing CI makes
    archive = shutil.make_archive(str(DIST / f"SPWB-{sys.platform}"), "zip",
                                  root_dir=DIST, base_dir=APP)
    print(f"Ready to share: {archive} "
          f"({Path(archive).stat().st_size / 1e6:.0f} MB compressed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
