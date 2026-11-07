#!/usr/bin/env python3
"""Export Operations host history as the workbook MTAT's "VCF Operations / vROps Host Export" importer
reads (MTAT 3.2+, which the MTAT repo's "Export from Ops.md" says 3.3 and 4.0 share).

    python3 mtat_export_818.py --host ops.example.com --user admin --days 30
    python3 mtat_export_818.py --env ~/ops818.env --days 7 --interval 5

Read-only: it only GETs from the Operations API. Standard library only (no openpyxl), so it runs
on any laptop with Python 3 that can reach Operations, air-gapped or not. No adapter, no cloud proxy.

What MTAT needs, taken from its importer (MTAT_v3_2.ps1, VROPS_COLUMNS / vropsAddWorkbook):
  * .xlsx, not CSV; a host table whose header is within the first 30 rows.
  * required: host name, Guest Active (mem|active_average), Total Capacity (mem|host_provisioned).
    A row with no Total Capacity is skipped, so it is carried onto every row.
  * optional: Cluster, timestamp, Consumed, Capacity Available to VMs, allocated-to-powered-on-VMs,
    CPU utilization, CPU core utilization, CPU total MHz.
  * raw metric keys are matched first; a "(KB)" suffix on a mem| header fixes the unit, so MTAT
    never has to guess it. Values stay raw KB, the most precise form (MTAT's own advice).
  * TIMESTAMPED rows are what give MTAT a real peak, a real average and its history charts. One row
    per host gives it a single value that it has to use as both.
"""
import argparse
import datetime
import getpass
import io
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from xml.sax.saxutils import escape

# (metric key, header MTAT matches). Memory headers carry (KB) so the unit is explicit.
COLUMNS = [
    ("mem|active_average", "mem|active_average (KB)"),
    ("mem|consumed_average", "mem|consumed_average (KB)"),
    ("mem|host_provisioned", "mem|host_provisioned (KB)"),
    ("mem|totalCapacity_average", "mem|totalCapacity_average (KB)"),
    ("mem|memory_allocated_on_all_powered_on_vms", "mem|memory_allocated_on_all_powered_on_vms (KB)"),
    ("cpu|usage_average", "cpu|usage_average"),
    ("cpu|coreUtilization_average", "cpu|coreUtilization_average"),
    ("cpu|capacity_provisioned", "cpu|capacity_provisioned"),
]
# Static per host: carried onto every row, because MTAT skips a row with no capacity.
CARRY = {"mem|host_provisioned", "mem|totalCapacity_average", "cpu|capacity_provisioned"}
MAX_ROWS = 1_000_000          # Excel's sheet limit is 1,048,576; stay under it per workbook
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def env_file(path):
    e = {}
    for line in open(os.path.expanduser(path)):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


class Ops:
    def __init__(self, host, user, password):
        self.base = f"https://{host}/suite-api/api"
        self.tok = None
        self.tok = self.req("/auth/token/acquire", "POST", {"username": user, "password": password})["token"]

    def req(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Accept", "application/json")
        if data:
            r.add_header("Content-Type", "application/json")
        if self.tok:
            r.add_header("Authorization", f"vRealizeOpsToken {self.tok}")
        with urllib.request.urlopen(r, context=CTX, timeout=300) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}


def hosts(ops, cluster_filter):
    out, page = [], 0
    while True:
        r = ops.req(f"/resources?adapterKind=VMWARE&resourceKind=HostSystem&pageSize=1000&page={page}")
        out += r.get("resourceList", [])
        if len(out) >= r.get("pageInfo", {}).get("totalCount", 0):
            break
        page += 1
    rows = []
    for i in range(0, len(out), 100):
        chunk = out[i:i + 100]
        q = "&".join("resourceId=" + h["identifier"] for h in chunk)
        props = ops.req("/resources/properties?" + q).get("resourcePropertiesList", [])
        by = {p["resourceId"]: {x["name"]: x["value"] for x in p.get("property", [])} for p in props}
        for h in chunk:
            cl = by.get(h["identifier"], {}).get("summary|parentCluster", "")
            if cluster_filter and cl not in cluster_filter:
                continue
            rows.append((h["identifier"], h["resourceKey"]["name"], cl))
    return rows


