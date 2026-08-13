"""LabVIEW ground truth for the statistics primitives behind the TV Metrics
and Stats tabs.

SPWB's own TVM/statistics VIs take LabVIEW *waveform clusters*, whose
timestamp field does not marshal through COM, so they cannot be called from
here. What matters numerically, though, is the two NI primitives they are
built from - and those take plain arrays:

  Moment about Mean.vi          divides by N     (population moment)
  Std Deviation and Variance.vi divides by N-1   (sample variance)

They disagree with each other, and SPWB's Skewness and Kurtosis mix the
two. This script freezes both so the port cannot drift.

Requires LabVIEW 2022 + pywin32 on Windows.
"""
import os

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

ANALYSIS = (r"C:\Program Files\National Instruments\LabVIEW 2022"
            r"\vi.lib\Analysis")
MOMENT = ANALYSIS + r"\5stat.llb\Moment about Mean.vi"
STDDEV = ANALYSIS + r"\baseanly.llb\Std Deviation and Variance.vi"
RMS = ANALYSIS + r"\5stat.llb\RMS (DBL).vi"
OUT = r"W:\projects\Charette_AI_Group\SPWB-py\tests\fixtures"
os.makedirs(OUT, exist_ok=True)

app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
print("LabVIEW", app.Version, flush=True)


def call(path, names, vals):
    vi = app.GetVIReference(path, "", True)
    ole = vi._oleobj_
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 names)
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 vals)
    ole.Invoke(ole.GetIDsOfNames(0, "Call"), 0, pythoncom.DISPATCH_METHOD, 0,
               vn, vv)
    return vv.value


rng = np.random.default_rng(31)
cases = {
    # deliberately skewed and heavy-tailed, so the higher moments are
    # distinctive rather than near-Gaussian
    "skewed": np.concatenate([rng.standard_normal(400) * 2.5 + 1.3,
                              rng.standard_normal(20) * 6 + 12]),
    "tone": 3.0 * np.sin(2 * np.pi * 0.01 * np.arange(500)) + 0.7,
    "gaussian": rng.standard_normal(2000),
    "tiny": np.array([1.0, 2.0, 4.0, 8.0, 16.0]),
}

out = {}
for name, x in cases.items():
    out[f"x_{name}"] = x
    out[f"rms_{name}"] = np.array(
        call(RMS, ["X", "rms value"], [x.tolist(), 0.0])[1])
    r = call(STDDEV, ["X", "mean", "standard deviation", "variance"],
             [x.tolist(), 0.0, 0.0, 0.0])
    out[f"mean_{name}"] = np.array(float(r[1]))
    out[f"std_{name}"] = np.array(float(r[2]))
    out[f"var_{name}"] = np.array(float(r[3]))
    for order in (2, 3, 4):
        m = call(MOMENT, ["X", "order", "moment"], [x.tolist(), order, 0.0])[2]
        out[f"moment{order}_{name}"] = np.array(float(m))
    print(f"  {name:9s} rms={out[f'rms_{name}']:.8f} "
          f"std={out[f'std_{name}']:.8f} var={out[f'var_{name}']:.8f} "
          f"m3={out[f'moment3_{name}']:.8f} m4={out[f'moment4_{name}']:.8f}",
          flush=True)

np.savez(os.path.join(OUT, "labview_metrics_reference.npz"), **out)
print("saved", flush=True)
