"""Dump NI's raw windows (x = ones -> wx = w/CG) for exact comparison."""
import os

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

STDW = r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\Analysis\0measdsp.llb\Scaled Time Domain Window (DBL).vi"
OUT = r"W:\projects\Charette_AI_Group\SPWB-py\tests\fixtures"
app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
N = 1024
x = np.ones(N).tolist()
vi = app.GetVIReference(STDW, "", True)
ole = vi._oleobj_
dispid = ole.GetIDsOfNames(0, "Call")

codes = {
    "rectangular": (0, float("nan")), "hanning": (1, float("nan")),
    "hamming": (2, float("nan")), "blackman_harris": (3, float("nan")),
    "exact_blackman": (4, float("nan")), "blackman": (5, float("nan")),
    "flat_top": (6, float("nan")), "bh_4term": (7, float("nan")),
    "bh_7term": (8, float("nan")), "low_sidelobe": (9, float("nan")),
    "blackman_nuttall": (11, float("nan")), "triangle": (30, float("nan")),
    "bartlett_hanning": (31, float("nan")), "bohman": (32, float("nan")),
    "parzen": (33, float("nan")), "welch": (34, float("nan")),
    "kaiser": (60, 8.0), "dolph_chebyshev": (61, 60.0),
    "gaussian": (62, 0.2),
}
out = {}
for name, (code, param) in codes.items():
    vals = [x, int(code), param, [], (0.0, 0.0)]
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 ["X", "window", "window parameter", "Windowed X", "window properties"])
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, vals)
    ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0, vn, vv)
    o = vv.value
    wx = np.asarray(o[3]); enbw, cg = float(o[4][0]), float(o[4][1])
    out[f"raww_{name}"] = wx * cg   # recover unscaled w
    out[f"rawprops_{name}"] = np.array([enbw, cg])
    print(f"{name:18s} enbw={enbw:.10f} cg={cg:.10f}", flush=True)
np.savez(os.path.join(OUT, "labview_raw_windows.npz"), **out)
print("saved")
