#!/usr/bin/env python3
"""Generate the v3 (Java pak) bundled content from the 8.18 views -- one source of truth.

The three views and the dashboard were validated on 8.18.7 as tools/build_views_818.py builds them
(keys, defaults, UI import, round trip, binding, exports reconciled with the API). v3 ships the same
content inside a Java pak built by the VCF Content Factory, whose bundled content is YAML. This
writes that YAML from build_views_818's own VIEWS list, so the two can never drift.

One translation the factory forces: its subject filters accept EQUALS / NOT_EQUALS / GREATER_THAN
only (fail-closed on the vendor corpus), so the powered-on VM filter becomes EQUALS "Powered On"
instead of CONTAINS -- identical on the lab, where the property reads exactly "Powered On".

    python3 build_v3_content.py        # writes v3/views/*.yaml and v3/dashboards/*.yaml
"""
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_views_818 as b  # noqa: E402
import build_content as bc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V3 = os.path.join(ROOT, "v3")
SLUG = {b.INPUTS: "memtier_cluster_sizing_inputs", b.HOSTS: "memtier_hosts",
        b.ALLOC: "memtier_vm_allocation_powered_on"}
# v3 names: version-neutral (the pak targets 8.18 and 9.1.1). Titles are identity -- the view id is
# uuid5 of the title -- so these are new objects, not the 8.18 release's views renamed.
TITLE = {b.INPUTS: "Memory Tier Advanced - Cluster Sizing Inputs",
         b.HOSTS: "Memory Tier Advanced - Hosts",
         b.ALLOC: "Memory Tier Advanced - Powered-on VMs"}


# Properties Operations declares in KB (8.18 describe: unit='KB'). Without a unit the view shows
# raw KB (25,165,824 for 24 GB) -- the defect in Nick's 9.1.1 screenshot. rc.2 tests "gb" on them.
# rc.2 tested both in GB on 8.18: reservation reads correctly (nsx02 24, ops_networks 32), but the
# limit's "no limit" sentinel is -1 KB, which renders as "-0" GB. So only the reservation converts;
# the limit stays raw KB with the sentinel spelled out.
KB_PROPERTIES = {"config|memoryAllocation|reservation"}
LABEL_V3 = {"config|memoryAllocation|reservation": "Reservation configured GB",
            "config|memoryAllocation|limit": "Memory limit KB (-1 = no limit)"}
# The dashboard name is identity on upgrade: Operations matches pak dashboards by NAME, so a rename
# leaves the old dashboard behind (rc.1 -> rc.2, both labs). Never change "Sizing" / its folder.


def q(s):
    """YAML double-quoted scalar."""
    return json.dumps(s, ensure_ascii=False)


def parse_column(xml):
    p = dict(re.findall(r'<Property name="(\w+)" value="([^"]*)"', xml))
    tr = re.findall(r'<Item value="(\w+)"', xml)
    return {"attribute": p["attributeKey"], "display_name": p["displayName"],
            "unit": p.get("preferredUnitId", ""), "transformation": tr[0] if tr else "CURRENT",
            "percentile": p.get("percentile"), "is_property": p.get("isProperty") == "true"}


def filter_yaml(filter_json):
    groups = json.loads(filter_json)
    out = []
    for g in groups:
        for c in g:
            cond = "EQUALS" if c["condition"] == "CONTAINS" else c["condition"]
            v = c["metricValue"]["value"]
            out.append(f"    - filter_type: {c['filterType']}\n"
                       f"      metric_key: {q(c['metricKey'])}\n"
                       f"      condition: {cond}\n"
                       f"      value: {q(v) if isinstance(v, str) else v}\n"
                       + (f"      transform: {c['transform']}\n" if c.get("transform") else ""))
    if len(groups) != 1:
        raise SystemExit("only a single AND group is translated")
    return "  filter:\n" + "".join(out)


