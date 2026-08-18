"""The build self-test, checked here so it cannot lie in CI.

``spwb --selftest`` is what decides whether a standalone build gets
published, which makes it exactly the kind of code that must not fail open.
Two ways it could: by reporting PASS while a check never ran, or by letting
an exception escape and taking the remaining checks with it. Both are
pinned below.

The checks themselves are also run for real here, in the source tree, where
they must pass - so a change to the DSP or the resources that would break
the packaged application breaks the suite first.
"""
import os
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from spwb import cli, selftest


# -- the checks, run for real -----------------------------------------------
@pytest.fixture(scope="module")
def outcome():
    """The whole self-test, once - it builds five windows."""
    return selftest.run()


def test_it_passes_in_the_source_tree(outcome):
    passed, report = outcome
    assert passed, report


def test_every_check_is_reported(outcome):
    """A check that silently stopped running would still leave PASS."""
    _, report = outcome
    for name, _check, _required in selftest.CHECKS:
        assert f"{name}:" in report, f"{name} is missing from the report"


def test_the_report_names_what_it_ran_on(outcome):
    """The report is the only evidence when a CI build fails."""
    _, report = outcome
    from spwb import app_config

    assert app_config.APP_VERSION in report
    for field in ("result", "platform", "python", "frozen", "bundle"):
        assert field in report


@pytest.mark.parametrize("name,check,required", selftest.CHECKS,
                         ids=[c[0] for c in selftest.CHECKS])
def test_each_check_individually(name, check, required):
    """So a failure names the thing that broke, not just 'the self-test'."""
    result = selftest._run_check(name, check, required)

    assert result.ok, result.detail


# -- the failure paths ------------------------------------------------------
def test_a_raising_check_is_reported_not_raised():
    def explode():
        raise RuntimeError("h5py is missing its library")

    result = selftest._run_check("file io", explode)

    assert not result.ok
    assert "RuntimeError" in result.detail
    assert "h5py is missing its library" in result.detail


def test_one_failure_does_not_hide_the_later_checks(monkeypatch):
    """The point of catching per check: you get the whole picture at once."""
    def explode():
        raise RuntimeError("no platform plugin")

    monkeypatch.setattr(selftest, "CHECKS",
                        (("first", explode, True),
                         ("second", lambda: "fine", True)))
    passed, report = selftest.run()

    assert not passed
    assert "FAIL" in report
    assert "second: fine" in report


def test_a_warning_check_does_not_fail_the_build(monkeypatch):
    def explode():
        raise RuntimeError("the manuals moved")

    monkeypatch.setattr(selftest, "CHECKS", (("docs", explode, False),))
    passed, report = selftest.run()

    assert passed
    assert "[warn]" in report


def test_main_writes_the_report_and_returns_an_exit_code(tmp_path, monkeypatch):
    """CI reads the file, because a windowed build has no stdout."""
    monkeypatch.setattr(selftest, "CHECKS", (("ok", lambda: "fine", True),))
    path = tmp_path / "selftest.txt"

    assert selftest.main(str(path)) == 0
    assert "fine" in path.read_text(encoding="utf8")


def test_main_returns_one_when_a_required_check_fails(tmp_path, monkeypatch):
    def explode():
        raise RuntimeError("nope")

    monkeypatch.setattr(selftest, "CHECKS", (("broken", explode, True),))
    path = tmp_path / "selftest.txt"

    assert selftest.main(str(path)) == 1
    assert "FAIL" in path.read_text(encoding="utf8")


# -- how the built application invokes it -----------------------------------
def test_the_cli_routes_the_flag(monkeypatch):
    """--selftest must be handled before the GUI import, not after."""
    seen = {}

    def fake(path=None):
        seen["path"] = path
        return 0

    monkeypatch.setattr(selftest, "main", fake)

    assert cli.main(["spwb", "--selftest", "report.txt"]) == 0
    assert seen["path"] == "report.txt"


def test_the_flag_works_without_a_report_path(monkeypatch):
    seen = {}

    def fake(path=None):
        seen["called"] = True
        seen["path"] = path
        return 0

    monkeypatch.setattr(selftest, "main", fake)

    assert cli.main(["spwb", "--selftest"]) == 0
    assert seen["called"] and seen["path"] is None


def test_the_flag_does_not_need_a_display():
    """The real invocation CI makes, in a subprocess, with no Qt platform set.

    This is the one that would catch the self-test asking for a native
    window: on a headless runner that aborts inside Qt, which no test that
    imports Qt in-process can observe.
    """
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run([sys.executable, "-m", "spwb", "--selftest"],
                            capture_output=True, text=True, timeout=300,
                            env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
