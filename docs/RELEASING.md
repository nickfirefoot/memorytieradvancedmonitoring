# Releasing

How a Memory Tier Advanced v3 pak is built, checked and published. Nothing here runs in CI: this
repository has no workflows, so every check below is run by hand and recorded in the release notes.

## Versions

| | |
|---|---|
| Git tag and release | `v3.0.0-rc.N` while testing; `v3.0.0` for the final |
| Pak file | `vcfcf_sdk_memtier_advanced.0.0.0.N.pak`. The VCF Content Factory stamps every build not made by its own CI on its hand-built `0.0.0.N` line, with N = `build_number` in `v3/adapter.yaml`. The release tag is the version of record. |
| Assets | the pak, `memtier_818_calc.py`, `mtat_export_818.py`, `SHA256SUMS` |

- **Download URLs are permanent:** `…/releases/download/<tag>/<file>`. `…/releases/latest` always
  opens the newest full release.
- **A published asset is never replaced.** Builds are not byte-reproducible, so a rebuild gets a new
  sha256: bump `build_number` and cut a new rc instead.
- **Never rename a dashboard.** Operations matches pak dashboards by name, so a rename leaves the old
  one behind on upgrade (rc.1 → rc.2). Views are identified by a uuid5 of their title, so renaming a
  view also makes a new object.

## Build

1. Edit `tools/build_views_818.py` (views and help text shared with the manual 8.18 set) or
   `tools/build_v3_content.py` (v3 names, Memory Pressure dashboard, report, "Complete the install").
2. Regenerate and check:
   ```
   python3 tools/build_v3_content.py              # v3/views, v3/dashboards, v3/reports
   python3 tools/build_views_818.py               # tools/build/818; copy the three files to content/818/
   python3 tools/verify_818_views.py              # every key declared and collected by default on 8.18
   python3 tools/export_dashboard_docs.py         # docs/dashboards/*/text-panels.txt
   ```
3. Bump `build_number` in `v3/adapter.yaml`, then build with the factory:
   ```
   PYTHONPATH=<factory>/src python3 -m vcfcf_managementpacks validate-sdk v3
   PYTHONPATH=<factory>/src python3 -m vcfcf_managementpacks build-sdk v3 --output <dir> --sdk-jar <vrops-adapters-sdk.jar>
   ```
   The SDK jar is compile-only and never ships. The factory's own `--release` mode needs a CI
   reference pak, which this repository doesn't have, so builds are hand builds.
4. `python3 tools/test_help_contrast.py <pak>`: every text panel legible in light and dark themes.

## Verify before publishing

On **Aria Operations 8.18** and **VCF Operations 9.1.1**, through the UI a customer uses
(Integrations → Repository → ADD), never by content import:

- Install over the previous build: solution version, adapter instance GREEN (Start Collecting if
  stopped), VMs keep their host links.
- Every dashboard binds (no "not configured" after ~15 minutes) and shows data.
- After changing a dashboard's layout, look at it: text panels must not be clipped.
- Before each install or uninstall, check no other pak operation is running on the instance
  (`/casa/deployment/cluster/info`: `is_pak_installation_active`, `is_pak_uninstall_active`).

## Publish

1. Commit, push the branch.
2. Create the release from that commit with `prerelease: true`, the notes, and the four assets.
3. Download every asset **anonymously** from its permanent URL and check it against `SHA256SUMS`.
4. Promote to a full release (untick pre-release, set as latest) only when the owner decides.

## Docs

Refresh `docs/dashboards/` when a dashboard changes: regenerate the text with
`tools/export_dashboard_docs.py`, and retake screenshots from a lab with every object name replaced
(see [docs/dashboards/README.md](dashboards/README.md)).

## History

2.x was built differently (Python adapter image, super metrics, `tools/build_pak.py`); its notes are
in [docs/history](history/). `v2.1.1` to `v2.1.6` were private draft test builds; `v2.2.0-rc.1`
carries the same content as 2.1.6.