def view_yaml(title, kind, cols, opts):
    title = TITLE[title]
    lines = [f"id: {b.guid_for(title)}", f"name: {q(title)}",
             "description: >", "  Memory Tier Advanced. Generated from tools/build_views_818.py "
             "(validated on Aria Operations 8.18.7); edit there, not here.", "",
             "subject:", "  adapter_kind: VMWARE", f"  resource_kind: {kind}"]
    if opts.get("filter_json"):
        lines.append(filter_yaml(opts["filter_json"]).rstrip("\n"))
    lines += ["", "time_window:", "  unit: DAYS", f"  count: {opts.get('days', 30)}", ""]
    if opts.get("totals"):
        lines += ["summary:", "  - display_name: Total", "    aggregation: SUM",
                  f"    columns: {list(opts['totals'])}", ""]
    lines.append("columns:")
    for xml in cols:
        c = parse_column(xml)
        lines.append(f"  - attribute: {q(c['attribute'])}")
        label = LABEL_V3.get(c["attribute"], c["display_name"])
        lines.append(f"    display_name: {q(label)}")
        unit = c["unit"]
        if c["attribute"] in KB_PROPERTIES:
            unit = "gb"
        lines.append(f"    unit: {q(unit)}")
        if c["is_property"]:
            # Numeric KB properties must not be string attributes, or no unit conversion happens.
            numeric = c["attribute"] in KB_PROPERTIES
            lines += ["    is_property: true", f"    is_string_attribute: {'false' if numeric else 'true'}"]
        elif c["transformation"] != "CURRENT":
            lines.append(f"    transformation: {c['transformation']}")
            if c["transformation"] == "PERCENTILE":
                lines.append(f"    percentile: {int(float(c['percentile']))}")
    return "\n".join(lines) + "\n"


# What the pak can't switch on by itself. Click paths walked on 8.18.7 and 9.1.1 (2026-11-10).
SETUP = """<h3 {H}>Complete the install</h3>
<p {P}>The pak adds the views and this dashboard. Two steps need doing by hand, once.</p>
<p {P}><b {B}>1. Add the adapter instance.</b> Administration → Integrations → Repository → click
<b {B}>Memory Tier Advanced</b> → <b {B}>ADD ACCOUNT</b>. Type a Name, leave Label and Collector as
they are, click <b {B}>ADD</b>. It collects nothing and turns green within a few minutes. After an
upgrade, check it under Integrations → Accounts; if it shows stopped, choose <b {B}>Start Collecting</b>.</p>
<p {P}><b {B}>2. Turn on two VM metrics in the active policy.</b></p>
<ol style="margin:4px 0 4px 20px;padding:0;color:#e9edf0">
<li {P}>Open <b {B}>Policy Definition</b>: on 8.18, Operations → Configurations; on 9.x,
Administration → Configurations.</li>
<li {P}>Click the policy whose Status is <b {B}>Active</b> (normally Default Policy), then
<b {B}>EDIT POLICY</b> → <b {B}>Metrics and Properties</b>.</li>
<li {P}>Select Object Type: <code {C}>Virtual Machine</code> (vCenter → Virtual Machine).</li>
<li {P}>Filter <code {C}>Guest Active</code>, click Expand All, and set <b {B}>Memory → Guest Active
(KB)</b> to <b {B}>Activated</b>. 8.18 only; 9.x collects it already.</li>
<li {P}>Filter <code {C}>PCI</code> and set <b {B}>Configuration → Security → PCI PassThrough</b> to
<b {B}>Activated</b>. Both versions.</li>
<li {P}>Click <b {B}>SAVE</b>.</li>
</ol>
<p {P}><b {W}>Until step 2,</b> the VM Guest Active and PCI passthrough columns stay blank. Their
history starts when you save; Guest Active fills in within about 5 minutes. No super metrics are needed.</p>"""


# --- Memory Pressure: "which clusters are out of RAM today" (rc.4). Last 24 hours, demand and
# contention, not 30-day active. Every key checked native and collected by default on 8.18.7 and
# 9.1.1 (2026-11-11), except per-VM balloon, which is off by default and so left out. Colours only
# on % columns: the factory compares bounds with the raw value, and GB columns are converted from KB.
# The factory's subject filter cannot express OR, so the table is sorted worst-first, not filtered.
PCT_BANDS = {"workload": (80, 90, 100), "contention": (1, 2, 5), "facing": (5, 10, 25)}
P_CLUSTERS = "Memory Tier Advanced - Cluster Memory Pressure (24 hours)"
P_HOSTS = "Memory Tier Advanced - Host Memory Pressure (24 hours)"
P_VMS = "Memory Tier Advanced - VM Memory Pressure (24 hours)"


