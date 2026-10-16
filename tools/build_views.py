#!/usr/bin/env python3
"""Generate the View definitions the sizing dashboard binds to.

Why views at all: the only interaction pattern proven to ship and work in this lab is the one
in the vSAN pack's installed dashboards -- every panel a `View` widget with a `viewDefinitionId`,
a provider pinned to `vSphere World`, receivers wired by `widgetInteractions`, and
`periodLength: "dashboardTime"` on each receiver, which is what puts the 1H/6H/24H selector on
the screen. Scoreboards and Paretos cannot be driven that way and cannot page through hundreds
of VMs; a View List can do both (see OPS818-DESIGN sect 8, and the practitioner guide p47/p50).

Structure is cloned from `vSAN_Clusters.xml` and `vSAN_Host_Memory.xml` inside the installed
VsanHostMetrics pak rather than written from the schema -- the format has fields nobody here has
decoded, and assembling one from a partial reading is how the vSAN pack lost several rounds
(LESSONS.md sect 0).

Two rules that are load-bearing:

  * **GUIDs are uuid5 of the title.** They travel inside the XML and are NOT regenerated on
    import, so a dashboard can hard-code `viewDefinitionId` and have it resolve on every
    customer install. uuid4 would orphan every dashboard reference on each rebuild
    (LESSONS.md 3.5). Renaming a view therefore changes its identity -- titles are identity.
  * **`SubjectType type="descendant"` is what makes interaction work.** A VirtualMachine view
    driven by a selected cluster lists that cluster's VMs, with no depth or traversal spec on
    the widget. That is the mechanism the vSAN session spent the longest finding.

Views ship at content/reports/<Name>/<Name>.xml -- NOT a "views" directory (LESSONS.md 3.3).
"""
import os
import sys
import uuid
import xml.sax.saxutils as sx

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MEMTIER_VIEWS") or os.path.join(HERE, "build", "reports")

NAMESPACE = uuid.UUID("6f1a2b3c-4d5e-4a7b-8c9d-0e1f2a3b4c5d")
ADAPTER = "VMWARE"
CLUSTER, HOST, VM = "ClusterComputeResource", "HostSystem", "VirtualMachine"
SUFFIX = "[MTA]"          # so these are distinguishable from stock views in the picker


def sm_guid(name):
    """Super metric ids come from build_content.py -- ONE source. A second hand-kept table is
    how the vSAN pack's dashboards ended up pointing at stale ids (LESSONS.md 8)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bc", os.path.join(HERE, "build_content.py"))
    bc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bc)
    return bc.sm_uuid(name)


def sm_column(sm_name, label, kind, transform="CURRENT", sort=False):
    """A super metric as a view column. Verified shape: vCommunity's views carry
    attributeKey="Super Metric|sm_<uuid>" exactly like a native key."""
    return column(f"Super Metric|sm_{sm_guid(sm_name)}", label, kind,
                  transform=transform, sort=sort)


def guid_for(title):
    """Deterministic from the title: regeneration updates in place instead of duplicating."""
    return str(uuid.uuid5(NAMESPACE, title))


def column(key, label, kind, is_property=False, transform="CURRENT", sort=False):
    """One attributeInfo entry. transform CURRENT for configuration, MAX for performance --
    never average, which is a lagging indicator (practitioner guide p52)."""
    return f"""                            <Item>
                                <Value>
                                    <Property name="objectType" value="RESOURCE" />
                                    <Property name="attributeKey" value="{sx.escape(key)}" />
                                    <Property name="preferredUnitId" value="" />
                                    <Property name="isStringAttribute" value="false" />
                                    <Property name="adapterKind" value="{ADAPTER}" />
                                    <Property name="resourceKind" value="{kind}" />
                                    <Property name="rollUpType" value="NONE" />
                                    <Property name="rollUpCount" value="0" />
                                    <Property name="transformations">
                                        <List>
                                            <Item value="{transform}" />
                                        </List>
                                    </Property>
                                    <Property name="sortCriteria" value="{str(sort).lower()}" />
                                    <Property name="isProperty" value="{str(is_property).lower()}" />
                                    <Property name="displayName" value="{sx.escape(label)}" />
                                    <Property name="addTimestampAsColumn" value="false" />
                                    <Property name="isShowRelativeTimestamp" value="false" />
                                </Value>
                            </Item>"""


def view(title, kind, columns, seed, page=50, days=7):
    """One ViewDef. `seed` only namespaces the Control ids within the document; it carries no
    meaning beyond keeping them unique, which is how the reference views do it."""
    cols = "\n".join(columns)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Content>
    <Views>
        <ViewDef id="{guid_for(title)}">
            <Title>{sx.escape(title)}</Title>
            <Description />
            <SubjectType adapterKind="{ADAPTER}" resourceKind="{kind}" type="descendant" />
            <SubjectType adapterKind="{ADAPTER}" resourceKind="{kind}" type="self" />
            <Usage>dashboard</Usage>
            <Usage>report</Usage>
            <Usage>content</Usage>
            <Controls>
                <Control id="time-interval-selector_id_{seed}" type="time-interval-selector" visible="false">
                    <Property name="advancedTimeMode" value="false" />
                    <Property name="unit" value="DAYS" />
                    <Property name="count" value="{days}" />
                </Control>
                <Control id="attributes-selector_id_{seed + 1}" type="attributes-selector" visible="false">
                    <Property name="attributeInfos">
                        <List>
{cols}
                        </List>
                    </Property>
                </Control>
                <Control id="pagination-control_id_{seed + 2}" type="pagination-control" visible="true">
                    <Property name="start" value="0" />
                    <Property name="size" value="{page}" />
                </Control>
                <Control id="metadata_id_{seed + 3}" type="metadata" visible="false">
                    <Property name="maxPointsCount" value="5000" />
                    <Property name="hideObjectNameColumn" value="false" />
                    <Property name="listTopResultSize" value="-1" />
                </Control>
            </Controls>
            <DataProviders>
                <DataProvider dataType="list-view" id="list-view_id_{seed + 4}" />
            </DataProviders>
            <Presentation type="list" />
        </ViewDef>
    </Views>
</Content>
"""


