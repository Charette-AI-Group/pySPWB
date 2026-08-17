"""Run the manual companion examples, so they cannot rot unnoticed.

``examples/manuals/*.py`` are the source of the notebooks published beside
the user manuals. They quote the numbers the manuals quote, and they assert
them - so executing one is a check that the library still behaves the way
the documentation says it does.

This runs the scripts directly rather than through Jupyter: the notebook
build needs the ``docs`` extra, but the guarantee that matters here costs
nothing but matplotlib. Each runs in a fresh subprocess, with a scratch
working directory, so a script that quietly depended on the caller's state
or wrote stray files would be caught.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib",
                    reason="examples/ plot their results; see the dev extra")
pytest.importorskip("h5py", reason="the demo datasets are HDF5")

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((REPO / "examples" / "manuals").glob("*.py"))


def test_there_are_examples_to_run():
    """A glob that silently matches nothing would make this file a no-op."""
    assert EXAMPLES, "no percent-format examples in examples/manuals/"


@pytest.mark.slow
@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs_clean(script, tmp_path):
    environment = {**os.environ, "MPLBACKEND": "Agg"}
    # the scripts locate the repository from their own path, so an unrelated
    # working directory is exactly the case worth exercising
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=900,
        cwd=tmp_path, env=environment,
    )
    assert result.returncode == 0, (
        f"{script.name} failed - the documentation it backs is now wrong.\n"
        f"--- stdout ---\n{result.stdout[-4000:]}\n"
        f"--- stderr ---\n{result.stderr[-4000:]}")

    # every section signs off, and those lines carry the manual's numbers
    signed_off = [line for line in result.stdout.splitlines()
                  if line.startswith("section ") and " OK" in line]
    assert signed_off, f"{script.name} produced no section checks:\n{result.stdout}"

    stray = [p.name for p in tmp_path.iterdir()]
    assert not stray, f"{script.name} wrote files into the working directory: {stray}"