def col(key, label, transform="MAX", unit="", bands=None, sort=None, prop=False):
    c = {"attribute": key, "display_name": label, "unit": unit}
    if prop:
        c.update(is_property=True, is_string_attribute=True)
    elif transform != "CURRENT":
        c["transformation"] = transform
    if bands:
        y, o, r = PCT_BANDS[bands]
        c.update(yellow_bound=y, orange_bound=o, red_bound=r, ascending_range=False)
    if sort:
        c["sort"] = sort
    return c


def pressure_view(title, kind, cols, filter_json=None, page=None):
    v = {"id": b.guid_for(title), "name": title,
         "description": "Memory Tier Advanced: memory pressure over the last 24 hours. Generated from "
                        "tools/build_v3_content.py; edit there, not here.",
         "subject": {"adapter_kind": "VMWARE", "resource_kind": kind},
         "time_window": {"unit": "HOURS", "count": 24}, "columns": cols}
    text = yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=200)
    if filter_json:
        text = text.replace("time_window:", filter_yaml(filter_json) + "time_window:", 1)
    return text


def pressure_views():
    gb, pct = "gb", "percent"
    return {
        "memtier_pressure_clusters": pressure_view(P_CLUSTERS, b.CLUSTER, [
            col("config|name", "Cluster", prop=True),
            col("summary|number_running_hosts", "Running hosts", "CURRENT"),
            col("mem|demand|max_host_workload", "Busiest host memory workload peak %", unit=pct, bands="workload", sort="desc"),
            col("mem|workload", "Memory workload peak %", unit=pct, bands="workload"),
            col("OnlineCapacityAnalytics|mem|demand|capacityRemaining", "Capacity remaining GB", "CURRENT", gb),
            col("OnlineCapacityAnalytics|mem|demand|timeRemaining", "Time remaining days", "CURRENT"),
            col("mem|is_workload_non_green", "Operations flags memory (1 = yes)"),
            col("mem|max_vm_mem_contention", "Worst VM mem contention peak %", unit=pct, bands="contention"),
            col("mem|percentage_of_vms_facing_memory_contention", "VMs facing mem contention peak %", unit=pct, bands="facing"),
            col("mem|host_contentionPct", "Cluster mem contention peak %", unit=pct, bands="contention"),
            col("mem|vmmemctl_average", "Balloon peak GB", unit=gb),
            col("mem|swapinRate_average", "Swap-in rate peak KBps"),
            col("mem|swapoutRate_average", "Swap-out rate peak KBps"),
            col("mem|compressed_average", "Compressed peak GB", unit=gb),
            col("mem|host_demand", "Machine demand peak GB", unit=gb),
            col("mem|active_average", "Guest Active peak GB", unit=gb),
            col("mem|consumed_average", "Consumed peak GB", unit=gb),
            col("mem|demand|usableCapacity", "Usable after HA and buffer GB", "CURRENT", gb),
        ]),
        "memtier_pressure_hosts": pressure_view(P_HOSTS, b.HOST, [
            col("summary|parentCluster", "Cluster", prop=True),
            col("config|name", "Host", prop=True),
            col("mem|workload", "Memory workload peak %", unit=pct, bands="workload", sort="desc"),
            col("mem|max_vm_mem_contention", "Worst VM mem contention peak %", unit=pct, bands="contention"),
            col("mem|percentage_of_vms_facing_memory_contention", "VMs facing mem contention peak %", unit=pct, bands="facing"),
            col("mem|host_contentionPct", "Host mem contention peak %", unit=pct, bands="contention"),
            col("mem|vmmemctl_average", "Balloon peak GB", unit=gb),
            col("mem|swapinRate_average", "Swap-in rate peak KBps"),
            col("mem|swapoutRate_average", "Swap-out rate peak KBps"),
            col("mem|compressed_average", "Compressed peak GB", unit=gb),
            col("mem|host_demand", "Machine demand peak GB", unit=gb),
            col("mem|active_average", "Guest Active peak GB", unit=gb),
            col("mem|consumed_average", "Consumed peak GB", unit=gb),
            col("mem|usage_average", "Memory usage peak %", unit=pct),
        ], b.HOST_RUNNING),
        "memtier_pressure_vms": pressure_view(P_VMS, b.VM, [
            col("summary|parentHost", "Host", prop=True),
            col("config|name", "VM", prop=True),
            col("mem|20_sec_peak_host_contentionPct", "Mem contention 20s peak %", unit=pct, bands="contention", sort="desc"),
            col("mem|host_contentionPct", "Mem contention avg %", "AVG", pct, bands="contention"),
            col("mem|swapped_average", "Swapped peak GB", unit=gb),
            col("mem|swapinRate_average", "Swap-in rate peak KBps"),
            col("mem|compressed_average", "Compressed peak GB", unit=gb),
            col("cpu|swapwaitPct", "Swap wait peak %", unit=pct),
            col("mem|workload", "Memory workload peak %", unit=pct),
            col("mem|guest_provisioned", "Configured GB", "CURRENT", gb),
            col("cpu|20_sec_peak_readyPct", "CPU ready 20s peak %", unit=pct),
            col("cpu|iowaitPct", "IO wait avg %", "AVG", pct),
        ], b.VM_POWERED_ON),
    }


