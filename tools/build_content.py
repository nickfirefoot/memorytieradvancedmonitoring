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
OUT = os.path.join(HERE, "build")

PREFIX = "MemTier"   # separator is a SPACE: a super metric name may not contain | or :
CONSERVATIVE_FACTOR = float(os.environ.get("MEMTIER_CONSERVATIVE_FACTOR", "4"))
ADAPTER = "VMWARE"
CLUSTER, HOST, VM, WORLD = "ClusterComputeResource", "HostSystem", "VirtualMachine", "vSphere World"
DATACENTER = "Datacenter"
# Our own adapter's kinds -- see adapter/app/adapter.py. They hang off the vCenter objects, so a
# rollup reaches them from the cluster without caring which adapter produced them.
MTA_ADAPTER, MTA_VM = "MemTierAdvanced", "MemTierAdvancedVM"

# Clusters OPT IN to the fleet projection by carrying a vSphere tag. Opt-in rather than opt-out
# is deliberate: nothing is projected that somebody did not choose, so a SQL cluster being
# deferred is simply absent from the total while still visible in the per-cluster table.
# `summary|tag` is collected per cluster by the vCenter adapter (verified on a live instance).
OPT_IN_TAG = os.environ.get("MEMTIER_OPT_IN_TAG", "memtier-include")
GROUP_NAME = "Memory Tier Advanced Candidates"
GROUP_KIND, GROUP_ADAPTER = "Environment", "Container"

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
    # CPU, added to scope 2026-10-15. Tiering raises consolidation only if CPU can absorb the
    # extra VMs; ready time that is fixable by rightsizing is what frees that headroom. Note
    # the key differs by kind: the cluster has NO cpu|usage_average -- it is
    # cpu|capacity_usagepct_average there -- and io wait is cpu|iowait on a host but
    # cpu|iowaitPct on a VM.
    (CLUSTER, "cpu|capacity_usagepct_average"): "CPU utilisation (%)",
    (CLUSTER, "cpu|usagemhz_average"):          "CPU used (MHz)",
    (CLUSTER, "cpu|demandmhz"):                 "CPU demand (MHz)",
    (CLUSTER, "cpu|max_cpu_ready"):             "Worst VM CPU ready (%)",
    (CLUSTER, "cpu|percentage_of_vms_facing_cpu_ready"): "VMs facing CPU ready (%)",
    (CLUSTER, "cpu|workload"):                  "CPU workload (%)",
    (CLUSTER, "summary|total_number_hosts"):    "Hosts",
    (CLUSTER, "summary|total_number_mt_hosts"): "Hosts already tiered",
    (HOST,    "cpu|usage_average"):             "CPU utilisation (%)",
    (HOST,    "cpu|usagemhz_average"):          "CPU used (MHz)",
    (HOST,    "cpu|ready_summation"):           "CPU ready (ms)",
    (HOST,    "cpu|iowait"):                    "CPU io wait",
    (VM,      "cpu|usage_average"):             "CPU utilisation (%)",
    (VM,      "cpu|readyPct"):                  "CPU ready (%)",
    (VM,      "cpu|20_sec_peak_readyPct"):      "CPU ready, 20s peak (%)",
    (VM,      "cpu|iowaitPct"):                 "CPU io wait (%)",
    (VM,      "cpu|costopPct"):                 "CPU co-stop (%)",
    (VM,      "mem|guest_provisioned"): "Configured",
    (VM,      "mem|active_average"):    "Active",
    (VM,      "mem|reservation_used"):  "Reserved",
}


def sm_uuid(name):
    """Deterministic id from the metric name, so re-importing updates in place instead of
    leaving a second copy behind."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"memtier-advanced/{name}"))


def widget(wtype, title, y, x=1, w=12, h=6, config=None):
    wid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"memtier-advanced/widget/{title}"))
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


# Field reference, modelled on the vSAN pack's help panel. Inline style on every element --
# the rich-text editor discards <style> blocks and keeps only inline attributes, and unstyled
# text renders black on a dark theme (LESSONS.md 1.2).
_H = 'style="color:#e8eaed;font-size:15px;margin:0 0 8px"'
_P = 'style="color:#9aa4b0;margin:0 0 9px;line-height:1.5"'
_B = 'style="color:#e8eaed"'
_C = 'style="background:#2a2f36;color:#c8d0d8;padding:1px 4px;border-radius:3px"'
_W = 'style="color:#e8b84b"'

FIELDS = f"""<h3 {_H}>What each figure means</h3>

<p {_P}><b {_B}>Available</b> &mdash; <code {_C}>mem|host_provisioned</code>, summed over the
cluster's hosts. The memory the hypervisor presents. <b {_W}>On an untiered vSphere 8 host this
is installed DRAM; on a host that already has tiering it is DRAM <i>plus</i> the NVMe tier</b>,
which is why it is labelled <i>presented</i> throughout.</p>

<p {_P}><b {_B}>Allocated</b> &mdash; <code {_C}>mem|guest_provisioned</code>, summed over the
cluster's VMs. Memory configured to guests whether or not they ever touch it, and the figure a
tiered host must <i>present</i>. It appears <b {_B}>three times</b> on the cluster table, and
the comparison is the point.</p>
<p {_P}><b {_B}>Allocated (all VMs)</b> is the raw rollup and an <i>upper bound</i>: powered-off
VMs and templates keep reporting configured memory. &middot;
<b {_B}>Allocated (powered on)</b> counts only running VMs &mdash; <b {_W}>size against this
one</b>. &middot; <b {_B}>Allocated (powered off)</b> is the gap between them, measured at
<b {_W}>20.3%</b> of allocated on one estate. A large value is both a reclamation opportunity
and a warning that anything derived from the raw figure is overstated by that much.</p>

<p {_P}><b {_B}>Consumed</b> &mdash; <code {_C}>mem|consumed_average</code>. Host physical
memory actually backing guest pages, plus hypervisor overhead. Always less than or equal to
allocated, and usually well below it.</p>

<p {_P}><b {_B}>Active</b> &mdash; <code {_C}>mem|active_average</code>. The working set: pages
the guests are reading or writing. <b {_B}>This is the number tiering turns on</b>, because the
working set is what must stay in DRAM. It is an ESXi <i>estimate</i> from sampling, not a
measurement, and it is the reason both DRAM figures below carry margin.</p>

<p {_P}><b {_B}>Tierable of used</b> &mdash; <code {_C}>(consumed &minus; active) / 2</code>.
Cold memory: backed in DRAM today but outside the working set, so a candidate for NVMe. Halved
deliberately, because claiming all of it assumes the working set never moves.</p>

