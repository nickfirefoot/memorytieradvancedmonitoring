#!/usr/bin/env python3
"""Three native-metric views for a manual import on Operations 8.18 -- no pak, no adapter, no
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
import uuid as _uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_views import column, view, guid_for, VM_POWERED_ON, CLUSTER, HOST, VM  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def pct_column(key, label, kind, pct=95, unit=""):
    """PERCENTILE transformation, in the shape 8.18's own built-in views carry it (a `percentile`
    property before `transformations`, e.g. 99.9 on 'Peak Memory Contention')."""
    c = column(key, label, kind, transform="PERCENTILE", unit=unit)
    return c.replace('<Property name="transformations">',
                     f'<Property name="percentile" value="{pct}" />\n'
                     '                                    <Property name="transformations">', 1)


OUT = os.path.join(HERE, "build", "818")

INPUTS = "MemTier 8.18 Cluster Sizing Inputs"
HOSTS = "MemTier 8.18 Hosts"
ALLOC = "MemTier 8.18 VM Allocation Powered On"

# Every key below was checked on 8.18.7: declared, and collected by default (verify_818_views.py).
# Peaks are MAX of 5-minute averages over the 30-day window; Operations keeps no within-cycle
# peak for memory. Totals only on additive, static columns: a sum of peaks is a moment that
# never happened.
VIEWS = [
    (INPUTS, CLUSTER, 900, [
        column("config|name", "Cluster", CLUSTER, is_property=True, sort=True),
        column("summary|total_number_hosts", "Hosts", CLUSTER),
        column("summary|number_running_vms", "Running VMs", CLUSTER),
        column("summary|total_number_vms", "All VMs", CLUSTER),
        column("mem|host_provisioned", "Installed GB", CLUSTER, unit="gb"),
        column("mem|totalCapacity_average", "Available to VMs GB", CLUSTER, unit="gb"),
        # Guest Active total: the cluster metric IS the sum of its VMs' guest active memory,
        # sampled at the same moment, so it is the one total that never double counts.
        column("mem|active_average", "Guest Active total now GB", CLUSTER, transform="CURRENT", unit="gb"),
        column("mem|active_average", "Active peak GB", CLUSTER, transform="MAX", unit="gb"),
        pct_column("mem|active_average", "Active P95 GB", CLUSTER, 95, unit="gb"),
        column("mem|active_average", "Active avg GB", CLUSTER, transform="AVG", unit="gb"),
        # vMotion and maintenance mode can count a VM's working set on two hosts at once; a
        # peak far above P95 alongside vMotions in the window is that, not workload.
        column("summary|number_vmotion", "vMotions (max per 5 min)", CLUSTER, transform="MAX"),
        column("summary|number_drs_vmotion", "DRS vMotions (max per 5 min)", CLUSTER, transform="MAX"),
        column("mem|consumed_average", "Consumed peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("mem|consumed_average", "Consumed avg GB", CLUSTER, transform="AVG", unit="gb"),
        column("mem|usage_average", "Memory usage peak %", CLUSTER, transform="MAX", unit="percent"),
        column("mem|max_vm_mem_contention", "Worst VM mem contention peak %", CLUSTER, transform="MAX", unit="percent"),
        # Memory pressure already present: any non-zero here means DRAM is short today.
        column("mem|vmmemctl_average", "Balloon peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("mem|swapinRate_average", "Swap-in rate peak KBps", CLUSTER, transform="MAX", unit=""),
        column("mem|swapoutRate_average", "Swap-out rate peak KBps", CLUSTER, transform="MAX", unit=""),
        column("mem|compressed_average", "Compressed peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("mem|overhead_average", "VM overhead peak GB", CLUSTER, transform="MAX", unit="gb"),
        column("cpu|capacity_usagepct_average", "CPU avg %", CLUSTER, transform="AVG", unit="percent"),
        column("cpu|capacity_usagepct_average", "CPU peak %", CLUSTER, transform="MAX", unit="percent"),
        column("cpu|usagemhz_average", "CPU used peak MHz", CLUSTER, transform="MAX", unit=""),
        column("cpu|demandmhz", "CPU demand peak MHz", CLUSTER, transform="MAX", unit=""),
        column("cpu|max_cpu_ready", "Worst VM CPU ready peak %", CLUSTER, transform="MAX", unit="percent"),
        column("cpu|percentage_of_vms_facing_cpu_ready", "VMs facing CPU ready peak %", CLUSTER, transform="MAX", unit="percent"),
    ], {}),
    # Per host, for imbalance: a cluster that only fits because one host is empty.
    (HOSTS, HOST, 940, [
        column("summary|parentCluster", "Cluster", HOST, is_property=True, sort=True),
        column("config|name", "Host", HOST, is_property=True),
        column("summary|number_running_vms", "Running VMs", HOST),
        # MTAT's host inputs: Physical_RAM, Consumed_GB (average), Active_GB (maximum), CPU_Pct
        # (average) -- the same definitions MTAT v3.1 uses, so the figures line up with it.
        column("mem|host_provisioned", "Installed GB", HOST, unit="gb"),
        column("mem|active_average", "Active peak GB", HOST, transform="MAX", unit="gb"),
        pct_column("mem|active_average", "Active P95 GB", HOST, 95, unit="gb"),
        column("summary|number_vmotion", "vMotions (max per 5 min)", HOST, transform="MAX"),
        column("mem|consumed_average", "Consumed avg GB", HOST, transform="AVG", unit="gb"),
        column("mem|consumed_average", "Consumed peak GB", HOST, transform="MAX", unit="gb"),
        column("mem|usage_average", "Memory usage peak %", HOST, transform="MAX", unit="percent"),
        column("mem|vmmemctl_average", "Balloon peak GB", HOST, transform="MAX", unit="gb"),
        column("mem|swapinRate_average", "Swap-in rate peak KBps", HOST, transform="MAX", unit=""),
        column("cpu|usage_average", "CPU avg %", HOST, transform="AVG", unit="percent"),
        column("cpu|usage_average", "CPU peak %", HOST, transform="MAX", unit="percent"),
        column("cpu|usagemhz_average", "CPU used peak MHz", HOST, transform="MAX", unit=""),
        column("cpu|ready_summation", "CPU ready peak ms", HOST, transform="MAX", unit=""),
    ], {"totals": [3], "page": 500}),
    # Powered on only: powered-off VMs and templates still report configured memory (~20% of
    # allocated on the lab). Per-VM Guest Active is NOT collected by default on 8.18 (KB 445499),
    # so per-VM active is Non Zero Active, which is. Reservation columns are the native way to
    # spot VMs pinned to DRAM by a full reservation; latency sensitivity is not a native property.
    (ALLOC, VM, 920, [
        column("summary|parentCluster", "Cluster", VM, is_property=True, sort=True),
        column("summary|parentHost", "Host", VM, is_property=True),
        column("config|name", "VM", VM, is_property=True),
        column("config|guestFullName", "Guest OS", VM, is_property=True),
        # Monster VMs (512 GB+ or 128+ vCPUs) are excluded from tiering by VMware's guidance.
        column("config|hardware|numCpu", "vCPUs", VM, is_property=True),
        column("mem|guest_provisioned", "Configured GB", VM, unit="gb"),
        # Guest Active per VM is OFF by default on 8.18: blank until enabled in the policy, and
        # its history starts then. Non Zero Active is on by default and carries the 30 days.
        column("mem|active_average", "Guest Active peak GB (enable in policy)", VM, transform="MAX", unit="gb"),
        column("mem|nonzero_active", "Non Zero Active peak GB", VM, transform="MAX", unit="gb"),
        column("mem|consumed_average", "Consumed peak GB", VM, transform="MAX", unit="gb"),
        # Exclusions Operations can see: full reservation, Fault Tolerance, PCI passthrough.
        column("mem|reservation_used", "Reserved used GB", VM, unit="gb"),
        column("config|memoryAllocation|reservation", "Reservation (configured)", VM, is_property=True),
        column("config|memoryAllocation|limit", "Memory limit", VM, is_property=True),
        column("config|faultTolerant", "Fault Tolerant", VM, is_property=True),
        column("config|ft_role", "FT role", VM, is_property=True),
        column("config|security|pci_device_configured", "PCI passthrough (enable in policy)", VM, is_property=True),
        # Memory pressure on this VM today.
        column("mem|swapped_average", "Swapped peak GB", VM, transform="MAX", unit="gb"),
        column("mem|swapinRate_average", "Swap-in rate peak KBps", VM, transform="MAX", unit=""),
        column("mem|compressed_average", "Compressed peak GB", VM, transform="MAX", unit="gb"),
        column("guest|20_sec_peak_page.outRate_latest", "Guest page-out 20s peak", VM, transform="MAX", unit=""),
        column("summary|oversized|memory", "Oversized by GB", VM, unit="gb"),
        column("summary|undersized|memory", "Undersized by GB", VM, unit="gb"),
        column("mem|20_sec_peak_host_contentionPct", "Mem contention 20s peak %", VM, transform="MAX", unit="percent"),
        column("cpu|usage_average", "CPU peak %", VM, transform="MAX", unit="percent"),
        column("cpu|20_sec_peak_readyPct", "CPU ready 20s peak %", VM, transform="MAX", unit="percent"),
        column("cpu|costopPct", "CPU co-stop peak %", VM, transform="MAX", unit="percent"),
    ], {"filter_json": VM_POWERED_ON, "totals": [5, 9], "page": 1000}),
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
    env = build_dashboard_zip(os.path.join(OUT, "MemTier_818_Dashboard.zip"))
    print(f"wrote build/818/MemTier_818_Dashboard.zip ({len(env['dashboards'][0]['widgets'])} widgets, "
          f"{len(env['dashboards'][0]['widgetInteractions'])} interactions)")
    return 0



# --- dashboard ------------------------------------------------------------------------------
# Same wiring as the pak's proven dashboards (build_content.py): one self-provider rooted at
# vSphere World with selectFirstRow on, receivers driven through widgetInteractions, the views'
# own descendant SubjectType doing the traversal. Packaged for the UI dialog, which wants
# dashboard/dashboard.json inside a zip.
HELP_818 = """<h3 {H}>Memory tiering sizing (Aria Operations 8.18)</h3>
<p {P}><b {B}>Click a cluster</b> in the top table; the hosts and powered-on VMs below follow it. Every
column covers the <b {B}>last 30 days</b>. <b {B}>Peak</b> = the highest 5-minute average in that window
(Operations keeps no finer peak for memory). <b {B}>P95</b> = the value 95% of 5-minute samples stay under.
<b {B}>Avg</b> = the 30-day mean. <b {B}>Now</b> = the latest sample.</p>

