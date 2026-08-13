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
   | Repository name | `SPWB-py` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. **Repeat on TestPyPI** (optional but recommended for the first run) at
   <https://test.pypi.org/manage/account/publishing/>, with the same values
   except **Environment name** = `testpypi`.

4. **Create the two GitHub environments** at
   <https://github.com/Charette-AI-Group/SPWB-py/settings/environments>:
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
