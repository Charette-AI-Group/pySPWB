"""The README is rendered in two places, and only one of them is the repo.

PyPI renders it standalone on ``pypi.org/project/spwb/``, where a relative
link resolves against that page and 404s - which is what happened to every
``docs/...`` link in the 1.0.1 description. GitHub resolves the same link
against the repository and it works, so the mistake is invisible from the
place you are most likely to look.

Absolute links are correct in both. This is the same failure the notebooks
had (see tests/test_examples.py); the README is the other file that gets
published somewhere other than where it lives.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
README = REPO / "README.md"

#: a markdown link target, e.g. the "x.md" of "[see](x.md)"
_LINK = re.compile(r"\]\(([^)]+)\)")
_REPO_URL = "https://github.com/Charette-AI-Group/pySPWB"


def targets() -> list[str]:
    return _LINK.findall(README.read_text(encoding="utf8"))


def test_the_readme_exists_and_has_links():
    """A regex that silently matches nothing would make this file a no-op."""
    assert README.is_file()
    assert len(targets()) > 5


def test_no_link_is_relative():
    """The whole point: relative is wrong wherever this is published."""
    offenders = [t for t in targets()
                 if not t.startswith(("http://", "https://", "#", "mailto:"))]

    assert not offenders, (
        "relative links break on PyPI, which renders this README at "
        "pypi.org/project/spwb/ with no repository to resolve against:\n  "
        + "\n  ".join(offenders))


def file_links() -> list[str]:
    """Links into the repository's own files and directories.

    Not every link to the repo is one of these - the badges point at
    /actions/ and the issue tracker at /issues - so the file links are
    picked out by the /blob/ and /tree/ that name a path.
    """
    return [t for t in targets()
            if t.startswith(_REPO_URL) and ("/blob/" in t or "/tree/" in t)]


def test_the_readme_links_to_its_own_documentation():
    assert file_links(), "the README should link to its own docs"


def test_file_links_are_pinned_to_a_branch():
    for target in file_links():
        assert "/blob/main/" in target or "/tree/main/" in target, (
            f"{target} does not name a branch - it will rot or 404")


def test_every_file_link_points_at_something_that_exists():
    """Checked against the working tree, so a typo fails here rather than
    404ing for a reader. No network: this is about the path being real."""
    missing = [path for path in
               (t.split("/main/", 1)[1].split("#")[0] for t in file_links())
               if not (REPO / path).exists()]

    assert not missing, f"README links to paths that do not exist: {missing}"