def host_series(ops, rid, begin, end, interval):
    """{timestamp_ms: {key: value}} for one host, fetched a week at a time."""
    series = {}
    step = 7 * 86400 * 1000
    for b in range(begin, end, step):
        q = [("resourceId", rid), ("begin", b), ("end", min(b + step, end)), ("rollUpType", "AVG"),
             ("intervalType", "MINUTES"), ("intervalQuantifier", interval)]
        q += [("statKey", k) for k, _ in COLUMNS]
        r = ops.req("/resources/stats?" + urllib.parse.urlencode(q))
        for v in r.get("values", []):
            for s in v.get("stat-list", {}).get("stat", []):
                k = s["statKey"]["key"]
                for ts, val in zip(s.get("timestamps", []), s.get("data", [])):
                    series.setdefault(ts, {})[k] = val
    return series


def col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path, header, rows):
    """A minimal workbook: one sheet, inline strings, numbers as numbers. The parts MTAT's reader
    opens (workbook.xml, its rels, the sheet) plus what Excel needs to open it too."""
    def cell(ci, ri, v):
        ref = f"{col(ci)}{ri}"
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
    buf = io.StringIO()
    buf.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
    for ri, r in enumerate([header] + rows, start=1):
        buf.write(f'<row r="{ri}">' + "".join(cell(ci, ri, v) for ci, v in enumerate(r) if v is not None) + "</row>")
    buf.write("</sheetData></worksheet>")
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Host metrics" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": buf.getvalue(),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", help="file with OPS_HOST, OPS_USER, OPS_PASS")
    ap.add_argument("--host")
    ap.add_argument("--user")
    ap.add_argument("--days", type=int, default=30, help="history to export (default 30)")
    ap.add_argument("--interval", type=int, default=5, help="minutes per sample (default 5, Operations' own)")
    ap.add_argument("--cluster", action="append", help="limit to this cluster (repeatable)")
    ap.add_argument("--out", default=None, help="output file name (default: Host metrics <N> days.xlsx)")
    a = ap.parse_args()
    e = env_file(a.env) if a.env else {}
    host = a.host or e.get("OPS_HOST") or sys.exit("give --host or --env")
    user = a.user or e.get("OPS_USER") or sys.exit("give --user or --env")
    pw = e.get("OPS_PASS") or os.environ.get("OPS_PASS") or getpass.getpass(f"Password for {user}@{host}: ")
    ops = Ops(host, user, pw)
    end = int(time.time() * 1000)
    begin = end - a.days * 86400 * 1000
    hl = hosts(ops, set(a.cluster or []))
    print(f"{len(hl)} hosts; {a.days} days at {a.interval}-minute samples")
    header = ["HostName", "Cluster", "timestamp"] + [h for _, h in COLUMNS]
    out = a.out or f"Host metrics {a.days} days.xlsx"
    stem, ext = os.path.splitext(out)
    batch, files, empty = [], [], []

    def flush():
        if not batch:
            return
        name = out if not files and len(batch) < MAX_ROWS else f"{stem} part {len(files) + 1}{ext}"
        write_xlsx(name, header, batch)
        files.append((name, len(batch)))
        batch.clear()

    for rid, name, cl in hl:
        s = host_series(ops, rid, begin, end, a.interval)
        if not s:
            empty.append(name)
            continue
        carried = {}
        for k in CARRY:            # latest known value of each static column
            for ts in sorted(s, reverse=True):
                if k in s[ts]:
                    carried[k] = s[ts][k]
                    break
        if "mem|host_provisioned" not in carried:
            empty.append(name + " (no Total Capacity)")
            continue
        rows = []
        for ts in sorted(s):
            d = dict(carried)
            d.update({k: v for k, v in s[ts].items()})
            if "mem|active_average" not in d:
                continue
            iso = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append([name, cl or None, iso] + [d.get(k) for k, _ in COLUMNS])
        if len(batch) + len(rows) >= MAX_ROWS:
            flush()
        batch += rows
        print(f"   {name:40s} {cl or '(no cluster)':24s} {len(rows):6d} rows")
    flush()
    for f, n in files:
        print(f"wrote {f} ({n} rows)")
    if empty:
        print(f"no data for {len(empty)} host(s): {', '.join(empty)}")
    if len(files) > 1:
        print("Several workbooks: select them all together in MTAT's import; it merges them by host.")
    print("In MTAT: Offline Import > 'VCF Operations / vROps Host Export (.xlsx)' > select the file(s) > Process Import.")


if __name__ == "__main__":
    main()