<p {P}><b {W}>vMotion and maintenance-mode spikes.</b> While a VM moves, its working set can be counted on
the source and the destination host in the same sample, and DRS evacuations move many VMs at once. The
Guest Active <i>peak</i> can therefore be a moment that never really happened. If <b {B}>Active peak</b> sits
well above <b {B}>Active P95</b> and the <b {B}>vMotions</b> columns are non-zero, treat the peak as a
migration artefact and size on <b {B}>P95</b> (state which one you used). A peak close to P95 is real demand.</p>

<h4 {H}>Clusters</h4>
<p {P}><b {B}>Hosts / Running VMs / All VMs</b>: counts now. All VMs includes powered-off VMs and templates.<br>
<b {B}>Installed GB</b> (Memory | Total Capacity): physical DRAM in the cluster's hosts. On a host already
tiered it would include the NVMe tier; on ESXi 8 it is DRAM.<br>
<b {B}>Available to VMs GB</b> (Memory | Capacity Available to VMs): installed minus what ESXi keeps for itself.<br>
<b {B}>Guest Active total</b> (Memory | Guest Active): memory the guests actually touched, summed over every
VM in the cluster at the same moment. This is the working set and the basis of the DRAM figure. It is an
estimate ESXi makes by sampling pages. Shown as now, peak, P95 and average.<br>
<b {B}>vMotions / DRS vMotions</b> (max per 5 min): migration activity; read it beside the active peak.<br>
<b {B}>Consumed</b> (Memory | Consumed): host memory backing the guests. Includes memory the guest touched once
and never released, so it is usually far above active. Cold memory = consumed minus active.<br>
<b {B}>Memory usage %</b>: consumed as a share of capacity.<br>
<b {B}>Worst VM mem contention %</b>: the worst any VM waited for memory. Non-zero means memory is already short.<br>
<b {B}>Balloon, Swap-in/out rate, Compressed</b>: ESXi reclaiming memory today. Any non-zero value means the
cluster is already short of DRAM; tier only after that is understood.<br>
<b {B}>VM overhead</b>: memory ESXi uses to run the VMs; stays in DRAM.<br>
<b {B}>CPU avg / peak %</b> (CPU | Capacity Usage), <b {B}>CPU used / demand MHz</b>, <b {B}>Worst VM CPU ready %</b>,
<b {B}>VMs facing CPU ready %</b>: CPU headroom. Tiering only pays where memory runs out before CPU.</p>

