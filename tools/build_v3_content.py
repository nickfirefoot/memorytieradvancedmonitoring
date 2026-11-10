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


def dashboard_yaml():
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
  coords: {{x: 1, y: 25, w: 12, h: 22}}
  html: {q(html)}
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


if __name__ == "__main__":
    main()
