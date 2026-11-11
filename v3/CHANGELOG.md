# Changelog

## 3.0.0-rc.4 (build 0.0.0.6)

- New **Memory Pressure** dashboard: which clusters are out of memory now, last 24 hours, worst first
  and colour-coded; hosts and VMs for the selected cluster.
- New report **Memory Tier Advanced - Cluster Memory Pressure** (PDF and CSV).
- "Complete the install": the exact Start Collecting path (Accounts → expand the pack → ⋮ on the account row).
- Hosts table: ready, IO wait and swap wait in milliseconds replaced by percentages (CPU demand,
  CPU contention, worst-VM ready, VMs facing ready, worst-VM co-stop, memory contention).
- Clusters table: CPU contention, worst-VM CPU contention, worst-VM co-stop, memory contention and
  VMs facing memory contention, as %.
- VMs table: CPU ready average % and co-stop 20-second peak %.
- Help panel: new columns, "Hard to find in the Operations UI" (20-second peaks, rollups, Other Wait,
  the two Memory | Contention metrics, demand versus active). Taller, so its last line is no longer
  under the EDIT link.

## 3.0.0-rc.3 (build 0.0.0.3)

- "Complete the install" panel at the bottom of the dashboard.
- Memory limit back in KB with "-1 = no limit"; dashboard name frozen.

## 3.0.0-rc.2 (build 0.0.0.2)

- Own dashboard folder (Memory Tier Advanced › Sizing), version-neutral help, reservation in GB.

## 3.0.0-rc.1 (build 0.0.0.1)

- v3 Java pak: minimal adapter plus the 8.18-validated views and dashboard.
