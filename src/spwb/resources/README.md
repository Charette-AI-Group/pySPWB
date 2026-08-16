# Bundled resources

Files the application loads at runtime. Paths come from
[`spwb/app_config.py`](../app_config.py) — never build one by hand, because
a PyInstaller build reads them from the extraction directory rather than
from the source tree, and `app_config` is what knows the difference.

## The application icon

|  |  |
|---|---|
| `spwb.ico` | Windows and Linux — multi-size, 16 through 256 px |
| `spwb.png` | macOS — 1024×1024 |

Neither exists yet. `app_config.icon_file()` returns `None` until one does,
and the application runs without an icon rather than failing, so adding them
needs no code change: drop the files in and they are picked up.

CloakClip generates its pair with a `tools/makeIcon.py`; the same approach
would suit here.

Anything added to this folder ships in the wheel — `pyproject.toml` includes
`spwb/resources/*` as package data.
