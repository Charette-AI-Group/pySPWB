"""Execute the manual companion scripts and write them out as notebooks.

The source of truth is the ``.py`` file in ``examples/manuals/``, written in
jupytext's *percent* format: plain Python that runs with ``python``, that
VS Code, PyCharm and Jupyter all open directly as a notebook, and that
diffs like code instead of like JSON. This script runs one and stores the
executed result - text output, tables and figures - as an ``.ipynb`` beside
the manual it belongs to, where GitHub renders it inline with no toolchain
on the reader's part.

Committing generated notebooks only stays tolerable if rebuilding one
produces the same bytes when nothing has changed, so two sources of churn
are switched off deliberately:

* **cell ids are assigned by position**, not randomly by nbformat;
* **execution timings are not recorded**, since wall-clock timestamps would
  rewrite every cell on every build;
* **this machine's checkout path is scrubbed from the output**, so the
  committed notebook neither publishes the maintainer's directory layout
  nor changes depending on who built it.

Needs the ``docs`` extra::

    pip install -e .[docs]
    python tools/make_example_notebooks.py [names ...]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    # zmq cannot use the proactor loop and warns loudly on every build;
    # this is the selector policy its own message recommends.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO / "examples" / "manuals"
OUTPUT_DIR = REPO / "docs" / "manuals" / "notebooks"

try:
    import jupytext
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError
except ModuleNotFoundError as missing:                # pragma: no cover
    raise SystemExit(
        f"{missing.name} is not installed. The notebook build needs the "
        "docs extra:\n\n    pip install -e .[docs]\n\n"
        "Nothing else in the project requires it - the example scripts "
        "themselves run with matplotlib alone.") from missing


def merge_streams(outputs: list) -> list:
    """Join consecutive stdout/stderr outputs into one per stream.

    A cell that prints a table arrives as however many ZMQ messages the
    kernel happened to send, and that split varies run to run - which is
    enough to make two otherwise identical builds differ. Merging is also
    what the notebook shows anyway: consecutive stream outputs are
    concatenated when rendered.
    """
    merged: list = []
    for output in outputs:
        previous = merged[-1] if merged else None
        if (output.get("output_type") == "stream" and previous is not None
                and previous.get("output_type") == "stream"
                and previous.get("name") == output.get("name")):
            previous["text"] = "".join(
                [*_as_text(previous["text"]), *_as_text(output["text"])])
        else:
            merged.append(output)
    return merged


def _as_text(text) -> list[str]:
    """nbformat stores stream text as a string or as a list of lines."""
    return [text] if isinstance(text, str) else list(text)


#: what the checkout's absolute path is replaced with in stored output
REPO_PLACEHOLDER = "<your pySPWB checkout>"


def anonymise_paths(text: str) -> str:
    """Replace this machine's checkout path with a neutral placeholder.

    The examples find the repository for themselves and print where they
    found it, which is exactly the confirmation you want when running one.
    Stored in a committed notebook, though, that line publishes the
    maintainer's directory layout and shows readers a path that will never
    match their own clone - this one is not even named ``pySPWB``. Scrubbing
    it also makes the build reproducible across machines, rather than only
    on the machine that last ran it.
    """
    for variant in (str(REPO), str(REPO).replace("\\", "/")):
        text = text.replace(variant, REPO_PLACEHOLDER)
    return text


def stabilise(notebook) -> None:
    """Remove everything that would differ between two identical builds."""
    for position, cell in enumerate(notebook.cells):
        cell["id"] = f"cell-{position:03d}"
        # nbclient stores per-cell start/end timestamps here
        cell.get("metadata", {}).pop("execution", None)
        if not cell.get("outputs"):
            continue
        cell["outputs"] = merge_streams(cell["outputs"])
        for output in cell["outputs"]:
            if "text" in output:                      # stdout / stderr
                output["text"] = anonymise_paths(
                    "".join(_as_text(output["text"])))
            plain = output.get("data", {}).get("text/plain")
            if plain is not None:                     # a displayed value
                output["data"]["text/plain"] = anonymise_paths(
                    "".join(_as_text(plain)))


def build(source: Path) -> Path:
    """Execute one percent-format script into a rendered notebook."""
    notebook = jupytext.read(source, fmt="py:percent")
    client = NotebookClient(
        notebook,
        timeout=600,
        kernel_name="python3",
        record_timing=False,                 # no wall-clock in the output
        # cwd for the kernel: the scripts locate the repo for themselves,
        # but relative paths in any future example should mean this
        resources={"metadata": {"path": str(REPO)}},
    )
    try:
        client.execute()
    except CellExecutionError as failure:
        raise SystemExit(
            f"{source.name} failed to execute - the notebook was NOT "
            f"written.\nThis usually means the example is out of date with "
            f"the library.\n\n{failure}") from failure

    stabilise(notebook)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # fft_analysis.py -> fft-analysis.ipynb, beside fft-analysis.md
    target = OUTPUT_DIR / f"{source.stem.replace('_', '-')}.ipynb"
    nbformat.write(notebook, target)

    figures = sum(
        "image/png" in output.get("data", {})
        for cell in notebook.cells
        for output in cell.get("outputs", [])
    )
    size = target.stat().st_size / 1024
    print(f"   {target.name:34} {len(notebook.cells):3d} cells  "
          f"{figures:2d} figures  {size:7.1f} kB")
    return target


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    wanted = argv[1:]

    sources = sorted(SOURCE_DIR.glob("*.py"))
    if wanted:
        by_stem = {source.stem: source for source in sources}
        unknown = [name for name in wanted if name not in by_stem]
        if unknown:
            raise SystemExit(
                f"unknown example(s) {unknown}; known: {sorted(by_stem)}")
        sources = [by_stem[name] for name in wanted]
    if not sources:
        raise SystemExit(f"no percent-format scripts in {SOURCE_DIR}")

    print(f"executing {len(sources)} example(s) -> {OUTPUT_DIR}\n")
    for source in sources:
        build(source)
    print(f"\n{len(sources)} notebook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
