"""Cross-check: does LabVIEW 2022 read the WAV files spwb writes?

Writes a WAV with spwb.processing.io.write_wave, then has LabVIEW's own
`Snd Read Wave File.vi` read it back and compares sample rate, channel
count and the waveform data.

Requires LabVIEW 2022 + pywin32. Run from the repo root:
    python tools/verify_labview_reads_spwb_wav.py
"""
import os
import sys
import tempfile

import numpy as np
import pythoncom
import win32com.client
from win32com.client import VARIANT

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
from spwb import Signal
from spwb.processing.io import read_wave, write_wave

SND_READ = (r"C:\Program Files\National Instruments\LabVIEW 2022"
            r"\vi.lib\sound\lvsound.llb\Snd Read Wave File.vi")

FS = 8000
N = 4000
AMPLITUDE = 9.81

out_dir = tempfile.mkdtemp(prefix="spwb_wav_")
t = np.arange(N) / FS
signal = Signal("Accel X", AMPLITUDE * np.sin(2 * np.pi * 200 * t),
                1.0 / FS, y_unit="m/s2")
(written,) = write_wave(os.path.join(out_dir, "check.wav"), [signal])
print(f"spwb wrote: {os.path.basename(written)}", flush=True)

app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
print("LabVIEW", app.Version, flush=True)

vi = app.GetVIReference(SND_READ, "", True)
names = ["wave file path", "mono 16-bit", "sound format"]
ole = vi._oleobj_
vn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
             names)
vv = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
             [str(written), [], (0, 0, 0)])
try:
    ole.Invoke(ole.GetIDsOfNames(0, "Call"), 0, pythoncom.DISPATCH_METHOD, 0,
               vn, vv)
except Exception as exc:
    print("FAILED to call Snd Read Wave File.vi:", exc)
    raise SystemExit(1)

result = vv.value
data = np.asarray(result[1], dtype=float)
fmt = result[2]                       # (sound quality, rate, bits per sample)
print(f"LabVIEW read   : {len(data)} samples, format {tuple(fmt)}", flush=True)

# spwb's own read of the same file, for comparison
(back,) = read_wave(written)
print(f"spwb read back : {back.n_samples} samples, {back.fs:g} Hz, "
      f"peak {np.abs(back.y).max():.4f} {back.y_unit}", flush=True)

# The cluster is (sound quality, rate, bits per sample) and every field is an
# ENUM INDEX, not a literal value. Mapping probed empirically against files of
# known rate:
LV_CHANNELS = {0: "mono", 1: "stereo"}
LV_RATES = {0: 11025, 1: 22050, 2: 44100, 3: 8000}
LV_BITS = {0: 8, 1: 16}

ok = True
lv_channels = LV_CHANNELS.get(int(fmt[0]), "?")
lv_rate = LV_RATES.get(int(fmt[1]))
lv_bits = LV_BITS.get(int(fmt[2]))
print(f"LabVIEW decoded: {lv_channels}, {lv_rate} Hz, {lv_bits}-bit",
      flush=True)

if lv_channels != "mono":
    ok = False
    print(f"!! channel count mismatch: {lv_channels}", flush=True)
if lv_bits != 16:
    ok = False
    print(f"!! bit depth mismatch: {lv_bits}", flush=True)
if lv_rate != FS:
    ok = False
    print(f"!! rate mismatch: LabVIEW says {lv_rate} Hz, file is {FS} Hz",
          flush=True)
if len(data) != N:
    ok = False
    print(f"!! length mismatch: LabVIEW {len(data)} vs written {N}", flush=True)

# LabVIEW hands back the raw int16 codes; compare sample by sample
if len(data) == N:
    err = float(np.max(np.abs(data / 32768.0 * AMPLITUDE - back.y)))
    print(f"max |LabVIEW - spwb| = {err:.3e} {back.y_unit}", flush=True)
    if err > AMPLITUDE * 1e-6:
        ok = False
        print("!! sample data disagrees", flush=True)

if abs(np.abs(back.y).max() - AMPLITUDE) > AMPLITUDE * 1e-3:
    ok = False
    print("!! amplitude did not survive the round trip", flush=True)

print("\nNote: LabVIEW's Snd Read Wave File.vi reports the rate as an index "
      "into\n{11025, 22050, 44100, 8000} Hz. Files at any other rate "
      "(48 kHz, 51.2 kHz ...)\nstill read their samples correctly but are "
      "reported as 11025 Hz - a limitation\nof the original LabVIEW sound "
      "path that this port does not share.", flush=True)

print("\nRESULT:", "PASS" if ok else "FAIL", flush=True)
raise SystemExit(0 if ok else 1)
