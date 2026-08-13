"""LabVIEW ground truth for the transfer-function chain.

Calls NI_AALPro Cross Power Spectrum.vi (magnitude + phase) so the Python
port's cross-spectrum convention (which side is conjugated, and the 2/N^2
scaling) is pinned to LabVIEW rather than guessed.
"""
import os

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

CPS = r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\Analysis\0measdsp.llb\Cross Power Spectrum.vi"
APS = r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\Analysis\0measdsp.llb\Auto Power Spectrum.vi"
OUT = r"W:\projects\Charette_AI_Group\SPWB-py\tests\fixtures"
os.makedirs(OUT, exist_ok=True)

app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
print("LabVIEW", app.Version, flush=True)


def call(path, names, vals):
    vi = app.GetVIReference(path, "", True)
    ole = vi._oleobj_
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, names)
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, vals)
    ole.Invoke(ole.GetIDsOfNames(0, "Call"), 0, pythoncom.DISPATCH_METHOD, 0, vn, vv)
    return vv.value


N = 1024
dt = 1.0 / 1024.0
t = np.arange(N) * dt
rng = np.random.default_rng(4242)

# x -> known system -> y, so the expected H is analytic per bin as well
x = rng.standard_normal(N)
# y = 2x delayed by 3 samples + independent noise (gives coherence < 1)
y = 2.0 * np.roll(x, 3) + 0.3 * rng.standard_normal(N)

cases = {
    "noise_pair": (x, y),
    "sine_pair": (np.sin(2 * np.pi * 64 * t),
                  1.5 * np.sin(2 * np.pi * 64 * t + 0.9)),
    "mixed": (rng.standard_normal(N) + np.sin(2 * np.pi * 100 * t),
              rng.standard_normal(N) + 2 * np.sin(2 * np.pi * 100 * t - 0.4)),
}

out = {"dt": np.array(dt), "N": np.array(N)}
for name, (sx, sy) in cases.items():
    out[f"x_{name}"] = sx
    out[f"y_{name}"] = sy

    vals = call(CPS,
                ["Signal X (V)", "dt", "Signal Y (V)",
                 "Cross Power XY Spectrum Mag (V^2rms)",
                 "Cross Power XY Spectrum Phase (radians)", "df"],
                [sx.tolist(), dt, sy.tolist(), [], [], 0.0])
    mag = np.asarray(vals[3])
    phase = np.asarray(vals[4])
    df = float(vals[5])
    out[f"cps_mag_{name}"] = mag
    out[f"cps_phase_{name}"] = phase

    for label, sig in (("xx", sx), ("yy", sy)):
        vals = call(APS, ["Signal (V)", "dt", "Power Spectrum (V^2 rms)", "df"],
                    [sig.tolist(), dt, [], 0.0])
        out[f"aps_{label}_{name}"] = np.asarray(vals[2])

    out["df"] = np.array(df)
    print(f"{name}: len={len(mag)} df={df} "
          f"peak|Sxy|={mag.max():.6g}", flush=True)

np.savez(os.path.join(OUT, "labview_tf_reference.npz"), **out)
print("saved", flush=True)