PRESSURE_HELP = """<h3 {H}>Which clusters are out of memory now</h3>
<p {P}>Last <b {B}>24 hours</b>, peak of 5-minute samples, worst cluster first. Click a cluster; its hosts and the
VMs that waited for memory follow. Yellow, orange and red mark the % columns.</p>
<p {P}><b {W}>Out of memory today</b> = the busiest host's memory workload near 100% <b {B}>and</b> VMs facing
contention, or balloon, swap or compression above 0. Workload alone means no headroom; contention or
reclaim on top means users are waiting.</p>
<h4 {H}>Columns</h4>
<p {P}><b {B}>Busiest host / Memory workload %</b>: memory demand as a share of usable memory. The cluster
figure is an average, so one full host can hide behind it; the busiest-host column cannot.<br>
<b {B}>Capacity remaining, Time remaining</b>: Operations' capacity engine, on demand after HA and buffer.
0 means out now; "&gt; 1 Year" means a year or more.<br>
<b {B}>Operations flags memory</b>: 1 when Operations itself rates the cluster's memory workload not green.<br>
<b {B}>Worst VM mem contention %</b>: a VM waited for memory. Above 1 to 2% sustained is felt.
<b {B}>VMs facing mem contention %</b>: how widespread it is. <b {B}>Cluster mem contention %</b> is diluted
across the whole cluster and moves last.<br>
<b {B}>Balloon, Swap-in/out rate, Compressed</b>: ESXi taking memory back from guests. Swap-in is the
one users feel.<br>
<b {B}>Machine demand, Guest Active, Consumed</b>: demand is Operations' estimate and drives the capacity
figures; it typically runs 2 to 4 times Guest Active. Size DRAM for tiering on active (the Sizing
dashboard), not on demand.</p>
<h4 {H}>Hosts and VMs</h4>
<p {P}>Hosts: the same signals per running host, fullest first. VMs: powered-on VMs in the cluster, most
contended first, with swap wait (time stalled on swapped memory), CPU ready and IO wait as %. A VM with
high IO wait is waiting on storage or network, which more memory will not fix.</p>"""


def pressure_dashboard_yaml(setup):
    help_html = f"<div {bc._CARD}>" + PRESSURE_HELP.format(H=bc._H, P=bc._P, B=bc._B, W=bc._W, C=bc._C) + "</div>"
    return f"""id: {b._uuid.uuid5(b._uuid.NAMESPACE_URL, "memtier-v3/dashboard-pressure")}
name: "Memory Pressure"
name_path: "Memory Tier Advanced"
description: >
  Which clusters are out of memory now: demand, contention and reclaim over the last 24 hours,
  worst first. Generated from tools/build_v3_content.py. Never rename it (pak dashboards are matched by name).
released: false
version: "3.0.0"

interactions:
- from: clusters
  to: hosts
  type: resourceId
- from: clusters
  to: vms
  type: resourceId

widgets:
- id: clusters
  type: View
  title: "Clusters, worst first (click one)"
  coords: {{x: 1, y: 1, w: 12, h: 6}}
  self_provider: true
  select_first_row: true
  pin:
    adapter_kind: VMWARE
    resource_kind: vSphere World
  view: {q(P_CLUSTERS)}
- id: hosts
  type: View
  title: "Hosts in the selected cluster"
  coords: {{x: 1, y: 7, w: 12, h: 7}}
  view: {q(P_HOSTS)}
- id: vms
  type: View
  title: "VMs in the selected cluster, most contended first"
  coords: {{x: 1, y: 14, w: 12, h: 10}}
  view: {q(P_VMS)}
- id: help
  type: TextDisplay
  title: "How to read this"
  coords: {{x: 1, y: 24, w: 12, h: 11}}
  html: {q(help_html)}
- id: setup
  type: TextDisplay
  title: "Complete the install"
  coords: {{x: 1, y: 35, w: 12, h: 9}}
  html: {q(setup)}
"""


