# Overview: Memory Tier Advanced

For the version, see [docs/README.md](README.md) (regenerated on every build) or the GitHub release.

## What's in the Pack

Sizes vSphere clusters for NVMe memory tiering, and shows which clusters are out of memory now, from
native vCenter metrics VCF Operations already collects. No super metrics.

| Content | Purpose |
|---|---|
| **Memory Tier Advanced › Sizing** dashboard | 30-day sizing: clusters, running hosts, powered-on VMs |
| **Memory Tier Advanced › Memory Pressure** dashboard | Last 24 hours: demand, contention and reclaim, worst first |
| Views: Cluster Sizing Inputs, Hosts, Powered-on VMs | The Sizing tables |
| Views: Cluster / Host / VM Memory Pressure (24 hours) | The Memory Pressure tables |
| Report: Cluster Memory Pressure | PDF and CSV of the cluster pressure table |

Screenshots and the dashboards' help text: [docs/dashboards](../../docs/dashboards/).

### Resource Kinds (1)

- **Memory Tier Advanced World** (`World`): the adapter's only object. It has no metrics and no
  relationships.

## Cross-Adapter Notes

All content reads the built-in vCenter adapter's objects (`VMWARE`: ClusterComputeResource,
HostSystem, VirtualMachine). The adapter writes nothing onto them.

## Known Limitations

- Two VM metrics need enabling in the policy: Guest Active (8.18 only) and PCI PassThrough.
- IO wait as a % exists only per VM; hosts and clusters report it only in milliseconds.
- The Memory Pressure table is sorted worst first, not filtered: the factory's view filters cannot
  express "balloon OR swap OR non-green".
- Tested on Aria Operations 8.18.7 and VCF Operations 9.1.1, both against a VCF 9.1.1 vCenter; not
  yet against a vCenter 8.
