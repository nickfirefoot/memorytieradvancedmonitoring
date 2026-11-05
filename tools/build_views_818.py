#!/usr/bin/env python3
"""Two native-metric views for a manual import on Operations 8.18 -- no pak, no adapter, no
super metrics (customer install 2026-11-06).

Why no super metrics: they calculate only from the moment they are enabled, so on day one they
hold one day. The 30-day peaks these views show come from native metrics the customer has
already collected. The sizing arithmetic is done on the exported CSVs instead.

Why no dashboard: the UI import dialog strips viewDefinitionId from dashboards (LESSONS 1.9), so
a dashboard imported that way loses its views. Views import on their own.

Keys only, never display names: names drift between 8.x and 9.x, keys are what the XML binds to.
Every key below is used by the shipped MTAT views or was checked against the KB 445499 change
list (8.18 -> 9.1). Deliberately NOT used: VirtualMachine mem|active_average ("Guest Active"),
which 8.18 does not collect by default (KB 445499: default collection False -> True in 9.1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_views import column, view, guid_for, VM_POWERED_ON, CLUSTER, VM  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build", "818")

INPUTS = "MemTier 8.18 Cluster Sizing Inputs"
ALLOC = "MemTier 8.18 VM Allocation Powered On"

VIEWS = [
    (INPUTS, CLUSTER, 900, [
        column("config|name", "Cluster", CLUSTER, is_property=True, sort=True),
        column("summary|total_number_hosts", "Hosts", CLUSTER),
        column("mem|host_provisioned", "Installed GB", CLUSTER, unit="gb"),
        column("mem|active_average", "Active peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("mem|active_average", "Active avg GB", CLUSTER, transform="AVG", unit="gb"),
        column("mem|consumed_average", "Consumed avg GB", CLUSTER, transform="AVG", unit="gb"),
        column("mem|consumed_average", "Consumed peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("cpu|capacity_usagepct_average", "CPU avg %", CLUSTER, transform="AVG",
               unit="percent"),
        column("cpu|capacity_usagepct_average", "CPU peak %", CLUSTER, transform="MAX",
               unit="percent"),
    ], {}),
    # Powered on only: powered-off VMs and templates still report configured memory (~20% of
    # allocated on the lab). Total row on the one additive column.
    (ALLOC, VM, 920, [
        column("summary|parentCluster", "Cluster", VM, is_property=True, sort=True),
        column("config|name", "VM", VM, is_property=True),
        column("mem|guest_provisioned", "Configured GB", VM, unit="gb"),
    ], {"filter_json": VM_POWERED_ON, "totals": [2], "page": 1000}),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    defs = []
    singles = []
    for title, kind, seed, cols, opts in VIEWS:
        xml = view(title, kind, cols, seed, **opts)
        start, end = xml.index("        <ViewDef"), xml.index("    </Views>")
        defs.append(xml[start:end])
        # One file per view as well, in case the 8.18 import dialog takes one view per file.
        single = os.path.join(OUT, title.replace(" ", "_").replace(".", "") + ".xml")
        with open(single, "w") as f:
            f.write(xml)
        singles.append(single)
    combined = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Content>\n'
                "    <Views>\n" + "".join(defs) + "    </Views>\n</Content>\n")
    path = os.path.join(OUT, "MemTier_818_Views.xml")
    with open(path, "w") as f:
        f.write(combined)
    import zipfile
    with zipfile.ZipFile(os.path.join(OUT, "MemTier_818_Views.zip"), "w",
                         zipfile.ZIP_DEFLATED) as z:
        for p in [path] + singles:
            z.write(p, os.path.basename(p))
    for title, *_ in VIEWS:
        print(f"   {guid_for(title)}  {title}")
    print(f"wrote {os.path.relpath(path, HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