<h4 {H}>Hosts</h4>
<p {P}>The same memory and CPU columns per host, to spot imbalance: a cluster that only fits because one host is
nearly empty. <b {B}>CPU ready ms</b> is time VMs waited for a CPU. Total row: installed GB.</p>

<h4 {H}>Powered-on VMs</h4>
<p {P}><b {B}>Configured GB</b> (Memory | Total Capacity): memory given to the VM. The Total row is
<b {B}>allocated</b>, the amount the tiered design must present. Powered-off VMs are excluded.<br>
<b {B}>Guest Active peak</b>: per-VM Guest Active. <b {W}>Not collected by default on 8.18</b>: blank until
enabled in the policy (Collect Metrics and Properties, Virtual Machine, Memory | Guest Active), and its history
starts then. Do not add per-VM peaks together: they happen at different times. Use the cluster total.<br>
<b {B}>Non Zero Active peak</b>: collected by default, so it has the 30 days; use it per VM until Guest Active
has history.<br>
<b {B}>Consumed peak</b>: host memory backing this VM.<br>
<b {B}>Reserved used GB / Reservation / Memory limit</b>: a VM whose reservation equals its configured memory is
<b {W}>pinned to DRAM</b> and cannot be tiered; subtract it. Latency-sensitive VMs are also pinned and are not
visible here; check them by hand.<br>
<b {B}>Host / Guest OS / vCPUs</b>: where it runs and what it is; vCPUs and Configured GB identify monster VMs.<br>
<b {B}>Swapped, Swap-in rate, Compressed, Guest page-out 20s peak</b>: this VM is already short of memory.<br>
<b {B}>Oversized / Undersized by</b>: Operations' right-sizing view of the VM.<br>
<b {B}>Mem contention / CPU ready 20s peak, CPU co-stop</b>: the worst moment inside a collection cycle.</p>