<p {_P}><b {_W}>It is an upper bound, and on a vSAN or NSX cluster a loose one.</b> Consumed is
a <i>host</i> figure and includes memory that was never granted to any guest &mdash; vSAN,
NSX and hypervisor structures &mdash; none of which can be tiered. Measured on a 4-host vSAN
cluster over a 30-day peak: <b {_B}>consumed 626.4 GB against granted 508.7 GB</b>, so
<b {_W}>117.8 GB &mdash; 19% of consumed, and about 27% of the tierable figure</b> &mdash; was
host overhead rather than cold guest memory. Compare
<i {_C}>mem|granted_average</i> against <i {_C}>mem|consumed_average</i> on the host list to
size the gap on your own estate before trusting this column.</p>

<h3 {_H}>The two DRAM numbers, and why there are two</h3>

<p {_P}><b {_B}>DRAM required &mdash; floor</b> is <code {_C}>peak active</code>. The aggressive
number: at peak, every page the guests touch fits in DRAM and everything else lives on NVMe.
<b {_W}>It is a floor, not a recommendation.</b> No margin for growth, none for the working set
shifting, and none for active being an estimate.</p>

<p {_P}><b {_B}>DRAM required &mdash; conservative</b> is
<code {_C}>peak active &times; {{factor}}</code>. The planning number: the working set with
{{factor}}&times; headroom. The factor is a starting point and is meant to be tuned once real
peaks from a full business cycle are in hand.</p>

<p {_P}><b {_W}>Both are only as good as the word "peak".</b> A super metric cannot compute a
maximum over a window &mdash; it produces one value per collection. Because both formulas are
<i>linear</i> in active, <code {_C}>max(k &times; active)</code> equals
<code {_C}>k &times; max(active)</code>, so setting a widget or View to the <b {_B}>Maximum</b>
transformation over 30 days turns either into a genuine peak-based figure. Read straight off a
scoreboard tile they are the <i>latest sample</i>, which on a quiet Sunday sizes the purchase
off a trough.</p>

<p {_P}><b {_B}>Implied DRAM share at floor</b> tells you which supported ratio the workload
could carry: <b {_B}>50%</b> is 1:1, <b {_B}>33%</b> is 1:2, <b {_B}>20%</b> is 1:4. Below 20%
the workload is colder than the platform's maximum ratio allows, so the <i>ratio</i> is the
limit rather than the workload &mdash; worth saying out loud in front of a customer.</p>

<h3 {_H}>Sanity check, and what this screen cannot see</h3>

<p {_P}><b {_B}>Active of consumed</b> is the check on the whole exercise. Typical estates run
<b {_B}>8&ndash;12%</b>, nearer 15% where databases dominate. Outside roughly 5&ndash;20%,
suspect the metric rather than the workload &mdash; a cluster reading 1% active is a collection
problem, and it would otherwise look like the best tiering candidate you own.</p>

<p {_P}><b {_W}>vCenter cannot see large pages &mdash; this pack collects them itself.</b>
No performance counter in vCenter reports guest page size or large-page backing &mdash; every
counter mentioning "page" concerns zero pages, compression, swap or page-fault latency, and the
vCenter adapter exposes only three VM advanced settings, none of them the relevant ones
(measured across 208 VM properties). That is why this pack ships <b {_B}>its own collector</b>:
the <i {_C}>MemTierAdvanced</i> adapter reads the settings straight from vSphere and publishes
them as properties on every powered-on VM and host. 2 MB pages are not a disqualifier &mdash;
they are broken down under pressure &mdash; so only the 1 GB opt-in counts.</p>
<p {_P}><b {_B}>Reserved memory is visible and IS a disqualifier:</b> a VM whose reservation
equals its configured memory is pinned to DRAM and cannot be tiered however cold it looks. Both
halves are columns on the VM list &mdash; <i {_C}>Reserved (configured)</i> against the VM's
configured memory. A memory <i {_C}>limit</i> is shown beside it for the same reason.</p>

<h3 {_H}>Disqualifiers: what cannot be tiered, and how this pack finds it</h3>

<p {_P}>A pinned VM cannot be tiered however cold it looks. <b {_W}>Five disqualifiers are
collected and counted as pinned:</b></p>
<p {_P}><b {_B}>PCI passthrough or vGPU</b> &mdash; forces a <b {_W}>100% memory
reservation</b>. A GPU host full of vGPU VMs has every byte pinned and cannot be tiered at all.
This is the one most likely to catch you out. &middot;
<b {_B}>Latency sensitivity = High</b> &mdash; forces full reservation and CPU pinning. &middot;
<b {_B}>memoryReservationLockedToMax</b> &mdash; reservation tracks configured memory forever.
&middot; <b {_B}>1 GB pages</b> &mdash; explicit per-VM opt-in, stays pinned. &middot;
<b {_B}>Full memory reservation</b> &mdash; reservation equal to configured memory. This also
covers <b {_B}>Fault Tolerance</b>, since FT VMs are fully reserved.</p>

<p {_P}><b {_B}>NUMA node affinity</b> is collected and shown per VM but deliberately
<i>not</i> counted as pinned: it does not stop a VM being tiered, it constrains which node's
DRAM it can use. The DRAM tier is per-NUMA-node, so pinned-to-a-node VMs size against that
node rather than the host. <i {_C}>VM % remote memory</i> does not exist in Operations at any
version, so affinity is the only signal available.</p>

<p {_P}><b {_W}>The two RAM-saved figures are gross, not net of pinned memory</b> &mdash;
deliberately. They are built only from vCenter metrics, so they still compute on an estate
where this pack's collector has not been configured. <b {_B}>Pinned memory (GB)</b> and
<b {_B}>pinned VMs</b> sit beside them as their own columns, and
<b {_B}>tierable memory (GB)</b> is allocated already net of pinned. To get net savings,
subtract pinned memory from the saved figure yourself &mdash; or read tierable memory, which
has done it for you.</p>

<p {_P}><b {_W}>The pinned columns are only meaningful once the MemTierAdvanced adapter instance
is configured.</b> Until it collects they read blank or zero, which looks identical to a clean
estate. Confirm the pinned VM count on the VM list before quoting anything &mdash; a blank
there means "not measured", not "none".</p>

<h3 {_H}>CPU: the other half of consolidation</h3>

<p {_P}>Memory tiering buys <b {_B}>consolidation</b> &mdash; more VMs per host, because each
host presents more memory. Consolidation is gated by whichever resource runs out
<i {_C}>first</i>, so a cluster already short of CPU gains nothing from extra presented memory.
Read <b {_B}>CPU headroom %</b> against <b {_B}>Active of host RAM %</b>: the smaller number is
the binding constraint. Tiering pays where <i {_C}>memory</i> binds first.</p>

