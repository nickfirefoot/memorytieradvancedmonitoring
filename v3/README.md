# Memory Tier Advanced (v3 pak project)

The VCF Content Factory project for the Memory Tier Advanced pak. Start at the
[repository README](../README.md) for what the pack does, how to install it and how to read it.

| Path | What it is |
|---|---|
| `adapter.yaml` | Pak manifest: name, `build_number`, and the bundled content list |
| `describe.xml`, `src/` | The minimal Java adapter: no credentials, no outbound connection, registers one World object |
| `views/`, `dashboards/`, `reports/` | **Generated** by `tools/build_v3_content.py`; edit the generator, not these |
| `docs/` | Pak docs; `docs/README.md` and `inventory-tree.*` are regenerated on every build |
| `REFERENCE*.md`, `CHANGELOG.generated.md` | Regenerated on every build |

Build and release steps: [docs/RELEASING.md](../docs/RELEASING.md).

## Installation

Administration → Integrations → Repository → ADD, tick **Ignore the PAK file signature checking**, and
accept the unsigned-pak warning and the EULA. Then follow the **Complete the install** panel at the
bottom of either dashboard. Details: [docs/installing.md](docs/installing.md).

## Configuration

One adapter instance (Integrations → Repository → Memory Tier Advanced → ADD ACCOUNT):

| Field | Description | Default |
|---|---|---|
| Name | Any name | |
| Label | Leave as it is | Memory Tier Advanced |

## Object Types

- Memory Tier Advanced World
