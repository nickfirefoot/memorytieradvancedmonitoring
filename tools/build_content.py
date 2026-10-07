#!/usr/bin/env python3
"""Generate the memory-tiering sizing dashboard and its optional super metrics.

Design rules, from BACKLOG.md:
  §9  no hardcoded names -- every widget binds by resource KIND, never by resource, and no
      host, VM, cluster, datacenter, domain or IP appears anywhere in the output.
  §1  these are sizing dashboards, not `Rapid` dashboards.

The dashboard uses ONLY metrics the vCenter adapter already collects and that were verified
populated on a live instance (probes p15/p16/p19), so it shows data the moment it is imported,
with no super metrics and no policy edit. The super metrics in supermetric.json are a separate,
optional second step.

Envelope (top-level keys, dashboard object fields, widget wrapper fields) is modelled on a real
VCF Operations 9.1.1 UI export. Widget config bodies follow the shapes in the inherited
mtat-ops content, which were diffed key-for-key against product exports.

Usage:
    python3 build_content.py                 # write build/
    python3 build_content.py --verify        # also check every metric key against the live
                                             # instance named in ~/ops.env
"""
import argparse
import json
import os
import sys
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MEMTIER_CONTENT") or os.path.join(os.path.dirname(HERE), "content")

PREFIX = "Sizing"
ADAPTER = "VMWARE"
CLUSTER, HOST, VM, WORLD = "ClusterComputeResource", "HostSystem", "VirtualMachine", "vSphere World"

# Resource kinds referenced by the dashboard, in the order their placeholder ids are assigned.
KINDS = [CLUSTER, HOST, VM]
KIND_ID = {k: f"resourceKind:id:{i}_::_" for i, k in enumerate(KINDS)}
GROUP_TEXT = {CLUSTER: "Cluster Compute Resource", HOST: "Host System", VM: "Virtual Machine"}

# Every metric key used below, with the kind it is read from. Verified observed and populated
# on a live 9.1.1 instance -- see probes/p15, p16, p19. `mem|host_active` is deliberately absent:
# it is declared on VirtualMachine and collected on zero VMs (OPS818-REVIEW.md finding A).
METRICS = {
    (CLUSTER, "mem|host_provisioned"):  "Presented memory",
    (CLUSTER, "mem|consumed_average"):  "Consumed",
    (CLUSTER, "mem|active_average"):    "Active",
    (HOST,    "mem|host_provisioned"):  "Presented memory",
    (HOST,    "mem|consumed_average"):  "Consumed",
    (HOST,    "mem|active_average"):    "Active",
    (HOST,    "mem|usage_average"):     "Memory usage (%)",
    (VM,      "mem|guest_provisioned"): "Configured",
    (VM,      "mem|active_average"):    "Active",
    (VM,      "mem|reservation_used"):  "Reserved",
}