<p {_P}><b {_B}>Worst VM ready %</b> and <b {_B}>VMs facing ready %</b> are the ones to act on,
and they often change the answer. Ready time means vCPUs waiting for a physical core &mdash;
and it is frequently caused by <i {_C}>oversized</i> VMs, where a VM with far more vCPUs than it
uses must wait for all of them to be schedulable at once. Right-size those and CPU utilisation
<b {_B}>falls</b>, headroom appears, and memory becomes the binding constraint. A cluster that
looks CPU-bound today can be a good tiering candidate after rightsizing, which is why the
<i {_C}>Oversized by</i> column sits on the VM list beside ready.</p>

<p {_P}><b {_B}>CPU io wait</b> is a different bottleneck again &mdash; cores idle waiting on
storage, not on each other. High io wait with low utilisation means the fix is in the storage
path, and neither rightsizing nor tiering will touch it.</p>

<p {_P}><b {_W}>If a cluster shows a DRAM requirement of zero, do not believe it.</b> Both DRAM
figures are derived from active memory, so a cluster whose active metric is missing or reads
zero produces a DRAM requirement of zero &mdash; which presents as "this cluster needs no DRAM"
rather than as a collection failure. Check <b {_B}>Active of consumed</b> first: a plausible
cluster sits in the 5&ndash;20% band, and anything reading near zero is a broken metric, not a
cold workload.</p>"""


def _view_guids():
    """GUIDs come from build_views.py, never a second hand-kept table -- a duplicated list is
    how the vSAN pack's dashboards ended up pointing at stale view ids (LESSONS.md 8)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "build_views.py"))
    bv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bv)
    return bv, {t: bv.guid_for(t) for t, _, _, _ in bv.VIEWS}


def view_provider(title, view_guid, y, x=1, w=2, h=9):
    """Self-provider rooted at vSphere World -- a singleton that exists on every instance, which
    is what makes it portable. An Object List pinned to a named cluster resolves only on the
    system it was exported from (BACKLOG sect 9). selectFirstRow MUST be true: with it off
    nothing is selected at load, no interaction fires, and every receiver renders empty."""
    return widget("View", title, y, x=x, w=w, h=h, config={
        "refreshInterval": 400,
        "resource": {"resourceId": "resource:id:0_::_", "traversalSpecId": "",
                     "resourceName": "vSphere World",
                     "resourceKindId": f"002006{ADAPTER}vSphere World"},
        "traversalSpecId": None, "isUpdatedView": True,
        "viewDefinitionId": view_guid, "titleLocalized": title,
        "chartViewItems": [], "selectFirstRow": {"selectFirstRow": True},
        "viewDetails": "", "selfProvider": {"selfProvider": True}})


def view_receiver(title, view_guid, y, x=1, w=12, h=9):
    """Driven by the provider through one widgetInteractions entry. No depth and no traversal
    spec: the view's own SubjectType type="descendant" does the traversal, which is the part
    that takes longest to find. periodLength dashboardTime is what puts the 1H/6H/24H selector
    on the dashboard -- without it on at least one widget the control greys out."""
    return widget("View", title, y, x=x, w=w, h=h, config={
        "refreshInterval": 300, "resource": None, "traversalSpecId": "",
        "isUpdatedView": True, "viewDefinitionId": view_guid, "titleLocalized": title,
        "viewType": "LIST", "chartViewItems": [],
        "selectFirstRow": {"selectFirstRow": False}, "viewDetails": "",
        "selfProvider": {"selfProvider": False}, "periodLength": "dashboardTime"})


def _interactions(widgets):
    """One entry per receiver, from the one self-provider on the dashboard."""
    def sp(w):
        return w["config"].get("selfProvider", {}).get("selfProvider") is True
    providers = [w for w in widgets if w["type"] == "View" and sp(w)]
    receivers = [w for w in widgets if w["type"] == "View" and not sp(w)]
    if not providers or not receivers:
        return []
    if len(providers) > 1:
        raise ValueError(f"{len(providers)} self-providers on one dashboard; wiring is ambiguous")
    return [{"widgetIdProvider": providers[0]["id"], "type": "resourceId",
             "widgetIdReceiver": r["id"]} for r in receivers]


def _wid(widgets, title):
    """Widget id by title. Raises rather than returning None, because a missing provider wires
    an interaction to nothing and the dashboard still imports cleanly."""
    for w in widgets:
        if w["title"] == title:
            return w["id"]
    raise KeyError(f"no widget titled {title!r} to wire an interaction to")