# --- the views -------------------------------------------------------------------------------
# (A thin one-column selector was dropped: the sizing table is the provider, so a
# separate selector was a widget that existed only to be clicked.)

# Receiver: the VMs inside whichever cluster is selected. MAX rather than CURRENT on the
# performance columns, so a row shows the worst the VM reached in the window rather than
# whatever it happened to be doing at refresh. Clicking a row's object name opens that VM's
# summary, which is the route into its trend charts.
VMS = f"Memory Tier Advanced VMs {SUFFIX}"

# Receiver: per-host detail for the selected cluster, for spotting imbalance between hosts.
HOSTS = f"Memory Tier Advanced Hosts {SUFFIX}"

# The headline table. It REPLACES the scoreboard: a scoreboard renders at most 100 cells
# (metrics x objects), shows present value only, and cannot carry dashboardTime -- so the one
# panel holding the sizing numbers was the one panel that could not honour the time selector or
# a MAX transformation, which the whole peak-based model depends on. A View List has no cell
# cap, pages, sorts, and transforms per column. The vSAN pack's seven shipped dashboards use
# zero scoreboards for the same reasons.
#
# This table is ALSO the provider: clicking a cluster row drives the host and VM lists below,
# which removes a separate selector widget.
SIZING = f"Memory Tier Advanced Clusters {SUFFIX}"