def sm_uuid(name):
    """Deterministic id from the metric name, so re-importing updates in place instead of
    leaving a second copy behind."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"memtier-sizing/{name}"))


def widget(wtype, title, y, x=1, w=12, h=6, config=None):
    wid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"memtier-sizing/widget/{title}"))
    cfg = {"refreshInterval": 300, "widgetId": wid, "description": "", "title": title,
           "refreshContent": {"refreshContent": True},
           "customFilter": {"filter": [], "excludedResources": None, "includedResources": None},
           "selfProvider": {"selfProvider": True}}
    cfg.update(config or {})
    return {"collapsed": False, "id": wid, "gridsterCoords": {"w": w, "x": x, "h": h, "y": y},
            "state": "", "type": wtype, "title": title, "config": cfg, "height": 0}


def scoreboard_metric(kind, key, label, idx, bounds=None):
    m = {"metricKey": key, "metricName": METRICS[(kind, key)], "isStringMetric": False,
         "resourceKindId": KIND_ID[kind], "resourceKindName": kind,
         "colorMethod": 1, "handleOldColoring": False,
         "id": f"extModel{idx}-1", "label": label,
         "yellowBound": None, "orangeBound": None, "redBound": None}
    if bounds:
        m["yellowBound"], m["orangeBound"], m["redBound"] = bounds
    return m


def scoreboard(title, kind, entries, y, h=4):
    return widget("Scoreboard", title, y, h=h, config={
        "metric": {"mode": "resourceKind", "resourceMetrics": [],
                   "resourceKindMetrics": [scoreboard_metric(kind, k, lbl, i + 1)
                                           for i, (k, lbl) in enumerate(entries)]},
        "resource": [], "relationshipMode": {"relationshipMode": 0},
        "depth": 1, "resInteractionMode": None, "visualTheme": 8,
        "mode": {"layoutMode": "fixedView"},
        "showResourceName": {"showResourceName": True}, "showMetricName": {"showMetricName": True},
        "showMetricUnit": {"showMetricUnit": True}, "showDT": {"showDT": False},
        "showSparkline": {"showSparkline": True},
        "periodLength": None, "maxCellCount": 100, "oldMetricValues": False,
        "roundDecimals": 1, "valueSize": 24, "labelSize": 12,
        "boxHeight": None, "boxColumns": 1,
        # present in the proven 9.1.1 Scoreboard export; absent keys are how a widget falls
        # back to a generic object badge (vSAN pack, DASHBOARD-PRACTICE.md)
        "focusOnPercent": False, "showPercentText": False, "showRemaining": False,
        "viewDetails": ""})
    # NOTE maxCellCount: a Scoreboard renders at most 100 cells = metrics x objects. Three
    # metrics here, so this panel dies silently past ~33 clusters. Sizing estates are usually
    # smaller than that; a View List is the right widget if one is not.


def pareto(title, kind, key, y, x=1, w=6, bars=15):
    return widget("ParetoAnalysis", title, y, x=x, w=w, h=7, config={
        "resource": [], "relationshipMode": {"relationshipMode": [-1, 0]},
        "mode": "all", "filterMode": "tagPicker", "tagFilter": None, "depth": 10,
        "filterOldMetrics": {"filterOldMetrics": False},
        "topOption": "metricsHighestUtilization", "barsCount": bars,
        "roundDecimals": 1.0, "regenerationTime": 15, "percentileValue": None,
        "metricName": METRICS[(kind, key)],
        "metricUnit": {"metricUnitId": -1, "metricUnitName": "Auto"},
        "additionalColumns": [],
        "metric": {"metricKey": key, "name": METRICS[(kind, key)]},
        "resourceKind": [{"id": KIND_ID[kind]}]})


def heatmap(title, kind, color_key, size_key, group_kind, y, h=7):
    return widget("Heatmap", title, y, h=h, config={
        "mode": "all", "depth": 10, "resource": [],
        "relationshipMode": {"relationshipMode": [1, -1, 0]},
        "refreshContent": {"refreshContent": False}, "value": 0,
        "viewDetails": "",
        "configs": [{
            "id": "extModel1-1",
            "name": title, "nameOrig": title, "nameLocalized": title,
            "resourceKind": KIND_ID[kind],
            "colorBy": {"metricKey": color_key, "value": METRICS[(kind, color_key)]},
            "sizeBy": {"metricKey": size_key, "value": METRICS[(kind, size_key)]},
            "attributeKind": {"value": ""},
            "customFilter": {"filter": [], "excludedResources": None, "includedResources": None},
            # groupBy names the KIND twice -- placeholder typeId and the encoded kind id. Both
            # encode a resource kind, never an instance, so both are portable (BACKLOG §9).
            "groupBy": {"resourceKind": group_kind, "adapterKind": ADAPTER,
                        "typeId": KIND_ID[group_kind],
                        "id": f"004null002006{ADAPTER}{group_kind}",
                        "text": GROUP_TEXT.get(group_kind, group_kind),
                        "type": "resourceKind", "parentText": "vCenter", "parentId": ADAPTER},
            "thenBy": None,
            # green / amber / red, the product's own palette; thresholds are per-widget so the
            # panel carries its own banding with no alert definition behind it
            # capacity genre: low utilisation is WASTAGE and reads dark grey, not green
            # (practitioner guide p44, p136); green = healthy use; red = hot
            "color": {"thresholds": {"values": [0, 40, 80, 100],
                                     "colors": ["#5A5A5A", "#67CA16", "#FFDB24", "#FF4D2E"]}},
            "colorRange": {"min": None, "max": None},
            "filterMode": "tagPicker", "focusOnGroups": True,
            "relationalGrouping": False, "solidColoring": False,
            "mode": {"mode": False},
            "config": {"value": ""}}]})


# Inline style on EVERY element: the editor strips <style> blocks and keeps only inline
# attributes, and unstyled text renders black on a dark theme (vSAN pack lesson). #7f8c9a is a
# mid tone that stays legible on both the light and dark themes; confirm visually on import.
_C = 'style="color:#7f8c9a"'
_B = 'style="color:#9fb0c0;font-weight:bold"'
HELP = f"""<p {_C}><b {_B}>Memory tiering sizing &mdash; sample.</b> Every tile below reads a metric the
vCenter adapter already collects. <b {_B}>No super metrics are required for this dashboard</b>; if you
import <code {_C}>supermetric.json</code> as well, the derived figures become available for a second
screen.</p>
<p {_C}><b {_B}>This is a sizing tool, not a monitoring tool.</b> It answers <i {_C}>what hardware would this
workload need if it were tiered</i>. On a vSphere 8 estate there is no tiering to report, which
is the point &mdash; the assessment happens before the upgrade.</p>
<p {_C}><b {_B}>Reading this on a cluster that already has tiering enabled?</b> Then
<code {_C}>mem|host_provisioned</code> is <i {_C}>presented</i> memory &mdash; installed DRAM plus the NVMe
tier &mdash; not installed DRAM. Measured on a tiered lab host: 639.4 GiB presented against a
127.9 GiB DRAM tier, a 5.00&times; overstatement. Every tile labelled <i {_C}>presented memory</i>
says presented for that reason. On an untiered vSphere 8 host the two are the same number.</p>
<p {_C}><b {_B}>Tiles show the latest sample, not a peak.</b> Sizing must be done on business-cycle peaks,
which need a View transformation rather than a dashboard tile. Treat these values as a shape
check, not as the number on the quote.</p>"""


def build_dashboard():
    dash_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-sizing/dashboard"))
    widgets = [
        widget("TextDisplay", "How to read this", y=1, h=5, config={
            "editorData": HELP, "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
        scoreboard("Cluster memory", CLUSTER, [
            ("mem|host_provisioned", "Presented memory (KB)"),
            ("mem|consumed_average", "Consumed (KB)"),
            ("mem|active_average", "Active (KB)")], y=6),
        # Colour MUST be a percentage: the threshold block [0, 50, 100] is a percent scale, and
        # colouring by a KB metric against it paints every host red (caught 2026-10-02).
        heatmap("Hosts: memory usage (%), sized by presented memory, grouped by cluster",
                HOST, "mem|usage_average", "mem|host_provisioned", CLUSTER, y=10),
        pareto("Hosts by consumed memory", HOST, "mem|consumed_average", y=17, x=1),
        pareto("Hosts by active memory", HOST, "mem|active_average", y=17, x=7),
        pareto("VMs by configured memory (allocated)", VM, "mem|guest_provisioned", y=24, x=1, bars=25),
        pareto("VMs by active memory", VM, "mem|active_average", y=24, x=7, bars=25),
        pareto("VMs by reserved memory (cannot be tiered)", VM, "mem|reservation_used", y=31, x=1, bars=25),
    ]
    for w in widgets:
        w["tabId"] = dash_id
    return {
        "entries": {
            "resourceKind": [{"resourceKindKey": k, "internalId": KIND_ID[k],
                              "adapterKindKey": ADAPTER} for k in KINDS],
            "resource": [],          # deliberately empty: never pin a resource (BACKLOG §9)
        },
        "dashboards": [{
            "id": dash_id,
            "name": "Memory Tiering Sizing - Clusters",
            "description": "Sizing a vSphere estate for NVMe memory tiering, from metrics the "
                           "vCenter adapter already collects.",
            "userId": "00000000-0000-0000-0000-000000000000",
            "lastUpdateUserId": "00000000-0000-0000-0000-000000000000",
            "shared": True, "hidden": False, "disabled": False, "locked": False,
            "editAllowed": True, "homeTab": False, "rank": 0,
            "creationTime": 0, "lastUpdateTime": 0,
            "importAttempts": 0, "importComplete": True, "autoswitchEnabled": False,
            "columnCount": 0, "columnProportion": "1", "gridsterMaxColumns": 12,
            "states": [], "dashboardNavigations": {},
            "widgets": widgets,
        }],
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-sizing/export")),
    }


def sm(name, formula, kind, unit, description):
    return sm_uuid(name), {
        "name": name, "formula": formula, "description": description, "unitId": unit,
        "resourceKinds": [{"resourceKindKey": kind, "adapterKindKey": ADAPTER}]}


def roll(kind, key, depth):
    return f"sum(${{adaptertype={ADAPTER}, objecttype={kind}, metric={key}, depth={depth}}})"


def build_supermetrics():
    KB_PER_GB = 1048576
    host_active = roll(HOST, "mem|active_average", 1)
    host_consumed = roll(HOST, "mem|consumed_average", 1)
    vm_alloc = roll(VM, "mem|guest_provisioned", 2)
    out = {}
    for k, v in [
        sm(f"{PREFIX}|Allocated (GB)", f"{vm_alloc} / {KB_PER_GB}", CLUSTER, "gb",
           "Sum of configured memory across the cluster's VMs. The one base figure with no "
           "native cluster metric. Note: powered-off VMs and templates still report "
           "configured memory, so treat this as an upper bound on what is really running."),
        sm(f"{PREFIX}|Tierable of Used (GB)",
           f"(({host_consumed} - {host_active}) / 2) / {KB_PER_GB}", CLUSTER, "gb",
           "Cold memory currently backed in DRAM, halved for conservatism. Consumed minus "
           "active, in that order -- active is the working set within consumed."),
        sm(f"{PREFIX}|Active of Allocated (%)",
           f"({host_active} / {vm_alloc}) * 100", CLUSTER, "percent",
           "Raw active as a share of allocated, with NO headroom factor applied, so the number "
           "means what its name says. Apply headroom in the classification, not here."),
        sm(f"{PREFIX}|Active of Consumed (%)",
           f"({host_active} / {host_consumed}) * 100", CLUSTER, "percent",
           "Plausibility check on the whole exercise. Typical estates sit at 8-12%, nearer 15% "
           "where databases dominate. Outside 5-20% suspect the metric, not the workload."),
        # --- A/B test, remove once settled: which depth reaches hosts from vSphere World? ---
        sm(f"{PREFIX}|TEST Fleet Active depth3 (GB)",
           f"{roll(HOST, 'mem|active_average', 3)} / {KB_PER_GB}", WORLD, "gb",
           "A/B TEST ONLY. Measured tree depth from vSphere World to HostSystem is 3."),
        sm(f"{PREFIX}|TEST Fleet Active depth10 (GB)",
           f"{roll(HOST, 'mem|active_average', 10)} / {KB_PER_GB}", WORLD, "gb",
           "A/B TEST ONLY. The inherited content uses depth=10. If this one reports data and "
           "depth3 does not, depth means 'up to N'; if the reverse, it means 'exactly N'."),
    ]:
        out[k] = v
    return out


def self_check(dash):
    problems = []
    widgets = dash["dashboards"][0]["widgets"]
    cells = set()
    for w in widgets:
        g = w["gridsterCoords"]
        if g["x"] < 1 or g["y"] < 1:
            problems.append(f"{w['title']}: gridsterCoords must be 1-based, got {g}")
        if g["x"] + g["w"] - 1 > 12:
            problems.append(f"{w['title']}: overflows the 12-column grid")
        for xx in range(g["x"], g["x"] + g["w"]):
            for yy in range(g["y"], g["y"] + g["h"]):
                if (xx, yy) in cells:
                    problems.append(f"{w['title']}: overlaps another widget at {(xx, yy)}")
                cells.add((xx, yy))
    for w in widgets:
        if w["title"] != w["config"].get("title"):
            problems.append(f"{w['title']}: title differs between widget and config")
    blob = json.dumps(dash)
    for bad in ("includedResources\": [", "excludedResources\": ["):
        if bad in blob:
            problems.append("a widget pins resources -- forbidden by BACKLOG §9")
    if dash["entries"]["resource"]:
        problems.append("entries.resource is not empty -- forbidden by BACKLOG §9")
    return problems


def verify_live(dash, sms, host, user, password):
    """Check every metric key the dashboard uses is observed on a real object of that kind.
    Self-contained: no dependency on anything outside this file."""
    import base64, json as _json, ssl, urllib.request, urllib.parse as _up
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    base = f"https://{host}/suite-api/api"

    def req(path, body=None, token=None):
        data = _json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data,
                                   method="POST" if data else "GET")
        r.add_header("Accept", "application/json")
        if data:
            r.add_header("Content-Type", "application/json")
        if token:
            r.add_header("Authorization", f"vRealizeOpsToken {token}")
        with urllib.request.urlopen(r, context=ctx, timeout=90) as resp:
            return _json.loads(resp.read().decode())

    tok = req("/auth/token/acquire", {"username": user, "password": password})["token"]
    ok = True
    for kind in KINDS:
        rl = req(f"/resources?adapterKind={ADAPTER}&resourceKind={_up.quote(kind)}&pageSize=1000",
                 token=tok)["resourceList"]
        observed = set()
        for r in rl[:12]:
            sk = req(f"/resources/{r['identifier']}/statkeys", token=tok)
            observed |= {s["key"] for s in sk.get("stat-key", [])}
        for k in sorted({k for (kk, k) in METRICS if kk == kind}):
            hit = k in observed
            ok &= hit
            print(f"   {'OK  ' if hit else 'MISS'}  {kind:<24} {k}")
    declared = {rk["resourceKindKey"] for rk in dash["entries"]["resourceKind"]}
    declared |= {r["resourceKindKey"] for v in sms.values() for r in v["resourceKinds"]}
    all_kinds = {k["key"] for k in
                 req(f"/adapterkinds/{ADAPTER}/resourcekinds?limit=500", token=tok)["resource-kind"]}
    for k in sorted(declared):
        hit = k in all_kinds
        ok &= hit
        print(f"   {'OK  ' if hit else 'MISS'}  resource kind exists: {k}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="check every metric key against a live instance before writing")
    ap.add_argument("--host", help="Operations host, for --verify")
    ap.add_argument("--user", help="username, for --verify")
    ap.add_argument("--password", help="password, for --verify; prompted if omitted")
    args = ap.parse_args()

    dash = build_dashboard()
    sms = build_supermetrics()

    problems = self_check(dash)
    if problems:
        for p in problems:
            print("SELF-CHECK FAILED:", p, file=sys.stderr)
        return 1
    print(f"self-check passed: {len(dash['dashboards'][0]['widgets'])} widgets, "
          f"1-based grid, no overlaps, no pinned resources")

    os.makedirs(OUT, exist_ok=True)
    dj = os.path.join(OUT, "dashboard.json")
    with open(dj, "w") as f:
        json.dump(dash, f, indent=1)
    # A dashboard export is a zip with dashboard/dashboard.json at that exact path; the UI
    # import dialog does not accept a bare .json.
    with zipfile.ZipFile(os.path.join(OUT, "Dashboard.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dj, "dashboard/dashboard.json")
    with open(os.path.join(OUT, "supermetric.json"), "w") as f:
        json.dump(sms, f, indent=1)
    print(f"wrote {OUT}/dashboard.json, Dashboard.zip, supermetric.json "
          f"({len(sms)} super metrics)")

    if args.verify:
        import getpass
        host, user = args.host, args.user
        if not host or not user:
            envf = os.path.expanduser("~/ops.env")
            if os.path.exists(envf):
                e = dict(l.strip().split("=", 1) for l in open(envf)
                         if "=" in l and not l.strip().startswith("#"))
                host = host or e.get("OPS_HOST", "").strip("'\"")
                user = user or e.get("OPS_USER", "").strip("'\"")
        if not host or not user:
            print("--verify needs --host and --user", file=sys.stderr)
            return 1
        pw = args.password or os.environ.get("OPS_PASSWORD")
        if not pw:
            envf = os.path.expanduser("~/ops.env")
            if os.path.exists(envf):
                e = dict(l.strip().split("=", 1) for l in open(envf)
                         if "=" in l and not l.strip().startswith("#"))
                pw = e.get("OPS_PASS", "").strip("'\"") or None
        pw = pw or getpass.getpass(f"password for {user}@{host}: ")
        print("\nverifying every metric key against the live instance:")
        if not verify_live(dash, sms, host, user, pw):
            print("\nVERIFY FAILED: at least one key or kind is missing", file=sys.stderr)
            return 1
        print("\nverify passed: every metric key is observed and every resource kind exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
