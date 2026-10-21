# Memory Tier Advanced 2.1.0: prototype runbook

Written 2026-10-17. Targets: a **working prototype by Monday**, **something ready for scale
testing by Friday**. The rule throughout: test the pak a customer installs, never stop at a
content import.

## Where it stands

| Layer | State | Evidence |
|---|---|---|
| Content (3 dashboards, 6 views, 32 super metrics) | works via content import | imported on the lab 2026-10-17; MTAT export files pass a port of MTAT's parser (probe p41) |
| Adapter code | works | `test` + `collect` against the lab vCenter; 5,000 VMs / 101 hosts in ~14 s on vcsim; every pin condition checked (below) |
| Adapter **image** 2.1.0 | built locally, **not pushed** | runs in the container and through its own HTTP server, exactly as a cloud proxy calls it |
| Pak 2.1.0 | builds, self-checks pass | **still pins the 2.0.0 image digest** until 2.1.0 is pushed |
| Pak **install** | never completed, anywhere | the release gate in RELEASING.md |

### Two defects in released 2.0.0 that only running the shipped image found

1. **The image has no Integration SDK library.** `adapter_requirements.txt` listed only
   pyvmomi, so every command dies on `import aria.ops`. A 2.0.0 adapter instance can never
   have worked.
2. **`adapter_definition()` raises TypeError** on SDK lib 1.1.0: `define_enum_parameter`'s
   label collided with `values`.

Both are fixed in the working tree. **Neither is committed**: see step 1.

### Pin detection, verified end to end (vcsim, inside the 2.1.0 container)

| Configured | pinned | pinReason |
|---|---|---|
| `sched.mem.lpage.enable1GPage=TRUE` | 1 | 1GB pages |
| latency sensitivity high | 1 | latency sensitivity high |
| `memoryReservationLockedToMax` | 1 | reservation locked to max |
| reservation = configured memory | 1 | fully reserved |
| vGPU device (Vmiop backing) | 1 | vGPU |
| PCI passthrough device | 1 | PCI passthrough |
| NUMA node affinity only | 0 | none |
| half reservation | 0 | none |
| untouched VM | 0 | none |

## Monday: your steps, in order

1. **Review and commit the working tree** on `agent/memtier-sizing`. Uncommitted:
   `adapter/app/adapter.py`, `adapter/adapter_requirements.txt`, `tools/build_pak.py` (the
   describe.xml drift check), and this file.
2. **Push the 2.1.0 image** (built locally as `memtieradvanced:2.1.0`):
   ```sh
   docker tag memtieradvanced:2.1.0 ghcr.io/nickfirefoot/memorytieradvancedmonitoring:2.1.0
   docker push ghcr.io/nickfirefoot/memorytieradvancedmonitoring:2.1.0
   docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/nickfirefoot/memorytieradvancedmonitoring:2.1.0
   ```
3. **Pin the new digest and rebuild the pak.** Set `IMAGE_DIGEST` in `tools/build_pak.py` to
   the `sha256:` the last command printed, then build with the SDK's Python so the
   describe/adapter comparison runs instead of being skipped:
   ```sh
   cd tools && python3 build_content.py && python3 build_views.py && ~/.mp/bin/python3 build_pak.py
   ```
4. **Clean the lab** so the install proves what the pak delivers, not what was imported
   before it (same IDs): delete the three Memory Tier Advanced dashboards, the six `[MTA]`
   views, the three `[MTA probe p41]` items, and the `MemTier *` super metrics.
5. **Install** `tools/build/MemoryTierAdvanced_2.1.0.pak`: Integrations → Repository → Add,
   ticking *Ignore signature checking*.
6. **Check what landed**: `python3 ~/memory-tiering/probes/p43_pak_install_check.py`.
   Lines 1–3 should pass now; 4–6 need the next step.
7. **Create an adapter instance**: vCenter FQDN, a read-only account, certificate
   verification off. The first collection should give 30 VMs (3 pinned, all
   `fully reserved`) and 4 hosts on the lab. Re-run p43: all six lines should pass.
8. **Enable the `MemTier` super metrics** in the active policy, then wait two collection
   cycles.
9. **Export for MTAT dashboard**: click `mgmt01-cl01`, check each host's `Active_GB` is a
   quarter of the cluster's "Active peak GB", export both tables, import them into MTAT.

That is the Monday prototype: installed from the pak, collecting, and feeding MTAT.

## Friday: what scale testing needs to answer

**Measured so far:** adapter collection, 5,000 VMs / 101 hosts in ~14 s against vcsim. vcsim
answers locally, so this measures payload and code, not network. About 215 vCenter round trips
at that size; the 2.0.0 code needed over 10,000.

Open, in the order they could block:

- [x] **Super metric parent lookup** (removed in 2.1.5; `Active_GB` is the built-in host peak). Was: `MemTier MTAT Active Share (GB)` reached the cluster with
      `depth=-1`. That is the documented direction but has never been seen computing. If it is
      blank after step 8, the export's `Active_GB` is blank, and MTAT reads blank as zero.
- [ ] **Export row limits.** The MTAT views page at 1,000 rows. Whether the widget's CSV export
      writes all rows or one page is untested, and a cluster with more than 1,000 powered-on
      VMs would hit it.
- [ ] **Collection time against a real large vCenter**, where each round trip costs real
      latency. Watch the collection duration on the adapter instance.
- [ ] **Super metric cost**: 24 cluster-level super metrics plus one per host, recalculated
      every cycle. Watch the analytics node's load at estate size.
- [ ] **VM view rendering** at thousands of VMs per cluster.
- [ ] **8.18**: nothing has run there.

Decisions still yours: whether to keep **Hardware Refresh** now that MTAT owns the
projections, and whether the **DRAM floor** gains the overhead term and the 1:4 cap.

## Reproducing the adapter tests

```sh
# against the lab vCenter (~/vcenter.env), in the shipped image
~/.mp/bin/python3 ~/memory-tiering/probes/p42_adapter_local_run.py --image memtieradvanced:2.1.0

# a 5,000-VM simulator on 127.0.0.2:443 (takes a few minutes to build its inventory)
docker run -d --name vcsim-scale -p 127.0.0.2:443:443 vmware/vcsim:latest \
  -l 0.0.0.0:443 -dc 1 -cluster 4 -host 25 -pool 1 -vm 1000
printf 'VC_HOST=127.0.0.2\nVC_USER=user\nVC_PASS=pass\n' > /tmp/vcsim.env
MEMTIER_VC_ENV=/tmp/vcsim.env ~/.mp/bin/python3 ~/memory-tiering/probes/p42_adapter_local_run.py
```