REPORT = f"""id: {b._uuid.uuid5(b._uuid.NAMESPACE_URL, "memtier-v3/report-pressure")}
name: "Memory Tier Advanced - Cluster Memory Pressure"
description: >
  Every cluster's memory demand, contention and reclaim over the last 24 hours, worst first.
  Run it on vSphere World, or schedule it daily (Reports, then Schedule). PDF and CSV.
released: false
sections:
- type: View
  view: {q(P_CLUSTERS)}
  orientation: Landscape
  colorize: true
settings:
  output_formats:
  - pdf
  - csv
  show_page_footer: true
subject_types:
- adapter_kind: VMWARE
  resource_kind: vSphere World
  type: self
"""


def setup_html():
    return f"<div {bc._CARD}>" + SETUP.format(H=bc._H, P=bc._P, B=bc._B, W=bc._W, C=bc._C) + "</div>"


def dashboard_yaml():
    setup = setup_html()
    help_body = (b.HELP_818.format(H=bc._H, P=bc._P, B=bc._B, W=bc._W, C=bc._C)
                 .replace("<i>", f"<i {bc._I}>")
                 # v3 targets 8.18 and 9.1.1; the 8.18-only title stays in the 8.18 set.
                 .replace("Memory tiering sizing (Aria Operations 8.18)", "Memory tiering sizing"))
    html = f"<div {bc._CARD}>" + help_body + "</div>"
    return f"""id: {b._uuid.uuid5(b._uuid.NAMESPACE_URL, "memtier-v3/dashboard")}
name: "Sizing"
name_path: "Memory Tier Advanced"
description: >
  Memory tiering sizing from native vCenter metrics, last 30 days. Click a cluster; its running
  hosts and powered-on VMs follow. Generated from tools/build_views_818.py.
released: false
version: "3.0.0"

interactions:
- from: clusters
  to: hosts
  type: resourceId
- from: clusters
  to: vms
  type: resourceId

widgets:
- id: clusters
  type: View
  title: "Clusters (click one)"
  coords: {{x: 1, y: 1, w: 12, h: 6}}
  self_provider: true
  select_first_row: true
  pin:
    adapter_kind: VMWARE
    resource_kind: vSphere World
  view: {q(TITLE[b.INPUTS])}
- id: hosts
  type: View
  title: "Hosts in the selected cluster"
  coords: {{x: 1, y: 7, w: 12, h: 7}}
  view: {q(TITLE[b.HOSTS])}
- id: vms
  type: View
  title: "Powered-on VMs in the selected cluster"
  coords: {{x: 1, y: 14, w: 12, h: 11}}
  view: {q(TITLE[b.ALLOC])}
- id: help
  type: TextDisplay
  title: "How to read this"
  coords: {{x: 1, y: 25, w: 12, h: 34}}
  html: {q(html)}
- id: setup
  type: TextDisplay
  title: "Complete the install"
  coords: {{x: 1, y: 59, w: 12, h: 9}}
  html: {q(setup)}
"""


def main():
    os.makedirs(os.path.join(V3, "views"), exist_ok=True)
    os.makedirs(os.path.join(V3, "dashboards"), exist_ok=True)
    for title, kind, seed, cols, opts in b.VIEWS:
        path = os.path.join(V3, "views", SLUG[title] + ".yaml")
        open(path, "w").write(view_yaml(title, kind, cols, opts))
        print("wrote", os.path.relpath(path, ROOT), len(cols), "columns")
    path = os.path.join(V3, "dashboards", "memtier_sizing.yaml")
    open(path, "w").write(dashboard_yaml())
    print("wrote", os.path.relpath(path, ROOT))
    for slug, text in pressure_views().items():
        path = os.path.join(V3, "views", slug + ".yaml")
        open(path, "w").write(text)
        print("wrote", os.path.relpath(path, ROOT))
    path = os.path.join(V3, "dashboards", "memtier_pressure.yaml")
    open(path, "w").write(pressure_dashboard_yaml(setup_html()))
    print("wrote", os.path.relpath(path, ROOT))
    os.makedirs(os.path.join(V3, "reports"), exist_ok=True)
    path = os.path.join(V3, "reports", "memtier_pressure_report.yaml")
    open(path, "w").write(REPORT)
    print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
