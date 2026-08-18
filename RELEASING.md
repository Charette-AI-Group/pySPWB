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

1. Bump `version` in `pyproject.toml` (the workflow refuses to publish if
   the tag and this version disagree).
2. Commit, then draft a release on GitHub with tag `v<version>` —
   e.g. `v0.1.0` for version `0.1.0`.
3. Publish the release. The `publish` workflow then runs the full test
   suite, builds the sdist and wheel, checks the metadata, verifies the tag
   matches, and uploads to PyPI.

## The standalone application

The same tag publishes the downloads for people without Python.
`.github/workflows/build.yml` builds `dist/SPWB` on Windows, Apple Silicon
and Intel macOS, runs `spwb --selftest` against each built executable, and
attaches the three zips plus `SPWB-checksums.txt` to the release created
above. Nothing extra to do — but two things are worth knowing:

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
