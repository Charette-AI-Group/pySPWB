# Releasing

Publishing uses **PyPI Trusted Publishing** (OIDC): GitHub Actions proves
its identity to PyPI directly, so there is no API token to create, store or
leak. Nothing about publishing lives on anyone's laptop.

## One-time setup on pypi.org

These steps need a browser and your PyPI account, so they cannot be
automated from here.

1. **Create a PyPI account** if you do not have one, and turn on 2FA
   (PyPI requires it for publishing).

2. **Add a pending publisher** at
   <https://pypi.org/manage/account/publishing/>. Because `spwb` does not
   exist on PyPI yet, use the *pending publisher* form — it reserves the
   name and lets the first upload create the project. Fill in exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `spwb` |
   | Owner | `Charette-AI-Group` |
   | Repository name | `pySPWB` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. **Repeat on TestPyPI** (optional but recommended for the first run) at
   <https://test.pypi.org/manage/account/publishing/>, with the same values
   except **Environment name** = `testpypi`.

4. **Create the two GitHub environments** at
   <https://github.com/Charette-AI-Group/pySPWB/settings/environments>:
   one named `pypi` and one named `testpypi`. Leave them empty — they hold
   no secrets. Adding *Required reviewers* to `pypi` is worth doing: it
   makes every upload pause for a human click.

That is the whole setup. No secrets are ever added to the repository.

## Cutting a release

One tag produces both halves of a release: the PyPI package and the
standalone downloads. It ends with a human pressing Publish, for a reason
given below.

1. Bump the version in **both** `pyproject.toml` and `src/spwb/__init__.py`.
   `tests/test_app_config.py` fails if they disagree, and the publish
   workflow refuses if the tag disagrees with `pyproject.toml`.
2. `python -m build && python -m twine check dist/*` locally. This catches
   packaging and metadata problems without spending a version number, which
   matters because a version can never be reused or its description edited.
3. Commit and push. Wait for `tests` to go green.
4. Tag and push the tag:

   ```bash
   git tag -a v1.1.0 -m "..." && git push origin v1.1.0
   ```

   `build.yml` then builds the standalone application on Windows, Apple
   Silicon and Intel macOS, runs `spwb --selftest` against each built
   executable, and opens a **draft** release with the three zips and
   `SPWB-checksums.txt` attached. A platform that fails its self-test fails
   the job, and no release appears.
5. **Review the draft and press Publish.** That is what uploads to PyPI:
   publishing triggers `publish.yml`, which runs the full suite, builds the
   sdist and wheel, checks the metadata, verifies the tag matches and
   uploads.

Step 5 cannot be automated away, and it is better that it cannot. GitHub
does not start a workflow from an event raised by the default
`GITHUB_TOKEN`, so a release published by `build.yml` itself would attach
the binaries and never reach PyPI — silently, with every job green. The
draft turns that constraint into the one thing this process was missing:
a person looking at the artifacts before an upload that can never be
undone.

## The standalone application

Built and attached by step 4 above. Two things are worth knowing:

* **The self-test is the gate.** A bundle can build cleanly and still be
  missing its icons, its Qt platform plugin or a working h5py; every one of
  those is silent at startup and fatal later. If a build job fails, the
  `selftest-*` artifact on the run says exactly which check failed. Never
  publish past a red one.
* **The builds are unsigned**, so users meet SmartScreen on Windows and
  Gatekeeper on macOS. Both are documented in the README's download
  section. Signing would need a certificate (and an Apple Developer
  account at $99/year) — until then the checksums file is what lets people
  verify a download.

To try the whole thing without releasing anything: Actions → **build** →
*Run workflow*. It builds all three and uploads them as run artifacts,
skipping the release job entirely. Locally, `python
tools/build_standalone.py` (or double-clicking `buildStandalone.cmd`) does
one platform and runs the same self-test.

## Trying it against TestPyPI first

Actions → **publish** → *Run workflow* → target `testpypi`. Then check the
result installs:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ spwb
```

The extra index is needed because numpy and scipy are not on TestPyPI.

TestPyPI will not accept the same version twice, so if you want to retry
you must bump the version. A common habit is to test with a throwaway
`0.1.0rc1` and release `0.1.0` for real.

## After the first release

Update the install instructions in the two READMEs, which currently point
at the GitHub repo because no release exists yet:

* `README.md` in this repo (the `pip install spwb` block is already correct
  — it is the *original* repo that needs changing)
* `README.md` in <https://github.com/Charette-AI-Group/SPWB>, which says
  `pip install "git+https://github.com/..."` and notes that PyPI is coming
