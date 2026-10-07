#!/usr/bin/env python3
"""Install the sizing dashboard and super metrics WITHOUT a pak, via the content-import API.

Why this exists: four pak uploads have now failed (LESSONS.md 4.12) -- three registered
nothing silently, the fourth failed at "Applied Adapter". The content-import endpoint is a
different, documented path that sentania-labs' installer uses in production against Aria
Operations 8.18 and VCF Operations 9.x. The wire format below is theirs, reimplemented for
this content only; credit: github.com/sentania-labs/vcf-content-factory-bundles.

It also does the thing a *working* pak would NOT do: enable the super metrics in the active
policy. Super metrics arrive disabled however they are imported (LESSONS.md 4.13), and the
two-step enable (resource-kind assign, then policy export/edit/import) is the only method
known to work for content-zip imports.

    python3 install_content.py                 # import + enable
    python3 install_content.py --dry-run       # build the zips, write them to build/, send nothing
    python3 install_content.py --no-enable     # import only

Credentials: --host and --user, with the password prompted for. If ~/ops.env exists with
OPS_HOST / OPS_USER / OPS_PASS it is used as a fallback, which is a convenience for the machine
this was developed on and not required.
"""
import argparse
import getpass
import io
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.environ.get("MEMTIER_CONTENT") or os.path.join(os.path.dirname(HERE), "content")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def env():
    """Optional ~/ops.env fallback; absent on any normal machine, which is fine."""
    e = {}
    path = os.path.expanduser("~/ops.env")
    if not os.path.exists(path):
        return e
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


def credentials(args):
    e = env()
    host = args.host or e.get("OPS_HOST")
    user = args.user or e.get("OPS_USER")
    if not host or not user:
        sys.exit("need --host and --user (or an ~/ops.env with OPS_HOST/OPS_USER)")
    password = args.password or os.environ.get("OPS_PASSWORD") or e.get("OPS_PASS")
    if not password:
        password = getpass.getpass(f"password for {user}@{host}: ")
    return host, user, password


class Ops:
    def __init__(self, host, user, password):
        self.base = f"https://{host}/suite-api"
        self.token = None
        r = self.req("POST", "/api/auth/token/acquire",
                     body={"username": user, "password": password})
        self.token = r["token"]

    def req(self, method, path, body=None, raw=None, content_type=None, accept="application/json"):
        url = self.base + path
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Accept", accept)
        if data is not None:
            r.add_header("Content-Type", content_type or "application/json")
        if self.token:
            r.add_header("Authorization", f"vRealizeOpsToken {self.token}")
        with urllib.request.urlopen(r, context=CTX, timeout=180) as resp:
            payload = resp.read()
            if accept != "application/json":
                return payload
            return json.loads(payload) if payload else {}

    def multipart(self, path, field, filename, blob, params=""):
        """urllib has no multipart helper; build one. The importer is strict about the part
        name ('contentFile') and rejects anything else with a 400."""
        boundary = "----memtier" + str(int(time.time() * 1000))
        body = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: application/zip\r\n\r\n").encode() + blob + \
               f"\r\n--{boundary}--\r\n".encode()
        return self.req("POST", path + params, raw=body,
                        content_type=f"multipart/form-data; boundary={boundary}")


def discover_marker(ops):
    """The importer rejects a bundle whose marker filename is not the server's own. The only
    way to learn it is to run a throwaway export and read the name out of the zip."""
    def state():
        try:
            return ops.req("GET", "/api/content/operations/export") or {}
        except urllib.error.HTTPError:
            return {}
    deadline = time.time() + 180
    while (state().get("state") or "") in ("RUNNING", "INITIALIZED"):
        if time.time() > deadline:
            sys.exit("a prior content export never finished; cannot discover the marker")
        time.sleep(2)
    prior = state().get("startTime") or 0
    ops.req("POST", "/api/content/operations/export",
            body={"scope": "CUSTOM", "contentTypes": ["SUPER_METRICS"]})
    deadline = time.time() + 180
    while True:
        s = state()
        if (s.get("startTime") or 0) > prior and str(s.get("state", "")).startswith("FINI"):
            break
        if time.time() > deadline:
            sys.exit(f"marker-probe export timed out; state={s.get('state')}")
        time.sleep(2)
    blob = ops.req("GET", "/api/content/operations/export/zip", accept="application/zip")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            if n.endswith("L.v1"):
                return n
    sys.exit("export zip carried no *L.v1 marker file")


def sm_zip(sms, marker, owner):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(marker, owner)
        z.writestr("supermetrics.json", json.dumps(sms, indent=2))
        z.writestr("configuration.json",
                   json.dumps({"superMetrics": len(sms), "type": "ALL"}, indent=2))
    return buf.getvalue()


