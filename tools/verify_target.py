#!/usr/bin/env python3
"""Check the BUILT content against a target Operations instance, before installing on it.

Written for the 8.18 / vCenter 8 target. Everything here was built and proven on VCF Operations
9.1.1 against a VCF 9 vCenter, and the build's own --verify checks a hand-kept metric list
rather than what the views actually use -- which is how view-only keys went unchecked. This
reads every key out of build/ (views, super metric formulas, view filters, dashboards) and
asks the instance in ~/ops.env (or --env) about each one:

    OK    declared for the kind AND observed on a live object
    WARN  declared but not observed: exists on this version, not collecting here (policy,
          no such objects, or a property not yet populated)
    MISS  not declared for the kind on this instance at all -- a column that will be blank,
          or a super metric that computes nothing, on this version

--formulas additionally POSTs each super metric formula as a temporary super metric named
"MemTier PROBE <n>", records accept/reject, and deletes it. The API validates on create
(LESSONS.md 11: a 500 is a definitive rejection). This WRITES to the target, briefly; it is
off unless asked for. Formulas referencing other super metrics resolve by id, so run it on an
instance where the pak is installed, or rejections of those formulas mean nothing.

Read-only otherwise. Usage:
    python3 verify_target.py                  # against ~/ops.env
    python3 verify_target.py --env ~/ops818.env --formulas
"""
import argparse
import glob
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# Keys this pack is known to take from VCF 9-only features. Listed so a MISS on 8.18 reads as
# expected-and-handled rather than as a surprise; every other MISS is a defect for 8.18.
KNOWN_9X_ONLY = {"summary|total_number_mt_hosts"}


def env(path):
    e = {}
    for line in open(os.path.expanduser(path)):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