<h4 {H}>The sizing</h4>
<p {P}>Per cluster, A = Active peak (or P95, see above), H = Hosts, V = VM Total configured GB, I = Installed GB.
<b {B}>VMware's rule</b>: active memory should be <b {B}>50% or less of DRAM</b>, so the
<b {B}>recommended DRAM</b> = 2 &times; A + 20 GB &times; H. <b {B}>Floor</b> (1 &times; A + reserve) is the
absolute minimum and sits below VMware's guidance. <b {B}>Conservative</b> = 4 &times; A + reserve.
<b {B}>NVMe needed</b> = V &minus; DRAM; per host it must stay under <b {B}>4,096 GB</b>.
<b {B}>Retrofit headroom</b> = I &minus; DRAM: positive means NVMe alone is enough. The 20 GB per host is held
for vSAN, NSX and the hypervisor. Export the tables (Export as CSV) and <code {C}>memtier_818_calc.py</code>
prints all of it.</p>

<h4 {H}>Which VMs cannot be tiered</h4>
<p {P}>From VMware's guidance. <b {B}>Visible here</b>: Fault Tolerance (Fault Tolerant, FT role); full
memory reservation (Reservation equal to Configured); <b {B}>monster VMs</b>, 512 GB or more configured or
128 or more vCPUs (sort the VM table); PCI passthrough (enable in policy).
<b {W}>Not visible in Operations</b>, check in vCenter: latency sensitivity High, SEV / SGX / TDX
confidential computing, nested virtualisation, 1 GB huge-page backing.</p>

