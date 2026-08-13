"""Batch-export all SPWB VIs to HTML docs (block diagram, panel, connector,
controls, subVI list) via LabVIEW 2022 COM automation.

Resumable: skips VIs whose export dir already has doc.html.
Self-healing: if LabVIEW dies (RPC failure), relaunches and continues.
"""
import json
import os
import time

import pythoncom
import win32com.client

REPO = r"W:\projects\Charette_AI_Group\SPWB"
OUT = r"W:\projects\Charette_AI_Group\SPWB_export"
MANIFEST = os.path.join(OUT, "manifest.json")

SKIP_DIRS = {"compiled", ".git", ".webSiteBranch", ".wikiBranch"}

def collect_vis():
    vis = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith((".vi", ".vit")):
                p = os.path.join(root, f)
                vis.append(p)
    return sorted(vis)

def launch():
    app = win32com.client.dynamic.Dispatch("LabVIEW.Application")
    app.PrintSetupCustomConnector = True
    app.PrintSetupCustomDescription = True
    app.PrintSetupCustomPanel = True
    app.PrintSetupCustomControls = True
    app.PrintSetupCustomControlDesc = True
    app.PrintSetupCustomControlTypes = True
    app.PrintSetupCustomDiagram = True
    app.PrintSetupCustomDiagramHidden = True
    app.PrintSetupCustomDiagramRepeat = False
    app.PrintSetupCustomSubVIs = True
    app.PrintSetupCustomLabel = True
    return app

def is_rpc_dead(exc):
    return getattr(exc, "hresult", None) in (-2147023170, -2147023174, -2147418111)

def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            manifest = json.load(fh)

    vis = collect_vis()
    print(f"{len(vis)} VIs to process", flush=True)

    app = launch()
    print("LabVIEW", app.Version, flush=True)

    done = fail = skip = 0
    t0 = time.time()
    for i, vip in enumerate(vis):
        rel = os.path.relpath(vip, REPO)
        out_dir = os.path.join(OUT, "vis", rel)  # dir named after the VI file
        html = os.path.join(out_dir, "doc.html")
        if os.path.exists(html) and rel in manifest and manifest[rel].get("status") == "ok":
            skip += 1
            continue
        os.makedirs(out_dir, exist_ok=True)
        entry = {"path": rel, "status": "fail", "error": None}
        for attempt in (1, 2):
            vi = None
            try:
                vi = app.GetVIReference(vip, "", False)
                entry["qualified_name"] = vi.Name
                try: entry["description"] = vi.Description
                except Exception: entry["description"] = ""
                try: entry["callees"] = list(vi.Callees)
                except Exception: entry["callees"] = []
                try: entry["reentrant"] = bool(vi.IsReentrant)
                except Exception: pass
                # Invoke via explicit dispid: win32com's dynamic __getattr__ probe
                # makes the first PrintVIToHTML call on each new wrapper fail.
                ole = vi._oleobj_
                dispid = ole.GetIDsOfNames(0, "PrintVIToHTML")
                ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0,
                           html, False, 4, 0, 8, out_dir)
                entry["status"] = "ok"
                entry["error"] = None
                break
            except Exception as e:
                entry["error"] = str(e)
                if is_rpc_dead(e) and attempt == 1:
                    print(f"  !! LabVIEW died at {rel}; relaunching...", flush=True)
                    time.sleep(5)
                    os.system('taskkill /IM LabVIEW.exe /F >nul 2>&1')
                    time.sleep(3)
                    app = launch()
                else:
                    break
            finally:
                vi = None
        manifest[rel] = entry
        done += entry["status"] == "ok"
        fail += entry["status"] != "ok"
        if (done + fail) % 10 == 0:
            el = time.time() - t0
            print(f"  [{i+1}/{len(vis)}] ok={done} fail={fail} skip={skip} "
                  f"({el:.0f}s, {el/max(done+fail,1):.1f}s/vi)", flush=True)
            with open(MANIFEST, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=1)

    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"DONE ok={done} fail={fail} skip={skip} in {time.time()-t0:.0f}s", flush=True)
    fails = [k for k, v in manifest.items() if v.get("status") != "ok"]
    if fails:
        print("FAILED VIs:", flush=True)
        for f in fails:
            print("  ", f, "->", manifest[f].get("error", "")[:120], flush=True)

if __name__ == "__main__":
    main()
