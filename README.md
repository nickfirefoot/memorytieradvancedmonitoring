# Memory Tiering Sizing for VCF Operations

Dashboards and super metrics that size a vSphere estate for **VCF 9 NVMe memory tiering**,
using only metrics the built-in vCenter adapter already collects.

Built for **Aria Operations 8.18** and **VCF Operations 9.x**. No adapter, no container image,
no registry, no collector — this is content, and it reads metrics that are already there.

---

## What question it answers

You are planning a VCF 9 upgrade and want to know, per cluster:

- how much memory is **allocated** to VMs versus **consumed** by hosts versus actually **active**
- how much of that is **cold** — backed in DRAM but outside the working set, the candidate for an NVMe tier
- what **DRAM:NVMe ratio** the workload could carry (1:1, 1:2, 1:4), and which clusters cannot tier at all
- which **VMs are least suited** to tiering — high active share, or fully reserved and therefore pinned to DRAM

Two use cases, and they need different maths:

| | Hardware replacement | Retrofit |
|---|---|---|
| Installed DRAM is | an **output** — size it to the workload | a **constraint** — you already own it |
| The gate | the supported ratio covers the workload | peak active must fit the DRAM you have |
| You want | GB of DRAM + GB of NVMe to buy | GB of NVMe to add, and how much more workload then fits |

## What it is not

**A sizing tool, not a monitoring tool.** On a vSphere 8 estate there is no tiering to report —
that is the point; the assessment happens *before* the upgrade. Nothing here reads tiering
telemetry, because none exists on the source estate.

**Do not point it at a cluster that already has tiering enabled.** There,
`mem|host_provisioned` reports *presented* memory — installed DRAM plus the NVMe tier — not
installed DRAM. Measured on a tiered host: 639.4 GiB presented against a 127.9 GiB DRAM tier, a
5.00× overstatement, with no visible symptom. On an untiered vSphere 8 host the two are the
same number.

**Tiles show the latest sample, not a peak.** Sizing must be done on business-cycle peaks, which
need a View transformation rather than a dashboard tile. Treat the values as a shape check, not
as the number that goes on a quote.

---

## Install

### Recommended: the installer

```sh
python3 tools/install_content.py --host <ops-host> --user <user>
```

Imports the dashboard and the super metrics through
`POST /suite-api/api/content/operations/import`, then enables the super metrics in the active
policy. That last step matters: **super metrics arrive disabled however they are imported**, and
a dashboard whose tiles all read no data looks exactly like a failed install.

| Flag | Effect |
|---|---|
| `--dry-run` | build the content zips locally, send nothing |
| `--no-enable` | import, but do not touch the active policy — enable the super metrics yourself |

The enable step exports your active policy, adds `<SuperMetric enabled="true">` entries and
re-imports it with `forceImport=true`. That is a real change to the policy governing the whole
instance. `--no-enable` avoids it at the cost of one manual step in
Administration → Policies → *your policy* → Super Metrics.

### Manual, through the UI

1. **Administration → Super Metrics → Import** → `content/supermetric.json`
2. Enable all six in the policy that applies to your vCenter
3. **Visualize → Dashboards → Manage → Import** → `content/Dashboard.zip`

The zip, not the loose `dashboard.json` — a dashboard export is a zip containing
`dashboard/dashboard.json` at that exact path, and the import dialog will not take a bare file.

Give it two or three collection cycles before judging a tile. A dashboard whose widgets read
*"not configured — select a view"* with hourglasses is the import still running; it corrects
itself.

---

## What ships

```
content/Dashboard.zip      the dashboard, ready for the UI import dialog
content/dashboard.json     the same JSON unzipped, for diffing
content/supermetric.json   6 super metrics
tools/install_content.py   the installer
tools/build_content.py     regenerates the content with your own thresholds
tools/build_pak.py         experimental: assembles a .pak (see Status)
```

### The dashboard

Eight widgets, all bound by **resource kind** — no host, VM, cluster or datacentre name appears
anywhere in the JSON, so it works on any estate. Cluster scoreboard on native rollups; a host
heat map coloured by usage and sized by presented memory; Paretos for hosts by consumed and
active, and for VMs by configured, active and reserved memory.

Low utilisation reads **dark grey**, not green — the capacity convention, because unused memory
you paid for is the finding, not a healthy state.

### The super metrics

| Name | What it is |
|---|---|
| `Sizing\|Allocated (GB)` | sum of configured memory across the cluster's VMs |
| `Sizing\|Tierable of Used (GB)` | cold memory: `(consumed − active) / 2` |
| `Sizing\|Active of Allocated (%)` | the figure that decides the ratio — no headroom baked in |
| `Sizing\|Active of Consumed (%)` | the sanity check: 8–12% typical, ~15% with databases |
| `Sizing\|TEST Fleet Active depth3/depth10 (GB)` | an A/B pair — see Known unknowns |

### Rebuilding with your own numbers

```sh
python3 tools/build_content.py --verify
```

`--verify` checks every metric key against a live instance before writing anything. Thresholds,
the headroom factor and the plausibility band are arguments, not literals in the JSON.

---

## Known unknowns

Stated rather than buried, because each one changes how you should read the output.

**Super metric rollup depth.** The two `TEST` metrics are identical except `depth=3` versus
`depth=10` from `vSphere World`. Measured tree depth from that object to `HostSystem` on a
9.1.1 instance is **3**. Import both, enable them, and look at the vSphere World object: if
depth3 has data and depth10 does not, `depth=N` means *exactly* N; if both do, it means *up to*
N and anything reachable by two paths risks double counting. Delete them once you know.

**Powered-off VMs inflate `Allocated`.** They keep reporting configured memory — measured at
19.1% of allocated on one lab — so treat the figure as an upper bound. Templates do the same and
do not even report a power state.

**Peak versus latest.** See above; the tiles are instantaneous.

---

## Status

| Piece | State |
|---|---|
| Dashboard and super metrics | built, metric keys verified against a live 9.1.1 instance |
| `install_content.py` | wire format verified offline; **not yet run end to end against an instance** |
| `build_pak.py` | **experimental and not working** — see below |

**The `.pak` does not install yet.** Five builds have been tried. A pak with no `<Kind>.conf`
installs with a clean log and registers nothing at all; a pak with a `.conf` but no
`REGISTRY`/`REPOSITORY`/`DIGEST` fails at *Applied Adapter*. Every known-working pak carries all
three image fields, which means a pak wants a real container image even when its content needs
no collector. Until that is resolved, the installer is the supported route. `build_pak.py` is
in the tree because the investigation is reproducible, not because it works.

---

## Credits

The content-import wire format — marker discovery, the `dashboards/<ownerId>` inner zip,
`dashboardsharings`, `usermappings`, and the two-step super-metric enable — was reverse
engineered from
[sentania-labs/vcf-content-factory-bundles](https://github.com/sentania-labs/vcf-content-factory-bundles).

Pak structure and the super-metric packaging convention follow
[vmbro/VCF-Operations-vCommunity](https://github.com/vmbro/VCF-Operations-vCommunity).

`tools/describeSchema.xsd` is VMware's published describe schema, shipped unmodified, as the
VCF Operations Integration SDK and community packs do.

Not affiliated with or endorsed by Broadcom or VMware.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
