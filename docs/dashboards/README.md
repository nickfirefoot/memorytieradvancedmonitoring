# Dashboards

One folder per dashboard the Memory Tier Advanced pak installs. Each folder holds screenshots and `text-panels.txt`, the dashboard's text panels as plain text.

| Dashboard | Folder |
|---|---|
| Memory Tier Advanced › Sizing | [sizing/](sizing/) |

## Updating

- **Text:** run `python3 tools/build_v3_content.py`, then `python3 tools/export_dashboard_docs.py`. The text files are generated from `v3/dashboards/*.yaml`; don't edit them by hand.
- **Screenshots:** take them from a lab with the pak installed. Replace every object name before capturing: clusters, hosts, VMs, datacenters, datastores, vCenter accounts, and IP addresses inside names. Hide the licence banner, and check the PNGs carry no metadata.
