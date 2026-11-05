#!/usr/bin/env python3
"""Check the two manual-import views (build_views_818.py) against an Operations instance.

For every key a view column or view filter uses: is it declared for that object type on this
version, what does this version call it, and is it collected by default? A key that is declared
but not collected by default has no history on a customer who never changed policy -- that is
how per-VM Guest Active would have read blank on 8.18 (KB 445499).

Needs no hosts: declarations come from the built-in vCenter adapter's describe, not from data.
Read-only. Usage: python3 verify_818_views.py --env ~/ops818.env
"""
import argparse
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_target import Ops, env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XML = os.path.join(HERE, "build", "818", "MemTier_818_Views.xml")


def wanted():
    x = open(XML).read()
    want = []
    for vd in re.findall(r"<ViewDef.*?</ViewDef>", x, re.S):
        title = re.search(r"<Title>([^<]+)</Title>", vd).group(1)
        for m in re.finditer(r'attributeKey" value="([^"]+)".*?resourceKind" value="([^"]+)"'
                             r'.*?isProperty" value="(true|false)".*?displayName" value="([^"]+)"',
                             vd, re.S):
            want.append((m.group(2), m.group(1), m.group(3) == "true", f"{title}: {m.group(4)}"))
        flt = re.search(r"filter='([^']+)'|filter=\"([^\"]+)\"", vd)
        if flt:
            kind = re.search(r'resourceKind="([^"]+)"', vd).group(1)
            body = (flt.group(1) or flt.group(2)).replace("&quot;", '"')
            for k in re.findall(r'"metricKey":"([^"]+)"', body):
                want.append((kind, k, True, f"{title}: filter"))
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="~/ops818.env")
    a = ap.parse_args()
    e = env(a.env)
    ops = Ops(e)
    ver = ops.req("/versions/current")
    print(f"### {e['OPS_HOST']}  {ver.get('releaseName')}")
    decl = {}
    for kind in sorted({k for k, *_ in wanted()}):
        q = urllib.parse.quote(kind)
        for what in ("statkeys", "properties"):
            for attr in ops.req(f"/adapterkinds/VMWARE/resourcekinds/{q}/{what}?pageSize=10000"
                                ).get("resourceTypeAttributes", []):
                decl[(kind, attr["key"])] = (what, attr)
    bad = 0
    for kind, key, prop, use in wanted():
        hit = decl.get((kind, key))
        if not hit:
            bad += 1
            print(f"   MISS  {kind:24s} {key:34s} not declared on this version  ({use})")
            continue
        what, attr = hit
        dm = attr.get("defaultMonitored")
        flag = "OK  " if dm in (True, None) and (what == "properties") == prop else "WARN"
        if flag == "WARN":
            bad += 1
        print(f"   {flag}  {kind:24s} {key:34s} {what[:-1] if what.endswith('s') else what:9s} "
              f"name={attr.get('name')!r} unit={attr.get('unit')!r} defaultMonitored={dm}  ({use})")
    # Control: per-VM Guest Active is off by default on 8.18 and on in 9.1 (KB 445499). If this
    # does not read False on 8.18, the defaultMonitored flag is not what it seems.
    ctl = ops.req("/adapterkinds/VMWARE/resourcekinds/VirtualMachine/statkeys?pageSize=10000")
    for attr in ctl.get("resourceTypeAttributes", []):
        if attr["key"] == "mem|active_average":
            print(f"   control: VirtualMachine mem|active_average defaultMonitored="
                  f"{attr.get('defaultMonitored')} (KB 445499: False on 8.18, True on 9.1)")
    print("\nRESULT:", "all keys declared and collected by default" if not bad
          else f"{bad} problem(s) above")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
