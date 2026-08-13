"""LabVIEW ground truth for the STFT spectrogram.

Calls NI_AdvSigProcTFA "TFA STFT Spectrogram (Real).vi" so the port's
spectrogram scaling, block placement and frequency-bin count are pinned to
LabVIEW rather than guessed.
"""
import os

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

STFT = (r"C:\Program Files\National Instruments\LabVIEW 2022\vi.lib\addons"
        r"\Time Frequency Analysis\Spectrogram.llb"
        r"\TFA STFT Spectrogram (Real).vi")
OUT = r"W:\projects\Charette_AI_Group\SPWB-py\tests\fixtures"
os.makedirs(OUT, exist_ok=True)

app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
print("LabVIEW", app.Version, flush=True)
vi = app.GetVIReference(STFT, "", True)
ole = vi._oleobj_
dispid = ole.GetIDsOfNames(0, "Call")

FS = 1024.0
N = 4096
t = np.arange(N) / FS
rng = np.random.default_rng(99)

cases = {
    # stationary tone: every time step must look the same
    "tone": np.sin(2 * np.pi * 128.0 * t),
    # linear chirp 50 -> 400 Hz: the ridge must climb
    "chirp": np.sin(2 * np.pi * (50.0 * t + (350.0 / (2 * t[-1])) * t ** 2)),
    # two tones + noise
    "mixed": (np.sin(2 * np.pi * 100 * t) + 0.5 * np.sin(2 * np.pi * 300 * t)
              + 0.1 * rng.standard_normal(N)),
}

# SPWB's panel exposes ONE "FFT block size", so window length == frequency
# bins; that is how the application calls this VI and what we reproduce.
BLOCK = 256
TIME_STEPS = 128

out = {"fs": np.array(FS), "N": np.array(N),
       "block": np.array(BLOCK), "time_steps": np.array(TIME_STEPS)}

# NI TFA window ring -> spwb window name (mapped empirically, see probe)
WINDOW_RING = {0: "rectangular", 1: "hanning", 2: "hamming",
               3: "blackman_harris", 4: "exact_blackman", 5: "blackman",
               6: "flat_top", 7: "bh_4term"}

for name, x in cases.items():
    out[f"sig_{name}"] = x
    names = ["signal", "sampling rate", "time-frequency sampling info",
             "window info", "spectrogram", "scale info"]
    # time-frequency sampling info: (time steps == hop, frequency bins)
    # window info: (type, length); type 1 == Hanning in NI's window ring
    vals = [x.tolist(), FS, (TIME_STEPS, BLOCK), (1, BLOCK),
            [], (0.0, 0.0, 0.0, 0.0)]
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 names)
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 vals)
    try:
        ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0, vn, vv)
    except Exception as exc:
        print(f"{name}: FAILED {exc}", flush=True)
        continue
    r = vv.value
    spec = np.asarray(r[4], dtype=float)
    info = r[5]
    out[f"spec_{name}"] = spec
    if info is not None:
        out[f"info_{name}"] = np.array([float(v) for v in info])
    print(f"{name}: spectrogram {spec.shape} scale info={info} "
          f"max={spec.max():.6g}", flush=True)

# one spectrogram per window type, so the ring mapping is regression-tested
tone = cases["tone"]
for code, wname in WINDOW_RING.items():
    names = ["signal", "sampling rate", "time-frequency sampling info",
             "window info", "spectrogram"]
    vals = [tone.tolist(), FS, (TIME_STEPS, BLOCK), (code, BLOCK), []]
    vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 names)
    vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                 vals)
    ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0, vn, vv)
    spec = np.asarray(vv.value[4], dtype=float)
    out[f"win_{wname}"] = spec
    print(f"  window {code} ({wname}): max={spec.max():.8f}", flush=True)

np.savez(os.path.join(OUT, "labview_stft_reference.npz"), **out)
print("saved", flush=True)