VIEWS = [
    (SIZING, CLUSTER, 760, [
        column("config|name", "Cluster", CLUSTER, is_property=True, sort=True),
        column("mem|host_provisioned", "Presented", CLUSTER),
        sm_column("MemTier Allocated (GB)", "Allocated GB (all VMs)", CLUSTER),
        sm_column("MemTier Allocated Powered On (GB)", "Allocated GB (powered on)", CLUSTER),
        sm_column("MemTier Allocated Powered Off (GB)", "Allocated GB (powered off)", CLUSTER),
        column("mem|consumed_average", "Consumed (max)", CLUSTER, transform="MAX"),
        column("mem|active_average", "Active (max)", CLUSTER, transform="MAX"),
        sm_column("MemTier Active of Consumed (%)", "Active of consumed %", CLUSTER, transform="MAX"),
        sm_column("MemTier DRAM Required Floor (GB)", "DRAM floor GB (peak)", CLUSTER, transform="MAX"),
        sm_column("MemTier DRAM Required Conservative (GB)", "DRAM conservative GB (peak)", CLUSTER, transform="MAX"),
        sm_column("MemTier Implied DRAM Share at Floor (%)", "Implied DRAM share %", CLUSTER, transform="MAX"),
        sm_column("MemTier Tierable of Used (GB)", "Tierable GB", CLUSTER, transform="MAX"),
        sm_column("MemTier Unused (GB)", "Unused GB", CLUSTER, transform="MAX"),
        sm_column("MemTier Unallocated (GB)", "Unallocated GB", CLUSTER),
        sm_column("MemTier Active of Host RAM (%)", "Active of host RAM %", CLUSTER, transform="MAX"),
        sm_column("MemTier Overcommit (%)", "Overcommit %", CLUSTER),
        # the saving -- the number the pack exists to produce
        sm_column("MemTier RAM Saved at Floor (GB)", "RAM saved GB (floor)", CLUSTER, transform="MAX"),
        sm_column("MemTier RAM Saved Conservative (GB)", "RAM saved GB (conservative)", CLUSTER, transform="MAX"),
        # what cannot be tiered whatever the numbers say
        sm_column("MemTier Pinned VMs", "Pinned VMs", CLUSTER),
        sm_column("MemTier Pinned Memory (GB)", "Pinned GB", CLUSTER),
        sm_column("MemTier Tierable Memory (GB)", "Tierable GB (less pinned)", CLUSTER),
        # retrofit: can this cluster be tiered on the DRAM it already owns?
        sm_column("MemTier Retrofit Headroom (GB)", "Retrofit headroom GB", CLUSTER, transform="MAX"),
        sm_column("MemTier Retrofit NVMe to Add (GB)", "NVMe to add GB", CLUSTER),
        # CPU: consolidation is gated by whichever resource binds first.
        column("cpu|capacity_usagepct_average", "CPU util % (max)", CLUSTER, transform="MAX"),
        sm_column("MemTier CPU Headroom (%)", "CPU headroom %", CLUSTER),
        column("cpu|usagemhz_average", "CPU used MHz (max)", CLUSTER, transform="MAX"),
        column("cpu|demandmhz", "CPU demand MHz (max)", CLUSTER, transform="MAX"),
        column("cpu|max_cpu_ready", "Worst VM ready % (max)", CLUSTER, transform="MAX"),
        column("cpu|percentage_of_vms_facing_cpu_ready", "VMs facing ready % (max)", CLUSTER, transform="MAX"),
    ]),
    (HOSTS, HOST, 720, [
        column("config|name", "Host", HOST, is_property=True, sort=True),
        column("mem|host_provisioned", "Presented memory", HOST),
        column("mem|consumed_average", "Consumed (max)", HOST, transform="MAX"),
        column("mem|active_average", "Active (max)", HOST, transform="MAX"),
        column("mem|usage_average", "Memory usage % (max)", HOST, transform="MAX"),
        column("cpu|usage_average", "CPU util % (max)", HOST, transform="MAX"),
        column("cpu|usagemhz_average", "CPU used MHz (max)", HOST, transform="MAX"),
        column("cpu|ready_summation", "CPU ready ms (max)", HOST, transform="MAX"),
        column("cpu|iowait", "CPU io wait (max)", HOST, transform="MAX"),
    ]),
    (VMS, VM, 740, [
        column("config|name", "VM", VM, is_property=True, sort=True),
        column("mem|guest_provisioned", "Configured", VM),
        column("mem|active_average", "Active (max)", VM, transform="MAX"),
        column("mem|consumed_average", "Consumed (max)", VM, transform="MAX"),
        column("mem|reservation_used", "Reserved (used)", VM),
        column("config|memoryAllocation|reservation", "Reserved (configured)", VM, is_property=True),
        column("config|memoryAllocation|limit", "Memory limit", VM, is_property=True),
        column("summary|oversized|memory", "Oversized by", VM),
        column("summary|undersized|memory", "Undersized by", VM),
        # 20-second peak ready is the one that catches contention a 5-minute average hides.
        column("cpu|usage_average", "CPU util % (max)", VM, transform="MAX"),
        column("cpu|20_sec_peak_readyPct", "CPU ready 20s peak % (max)", VM, transform="MAX"),
        column("cpu|costopPct", "CPU co-stop % (max)", VM, transform="MAX"),
        column("cpu|iowaitPct", "CPU io wait % (max)", VM, transform="MAX"),
        column("mem|guest_activePct", "Active % of configured (max)", VM, transform="MAX"),
    ]),
]


def main():
    # Clear stale output first. A view removed from VIEWS otherwise lingers on disk and ships
    # in the pak referenced by nothing -- caught by build_pak.py's own guard, which is the only
    # reason it did not reach an instance.
    import shutil
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    for title, kind, seed, cols in VIEWS:
        xml = view(title, kind, cols, seed)
        safe = title.replace(" ", "_").replace("[", "").replace("]", "")
        d = os.path.join(OUT, safe)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{safe}.xml")
        with open(path, "w") as f:
            f.write(xml)
        manifest[title] = guid_for(title)
        print(f"   {len(xml):>6} B  {os.path.relpath(path, HERE)}")
        print(f"            guid {guid_for(title)}  subject {kind}  {len(cols)} column(s)")

    # Fail loudly on the one mistake that silently breaks every dashboard binding.
    if len(set(manifest.values())) != len(manifest):
        print("FAILED: two views share a GUID", file=sys.stderr)
        return 1
    import json
    with open(os.path.join(OUT, "view-guids.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"\n{len(manifest)} views; GUIDs written to {os.path.relpath(OUT, HERE)}/view-guids.json")
    print("GUIDs are uuid5 of the title -- renaming a view creates a new one and orphans every "
          "dashboard reference to the old id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
