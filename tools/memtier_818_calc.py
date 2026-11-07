#!/usr/bin/env python3
"""Sizing figures from the two 8.18 view exports (docs/MANUAL-8.18.md, section 4).

    python3 memtier_818_calc.py "MemTier 8.18 Cluster Sizing Inputs.csv" \
                                "MemTier 8.18 VM Allocation Powered On.csv" [--reserve 20] [--out sizing.csv]

Standard library only, so it runs on any laptop with Python 3. Values are GB. A "-" in the export
means Operations has no data for that cell; any figure that depends on it prints as blank, never
as zero.
"""
import argparse
import csv
import sys

PER_HOST_NVME_LIMIT_GB = 4096


def num(v):
    v = (v or "").strip().replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def allocated_by_cluster(path):
    alloc = {}
    for r in rows(path):
        cluster = (r.get("Cluster") or "").strip()
        gb = num(r.get("Configured GB"))
        # The Total row and any VM outside a cluster carry no cluster name; skip them.
        if not cluster or cluster == "-" or gb is None or (r.get("Name") or "").strip() == "Total":
            continue
        alloc[cluster] = alloc.get(cluster, 0.0) + gb
    return alloc


def size(c, v, reserve_per_host):
    # Running hosts first: Installed GB covers only hosts that report memory (2026-11-07 lab).
    h = num(c.get("Running hosts")) or num(c.get("Hosts"))
    i, a = num(c.get("Installed GB")), num(c.get("Active peak GB"))
    aavg, cons, cpu = num(c.get("Active avg GB")), num(c.get("Consumed avg GB")), num(c.get("CPU peak %"))

    def f(fn):
        try:
            return fn()
        except (TypeError, ZeroDivisionError):
            return None
    res = f(lambda: h * reserve_per_host)
    floor = f(lambda: a + res)
    # VMware's published rule: active memory at or under 50% of DRAM, i.e. DRAM >= 2 x active.
    vmw = f(lambda: 2 * a + res)
    cons_dram = f(lambda: 4 * a + res)
    nvme = f(lambda: v - floor)
    return {
        "Hosts": h, "Installed GB": i, "Allocated GB (powered on)": v, "Active peak GB": a,
        "Reserve GB": res,
        "DRAM floor GB (1x active, below VMware guidance)": floor,
        "DRAM recommended GB (VMware 50% rule, 2x active)": vmw,
        "Active within 50% of installed DRAM today": f(lambda: "yes" if a <= 0.5 * i else "NO"),
        "DRAM conservative GB": cons_dram,
        "NVMe needed / RAM saved at floor GB": nvme,
        "NVMe needed at VMware rule GB": f(lambda: v - vmw),
        "RAM saved conservative GB": f(lambda: v - cons_dram),
        "NVMe per host GB": f(lambda: nvme / h),
        "NVMe per host within 4096": f(lambda: "yes" if nvme / h <= PER_HOST_NVME_LIMIT_GB else "NO"),
        "Active of allocated at peak %": f(lambda: a / v * 100),
        "Implied DRAM share %": f(lambda: floor / v * 100),
        "Retrofit headroom GB": f(lambda: i - floor),
        "NVMe to add (retrofit) GB": f(lambda: v - i),
        "Overcommit %": f(lambda: v / i * 100),
        "Active of consumed %": f(lambda: aavg / cons * 100),
        "CPU headroom %": f(lambda: 100 - cpu),
        "Memory headroom %": f(lambda: 100 - a / i * 100),
    }


def fmt(x):
    if x is None:
        return ""
    return x if isinstance(x, str) else f"{x:,.1f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clusters_csv")
    ap.add_argument("vms_csv")
    ap.add_argument("--reserve", type=float, default=20.0,
                    help="GB per host held back for vSAN, NSX and the hypervisor (default 20)")
    ap.add_argument("--out", help="also write the results to this CSV")
    a = ap.parse_args()
    alloc = allocated_by_cluster(a.vms_csv)
    results = []
    for c in rows(a.clusters_csv):
        name = (c.get("Name") or c.get("Cluster") or "").strip()
        if not name:
            continue
        results.append((name, size(c, alloc.get(name), a.reserve)))
    if not results:
        sys.exit("no clusters in the cluster export")
    for name, r in results:
        print(f"\n== {name}")
        for k, v in r.items():
            print(f"   {k:38s} {fmt(v):>12s}")
    missing = [n for n, r in results if r["Allocated GB (powered on)"] is None]
    if missing:
        print(f"\nNOTE: no powered-on VMs matched to {missing}. Check the VM export's Cluster column.")
    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Cluster"] + list(results[0][1].keys()))
            for name, r in results:
                w.writerow([name] + [fmt(v) for v in r.values()])
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
