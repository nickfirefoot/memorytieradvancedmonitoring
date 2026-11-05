# Memory tiering sizing on Aria Operations 8.18: manual install

Two views, no management pack, no adapter, no super metrics. They read only metrics the built-in
vCenter integration already collects, so they work **air-gapped** and show **30 days of history
the moment they are imported**.

File: [`content/818/MemTier_818_Views.xml`](../content/818/MemTier_818_Views.xml) (one file, both views, about 24 KB).

Tested on Aria Operations 8.18.7 (2026-11-05):
- Every metric is present and collected by default.
- The UI import succeeds, and the views export back unchanged.
- With a vCenter attached, both views fill. The VM total matched the API exactly (19 VMs,
  331 GB), and the calculator's figures were checked by hand.

The attached vCenter was a 9.1.1 lab. Per-host memory figures were identical on Ops 8.18 and
9.1.1.

## Before you go

- **Ops must hold 30 days of cluster data.** Default retention covers this, if Ops has been
  collecting the clusters for 30 days.
- **You need an account that can import views.** Admin is simplest.
- **Bring the XML on a USB stick or by email.** Nothing is downloaded on site.

## 1. Import (2 minutes)

1. **Operations → Views → Manage.**
2. Click the **⋯** button next to **ADD**, then **Import**.
3. **Browse…**, choose `MemTier_818_Views.xml`, then click **IMPORT**.
4. Wait for *"Views imported successfully"*, then click **DONE**.
5. Type `MemTier` in the filter. You should see two views:
   - **MemTier 8.18 Cluster Sizing Inputs**: subject Cluster Compute Resource.
   - **MemTier 8.18 VM Allocation Powered On**: subject Virtual Machine.

If you re-import, choose **Overwrite existing View**.

## 2. Run and export

Do this for **each** of the two views:

1. **Operations → Views → Manage**, filter `MemTier`, and click the view's name.
2. **Set Preview source to vSphere World.** This step matters. Open the **Preview source**
   dropdown at the top right, choose **Select preview source…**, pick **vSphere World**, then
   click **OK**. 8.18 remembers whatever object it last used. On the test instance, the VM view
   opened on a port group and listed 2 of 19 VMs. To size one cluster only, pick that cluster
   instead.
3. Check the row count at the bottom right: one row per cluster, or one row per powered-on VM.
4. Click **Export as CSV**, the third icon in the toolbar above the table, next to **Select Date
   Range**. The downloads are named:
   - `MemTier 8.18 Cluster Sizing Inputs.csv`
   - `MemTier 8.18 VM Allocation Powered On.csv`

The views cover the last 30 days. To change the window, use **Select Date Range** before
exporting.

## 2a. Turn the CSVs into the sizing (optional)

[`tools/memtier_818_calc.py`](../tools/memtier_818_calc.py) needs only Python 3 (standard library),
so it runs on a laptop with no network:

```
python3 memtier_818_calc.py "MemTier 8.18 Cluster Sizing Inputs.csv" \
                            "MemTier 8.18 VM Allocation Powered On.csv" --out sizing.csv
```

It prints every figure in section 4 for each cluster and writes them to `sizing.csv`. Use
`--reserve N` to change the 20 GB per-host reserve. A cell with no data in Operations prints
blank, never zero. If the calculator can't match a cluster to any VMs, it says so.

## 3. What the views contain

**MemTier 8.18 Cluster Sizing Inputs** has one row per cluster, over the last 30 days:

| Column | Metric (8.18 name) | Transformation |
|---|---|---|
| Hosts | Summary \| Total Number of Hosts | current |
| Installed GB | Memory \| Total Capacity | current |
| Active peak GB | Memory \| Guest Active | maximum |
| Active avg GB | Memory \| Guest Active | average |
| Consumed avg GB | Memory \| Consumed | average |
| Consumed peak GB | Memory \| Consumed | maximum |
| CPU avg % | CPU \| Capacity Usage | average |
| CPU peak % | CPU \| Capacity Usage | maximum |

**MemTier 8.18 VM Allocation Powered On** has one row per powered-on VM, with its cluster and
configured GB (Memory | Total Capacity), plus a **Total** row. Powered-off VMs and templates are
excluded because they still report configured memory, which inflates allocated by about 20%.

The active peak comes from the **cluster** metric. Per-VM Guest Active is **not collected by
default on 8.18** (Broadcom KB 445499), so a per-VM active column would be blank.

## 4. The sizing

Work per cluster, in GB. **H** = Hosts, **I** = Installed GB, **A** = Active peak GB,
**Aavg** = Active avg GB, **C** = Consumed avg GB, **V** = the sum of Configured GB for that
cluster's powered-on VMs.

| Figure | Formula | Read it as |
|---|---|---|
| Reserve | H × 20 | Allows 20 GB per host for vSAN, NSX and the hypervisor; never tierable. Adjust if the cluster has no vSAN or NSX. |
| **DRAM required, floor** | A + Reserve | Aggressive: DRAM sized to the peak working set, no margin. |
| **DRAM required, conservative** | 4 × A + Reserve | The planning figure. |
| NVMe needed = RAM saved at floor | V − (A + Reserve) | Negative means investigate before sizing. |
| RAM saved, conservative | V − (4 × A + Reserve) | Negative means no saving at this factor. |
| **NVMe per host** | NVMe needed ÷ H | **Must be under 4,096 GB**, the per-host limit. Above it, lower the ratio or add hosts. |
| Active of allocated at peak | A ÷ V × 100 | Over 50%: the working set sets DRAM. Under 20%: the 1:4 maximum ratio binds. |
| Implied DRAM share | (A + Reserve) ÷ V × 100 | Supported ratios: 50% is 1:1, 33% is 1:2, 20% is 1:4. |
| **Retrofit headroom** | I − (A + Reserve) | **Positive: the cluster can be tiered by adding NVMe alone.** |
| NVMe to add (retrofit) | V − I | NVMe needed to present today's allocation on today's hosts. |
| Overcommit | V ÷ I × 100 | Up to 110% is mild. |
| Active of consumed | Aavg ÷ C × 100 | Sanity check: typical is 8–12%. Outside 5–20%, distrust the data. |
| CPU headroom | 100 − CPU peak % | Compare with memory headroom, 100 − A ÷ I × 100. The smaller one binds consolidation first. |

## 5. Limits

- **Pinned VMs are not detected.** Latency sensitivity High, full memory reservation, and
  similar settings make a VM untierable, and only the management pack's adapter checks for them.
  Review business-critical and latency-sensitive VMs by hand, and subtract their configured
  memory from V.
- **Guest Active is an estimate** that ESXi samples. The conservative 4× figure exists for that
  reason.
- **Installed GB is DRAM only while no host is tiered**, which holds on ESXi 8, where tiering is a
  tech preview.
- **Tested on 8.18.7.** Other 8.x builds use the same metric keys, but they weren't tested.
