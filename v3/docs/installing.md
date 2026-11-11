# Installing & Configuring: Memory Tier Advanced

## Prerequisites

- Aria Operations 8.18 or VCF Operations 9.x, with the built-in vCenter integration collecting the
  clusters to size. 30 days of history gives full sizing figures.
- Permission to install a pak, and to edit the active policy.

## Permissions Required

None for the adapter: it has no credentials and makes no connection.

## Network Requirements

None. The adapter makes no outbound connection, so the pak works air-gapped.

## Configuration Fields

| Field | Key | Required | Default | Notes |
|-------|-----|----------|---------|-------|
| Name | | Yes | | Any name |
| Label | `label` | No | Memory Tier Advanced | Leave as it is |

## Step-by-Step Installation

1. **Administration → Integrations → Repository → ADD.** Choose the `.pak`, tick **Ignore the PAK
   file signature checking**, **UPLOAD**, **NEXT**. On 9.1.1, wait about 30 seconds after 100% for NEXT
   to enable.
2. Answer **YES** to the unsigned-pak warning, accept the EULA, **NEXT**. The install takes a few
   minutes; only one pak can install at a time.
3. **Add the adapter instance:** Integrations → Repository → click **Memory Tier Advanced** →
   **ADD ACCOUNT**. Type a Name, leave Label and Collector as they are, click **ADD**.
4. **Turn on two VM metrics in the active policy:**
   1. Open **Policy Definition**: on 8.18, Operations → Configurations; on 9.x, Administration →
      Configurations.
   2. Click the policy whose Status is **Active** (normally Default Policy) → **EDIT POLICY** →
      **Metrics and Properties**.
   3. Select Object Type: **Virtual Machine** (vCenter → Virtual Machine).
   4. Filter `Guest Active`, click Expand All, set **Memory → Guest Active (KB)** to **Activated**
      (8.18 only; 9.x collects it already).
   5. Filter `PCI`, set **Configuration → Security → PCI PassThrough** to **Activated** (both).
   6. **SAVE.**
5. Open **Dashboards → Memory Tier Advanced → Sizing**. If widgets read "The widget is not
   configured" with an hourglass, wait: binding takes up to 15 minutes after an install.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Pak installation is in progress" | Another pak is installing on the instance; wait and retry. |
| Adapter instance stopped after an upgrade (seen on 9.1.1) | Administration → Integrations → Accounts → expand Memory Tier Advanced → **⋮** on the account row → **Start Collecting**. |
| Widgets "not configured" | Wait up to 15 minutes after install or upgrade. |
| Guest Active per VM blank | Step 4; history starts when the policy is saved. |
| Old dashboard still present after upgrading from rc.1 | Delete "Memory Tier Advanced - Sizing" by hand (rc.2 renamed it). |