def build_dashboard():
    bv, guids = _view_guids()
    dash_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-advanced/dashboard"))
    widgets = [
        widget("TextDisplay", "How to read this", y=1, h=5, config={
            "editorData": HELP, "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
        # The sizing table is the headline AND the provider: click a cluster row and the host
        # and VM lists below follow it. A Scoreboard held these numbers and was replaced -- it
        # caps at 100 cells (metrics x objects), shows present value only, and cannot carry
        # dashboardTime, so the one panel with the sizing figures was the one panel that could
        # not honour the time range the whole peak-based model depends on. The vSAN pack's
        # seven shipped dashboards use zero Scoreboards for the same reasons.
        view_provider("Memory tiering sizing by cluster", guids[bv.SIZING], y=6, x=1, w=12, h=11),
        view_receiver("Hosts in the selected cluster", guids[bv.HOSTS], y=17, x=1, w=12, h=9),
        view_receiver("VMs in the selected cluster", guids[bv.VMS], y=26, x=1, w=12, h=11),
        # Heat map stays. Present-value-only is acceptable in the capacity genre and it is the
        # right widget for many objects at a glance (practitioner guide p50). Colour MUST be a
        # percentage: the [0, 50, 100] threshold block is a percent scale, and colouring a KB
        # metric against it paints every host red (caught 2026-10-02).
        heatmap("Hosts: memory usage (%), sized by presented memory, grouped by cluster",
                HOST, "mem|usage_average", "mem|host_provisioned", CLUSTER, y=37),
        widget("TextDisplay", "Field reference", y=44, h=14, config={
            "editorData": FIELDS.replace("{factor}", f"{CONSERVATIVE_FACTOR:g}"),
            "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
    ]
    for w in widgets:
        w["tabId"] = dash_id
    return _envelope(dash_id, widgets, "Memory Tier Advanced - Clusters")


REFRESH_HELP = f"""<h3 {_H}>Hardware refresh &mdash; sizing new hosts</h3>

<p {_P}>This screen answers <b {_B}>how much RAM do we actually need to buy</b>. Installed DRAM
is an <i>output</i> here: size presented memory to the workload, then split it DRAM/NVMe by the
ratio the workload can carry. The companion screen,
<b {_B}>Memory Tier Advanced &mdash; Clusters</b>, answers the other case: keeping the hosts you
own and adding NVMe.</p>

<p {_P}><b {_B}>Read these columns, in this order.</b>
<b {_B}>Allocated (powered on)</b> is what the new hosts must present &mdash; not the raw
allocated figure, which counts powered-off VMs and templates. &middot;
<b {_B}>DRAM floor</b> is peak active: the least DRAM that holds the working set. &middot;
<b {_B}>DRAM conservative</b> is the planning number. &middot;
<b {_B}>RAM saved</b> is what you do not buy, versus an untiered refresh where every presented
GB must be DRAM.</p>

<p {_P}><b {_W}>Subtract pinned memory before quoting anything.</b> <b {_B}>Pinned GB</b> is
memory belonging to VMs that cannot be tiered at all &mdash; 1 GB pages, latency-sensitive,
locked reservations, PCI passthrough or vGPU, or fully reserved. That memory must be DRAM in
any design, so the real saving is the saving column <i>less</i> the pinned column.
<b {_B}>Tierable GB</b> does that subtraction for you.</p>

<p {_P}><b {_W}>And check CPU before believing the memory answer.</b> New hosts sized on memory
alone will be wrong if CPU binds first &mdash; compare <b {_B}>CPU headroom %</b> against
<b {_B}>Active of host RAM %</b>. Ready time that is fixable by rightsizing frees CPU and moves
the constraint back to memory, which is where tiering pays.</p>

<p {_P}>Everything here reads the <b {_B}>Maximum</b> over the dashboard time range, so set it
to a full business cycle. A 24-hour window sizes a purchase off a quiet Tuesday.</p>"""


def build_refresh_dashboard():
    """Same three views, different framing. The views carry every column both cases need; what
    differs is which columns matter and what the reader is being asked to decide."""
    bv, guids = _view_guids()
    dash_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-advanced/dashboard-refresh"))
    widgets = [
        widget("TextDisplay", "Sizing new hardware", y=1, h=7, config={
            "editorData": REFRESH_HELP, "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
        view_provider("Clusters to refresh", guids[bv.SIZING], y=8, x=1, w=12, h=11),
        view_receiver("VMs in the selected cluster", guids[bv.VMS], y=19, x=1, w=12, h=11),
        view_receiver("Hosts in the selected cluster", guids[bv.HOSTS], y=30, x=1, w=12, h=9),
        # Same three views means the same columns, so the same field reference applies verbatim.
        # Parity with the as-is dashboard is the point: a reader who starts on either screen
        # gets the definitions without having to know the other one exists.
        widget("TextDisplay", "Field reference", y=39, h=14, config={
            "editorData": FIELDS, "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
    ]
    for w in widgets:
        w["tabId"] = dash_id
    return _envelope(dash_id, widgets, "Memory Tier Advanced - Hardware Refresh",
                     "Sizes replacement hosts: how much DRAM and NVMe to buy, and what "
                     "tiering saves against an untiered refresh.")


MTAT_HELP = f"""<h3 {_H}>How to export this cluster to MTAT</h3>

<p {_P}>MTAT (the Broadcom Memory Tiering Assessment Tool) sizes new hosts and prices DRAM
against NVMe, but it reads vCenter, where 30 days of history is kept as 2-hour averages. This
screen hands it Operations data instead: true 5-minute peaks. The two tables above are MTAT's
own import files, column for column.</p>

<p {_P}><b {_B}>1. Set the time range</b> at the top of this dashboard to a full business cycle
&mdash; 30 days at least, longer if month-end or quarter-end matters. Every peak is the Maximum
over that range. &middot;
<b {_B}>2. Click a cluster</b> in the first table. &middot;
<b {_B}>3. Export each table</b> with the widget's CSV export: the hosts table is MTAT's
<i>Hosts CSV</i>, the VMs table its <i>VMs CSV</i>. Do not open them in Excel first; a re-save
can reformat the numbers. &middot;
<b {_B}>4. In MTAT</b>: connect to vCenter (MTAT requires it even to import), pick the
<i>same</i> cluster, <b {_B}>Import Data Instead</b> &rarr; <b {_B}>MTAT Export (Hosts + VMs
CSV)</b>, attach both files, and give the range a label such as
<span {_C}>Ops 30d peak</span>. A yellow &ldquo;imported with notes&rdquo; message is normal.</p>

<p {_P}><b {_W}>Stop if Active_GB is blank in the hosts table.</b> It is a super metric, and
super metrics arrive disabled: enable the <span {_C}>MemTier</span> super metrics in the active
policy (Configure &rarr; Policies &rarr; Metrics and Properties) and wait a collection cycle.
MTAT reads a blank as zero, and a cluster with zero active memory passes every check it has.</p>

<p {_P}><b {_B}>Check the import.</b> MTAT's Active Memory total should equal
<b {_B}>Active peak GB</b> in the first table. Every host shows the same Active_GB on purpose:
it is the cluster's simultaneous peak shared evenly, because MTAT adds the column up and a sum
of each host's own peak counts moments that never happened together. Use the
<b {_B}>Clusters</b> dashboard for real per-host figures.</p>

<p {_P}><b {_B}>What MTAT will not know.</b> <b {_B}>Tiering</b> shows <i>Unknown</i> and
<b {_B}>Pinned_Memory</b> <i>N/A</i>; read pinned memory from the Clusters dashboard, and treat
it as DRAM in any design. Consumed_GB is the peak, where MTAT's own collection uses the average.
MTAT reserves no DRAM for vSAN, NSX or the VMkernel &mdash; at 1:1 that rarely changes the
answer, at higher ratios it can.</p>"""


def build_mtat_dashboard():
    """One screen whose only job is producing MTAT's two import files. Views are hard to find
    in the product, so the export lives on its own dashboard with the steps beneath it."""
    bv, guids = _view_guids()
    dash_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-advanced/dashboard-mtat"))
    widgets = [
        view_provider("Choose a cluster to export", guids[bv.MTAT_CLUSTERS], y=1, x=1, w=12,
                      h=7),
        view_receiver("MTAT Hosts CSV (export this)", guids[bv.MTAT_HOSTS], y=8, x=1, w=12,
                      h=8),
        view_receiver("MTAT VMs CSV (export this)", guids[bv.MTAT_VMS], y=16, x=1, w=12, h=11),
        widget("TextDisplay", "How to export to MTAT", y=27, h=13, config={
            "editorData": MTAT_HELP, "locationFile": "", "locationUrl": "",
            "refreshContent": {"refreshContent": False}, "viewModeHTML": True}),
    ]
    for w in widgets:
        w["tabId"] = dash_id
    return _envelope(dash_id, widgets, "Memory Tier Advanced - Export for MTAT",
                     "Produces MTAT's Hosts and VMs import files from Operations data, so MTAT "
                     "sizes on 5-minute peaks rather than vCenter's 2-hour averages.")


def _envelope(dash_id, widgets, name, description=None):
    return {
        "entries": {
            "resourceKind": [{"resourceKindKey": k, "internalId": KIND_ID[k],
                              "adapterKindKey": ADAPTER} for k in KINDS],
            "resource": [],          # deliberately empty: never pin a resource (BACKLOG §9)
        },
        "dashboards": [{
            "id": dash_id,
            "name": name,
            "description": description or ("Sizing a vSphere estate for NVMe memory tiering, "
                                           "from metrics the "
                           "vCenter adapter already collects."),
            "userId": "00000000-0000-0000-0000-000000000000",
            "lastUpdateUserId": "00000000-0000-0000-0000-000000000000",
            "shared": True, "hidden": False, "disabled": False, "locked": False,
            "editAllowed": True, "homeTab": False, "rank": 0,
            "creationTime": 0, "lastUpdateTime": 0,
            "importAttempts": 0, "importComplete": True, "autoswitchEnabled": False,
            "columnCount": 0, "columnProportion": "1", "gridsterMaxColumns": 12,
            "states": [], "dashboardNavigations": {},
            # Derive the wiring from the widgets themselves: the single self-provider
            # drives every receiver. Resolving by hardcoded title broke the moment a second
            # dashboard named its provider differently, and resolving by list index silently
            # rewires itself when a widget is added above.
            "widgetInteractions": _interactions(widgets),
            "widgets": widgets,
        }],
        "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, "memtier-advanced/export")),
    }


# A resource kind only exists under the adapter that defines it, and binding one to the wrong
# adapter is accepted silently: the super metric imports, reports no error, and is simply never
# attached to anything. Group kinds (Environment, Department, ...) come from the Container
# adapter -- not VMWARE -- so the pairing is derived here rather than passed in, because it was
# passed in once and the four fleet rollups spent their life bound to a VMWARE/Environment kind
# that does not exist.
KIND_ADAPTER = {GROUP_KIND: GROUP_ADAPTER}


def sm(name, formula, kind, unit, description):
    adapter = KIND_ADAPTER.get(kind, ADAPTER)
    return sm_uuid(name), {
        "name": name, "formula": formula, "description": description, "unitId": unit,
        "resourceKinds": [{"resourceKindKey": kind, "adapterKindKey": adapter}]}


def roll(kind, key, depth):
    return f"sum(${{adaptertype={ADAPTER}, objecttype={kind}, metric={key}, depth={depth}}})"


def build_supermetrics():
    KB_PER_GB = 1048576
    host_avail = roll(HOST, "mem|host_provisioned", 1)
    host_active = roll(HOST, "mem|active_average", 1)
    # --- finding E: a zero or missing `active` must not produce a confident wrong answer ------
    # Every sizing output below is derived from active, so a cluster whose active metric is
    # absent or reads zero yields "this cluster needs no DRAM" -- the cheapest possible buy,
    # presented as a result rather than as a collection failure.
    #
    # The guard is `* (active / active)`, NOT a ternary. When active > 0 that factor is exactly
    # 1 and the value is untouched; when active is 0 it is 0/0, which the engine renders as
    # BLANK rather than zero (practitioner guide p106: "the maths of 0 / 0 = undefined", shown
    # as an empty cell). So the panel goes empty, which reads as "no answer" instead of "no
    # DRAM needed". Arithmetic only -- no reliance on ternary support, which is documented for
    # 8.18 but unverified there, and a formula the importer rejects would be worse than the bug.
    guard = f"({host_active} / {host_active})"

    host_consumed = roll(HOST, "mem|consumed_average", 1)
    vm_alloc = roll(VM, "mem|guest_provisioned", 2)
    out = {}
    for k, v in [
        # --- finding C: allocated, with and without powered-off VMs ---------------------
        # Powered-off VMs and templates keep reporting configured memory -- 20.3% of allocated
        # measured on this estate -- and every sizing figure scales with it. A rollup aggregates
        # ONE metric and cannot filter, so the gate happens per VM and a second super metric
        # rolls it up. Proven syntax, not a guess: the vCommunity pack (SDK-built,
        # vcops_minimum_version 8.18.0) does this in 15 of its own super metrics. Rollups of a
        # super metric use attribute= rather than metric= (9 uses to 2 in theirs);
        # ${this, metric=...} is the self-reference form.
        #
        # The gate is a plain multiply by sys|poweredOn, which is 1 or 0 -- no division, no
        # 0/0, because a powered-off VM contributes genuine zero rather than "unknown". A
        # template with no power state yields blank and drops out of the sum, also correct.
        sm(f"{PREFIX} VM Allocated if Powered On (KB)",
           "${this, metric=mem|guest_provisioned} * ${this, metric=sys|poweredOn}",
           VM, "kb",
           "Per VM: configured memory if running, zero if not. Exists to be rolled up; it is "
           "not interesting on a single VM."),
        sm(f"{PREFIX} Allocated Powered On (GB)",
           f"sum(${{adaptertype={ADAPTER}, objecttype={VM}, attribute=Super Metric|"
           f"sm_{sm_uuid(f'{PREFIX} VM Allocated if Powered On (KB)')}, depth=2}}) / {KB_PER_GB}",
           CLUSTER, "gb",
           "Allocated counting only powered-on VMs. THIS is the figure to size against. The "
           "plain Allocated beside it includes powered-off VMs and templates, which still "
           "report configured memory and are reclamation candidates, not demand."),
        sm(f"{PREFIX} Allocated Powered Off (GB)",
           f"({vm_alloc} / {KB_PER_GB}) - (sum(${{adaptertype={ADAPTER}, objecttype={VM}, "
           f"attribute=Super Metric|sm_{sm_uuid(f'{PREFIX} VM Allocated if Powered On (KB)')}, "
           f"depth=2}}) / {KB_PER_GB})", CLUSTER, "gb",
           "The gap between the two: memory configured to VMs that are not running, measured "
           "at 20.3% of allocated on one estate. A reclamation opportunity, and a warning that "
           "anything derived from plain Allocated is overstated by this much."),
        sm(f"{PREFIX} Allocated (GB)", f"{vm_alloc} / {KB_PER_GB}", CLUSTER, "gb",
           "Sum of configured memory across the cluster's VMs. The one base figure with no "
           "native cluster metric. INCLUDES powered-off VMs and templates, so it is an upper "
           "bound -- compare it against Allocated Powered On, which does not."),
        sm(f"{PREFIX} Tierable of Used (GB)",
           f"((({host_consumed} - {host_active}) / 2) * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           "Cold memory currently backed in DRAM, halved for conservatism. Blank means the "
           "active metric is missing, not that everything is cold. Consumed minus "
           "active, in that order -- active is the working set within consumed."),
        sm(f"{PREFIX} Active of Allocated (%)",
           f"({host_active} / {vm_alloc}) * 100", CLUSTER, "percent",
           "Raw active as a share of allocated, with NO headroom factor applied, so the number "
           "means what its name says. Apply headroom in the classification, not here."),
        sm(f"{PREFIX} Active of Consumed (%)",
           f"({host_active} / {host_consumed}) * 100", CLUSTER, "percent",
           "Plausibility check on the whole exercise. Typical estates sit at 8-12%, nearer 15% "
           "where databases dominate. Outside 5-20% suspect the metric, not the workload."),
        # --- the originally specified base set ------------------------------------------
        # These four were in the brief verbatim and three of them were never built: the model
        # drifted into its own derivations (Active of Allocated / of Consumed) and left the
        # asked-for figures out. Restored 2026-10-07.
        sm(f"{PREFIX} Unused (GB)",
           f"({vm_alloc} - {host_consumed}) / {KB_PER_GB}", CLUSTER, "gb",
           "allocated - consumed. Memory configured to guests that the host has never had to "
           "back. Overcommit you are already harvesting, and the cheapest headroom there is."),
        sm(f"{PREFIX} Unallocated (GB)",
           f"({host_avail} - {vm_alloc}) / {KB_PER_GB}", CLUSTER, "gb",
           "available - allocated. Installed memory handed to no VM. NEGATIVE MEANS THE CLUSTER "
           "IS OVERCOMMITTED, which is a useful signal in itself -- it is deliberately not "
           "clamped at zero."),
        sm(f"{PREFIX} Active of Host RAM (%)",
           f"({host_active} / {host_avail}) * 100", CLUSTER, "percent",
           "active / available. The working set against the memory actually installed. This is "
           "the one that says whether a DRAM tier sized at today's hardware would hold the "
           "workload at all."),
        sm(f"{PREFIX} Overcommit (%)",
           f"({vm_alloc} / {host_avail}) * 100", CLUSTER, "percent",
           "allocated / available. Under 100% the cluster is not overcommitted. Estates that do "
           "overcommit typically sit 5-10% over, so 100-110% is mild and only past 110% is "
           "worth flagging -- judged on typical allocation, not on a peak, because allocation "
           "is a configuration fact that drifts slowly rather than a spiky metric."),
        # --- pinned VMs: what the cluster CANNOT tier, however cold it looks ------------
        # Our adapter publishes `pinned` (1/0) and `pinnedMemoryKB` per VM, set by any of: 1GB
        # pages, latencySensitivity high, memoryReservationLockedToMax, PCI passthrough or
        # vGPU, or a full reservation. Rolled up here so a cluster that cannot be tiered is
        # visible without reading the VM list. depth=3: cluster -> host -> VM -> our object.
        sm(f"{PREFIX} Pinned VMs",
           f"sum(${{adaptertype={MTA_ADAPTER}, objecttype={MTA_VM}, metric=pinned, depth=3}})",
           CLUSTER, "",
           "Count of VMs pinned to DRAM and therefore untierable, for any reason the adapter "
           "can see. Zero is the expected answer; a non-zero count caps what tiering can "
           "achieve here no matter how cold the cluster looks."),
        sm(f"{PREFIX} Pinned Memory (GB)",
           f"sum(${{adaptertype={MTA_ADAPTER}, objecttype={MTA_VM}, metric=pinnedMemoryKB, "
           f"depth=3}}) / {KB_PER_GB}", CLUSTER, "gb",
           "Configured memory belonging to pinned VMs. This much of the cluster must be DRAM "
           "regardless of the sizing model -- subtract it before believing any saving."),
        sm(f"{PREFIX} Tierable Memory (GB)",
           f"({vm_alloc} / {KB_PER_GB}) - (sum(${{adaptertype={MTA_ADAPTER}, "
           f"objecttype={MTA_VM}, metric=pinnedMemoryKB, depth=3}}) / {KB_PER_GB})",
           CLUSTER, "gb",
           "Allocated memory minus memory pinned to DRAM: the honest ceiling on what tiering "
           "can address in this cluster."),

        # --- the saving: the number this whole pack exists to produce --------------------
        # Without tiering every presented GB must be DRAM, so DRAM = allocated. With tiering at
        # the floor, DRAM = peak active. The difference is what tiering saves. Guarded, because
        # a missing active metric would otherwise report a saving equal to the whole estate.
        sm(f"{PREFIX} RAM Saved at Floor (GB)",
           f"(({vm_alloc} - {host_active}) * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           "allocated - peak active. RAM you would NOT have to buy if this cluster were tiered "
           "and DRAM sized to the working set. Read with the Maximum transformation over a full "
           "business cycle; blank means the active metric is missing."),
        sm(f"{PREFIX} RAM Saved Conservative (GB)",
           f"(({vm_alloc} - ({host_active} * {CONSERVATIVE_FACTOR})) * {guard}) / {KB_PER_GB}",
           CLUSTER, "gb",
           f"allocated - ({CONSERVATIVE_FACTOR:g} x peak active). The saving with the planning "
           "factor applied rather than the floor. Negative means the conservative DRAM figure "
           "exceeds what is allocated today, i.e. tiering saves nothing at this factor."),

        # --- retrofit: existing hardware, add NVMe --------------------------------------
        # The replacement case treats DRAM as an output. Retrofit inverts it: installed DRAM is
        # a CONSTRAINT, and the question is whether the working set already fits it.
        sm(f"{PREFIX} Retrofit Headroom (GB)",
           f"(({host_avail} - {host_active}) * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           "Installed DRAM minus peak active. POSITIVE means the working set already fits the "
           "DRAM you own, so this cluster can be tiered by adding NVMe alone, with no DRAM "
           "purchase. Negative means it cannot, whatever NVMe is added."),
        sm(f"{PREFIX} Retrofit NVMe to Add (GB)",
           f"(({vm_alloc} - {host_avail}) / {KB_PER_GB})", CLUSTER, "gb",
           "Allocated minus installed DRAM: the NVMe needed to present today's allocated memory "
           "on today's hosts. Zero or negative means installed DRAM already covers allocation "
           "and tiering would buy capacity you are not yet using."),

        # --- platform limits MTAT models and this did not ------------------------------
        # NVMe tier size is capped per host by the kernel/partition limit. A cluster whose
        # per-host NVMe requirement exceeds it cannot be built as designed, however good the
        # cluster-level arithmetic looks -- MTAT clamps at 4096 GB/host and this had no notion
        # of it at all.
        sm(f"{PREFIX} NVMe per Host (GB)",
           f"((({vm_alloc} - {host_active}) * {guard}) / {KB_PER_GB}) / "
           f"{roll(CLUSTER, 'summary|total_number_hosts', 0)}",
           CLUSTER, "gb",
           "NVMe tier each host would carry at the DRAM floor. COMPARE AGAINST 4096 GB: above "
           "that the tier exceeds the per-host kernel and partition limit and the design is not "
           "buildable, whatever the cluster total says. Reduce the ratio or add hosts."),
        sm(f"{PREFIX} Active of Allocated at Peak (%)",
           f"(({host_active} / {vm_alloc}) * 100) * {guard}", CLUSTER, "percent",
           "Peak working set as a share of allocated. The 50% line is the safety limit: above "
           "it active memory, not the chosen ratio, is what binds the DRAM size. Below 20% the "
           "platform's maximum 1:4 ratio binds instead -- the workload is colder than the "
           "platform can exploit."),
        # --- consolidation: CPU is the other constraint ---------------------------------
        # Memory tiering buys consolidation headroom, and consolidation is gated by whichever
        # resource binds FIRST. Read this against Active of Host RAM: if CPU headroom is the
        # smaller number, extra presented memory buys nothing until CPU is addressed. If
        # memory is the smaller number, tiering is pointed at the real constraint.
        sm(f"{PREFIX} CPU Headroom (%)",
           f"100 - {roll(HOST, 'cpu|usage_average', 1)} / "
           f"({roll(HOST, 'cpu|usage_average', 1)} / {roll(HOST, 'cpu|usage_average', 1)})",
           CLUSTER, "percent",
           "100 - CPU utilisation, as a cluster rollup. Compare against Active of Host RAM: "
           "the SMALLER headroom is the constraint that binds consolidation first. Tiering only "
           "pays where memory binds before CPU. Blank means the CPU metric is missing."),
        # --- DRAM sizing: a floor and a conservative number -----------------------------
        # Both are LINEAR in active, which is what makes peak-based sizing possible at all:
        # a super metric cannot compute a maximum over a window, but max(k * active) equals
        # k * max(active), so a widget or View with the Maximum transformation over 30 days
        # yields a true peak-based figure from an instantaneous formula. Use it that way.
        sm(f"{PREFIX} DRAM Required Floor (GB)",
           f"({host_active} * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           "AGGRESSIVE. DRAM sized to the working set and nothing more: at peak, every page "
           "the guests are actually touching fits in DRAM and all cold memory lives on NVMe. "
           "Blank means the active metric is missing, NOT that no DRAM is needed. "
           "This is a floor, not a recommendation -- there is no margin for growth, for a "
           "working set that moves, or for active memory being an ESXi estimate rather than a "
           "measurement. Read it with the Maximum transformation over 30 days."),
        sm(f"{PREFIX} DRAM Required Conservative (GB)",
           f"({host_active} * {CONSERVATIVE_FACTOR} * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           f"CONSERVATIVE. {CONSERVATIVE_FACTOR:g}x the working set, so DRAM holds the active "
           f"set with {CONSERVATIVE_FACTOR:g}x headroom for growth and for the working set "
           "shifting. Starting point for planning, not a final answer -- tune the factor once "
           "real peaks are in hand. Read it with the Maximum transformation over 30 days."),
        sm(f"{PREFIX} NVMe Required at Floor (GB)",
           f"(({vm_alloc} - {host_active}) * {guard}) / {KB_PER_GB}", CLUSTER, "gb",
           "Allocated memory that would sit on NVMe if DRAM were sized to the floor. Negative "
           "means the working set already exceeds what is allocated -- investigate before "
           "sizing anything on it."),
        sm(f"{PREFIX} Implied DRAM Share at Floor (%)",
           f"({host_active} / {vm_alloc}) * 100 * {guard}", CLUSTER, "percent",
           "DRAM as a share of presented memory at the floor. Compare against the supported "
           "ratios: 50% is 1:1, 33% is 1:2, 20% is 1:4. Below 20% the workload is cold enough "
           "that the platform's maximum ratio, not the workload, is the limit."),
        # --- fleet projection over the OPTED-IN clusters only ----------------------------
        # Assigned to the custom group, not to Datacenter or vSphere World, so the total covers
        # exactly the clusters someone tagged. depth=1: group -> member cluster.
        sm(f"{PREFIX} Fleet RAM Saved at Floor (GB)",
           f"sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, attribute=Super Metric|"
           f"sm_{sm_uuid(f'{PREFIX} RAM Saved at Floor (GB)')}, depth=1}})",
           GROUP_KIND, "gb",
           "Total RAM not purchased across every cluster tagged into this group. The headline "
           "number, and it only counts clusters someone opted in."),
        sm(f"{PREFIX} Fleet RAM Saved Conservative (GB)",
           f"sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, attribute=Super Metric|"
           f"sm_{sm_uuid(f'{PREFIX} RAM Saved Conservative (GB)')}, depth=1}})",
           GROUP_KIND, "gb",
           "The same total with the planning factor applied rather than the floor."),
        sm(f"{PREFIX} Fleet Allocated Powered On (GB)",
           f"sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, attribute=Super Metric|"
           f"sm_{sm_uuid(f'{PREFIX} Allocated Powered On (GB)')}, depth=1}})",
           GROUP_KIND, "gb",
           "Allocated memory across the opted-in clusters, running VMs only."),
        sm(f"{PREFIX} Fleet Pinned Memory (GB)",
           f"sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, attribute=Super Metric|"
           f"sm_{sm_uuid(f'{PREFIX} Pinned Memory (GB)')}, depth=1}})",
           GROUP_KIND, "gb",
           "Memory across the opted-in clusters that is pinned to DRAM and cannot be tiered. "
           "Subtract it from the saving before quoting a number."),
        # --- export for MTAT: per-host share of the cluster's SIMULTANEOUS active ----------
        # MTAT adds up its hosts' Active_GB to get cluster active. Exporting each host's own
        # 30-day peak would hand it a sum of peaks that happened at different times, which
        # overstates the cluster. Computed every 5 minutes as cluster active / host count, the
        # Maximum of this over the window is the cluster's real peak / n, and MTAT's sum of
        # n rows is exactly that peak. Cost: every host in the export shows the same figure.
        # depth=-1 reaches the PARENT cluster. That is the documented direction for negative
        # depth but has not been observed computing on this lab -- confirm the export's total
        # against "Active peak GB" on the export dashboard before trusting it.
        sm(f"{PREFIX} MTAT Active Share (GB)",
           f"(sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, metric=mem|active_average, "
           f"depth=-1}}) / sum(${{adaptertype={ADAPTER}, objecttype={CLUSTER}, "
           f"metric=summary|total_number_hosts, depth=-1}})) / {KB_PER_GB}",
           HOST, "gb",
           "This host's equal share of its cluster's active memory at the same instant. For the "
           "MTAT export only: MTAT sums the column, so the total is the cluster's real "
           "simultaneous peak rather than a sum of per-host peaks. Read it with Maximum."),
        # --- A/B test, remove once settled: which depth reaches hosts from vSphere World? ---
        sm(f"{PREFIX} TEST Fleet Active depth3 (GB)",
           f"{roll(HOST, 'mem|active_average', 3)} / {KB_PER_GB}", WORLD, "gb",
           "A/B TEST ONLY. Measured tree depth from vSphere World to HostSystem is 3."),
        sm(f"{PREFIX} TEST Fleet Active depth10 (GB)",
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
    ids = {w["id"]: w for w in widgets}
    for i in dash["dashboards"][0].get("widgetInteractions", []):
        for role in ("widgetIdProvider", "widgetIdReceiver"):
            if i[role] not in ids:
                problems.append(f"interaction {role} names no widget on this dashboard")
        prov = ids.get(i["widgetIdProvider"], {}).get("config", {})
        if prov and not prov.get("selfProvider", {}).get("selfProvider"):
            problems.append(f"interaction provider {ids[i['widgetIdProvider']]['title']!r} "
                            f"is not a self-provider")
        recv = ids.get(i["widgetIdReceiver"], {}).get("config", {})
        if recv and recv.get("selfProvider", {}).get("selfProvider"):
            problems.append(f"interaction receiver {ids[i['widgetIdReceiver']]['title']!r} "
                            f"is a self-provider; it will ignore the provider")
    refs = {w["config"]["viewDefinitionId"] for w in widgets if "viewDefinitionId" in w["config"]}
    bv, guids = _view_guids()
    missing = refs - set(guids.values())
    if missing:
        problems.append(f"dashboard references view GUIDs no view defines: {sorted(missing)}")
    if refs and not any(w["config"].get("periodLength") == "dashboardTime" for w in widgets):
        problems.append("no widget set to dashboardTime -- the 1H/6H/24H selector will grey out")
    if dash["entries"]["resource"]:
        problems.append("entries.resource is not empty -- forbidden by BACKLOG §9")
    return problems


def verify_live(dash, sms):
    """Check every metric key the dashboard uses is observed on a real object of that kind."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "probes"))
    from _opslib import req, token, statkeys      # noqa: E402
    tok = token()
    ok = True
    for kind in KINDS:
        rl = req(f"/resources?adapterKind={ADAPTER}&resourceKind={kind}&pageSize=1000",
                 token=tok)["resourceList"]
        observed = set()
        for r in rl[:12]:
            observed |= statkeys(r["identifier"], tok)
        wanted = {k for (kk, k) in METRICS if kk == kind}
        for k in sorted(wanted):
            hit = k in observed
            ok &= hit
            print(f"   {'OK  ' if hit else 'MISS'}  {kind:<24} {k}")
    kinds_declared = {rk["resourceKindKey"] for d in [dash] for rk in d["entries"]["resourceKind"]}
    kinds_declared |= {r["resourceKindKey"] for v in sms.values() for r in v["resourceKinds"]}
    all_kinds = {k["key"] for k in req(f"/adapterkinds/{ADAPTER}/resourcekinds?limit=500",
                                       token=tok)["resource-kind"]}
    # Group kinds (Environment, Department, ...) belong to the Container adapter, and our own
    # object kinds to our adapter -- a VMWARE-only check wrongly fails both.
    for extra in (GROUP_ADAPTER, MTA_ADAPTER):
        try:
            all_kinds |= {k["key"] for k in req(
                f"/adapterkinds/{extra}/resourcekinds?limit=500", token=tok)["resource-kind"]}
        except Exception:
            pass   # our own adapter is absent until the pak is installed; expected
    for k in sorted(kinds_declared):
        hit = k in all_kinds
        ok &= hit
        print(f"   {'OK  ' if hit else 'MISS'}  resource kind exists: {k}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="check metric keys against the live instance in ~/ops.env")
    args = ap.parse_args()

    dash = build_dashboard()
    refresh = build_refresh_dashboard()
    mtat = build_mtat_dashboard()
    sms = build_supermetrics()

    legal = {(ADAPTER, CLUSTER), (ADAPTER, HOST), (ADAPTER, VM), (ADAPTER, WORLD),
             (GROUP_ADAPTER, GROUP_KIND), (MTA_ADAPTER, MTA_VM)}
    for v in sms.values():
        for rk in v.get("resourceKinds", []):
            pair = (rk.get("adapterKindKey"), rk.get("resourceKindKey"))
            if pair not in legal:
                print(f"SELF-CHECK FAILED: {v['name']!r} binds {pair[1]!r} to adapter "
                      f"{pair[0]!r}. A resource kind belongs to exactly one adapter; the wrong "
                      f"pairing imports cleanly and then attaches to nothing.", file=sys.stderr)
                return 1
    for v in sms.values():
        if "|" in v["name"] or ":" in v["name"]:
            print(f"SELF-CHECK FAILED: super metric name may not contain '|' or ':': "
                  f"{v['name']!r}. The content importer reads such a name, creates nothing, "
                  f"and reports imported=0 with NO error -- a silent total failure.",
                  file=sys.stderr)
            return 1
    problems = self_check(dash) + self_check(refresh) + self_check(mtat)
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
    rj = os.path.join(OUT, "dashboard-refresh.json")
    with open(rj, "w") as f:
        json.dump(refresh, f, indent=1)
    with open(os.path.join(OUT, "dashboard-mtat.json"), "w") as f:
        json.dump(mtat, f, indent=1)
    # A dashboard export is a zip with dashboard/dashboard.json at that exact path; the UI
    # import dialog does not accept a bare .json.
    with zipfile.ZipFile(os.path.join(OUT, "Dashboard.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dj, "dashboard/dashboard.json")
    with open(os.path.join(OUT, "supermetric.json"), "w") as f:
        json.dump(sms, f, indent=1)
    # Shape taken from a live group read back over the API, not invented.
    group = {
        "resourceKey": {"name": GROUP_NAME, "adapterKindKey": GROUP_ADAPTER,
                        "resourceKindKey": GROUP_KIND, "resourceIdentifiers": []},
        "autoResolveMembership": True,
        "membershipDefinition": {
            "includedResources": [], "excludedResources": [], "custom-group-properties": [],
            "rules": [{
                "resourceKindKey": {"resourceKind": CLUSTER, "adapterKind": ADAPTER},
                "statConditionRules": [],
                "propertyConditionRules": [
                    {"key": "summary|tag", "stringValue": OPT_IN_TAG, "compareOperator": "CONTAINS"}],
                "resourceNameConditionRules": [], "relationshipConditionRules": [],
                "resourceTagConditionRules": [],
            }],
        },
    }
    gdir = os.path.join(OUT, "customgroups")
    os.makedirs(gdir, exist_ok=True)
    with open(os.path.join(gdir, "MemoryTierAdvancedCandidates.json"), "w") as f:
        json.dump(group, f, indent=1)
    print(f"   opt-in group: clusters tagged {OPT_IN_TAG!r} join {GROUP_NAME!r}")
    print(f"wrote {OUT}/dashboard.json, Dashboard.zip, supermetric.json "
          f"({len(sms)} super metrics)")

    if args.verify:
        print("\nverifying every metric key against the live instance:")
        if not verify_live(dash, sms):
            print("\nVERIFY FAILED: at least one key or kind is missing", file=sys.stderr)
            return 1
        print("\nverify passed: every metric key is observed and every resource kind exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