class Ops:
    def __init__(self, e):
        self.base = f"https://{e['OPS_HOST']}/suite-api/api"
        self.tok = None
        self.tok = self.req("/auth/token/acquire", "POST",
                            {"username": e["OPS_USER"], "password": e["OPS_PASS"]})["token"]

    def req(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Accept", "application/json")
        if data:
            r.add_header("Content-Type", "application/json")
        if self.tok:
            r.add_header("Authorization", f"vRealizeOpsToken {self.tok}")
        with urllib.request.urlopen(r, context=CTX, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}


def wanted_keys():
    """(adapter, kind, key, is_property) -> where it is used."""
    want = {}

    def add(adapter, kind, key, prop, where):
        want.setdefault((adapter, kind, key, prop), set()).add(where)

    for f in sorted(glob.glob(os.path.join(BUILD, "reports", "*", "*.xml"))):
        x = open(f).read()
        title = re.search(r"<Title>([^<]+)</Title>", x).group(1)
        for m in re.finditer(r'attributeKey" value="([^"]+)".*?adapterKind" value="([^"]+)"'
                             r'.*?resourceKind" value="([^"]+)".*?isProperty" value="(true|false)"',
                             x, re.S):
            if not m.group(1).startswith("Super Metric|"):
                add(m.group(2), m.group(3), m.group(1), m.group(4) == "true", f"view {title}")
        for m in re.finditer(r'resourceKind="([^"]+)"[^>]*filter="([^"]+)"|filter="([^"]+)"[^>]*resourceKind="([^"]+)"', x):
            kind = m.group(1) or m.group(4)
            flt = (m.group(2) or m.group(3)).replace("&quot;", '"')
            for k in re.findall(r'"metricKey":"([^"]+)"', flt):
                add("VMWARE", kind, k, True, f"view filter {title}")
    sms = json.load(open(os.path.join(BUILD, "supermetric.json")))
    for v in sms.values():
        for m in re.finditer(r"adaptertype=(\w+), objecttype=([\w ]+?), metric=([^,}]+)", v["formula"]):
            add(m.group(1), m.group(2), m.group(3).strip(), False, f"super metric {v['name']}")
    for d in sorted(glob.glob(os.path.join(BUILD, "dashboard*.json"))):
        s = json.load(open(d))
        for w in s["dashboards"][0]["widgets"]:
            blob = json.dumps(w.get("config", {}))
            for k in re.findall(r'"(?:colorBy|sizeBy|metricKey|statKey)":\s*\{?[^}]*?"?key"?:\s*"([^"]+)"', blob):
                add("VMWARE", "HostSystem", k, False, f"dashboard widget {w['title']}")
    return want, sms


def check_keys(ops, want):
    by_kind = {}
    for (adapter, kind, key, prop) in want:
        by_kind.setdefault((adapter, kind), set()).add((key, prop))
    results = []
    for (adapter, kind), keys in sorted(by_kind.items()):
        try:
            declared = ops.req(f"/adapterkinds/{urllib.parse.quote(adapter)}/resourcekinds/"
                               f"{urllib.parse.quote(kind)}/statkeys?pageSize=10000")
            declared = {a.get("key") for a in declared.get("resourceTypeAttributes", [])}
        except urllib.error.HTTPError as e:
            for key, prop in sorted(keys):
                results.append(("MISS", adapter, kind, key, prop, f"kind not on instance (HTTP {e.code})"))
            continue
        try:
            props_declared = ops.req(f"/adapterkinds/{urllib.parse.quote(adapter)}/resourcekinds/"
                                     f"{urllib.parse.quote(kind)}/properties?pageSize=10000")
            props_declared = {a.get("key") for a in props_declared.get("resourceTypeAttributes", [])}
        except urllib.error.HTTPError:
            props_declared = set()
        rl = ops.req(f"/resources?adapterKind={urllib.parse.quote(adapter)}"
                     f"&resourceKind={urllib.parse.quote(kind)}&pageSize=12").get("resourceList", [])
        observed, observed_props = set(), set()
        for r in rl:
            rid = r["identifier"]
            observed |= {s["key"] for s in ops.req(f"/resources/{rid}/statkeys").get("stat-key", [])}
            observed_props |= {p["name"] for p in ops.req(f"/resources/{rid}/properties").get("property", [])}
        for key, prop in sorted(keys):
            dec = key in (props_declared if prop else declared) or key in declared or key in props_declared
            obs = key in (observed_props if prop else observed)
            status = "OK" if dec and obs else ("WARN" if dec else ("MISS" if not obs else "OK"))
            note = "" if status == "OK" else (
                "declared, not observed on the sampled objects" if status == "WARN" else
                ("expected: VCF 9-only" if key in KNOWN_9X_ONLY else "NOT DECLARED on this version"))
            results.append((status, adapter, kind, key, prop, note))
    return results


def check_formulas(ops, sms):
    out = []
    for i, v in enumerate(sms.values()):
        body = {"name": f"MemTier PROBE {i}", "formula": v["formula"], "description": "probe",
                "unitId": v.get("unitId", ""), "resourceKinds": v.get("resourceKinds", [])}
        try:
            created = ops.req("/supermetrics", "POST", body)
            sid = created.get("id")
            out.append(("OK", v["name"]))
            if sid:
                ops.req(f"/supermetrics/{sid}", "DELETE")
        except urllib.error.HTTPError as e:
            out.append((f"REJECTED {e.code}", v["name"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="~/ops.env")
    ap.add_argument("--formulas", action="store_true",
                    help="WRITES: create and delete each formula to prove the target accepts it")
    a = ap.parse_args()
    e = env(a.env)
    ops = Ops(e)
    ver = ops.req("/versions/current")
    print(f"### target: {e['OPS_HOST']}  {ver.get('releaseName')}  "
          f"({ver.get('major')}.{ver.get('minor')}.{ver.get('minorMinor', '')})")
    want, sms = wanted_keys()
    res = check_keys(ops, want)
    print(f"### {len(res)} keys used by the built content")
    for st, adapter, kind, key, prop, note in res:
        if st != "OK":
            uses = sorted(want[(adapter, kind, key, prop)])
            print(f"   {st:4s} {kind:24s} {'prop ' if prop else 'stat '}{key:44s} {note}")
            print(f"        used by: {'; '.join(uses)[:220]}")
    counts = {s: sum(1 for r in res if r[0] == s) for s in ("OK", "WARN", "MISS")}
    print(f"   {counts}")
    bad = [r for r in res if r[0] == "MISS" and r[3] not in KNOWN_9X_ONLY]
    if a.formulas:
        print("### super metric formulas (create + delete)")
        f = check_formulas(ops, sms)
        for st, name in f:
            if st != "OK":
                print(f"   {st}  {name}")
        print(f"   {sum(1 for s, _ in f if s == 'OK')}/{len(f)} accepted")
        bad += [x for x in f if x[0] != "OK"]
    print("\nRESULT:", "no blocking misses" if not bad else f"{len(bad)} blocking problem(s) above")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
