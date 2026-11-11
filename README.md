# Memory Tier Advanced for VCF Operations

Sizes vSphere clusters for **NVMe memory tiering**, and shows which clusters are **out of memory now**,
from metrics VCF Operations already collects. No super metrics, no vCenter credentials, no outbound
connection: it works air-gapped.

**Download: [latest release](../../releases/latest).** Tested on **Aria Operations 8.18.7** and
**VCF Operations 9.1.1**.

## What it ships

One pak (`vcfcf_sdk_memtier_advanced.<version>.pak`) containing:

| | |
|---|---|
| **Sizing** dashboard | Clusters, their running hosts and powered-on VMs over the last 30 days: Guest Active (now, peak, P95, average), installed and available memory, consumed, memory and CPU pressure, IO wait and disk latency, and the VMs that cannot be tiered. |
| **Memory Pressure** dashboard | Which clusters are out of memory now: demand, workload, capacity remaining, contention, balloon and swap over the last 24 hours, worst first and colour-coded. |
| 6 views | The tables behind both dashboards, usable on their own and exportable as CSV. |
| 1 report | *Memory Tier Advanced - Cluster Memory Pressure*, PDF and CSV, ready to schedule. |
| A minimal adapter | Needed for a Java pak; it registers one World object and collects nothing. |

Screenshots and the full text of each dashboard's help panels: [docs/dashboards](docs/dashboards/).

## Install

1. **Administration → Integrations → Repository → ADD.** Choose the `.pak`, tick **Ignore the PAK
   file signature checking**, **UPLOAD**, **NEXT**, answer **YES** to the unsigned-pak warning, accept
   the EULA, **NEXT**. It takes a few minutes. On 9.1.1 the wizard stages the pak for about 30
   seconds after the upload reaches 100% before NEXT enables.
2. **Complete the install**: the same steps are in a panel at the bottom of each dashboard.
   - **Add the adapter instance:** Integrations → Repository → click **Memory Tier Advanced** →
     **ADD ACCOUNT** → type a Name → **ADD**. It turns green within a few minutes.
   - **Turn on two VM metrics in the active policy:** per-VM **Guest Active** (8.18 only; 9.x
     collects it already) and **PCI PassThrough** (both). Policy Definition is under Operations →
     Configurations on 8.18 and Administration → Configurations on 9.x; then the Active policy →
     EDIT POLICY → Metrics and Properties → Virtual Machine → set each to **Activated** → SAVE.
3. **Wait.** Dashboards can show "The widget is not configured" with an hourglass for up to 15
   minutes after an install or upgrade while Operations links them to their views. Per-VM Guest
   Active history starts when the policy is saved; everything else already has 30 days.

### Upgrading

- Install the new pak over the old one. Then check the adapter instance: Administration → Integrations
  → Accounts → expand Memory Tier Advanced. If it is stopped (an upgrade once left it so on 9.1.1),
  open **⋮** on its row and choose **Start Collecting**.
- **From v3.0.0-rc.1 only:** rc.2 renamed the dashboard, and Operations matches pak dashboards by
  name, so the rc.1 dashboard ("Memory Tier Advanced - Sizing") is left behind. Delete it by hand.
  An uninstall after that upgrade also leaves "Memory Tier Advanced › Sizing" behind; delete it too.
  Dashboard names are frozen from rc.3 on.
- **Not a drop-in over 2.x:** v3's adapter kind is `memtier_advanced`. Uninstall 2.x first (see below).

### Uninstall

Integrations → Repository → click **Memory Tier Advanced** → **⋯** → **Uninstall**, tick *I understand
the risk and agree*, **OK**. It removes the solution, the adapter instance and its World, the views,
dashboards and report; vCenter's objects are untouched. Takes about 10 minutes.

### Without the pak

For an instance where an unsigned pak cannot be installed, the sizing views can be imported by hand
on 8.18: [docs/MANUAL-8.18.md](docs/MANUAL-8.18.md). That set has the Sizing tables only, not the
Memory Pressure dashboard or the report.

## How the sizing works

