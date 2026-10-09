# Release retirement review

Prepared locally on 2026-10-09. No GitHub release, asset, tag, branch or history
was changed. This is an inventory for review, not authorization to delete.

## Update before this review

On 2026-10-09, before this inventory was taken, the GitHub releases and tags v0.1.0, v0.1.1, v1.0.0, v1.0.1 and v1.0.2 (MIT) and v1.1.0 (its LICENSE file was PolyForm Small Business, not the GPL that LICENSING.md describes) were deleted. That is why the inventory below finds no MIT-era releases: they were already gone. The code at those commits stays in git history and the MIT terms remain valid for anyone who already has a copy. The MCP Registry still lists 1.0.1, 1.0.2 and 1.1.0 with download links that no longer work.

## Finding

**The reviewed public inventory contains no MIT-era release candidates.**
GitHub returned five published releases and five public tags. Both the root
`LICENSE` and Python package `LICENSE` at each tag contain GNU GPL version 3.
The `LICENSE` embedded in each release's Python wheel and MCPB bundle also
contains GPL version 3. Do not classify these releases as MIT merely because
their version numbers are old or the project was previously MIT licensed.

This check used unauthenticated public GET requests. Private drafts are outside
its scope. Large Revit ZIP archives were inventoried by name, ID and size but
their embedded license files were not inspected. The conclusion covers the
observed tagged source, wheels and MCPB bundles; it does not certify every file
inside every archive. `LICENSING.md` mentions historical MIT copies, which does
not make the accompanying GPL `LICENSE` an MIT license.

## Reviewed releases

Published times are UTC. Each license link is pinned to the resolved commit,
so a later moved tag does not silently change this evidence.

