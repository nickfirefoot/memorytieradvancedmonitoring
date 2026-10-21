# Target: Aria Operations 8.18 with vCenter 8

**The pak's target is Operations 8.18 and vCenter 8.** Everything built so far was proven on
**VCF Operations 9.1.1 against a VCF 9 vCenter**, and that is the only place it has installed
(2.1.1, 2026-10-21). Treat every line below as unproven on the target until it has been run
there.

## First hour on the 8.18 lab

1. `python3 tools/verify_target.py --env ~/ops818.env`: every metric and property key the built
   content uses, checked against 8.18's own declarations. Any `MISS` that is not marked
   VCF 9-only is a column that reads blank on 8.18. Read-only.
2. Install the pak, then `python3 tools/verify_target.py --env ~/ops818.env --formulas`: creates
   and deletes each super metric formula, which proves 8.18 accepts the syntax. It **writes**,
   briefly, and only means something once the pak is installed, because formulas reference
   each other by id.
3. `~/.mp/bin/python3 ~/memory-tiering/probes/p42_adapter_local_run.py --image ghcr.io/nickfirefoot/memorytieradvancedmonitoring@sha256:667b35ba…`,
   with `~/vcenter.env` pointing at the vCenter 8: the shipped adapter image against the
   target vCenter, before any adapter instance exists.
4. `python3 ~/memory-tiering/probes/p43_pak_install_check.py 2.1.1`, pointed at 8.18: what the
   install actually registered.

## Risk register

| # | Area | Risk on 8.18 / vCenter 8 | What it would break | Status |
|---|---|---|---|---|
| 1 | Metric keys | `summary|total_number_mt_hosts` (hosts already tiered) is a VCF 9 memory-tiering metric | "Hosts already tiered" column blank | **Expected**, harmless |
| 2 | Metric keys | `cpu|max_cpu_ready`, `cpu|percentage_of_vms_facing_cpu_ready`, `cpu|20_sec_peak_readyPct` may be newer than 8.18 | CPU columns blank | check with step 1 |
| 3 | Key typing | `hardware|memorySize` is a **property**; the MTAT Hosts view declared it as a metric, which 9.1.1 tolerates | MTAT `Physical_RAM` blank | **Fixed**: now `mem|host_provisioned`, a metric, identical values on all lab hosts |
| 4 | Super metrics | `depth=-1` (parent lookup) in `MemTier MTAT Active Share` | MTAT export `Active_GB` blank | **Removed in 2.1.5**: `Active_GB` is now the built-in host active peak |
| 5 | Super metrics | one super metric referencing another (`attribute=Super Metric|sm_…`), `abs()`, unit ids `gb`/`percent` | rollups compute nothing | proven on 9.1.1 only (OPS818-REVIEW §4, §5) |
| 6 | Content format | dashboards follow a **9.1.1** export shape; views are cloned from a pak installed on 9.1 | dashboards or views rejected or blank | unproven on 8.18 |
| 7 | View options | `hideObjectNameColumn`, the power-state subject filter, explicit `preferredUnitId` | name column reappears; powered-off VMs in the MTAT file; units differ | `hideObjectNameColumn` doesn't matter (MTAT ignores extra columns); the filter matters |
| 8 | Pak install | the installer ordering rule (directories before files) found on 9.1.1 | install fails at APPLY_ADAPTER | fixed and build-enforced; 8.18 may have other rules |
| 9 | Pak install | the custom group fails to import on 9.1.1 ("invalid input parameter") | fleet totals have no group | **open defect** on every version |
| 10 | Container adapter | 8.18 cloud proxies run SDK container adapters (vCommunity pak, built for 8.18, does) | adapter never starts | precedent only |
| 11 | Image pull | the 8.18 proxy must reach `ghcr.io` and pull by digest | adapter instance fails | customer network dependent |
| 12 | Unsigned pak | "Activate Unsigned PAK Installation" admin setting must exist on 8.18 | cannot install at all | recorded from vCommunity (LESSONS 4.15) |
| 13 | vCenter 8 API | properties the adapter reads: `config.latencySensitivity`, `memoryReservationLockedToMax`, `hardware.device`, `memoryAllocation.reservation`, host `LPage.*` / `Mem.AllocGuestLargePage` | disqualifier blank or host skipped (a missing option now reads "not set") | all exist in the vSphere 8 API; pyvmomi 8.0.3 in the image; untested against vCenter 8 |
| 14 | Diagnosing installs | 9.x forwards logs to Operations for Logs, reached by token exchange; 8.18 does not work that way | can't read why an install failed | plan: SSH to the 8.18 node, or a support bundle |
| 15 | Memory tiering on vCenter 8 | 8.0 U3 tiering is a tech preview, so most hosts report nothing tiering-related | none for sizing: this pack sizes from active and consumed memory, which vCenter 8 has | by design |
| 17 | Adapter relationships | the SDK default mode removes existing relationships not in the result; attaching under vCenter VMs and hosts can strip their parents | vCenter tree damaged: VMs drop out of every cluster view | **2.1.5 sends no relationships**; pinned rollups blank until a mode is proven to add links only |
| 18 | Heat map | a receiver heat map built from a guessed config returned null data | Internal Server Error on the dashboard | **removed in 2.1.5**; rebuild from a UI-made one |
| 16 | MTAT | MTAT needs PowerCLI and a vCenter connection even to import | the export flow needs both on the user's machine | documented on the dashboard |

Anything that turns up here on the lab becomes a row, with what was run and what came back.