Per cluster, from the Sizing dashboard: **A** = Guest Active peak (or P95), **R** = reserve =
Installed − Available to VMs (what ESXi keeps for itself, never tierable), **V** = configured memory of
powered-on VMs.

- **VMware's rule:** active memory should be 50% or less of DRAM, so **recommended DRAM = 2 × A + R**.
  Floor = A + R; conservative = 4 × A + R.
- **NVMe needed = V − DRAM**, at most 4,096 GB per host.
- **Exclude** VMs that cannot be tiered: full memory reservation, PCI passthrough, latency
  sensitivity (not visible in Operations; check by hand), and monster VMs.

Export the Sizing tables as CSV and run [`tools/memtier_818_calc.py`](tools/memtier_818_calc.py) for every
figure, or [`tools/mtat_export_818.py`](tools/mtat_export_818.py) to build an import workbook for
VMware's Memory Tiering Assessment Tool (MTAT 3.2 and later). Both are attached to each release and
need only Python 3.

**Active, not demand.** Operations' memory *demand* (Workload %, Capacity Remaining, Time Remaining)
runs 2 to 4 times Guest Active on the lab. It answers "is this cluster out of memory now", which is
what the Memory Pressure dashboard shows. VMware sizes tiering on active memory, so the Sizing
dashboard does.

## Known limits

- **vMotion and maintenance mode inflate the active peak.** Measured on the lab: a vMotion makes the
  destination host count the arriving VM's active memory about twice for roughly 10 minutes. The
  Sizing help panel explains how to tell a migration spike from real demand.
- **IO wait as a % exists only per VM.** Hosts report ready, IO wait and swap wait only as summed
  milliseconds; the dashboards show hosts' and clusters' pressure as contention %, worst-VM and
  %-of-VMs columns instead.
- **Not yet tested against a vCenter 8.** Both labs run a VCF 9.1.1 vCenter. Every key used is checked
  native and collected by default on 8.18.7.
- **Pak version reads 0.0.0.N.** The VCF Content Factory stamps every build not made by its own CI that
  way; the GitHub release tag is the version of record.
- **The EULA shown at install is the VCF Content Factory's MIT licence,** because the pak includes its
  MIT-licensed framework jar. This repository is Apache 2.0.

## Building from source

The views and dashboards are defined once in `tools/build_views_818.py` (shared with the manual 8.18
set) and `tools/build_v3_content.py`, which writes the pak's YAML under `v3/`. The pak is built with
the [VCF Content Factory](https://github.com/sentania-labs/vcf-content-factory). See
[docs/RELEASING.md](docs/RELEASING.md).

## Memory Tier Advanced 2.x

2.x was a different design: 29 super metrics, a vCenter-credentialed adapter and an opt-in custom
group, released as **v2.0.0**. It is superseded by v3.

**Known defect in v2.0.0: the fleet total reads blank.** The four `MemTier Fleet *` super metrics are
bound to a resource kind that does not exist (`VMWARE/Environment`; group kinds belong to the
`Container` adapter). They import without error and attach to nothing, so the opted-in fleet
projection never produces a value. Per-cluster figures are unaffected. It was fixed in source but
never released; v3 replaces it.

To remove 2.x: uninstall it the same way as above, then delete any `MemTier` super metrics and the
`memtier-include` custom group if they remain. 2.x working notes are in [docs/history](docs/history/).

## Credits

Built with the [VCF Content Factory](https://github.com/sentania-labs/vcf-content-factory) by Scott Bowe
(MIT licence).

The content-import wire format used by 2.x was reverse engineered from
[sentania-labs/vcf-content-factory-bundles](https://github.com/sentania-labs/vcf-content-factory-bundles).
2.x's pak structure and super-metric packaging followed
[vmbro/VCF-Operations-vCommunity](https://github.com/vmbro/VCF-Operations-vCommunity).

`tools/describeSchema.xsd` is VMware's published describe schema, shipped unmodified, as the VCF
Operations Integration SDK and community packs do.

Not affiliated with or endorsed by Broadcom or VMware.

## License

Apache License 2.0: see [LICENSE](LICENSE). The pak also carries the VCF Content Factory's MIT
licence for its framework jar.