| Release | Release ID | Published | Tagged commit | Root / package license | Decision |
| --- | --- | --- | --- | --- | --- |
| [v1.2.1](https://github.com/Sam-AEC/aec-model-bridge/releases/tag/v1.2.1) | 394671115 | 2026-09-23 13:07:56 | `8f2a24e44caf1424ac06015edfbce85de423e25f` | [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/8f2a24e44caf1424ac06015edfbce85de423e25f/LICENSE) / [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/8f2a24e44caf1424ac06015edfbce85de423e25f/packages/mcp-server-revit/LICENSE) | Retain; no MIT evidence |
| [v1.3.0](https://github.com/Sam-AEC/aec-model-bridge/releases/tag/v1.3.0) | 407690596 | 2026-10-09 08:09:33 | `ee85ad031fc9dde2781927162dfb26ac34cb81ff` | [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/ee85ad031fc9dde2781927162dfb26ac34cb81ff/LICENSE) / [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/ee85ad031fc9dde2781927162dfb26ac34cb81ff/packages/mcp-server-revit/LICENSE) | Retain; no MIT evidence |
| [v1.3.1](https://github.com/Sam-AEC/aec-model-bridge/releases/tag/v1.3.1) | 407738830 | 2026-10-09 09:03:27 | `c6e22a87e3c737c179c7ff6ea58ff7648a2fd0db` | [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/c6e22a87e3c737c179c7ff6ea58ff7648a2fd0db/LICENSE) / [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/c6e22a87e3c737c179c7ff6ea58ff7648a2fd0db/packages/mcp-server-revit/LICENSE) | Retain; no MIT evidence |
| [v1.3.2](https://github.com/Sam-AEC/aec-model-bridge/releases/tag/v1.3.2) | 407752747 | 2026-10-09 09:21:54 | `9e76b5e2af9fcb97a0c2758be346d1042aca3717` | [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/9e76b5e2af9fcb97a0c2758be346d1042aca3717/LICENSE) / [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/9e76b5e2af9fcb97a0c2758be346d1042aca3717/packages/mcp-server-revit/LICENSE) | Retain; no MIT evidence |
| [v1.3.3](https://github.com/Sam-AEC/aec-model-bridge/releases/tag/v1.3.3) | 407775082 | 2026-10-09 09:48:56 | `6ffd21493339e375267216858dd2732087404e39` | [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/6ffd21493339e375267216858dd2732087404e39/LICENSE) / [GPL](https://github.com/Sam-AEC/aec-model-bridge/blob/6ffd21493339e375267216858dd2732087404e39/packages/mcp-server-revit/LICENSE) | Retain; no MIT evidence |

## Uploaded asset inventory

29 uploaded assets were returned. Names are exact; sizes are bytes. GitHub's
generated source ZIP/TAR downloads are separate from these uploaded assets.

| Tag | Asset ID | Asset name | Bytes |
| --- | --- | --- | ---: |
| v1.2.1 | 583795151 | `aec-model-bridge-1.2.1.mcpb` | 280238 |
| v1.2.1 | 583795149 | `aec-model-bridge-revit-2027-1.2.1.zip` | 109540622 |
| v1.2.1 | 583795148 | `aec_model_bridge-1.2.1-py3-none-any.whl` | 144951 |
| v1.2.1 | 583795152 | `SHA256SUMS.txt` | 307 |
| v1.3.0 | 624329128 | `aec-model-bridge-1.3.0.mcpb` | 280537 |
| v1.3.0 | 624329133 | `aec-model-bridge-revit-2027-1.3.0.zip` | 137850632 |
| v1.3.0 | 624329129 | `aec_model_bridge-1.3.0-py3-none-any.whl` | 145269 |
| v1.3.0 | 624329130 | `SHA256SUMS.txt` | 307 |
| v1.3.1 | 624443179 | `aec-model-bridge-1.3.1.mcpb` | 280536 |
| v1.3.1 | 624443183 | `aec-model-bridge-revit-2024-1.3.1.zip` | 137999452 |
| v1.3.1 | 624443178 | `aec-model-bridge-revit-2025-1.3.1.zip` | 137852125 |
| v1.3.1 | 624443181 | `aec-model-bridge-revit-2026-1.3.1.zip` | 137852129 |
| v1.3.1 | 624443199 | `aec-model-bridge-revit-2027-1.3.1.zip` | 137852450 |
| v1.3.1 | 624443177 | `aec_model_bridge-1.3.1-py3-none-any.whl` | 145266 |
| v1.3.1 | 624443198 | `SHA256SUMS.txt` | 622 |
| v1.3.2 | 624485192 | `aec-model-bridge-1.3.2.mcpb` | 305231 |
| v1.3.2 | 624485190 | `aec-model-bridge-revit-2024-1.3.2.zip` | 137424520 |
| v1.3.2 | 624485193 | `aec-model-bridge-revit-2025-1.3.2.zip` | 137277174 |
| v1.3.2 | 624485195 | `aec-model-bridge-revit-2026-1.3.2.zip` | 137277171 |
| v1.3.2 | 624485222 | `aec-model-bridge-revit-2027-1.3.2.zip` | 137277502 |
| v1.3.2 | 624485191 | `aec_model_bridge-1.3.2-py3-none-any.whl` | 167971 |
| v1.3.2 | 624485231 | `SHA256SUMS.txt` | 622 |
| v1.3.3 | 624547009 | `aec-model-bridge-1.3.3.mcpb` | 305207 |
| v1.3.3 | 624547015 | `aec-model-bridge-revit-2024-1.3.3.zip` | 137426425 |
| v1.3.3 | 624547020 | `aec-model-bridge-revit-2025-1.3.3.zip` | 137279097 |
| v1.3.3 | 624547014 | `aec-model-bridge-revit-2026-1.3.3.zip` | 137279094 |
| v1.3.3 | 624547043 | `aec-model-bridge-revit-2027-1.3.3.zip` | 137279411 |
| v1.3.3 | 624547011 | `aec_model_bridge-1.3.3-py3-none-any.whl` | 167941 |
| v1.3.3 | 624547039 | `SHA256SUMS.txt` | 622 |

Wheel inspection read `.dist-info/licenses/LICENSE` and metadata; MCPB
inspection read the root `LICENSE` and manifest. This was not a binary runtime
test or a full dependency license audit.

## Preparation and possible later execution

The reviewed MIT deletion set is empty. After external review, refresh the
inventory with an authenticated account if draft visibility matters. The
following GitHub CLI commands are read-only; `gh` was not on PATH during this
review, so the evidence above came directly from the public API.

```powershell
gh api --paginate 'repos/Sam-AEC/aec-model-bridge/releases?per_page=100'
gh api --paginate 'repos/Sam-AEC/aec-model-bridge/tags?per_page=100'
# Inspect a specific reviewed ID, including current uploaded assets:
gh api 'repos/Sam-AEC/aec-model-bridge/releases/394671115'
```

If a future review identifies a specific MIT release or explicitly selects a
GPL release for a different retirement reason, record its tag, resolved commit,
release ID, asset IDs, license evidence and replacement download first. Save
release notes and assets before deletion if a recovery copy is wanted. Obtain
explicit authorization for those exact remote changes; the current instruction
is preparation only.

The future deletion endpoint is documented below as a **comment**, with an
unfilled ID. It has not been executed and no release in the table is selected.

```powershell
# Only after approval of the exact release ID and asset scope:
# gh api --method DELETE 'repos/Sam-AEC/aec-model-bridge/releases/REVIEWED_RELEASE_ID'
```

Retiring a GitHub release removes its release page and uploaded downloads; it
does not delete the Git tag or rewrite repository history. Existing clones,
forks and previously downloaded copies cannot be recalled by deleting a
release. Any separately approved tag deletion would need its own review;
history rewriting is outside this plan.

## Evidence sources

- [Public releases API, page 1](https://api.github.com/repos/Sam-AEC/aec-model-bridge/releases?per_page=100&page=1): five releases and 29 assets.
- [Public releases API, page 2](https://api.github.com/repos/Sam-AEC/aec-model-bridge/releases?per_page=100&page=2): empty when checked.
- [Public tags API](https://api.github.com/repos/Sam-AEC/aec-model-bridge/tags?per_page=100): the same five tags; annotated tag objects were resolved to the commits above.
- [GitHub release REST documentation](https://docs.github.com/en/rest/releases/releases#delete-a-release): listing scope and deletion endpoint.
- [GitHub CLI release deletion manual](https://cli.github.com/manual/gh_release_delete): deleting a release leaves its associated tag unless tag cleanup is separately requested.
