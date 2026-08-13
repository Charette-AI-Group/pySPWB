"""The console entry point, including its behaviour without the GUI extra."""
import subprocess
import sys

from spwb import cli


def test_missing_gui_extra_prints_the_fix(capsys, monkeypatch):
    """`pip install spwb` then `spwb` must explain itself, not traceback."""
    def raise_missing(*args, **kwargs):
        raise ImportError("No module named 'PySide6'", name="PySide6")

    monkeypatch.setattr("builtins.__import__", raise_missing)
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert 'pip install "spwb[gui]"' in err
    assert "spwb.processing" in err          # points at the library too


def test_a_real_import_error_is_not_swallowed(monkeypatch):
    """Only the GUI extra is special-cased; other failures still raise."""
    def raise_other(*args, **kwargs):
        raise ImportError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr("builtins.__import__", raise_other)
    try:
        cli.main([])
    except ImportError as exc:
        assert exc.name == "numpy"
    else:
        raise AssertionError("a non-GUI ImportError should propagate")


def test_module_entry_point_exists():
    """`python -m spwb` resolves; --help-less launch is not attempted here."""
    result = subprocess.run(
        [sys.executable, "-c", "import spwb.cli; print(spwb.cli.main)"],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "function main" in result.stdout