def dashboard_zip(dash, marker, owner, username):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dashboard/dashboard.json", json.dumps(dash, indent=1))
        for lang in ("", "_es", "_fr", "_ja"):
            z.writestr(f"dashboard/resources/resources{lang}.properties", "")
    ids = [d["id"] for d in dash.get("dashboards", []) if d.get("id")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as outer:
        outer.writestr(marker, owner)
        outer.writestr(zipfile.ZipInfo("dashboards/"), b"")
        outer.writestr(zipfile.ZipInfo("dashboardsharings/"), b"")
        outer.writestr(f"dashboards/{owner}", inner.getvalue())
        outer.writestr(f"dashboardsharings/{owner}", json.dumps(
            [{"groupName": "Everyone", "sourceType": "LOCAL",
              "dashboards": [{"dashboardId": i} for i in ids]}]))
        outer.writestr("usermappings.json", json.dumps(
            {"sources": [], "users": [{"userName": username, "userId": owner}]}, indent=2))
        outer.writestr("configuration.json", json.dumps(
            {"type": "CUSTOM", "dashboards": len(ids),
             "dashboardsByOwner": [{"owner": owner, "count": len(ids)}]}, indent=2))
    return buf.getvalue()


def do_import(ops, blob, label):
    ops.multipart("/api/content/operations/import", "contentFile", "content.zip", blob)
    deadline = time.time() + 300
    while True:
        s = ops.req("GET", "/api/content/operations/import") or {}
        state = str(s.get("state", ""))
        if state.startswith("FINI"):
            for entry in s.get("summaries", []) or []:
                print(f"     {entry.get('contentType')}: imported={entry.get('imported')} "
                      f"skipped={entry.get('skipped')}")
            if state != "FINISHED":
                sys.exit(f"import of {label} ended in state={state}")
            return s
        if time.time() > deadline:
            sys.exit(f"import of {label} did not finish; state={state}")
        time.sleep(3)


def enable_supermetrics(ops, names):
    """Two steps, both required. Resource-kind assignment alone makes a super metric visible
    but not calculated; policy enablement alone does nothing for content-zip imports."""
    ids = {}
    for n in names:
        body = ops.req("GET", "/api/supermetrics?name=" + urllib.parse.quote(n)) or {}
        for s in body.get("superMetrics", []) or []:
            sm = s.get("superMetric", s)
            if sm.get("name") == n:
                ids[n] = sm.get("id")
    missing = [n for n in names if n not in ids]
    if missing:
        print(f"   WARNING: not found after import, cannot enable: {missing}")
    for n, sid in ids.items():
        try:
            ops.req("PUT", "/internal/supermetrics/assign",
                    body={"superMetricId": sid, "resourceKindKeys": []})
        except urllib.error.HTTPError as e:
            print(f"   assign {n}: HTTP {e.code} (continuing to policy step)")
    blob = ops.req("GET", "/api/policies/export", accept="application/zip")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml_name = next(n for n in z.namelist() if n.endswith(".xml"))
        xml = z.read(xml_name).decode()
    root = ET.fromstring(xml)
    ns = {"d": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    def find(parent, tag):
        return parent.findall(f"{{*}}{tag}") or parent.findall(tag)
    added = 0
    for pkg in root.iter():
        if not pkg.tag.endswith("PackageSettings"):
            continue
        blocks = find(pkg, "SuperMetrics")
        block = blocks[0] if blocks else ET.SubElement(pkg, "SuperMetrics")
        have = {e.get("id") for e in list(block)}
        for n, sid in ids.items():
            if sid not in have:
                ET.SubElement(block, "SuperMetric", {"enabled": "true", "id": sid})
                added += 1
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(xml_name, ET.tostring(root, encoding="unicode"))
    ops.multipart("/api/policies/import", "policy", "exportedPolicies.zip", out.getvalue(),
                  params="?forceImport=true")
    print(f"   enabled {len(ids)} super metric(s) in policy ({added} entries added)")


def main():
    import urllib.parse as _up
    globals()["urllib"].parse = _up
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", help="VCF/Aria Operations hostname")
    ap.add_argument("--user", help="username, e.g. admin")
    ap.add_argument("--password", help="password; prompted for if omitted, or $OPS_PASSWORD")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the content zips locally and send nothing")
    ap.add_argument("--no-enable", action="store_true",
                    help="import but do not modify the active policy")
    args = ap.parse_args()

    dash = json.load(open(os.path.join(BUILD, "dashboard.json")))
    sms = json.load(open(os.path.join(BUILD, "supermetric.json")))
    names = [v["name"] for v in sms.values()]

    host, user, password = credentials(args)
    print(f"### connecting to {host}")
    ops = Ops(host, user, password)
    me = ops.req("GET", "/api/auth/currentuser") or {}
    owner = me.get("id") or me.get("userId")
    username = me.get("username") or user
    if not owner:
        sys.exit(f"could not resolve the current user id from {me}")
    print(f"   user {username} id={owner}")

    # The importer takes ownership from the zip, not from the file (LESSONS.md 1.4).
    for d in dash.get("dashboards", []):
        d["userId"] = owner
        d["lastUpdateUserId"] = owner
        d["shared"] = True

    marker = discover_marker(ops)
    print(f"   marker file: {marker}")

    smz = sm_zip(sms, marker, owner)
    dbz = dashboard_zip(dash, marker, owner, username)
    if args.dry_run:
        open(os.path.join(BUILD, "content-supermetrics.zip"), "wb").write(smz)
        open(os.path.join(BUILD, "content-dashboard.zip"), "wb").write(dbz)
        print(f"   dry run: wrote build/content-supermetrics.zip ({len(smz)} B) and "
              f"build/content-dashboard.zip ({len(dbz)} B); nothing sent")
        return 0

    print(f"### importing {len(sms)} super metrics")
    do_import(ops, smz, "super metrics")
    print("### importing dashboard")
    do_import(ops, dbz, "dashboard")
    if not args.no_enable:
        print("### enabling super metrics in the active policy")
        enable_supermetrics(ops, names)
    print("\ndone. verify with: python3 ../probes/p27_pak_install_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
