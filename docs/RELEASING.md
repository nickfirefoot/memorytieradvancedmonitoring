# Releasing

Same tag scheme as the vSAN Host Metrics pack (`~/vsan-net-mp/README.md`, "To release").

| | Dev build | Release |
|---|---|---|
| Tag | `vX.Y.Z-rc.N`, from any branch | `vX.Y.Z`, from the release branch |
| GitHub | **published pre-release**, named after the tag | full release |
| Pak file | `MemoryTierAdvanced_X.Y.Z-rc.N.pak`; `manifest.txt` inside carries the plain target `X.Y.Z` | `MemoryTierAdvanced_X.Y.Z.pak` |
| Image tag | `X.Y.Z-rc.N` | `X.Y.Z` |
| Assets | the pak + `SHA256SUMS` | the same |

- **Download URLs are permanent:** `…/releases/download/<tag>/<file>`. Never hand out a draft
  release's `untagged-…` link; it dies when the draft is published or re-cut.
- **The rc is in the file name** so every download says which build it is. Operations itself
  shows only `X.Y.Z`; confirm which rc is installed with `p43_pak_install_check.py`.
- **Builds are not byte-reproducible** (zip timestamps), so a rebuild of the same commit gets a
  different sha256. Never upload a rebuild under a name that is already published; the release
  asset is the artefact of record.
- **A version is never re-cut.** If `vX.Y.Z` is wrong, release `vX.Y.(Z+1)`. Each rc of the same
  target carries the same pak version, so reinstalling one over another needs *Install even if
  already installed*.
- **Promote to a release only after an install on an instance that isn't the development lab**
  (the gate in the development repo's `RELEASING.md`), and for this pack, on the **8.18**
  target (`docs/TARGET-8.18.md`).
- **No signing.** The vSAN pack signs and attests through CI; this repo has no CI, so nothing
  here is signed. The image digest in `MemTierAdvanced.conf` matches the release notes, which
  proves the pak and the image match each other and nothing about who built them.

## Cutting a dev build

1. `cd tools && python3 build_content.py && python3 build_views.py && MEMTIER_RC=N ~/.mp/bin/python3 build_pak.py`
   (the SDK's Python, so the describe/adapter comparison runs).
2. `cd build && sha256sum MemoryTierAdvanced_X.Y.Z-rc.N.pak > SHA256SUMS`
3. Commit, then `git tag -a vX.Y.Z-rc.N -m …` and push the branch and the tag.
4. If the adapter changed: build the image, test it (`p42_adapter_local_run.py --image`), push it,
   pin its digest in `build_pak.py`, and rebuild the pak.
5. Tag the image `X.Y.Z-rc.N`.
6. Create the release with `prerelease: true`, upload the pak and `SHA256SUMS`, then download
   the pak **anonymously** from its permanent URL and compare its sha256.

## History

`v2.1.1` to `v2.1.6` were private draft test builds cut before this scheme; only 2.1.1 onwards
installed. `v2.2.0-rc.1` carries the same content as 2.1.6.
