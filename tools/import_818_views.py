#!/usr/bin/env python3
"""Import the two manual-import views (build_views_818.py) into an instance through the content
API, and prove they landed by exporting views back and finding them by title.

This WRITES. Point it only at a disposable instance (~/ops818.env). It proves the XML is
accepted by that version's view importer; the customer path is the UI dialog
(Visualize -> Views -> Import), which takes the same ViewDef XML.
"""
import argparse
import io
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install_content as ic  # noqa: E402
from verify_target import env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SINGLES = [os.path.join(HERE, "build", "818", f) for f in (
    "MemTier_818_Cluster_Sizing_Inputs.xml", "MemTier_818_VM_Allocation_Powered_On.xml")]
TITLES = ["MemTier 8.18 Cluster Sizing Inputs", "MemTier 8.18 VM Allocation Powered On"]


def export_views(ops):
    prior = (ops.req("GET", "/api/content/operations/export") or {}).get("startTime") or 0
    ic._post_retry(ops, "/api/content/operations/export", "views export",
                   body={"scope": "CUSTOM", "contentTypes": ["VIEW_DEFINITIONS"]})
    deadline = time.time() + 300
    while time.time() < deadline:
        s = ops.req("GET", "/api/content/operations/export") or {}
        if str(s.get("state", "")).startswith("FINI") and (s.get("startTime") or 0) > prior:
            return ops.req("GET", "/api/content/operations/export/zip", accept="application/zip")
        time.sleep(3)
    sys.exit("views export did not finish")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="~/ops818.env")
    a = ap.parse_args()
    e = env(a.env)
    ops = ic.Ops(e["OPS_HOST"], e["OPS_USER"], e["OPS_PASS"])
    me = ops.req("GET", "/api/auth/currentuser") or {}
    owner = me.get("id") or me.get("userId")
    marker = ic.discover_marker(ops)
    print(f"### {e['OPS_HOST']}  user id={owner}  marker={marker}")
    blob, n = ic.views_zip(SINGLES, marker, owner)
    print(f"### importing {n} views")
    ic.do_import(ops, blob, "views")
    print("### exporting views back")
    z = zipfile.ZipFile(io.BytesIO(export_views(ops)))
    text = ""
    for name in z.namelist():
        data = z.read(name)
        if name.endswith(".zip"):
            inner = zipfile.ZipFile(io.BytesIO(data))
            text += "".join(inner.read(n).decode(errors="ignore") for n in inner.namelist())
        else:
            text += data.decode(errors="ignore")
    missing = [t for t in TITLES if f"<Title>{t}</Title>" not in text]
    for t in TITLES:
        print(f"   {'FOUND  ' if t not in missing else 'MISSING'} {t}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
