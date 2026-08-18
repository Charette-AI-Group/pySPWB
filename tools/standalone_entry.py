"""Entry point for the standalone (PyInstaller) build - see spwb.spec.

A package's own ``__main__.py`` cannot serve as the frozen entry script:
its ``from .cli import main`` is a relative import, which fails the moment
the file is run as a top-level script rather than as ``python -m spwb``.
So the bundled application starts here instead, and immediately hands over
to the same :func:`spwb.cli.main` every other way of starting SPWB uses -
including ``--selftest``, which CI runs against the built executable.
"""
import sys

from spwb.cli import main

if __name__ == "__main__":
    sys.exit(main())