<h4 {H}>Matches MTAT</h4>
<p {P}>The Hosts table carries MTAT's host inputs with MTAT's own definitions: Installed GB (Physical_RAM),
Consumed avg (Consumed_GB, average), Active peak (Active_GB, maximum), CPU avg (CPU_Pct, average). The VM
table carries Host, VM, Configured GB (Provisioned_GB) and Guest Active peak (Active_GB). MTAT reads
vCenter's 7-day history; these read Operations' 30 days of 5-minute samples.</p>"""


def _w818(wtype, title, y, h, config, x=1, w=12):
    """Widget in the exact shape 8.18's own exported dashboards carry. The 9.1.1-shaped widget
    from build_content.py imported "successfully" on 8.18.7 and was stored with an EMPTY config
    (no view, no title, no text) -- measured 2026-11-06 by exporting it back."""
    wid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "memtier-818/w/" + title))
    return {"collapsed": False, "id": wid, "gridsterCoords": {"w": w, "x": x, "h": h, "y": y},
            "type": wtype, "title": title, "height": 267, "config": config}


def _provider(title, view_id, y, h):
    return _w818("View", title, y, h, {
        "refreshInterval": 300,
        "resource": {"resourceId": "resource:id:0_::_",
                     "traversalSpecId": "vSphere Hosts and Clusters-VMWARE-vSphere World",
                     "resourceName": "vSphere World", "id": "Ext.vcops.chrome.model.Resource-1",
                     "resourceKindId": "002006VMWAREvSphere World"},
        "traversalSpecId": None, "refreshContent": {"refreshContent": False},
        "isUpdatedView": True, "chartViewItems": [],
        # on: something is selected at load, so the receivers are not empty
        "selectFirstRow": {"selectFirstRow": True},
        "selfProvider": {"selfProvider": True}, "title": title, "viewDefinitionId": view_id})


def _receiver(title, view_id, y, h):
    return _w818("View", title, y, h, {
        "refreshInterval": 300, "resource": None, "traversalSpecId": "",
        "refreshContent": {"refreshContent": False}, "isUpdatedView": True,
        "chartViewItems": [], "selectFirstRow": {"selectFirstRow": False},
        "selfProvider": {"selfProvider": False}, "title": title, "viewDefinitionId": view_id})


def _text(title, html, y, h):
    return _w818("TextDisplay", title, y, h, {
        "locationFile": "", "locationUrl": "", "editorData": html, "refreshInterval": 300,
        "titleLocalized": title, "refreshContent": {"refreshContent": False}, "title": title,
        "viewModeHTML": True})


def build_dashboard_zip(path):
    import io
    import json
    import zipfile
    import build_content as bc
    g = {t: guid_for(t) for t, *_ in VIEWS}
    dash_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "memtier-818/dashboard"))
    help_html = f"<div {bc._CARD}>" + HELP_818.format(H=bc._H, P=bc._P, B=bc._B, W=bc._W, C=bc._C) + "</div>"
    prov = _provider("Clusters (click one)", g[INPUTS], y=1, h=6)
    recv = [_receiver("Hosts in the selected cluster", g[HOSTS], y=7, h=7),
            _receiver("Powered-on VMs in the selected cluster", g[ALLOC], y=14, h=11)]
    widgets = [prov] + recv + [_text("What every column means", help_html, y=25, h=22)]
    kinds = ["ClusterComputeResource", "vSphere World", "HostSystem", "VirtualMachine"]
    env = {
        "entries": {
            "resourceKind": [{"resourceKindKey": k, "internalId": f"resourceKind:id:{i}_::_",
                              "adapterKindKey": "VMWARE"} for i, k in enumerate(kinds)],
            "resource": [{"resourceKindKey": "vSphere World", "internalId": "resource:id:0_::_",
                          "adapterKindKey": "VMWARE", "identifiers": [], "name": "vSphere World"}],
        },
        "dashboards": [{
            "shared": True, "temporary": False, "hidden": False, "creationTime": 0,
            "autoswitchEnabled": False, "importAttempts": 0, "columnProportion": "1",
            "importComplete": True,
            "description": "Memory tiering sizing from native vCenter metrics, last 30 days.",
            "states": [], "homeTab": False, "rank": 0, "disabled": False, "id": dash_id,
            "locked": False, "dashboardNavigations": {},
            "widgetInteractions": [{"widgetIdProvider": prov["id"], "type": "resourceId",
                                    "widgetIdReceiver": r["id"]} for r in recv],
            "lastUpdateUserId": "00000000-0000-0000-0000-000000000000", "columnCount": 1,
            "userId": "00000000-0000-0000-0000-000000000000", "name": "MemTier 8.18 Sizing",
            "gridsterMaxColumns": 12, "lastUpdateTime": 0, "widgets": widgets,
        }],
        "uuid": str(_uuid.uuid5(_uuid.NAMESPACE_URL, "memtier-818/export")),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dashboard/dashboard.json", json.dumps(env, indent=1))
        for lang in ("", "_es", "_fr", "_ja"):
            z.writestr(f"dashboard/resources/resources{lang}.properties", "")
    open(path, "wb").write(buf.getvalue())
    return env

if __name__ == "__main__":
    sys.exit(main())
