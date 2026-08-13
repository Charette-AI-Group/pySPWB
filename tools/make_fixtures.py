"""Generate LabVIEW ground-truth fixtures for the spwb-py regression tests.

Calls (via COM, explicit dispids):
  NI_AALPro.lvlib:Scaled Time Domain Window (DBL).vi  (X, window, window parameter)
  NI_AALPro.lvlib:Auto Power Spectrum.vi              (Signal (V), dt)
"""
import os
import pathlib

import numpy as np
import pythoncom
import win32com.client

STDW = r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\Analysis\0measdsp.llb\Scaled Time Domain Window (DBL).vi"
APS = r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\Analysis\0measdsp.llb\Auto Power Spectrum.vi"
# found relative to this script, so the tools follow the checkout wherever
# it is moved rather than writing to a stale absolute path
OUT = str(pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures")
os.makedirs(OUT, exist_ok=True)

app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
print("LabVIEW", app.Version, flush=True)

from win32com.client import VARIANT


def call_vi(path, names, vals):
    """Run a VI via VirtualInstrument.Call with byref SAFEARRAY params;
    returns the paramVals array after execution (outputs filled in)."""
    vi = app.GetVIReference(path, "", True)  # reserve for call
    ole = vi._oleobj_
    dispid = ole.GetIDsOfNames(0, "Call")
    vnames = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, names)
    vvals = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, vals)
    ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0, vnames, vvals)
    return vvals.value

# --- test signals -----------------------------------------------------------
N = 1024
dt = 1.0 / 1024.0
t = np.arange(N) * dt
rng = np.random.default_rng(20260809)
signals = {
    "sine_bin":    2.00 * np.sin(2 * np.pi * 128.0 * t),          # exact bin
    "sine_offbin": 1.50 * np.sin(2 * np.pi * 100.5 * t + 0.7),    # straddles bins
    "noise":       rng.standard_normal(N),
    "multitone":   0.5 + 1.0 * np.sin(2 * np.pi * 50.0 * t) \
                       + 0.25 * np.sin(2 * np.pi * 300.0 * t + 1.1),
}
# NI Scaled Time Domain Window codes (probed empirically; 10 has no NI
# equivalent -- Blackman-Nuttall will be analytic-only in the port):
windows = {  # name -> (NI code, parameter)
    "rectangular": (0, float("nan")),
    "hanning": (1, float("nan")),
    "hamming": (2, float("nan")),
    "blackman_harris": (3, float("nan")),
    "exact_blackman": (4, float("nan")),
    "blackman": (5, float("nan")),
    "flat_top": (6, float("nan")),
    "bh_4term": (7, float("nan")),
    "bh_7term": (8, float("nan")),
    "low_sidelobe": (9, float("nan")),
    "blackman_nuttall": (11, float("nan")),   # enbw/cg match B-N constants
    "triangle": (30, float("nan")),           # cg=0.5, enbw=4/3 -> Bartlett
    "bartlett_hanning": (31, float("nan")),
    "bohman": (32, float("nan")),
    "parzen": (33, float("nan")),
    "welch": (34, float("nan")),
    "kaiser": (60, 8.0),
    "dolph_chebyshev": (61, 60.0),
    "gaussian": (62, 0.2),
}

out = {"dt": np.array(dt), "N": np.array(N)}
for sname, x in signals.items():
    out[f"sig_{sname}"] = x
    # raw APS (no window)
    vals_back = call_vi(APS, ["Signal (V)", "dt", "Power Spectrum (V^2 rms)", "df"],
                        [x.tolist(), dt, [], 0.0])
    aps, df = np.asarray(vals_back[2]), float(vals_back[3])
    out[f"aps_{sname}"] = aps
    out["df"] = np.array(df)
    print(f"APS {sname}: len={len(aps)} df={df}", flush=True)

for wname, (code, param) in windows.items():
    x = signals["sine_offbin"]
    vals_back = call_vi(STDW, ["X", "window", "window parameter", "Windowed X", "window properties"],
                        [x.tolist(), int(code), param, [], (0.0, 0.0)])
    wx = np.asarray(vals_back[3])
    props = vals_back[4]
    enbw, cg = float(props[0]), float(props[1])
    out[f"win_{wname}_wx"] = wx
    out[f"win_{wname}_props"] = np.array([enbw, cg])
    # windowed APS as well (full chain)
    vals_back = call_vi(APS, ["Signal (V)", "dt", "Power Spectrum (V^2 rms)", "df"],
                        [wx.tolist(), dt, [], 0.0])
    out[f"winaps_{wname}"] = np.asarray(vals_back[2])
    print(f"STDW {wname}: enbw={enbw:.6f} cg={cg:.6f}", flush=True)

np.savez(os.path.join(OUT, "labview_reference.npz"), **out)
print("saved", os.path.join(OUT, "labview_reference.npz"), flush=True)
