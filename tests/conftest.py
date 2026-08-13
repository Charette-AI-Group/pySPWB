import pathlib

import numpy as np
import pytest


@pytest.fixture(scope="session")
def lv():
    """LabVIEW 2022 ground-truth reference data (see tools/make_fixtures)."""
    path = pathlib.Path(__file__).parent / "fixtures" / "labview_reference.npz"
    return np.load(path)
