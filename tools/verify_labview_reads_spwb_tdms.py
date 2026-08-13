"""Cross-check: does LabVIEW's own TDMS engine read files spwb writes?

Writes a TDMS with spwb.processing.io.write_tdms, then asks LabVIEW 2022 to convert it
to TDM (vi.lib Convert TDMS to TDM.vi). A clean conversion proves NI's TDMS
reader accepts our file; the resulting .tdm XML header is then checked for
the waveform properties and values we wrote.

Requires LabVIEW 2022 + pywin32. Run from the repo root:
    python tools/verify_labview_reads_spwb_tdms.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spwb import Signal
from spwb.processing.io import write_tdms

CONVERTER = (r"C:\Program Files\National Instruments\LabVIEW 2022"
             r"\vi.lib\Utility\tdmsutil.llb\Convert TDMS to TDM.vi")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="spwb_tdms_"))
    dt = 1.0 / 4096.0
    t = np.arange(4096) * dt
    sigs = [
        Signal("Accel X", 9.81 * np.sin(2 * np.pi * 100 * t), dt, t0=0.125,
               y_unit="m/s^2", attributes={"TDMS Group": "Run 1"}),
        Signal("Mic", 0.5 * np.cos(2 * np.pi * 250 * t), dt,
               y_unit="Pa", attributes={"TDMS Group": "Run 1"}),
    ]
    src = write_tdms(tmp / "spwb_written.tdms", sigs)
    dst = tmp / "converted.tdm"
    print(f"wrote {src} ({src.stat().st_size} bytes)")

    app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
    print("LabVIEW", app.Version)
    vi = app.GetVIReference(CONVERTER, "", True)
    ole = vi._oleobj_
    names = ["source file path (*.tdms)", "target file path (*.tdm)",
             "target file operation (2:create or replace)", "error out"]
    vals = [str(src), str(dst), 2, (False, 0, "")]
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, names)
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, vals)
    ole.Invoke(ole.GetIDsOfNames(0, "Call"), 0, pythoncom.DISPATCH_METHOD, 0, vn, vv)

    status, code, source = vv.value[3]
    if status or code:
        print(f"FAIL: LabVIEW returned error {code}: {source}")
        return 1
    if not dst.exists():
        print("FAIL: no .tdm produced")
        return 1
    print(f"LabVIEW converted it cleanly -> {dst} ({dst.stat().st_size} bytes)")

    xml = dst.read_text(encoding="utf-8", errors="replace")
    checks = {
        "channel Accel X": "Accel X" in xml,
        "channel Mic": "Mic" in xml,
        "group Run 1": "Run 1" in xml,
        "unit m/s^2": "m/s^2" in xml,
        "unit Pa": ">Pa<" in xml or "Pa" in xml,
        "wf_increment value": bool(re.search(r"2\.44140625[eE]?-?0*4|0\.000244140625", xml)),
        "wf_start_offset 0.125": "0.125" in xml,
    }
    ok = True
    for label, passed in checks.items():
        print(f"  [{'ok' if passed else 'MISSING'}] {label}")
        ok &= passed
    print("RESULT:", "PASS" if ok else "PARTIAL (conversion clean, see above)")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
