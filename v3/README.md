# Memory Tier Advanced

Sizes vSphere clusters for NVMe memory tiering from metrics VCF Operations already collects: cluster Guest Active (peak, P95, average), installed and available memory, powered-on VM allocation, memory pressure, CPU and IO wait headroom, and the VM exclusions Operations can see. Ships views and a dashboard; the adapter collects nothing.

## Installation

Upload the `.pak` file via **Administration → Solutions** in VCF Operations.

## Configuration

Create an adapter instance under **Integrations → Repository** and provide:

| Field | Description | Default |
|---|---|---|
| Label | | Memory Tier Advanced |

## Object Types

- Memory Tier Advanced World
