# WO-001 upstream audit

Checked 2026-10-31 to 2026-11-01 against villa `d57c28ebee8776b618f9851c2289cc407ea99dd4` ("the pin") [`villa`] and image digest `sha256:b2509de2c107852799a5077fd2038a917549a1d1e3665d5a1919c955858d698a` ("the image"). Reference clone: `~/src/villa`, outside this repo, read-only.

## What changes the plan

1. **Phase correlation of surface renders already exists in villa.** `estimate_canvas_offset.py` uses it for a different question (section 6). The DR-002 claim about inter-layer tilt survives, but the claim must be worded around the use, not the primitive.
2. **The renderer and the Python package are different code.** The newest published image is five and a half months older than the pin (section 2).
3. **`vc_objrefine` has no offset report at the pin**, so baseline B2 in WO-003 is "not available at `d57c28e`". PR #2224 is open, and #2358 did not bring the report in (section 1).
4. **`vc_tifxyz_winding` no longer exists at the pin.** Removed by #2358, it survives only in the May image (section 4).
5. **Rising layer number runs along the negative `vesuvius` normal.** WO-003 perturbations must use this sign (section 4).
6. **Public meshes carry no `approved` or `defective` tags.** See `data-survey.md`.

## 1. Pull request status

Status from `gh pr view`, presence from `git log --grep` and code reading in the clone.

| PR | Subject | State | At the pin? | Consequence |
|---|---|---|---|---|
| #2224 | `vc_objrefine` offset report | Open | No | B2 unavailable |
| #2358 | Tifxyz to object store | Merged 2026-10-29, `e1aa625` | Yes | Holds no offset report. `refine_surface` exists at `ObjAlphaCompRefinement.cpp:291`, but "report" has no match in that file. **Primer section 4 said #2358 ports the report; at the pin it does not** |
| #2365 | Light `tifxyz` extra | Open | No | The API is already present (section 3), but `vesuvius.tifxyz` needs extra dependencies. We added them |
| #2368 | `snap_labels` | Open | No | Not usable from the pin |
| #2373 | Python tifxyz renderer | Open | No | We keep `vc_render_tifxyz` |

## 2. Image against pin

`docs/decisions.md` DR-004 holds the digests.

| | Python `vesuvius` | `vc_render_tifxyz` and friends |
|---|---|---|
| Commit | `d57c28e` (2026-10-31) | `1e3f4c0` (2026-05-13), from the image label |

`:edge` and `:main` on GHCR both resolve to that May build, as checked with `skopeo inspect` on 2026-11-01, so pulling again changes nothing. Newer VC3D would have to be built from source, which is a new decision and not part of this WO. Issue #2049 reports that VC3D releases are deleted on promotion [T3, not checked further], which is a further reason to keep recording the digest.

Flag differences in `vc_render_tifxyz` between the image and the pin:

| Only in the image | Only at the pin |
|---|---|
| `--flatten`, `--flatten-iterations`, `--flatten-downsample`, `--affine-transform`, `--invert-affine` | `--flip-normals`, `--surface-interpolation`, `--composite-collapse`, `--zarr-compressor`, `--zarr-compression-level`, `--zarr-separator` |

`--slice-step` semantics also differ at pyramid levels above 0. In the image, `buildOffsetList` multiplies offsets by `2^-g`; at the pin it does not. **We render at `--group-idx 0`, where the two agree.** Any WO that renders at a coarser level must re-check this.

## 3. `vesuvius.tifxyz` at the pin

Read and write are both present, so WO-003 can use the writer. No hand-rolled `tifffile` writer is needed.

| Need | API |
|---|---|
| Read | `read_tifxyz(path)` returns `Tifxyz`. Also `TifxyzReader`, `list_tifxyz`, `load_folder` |
| Write | `write_tifxyz(path, surface, compression="lzw", tile_size=1024, write_mask=True, overwrite=False)`; also `TifxyzWriter` |
| Coordinates | `surface[rows, cols]` returns `x, y, z, valid`; `get_zyxs()` |
| Resolution | `resolution` is `"stored"` by default. `use_full_resolution()` interpolates (`interp_method`, default `catmull_rom`); `full_resolution_shape`; `retarget(factor)` |
| Normals | `compute_normals()` for the stored grid; `get_normals(row_start, row_end, col_start, col_end)`; `analyze_normal_direction()`, `orient_normals()`, `flip_normals()` |
| Grid scale | `get_scale_tuple()` returns `(scale_y, scale_x)` |

Import needs `cv2` and `numba`, and writing the default LZW needs `imagecodecs`. None comes with `vesuvius[volume-only]`, so on a clean install `import vesuvius.tifxyz` fails with `ModuleNotFoundError: cv2`. We added all three. The pin did not move.

On-disk format, from `reader.py`, `writer.py`, `types.py`, and real files:

| Item | Value |
|---|---|
| Files | `x.tif`, `y.tif`, `z.tif`, `meta.json`; optional `mask.tif` and `*_label.*` |
| Pixel type | `float32`, single page, coordinates in level-0 voxels of the mesh's volume |
| Compression, as found | Published `*-on-*.tifxyz`: uncompressed strips. `mesh/intermediate/tifxyz_original`: LZW, tiled 1024, horizontal predictor. Readers must handle both |
| Writer default | LZW, 1024 tiles, `minisblack` |
| Invalid points | `-1` in the published data we read, not NaN. **The validity rule is `mask.tif` if present, otherwise `z > 0` and finite.** A perturbation that pushes `z` to 0 or below therefore invalidates the point |
| `meta.json` required | `uuid`, `scale` as `[x, y]`, `bbox` as `[[xmin,ymin,zmin],[xmax,ymax,zmax]]`, `format: "tifxyz"`, `type: "seg"` |
| `meta.json` optional, seen on S3 | `area_vx2`, `area_cm2`, `tags`, `seed`, `seed_surface_id`, `max_gen`, `date_last_modified`, `source`, and others. Other fields land in `Tifxyz.extra` and are written back |
| Scale | `0.05` on every mesh we read: one stored grid step is 20 voxels. **The reader's fallback when `scale` is absent is `[20.0, 20.0]`**, the reciprocal convention, so never omit `scale` |

## 4. VC3D tools in the image

Verbatim `--help` output: `vc3d-help.txt`.

**`vc_render_tifxyz`.** Required: `--volume`, `--scale`, `--group-idx`, and one of `--tif-output` or `--zarr-output`. Other flags used here:

- Stacking: `--num-slices`, `--slice-step`. Accumulation with `--accum` and `--accum-type` is off by default, so each layer is a single sample.
- Crop: `--crop-x`, `--crop-y`, `--crop-width`, `--crop-height`, or `--auto-crop`. Units are output pixels. They are intersected with the surface canvas.
- Remote volume: `--remote-url <https url>`. `--volume` must still be given, and an unused local path works.
- Output: `--tif-output DIR` writes one file per layer, `00.tif` to `20.tif` for 21 layers, zero-padded to at least two digits. `--zarr-output` also exists.
- Size: `canvas = mesh grid / meta.json scale * --scale`, so `--scale 1 --group-idx 0` gives one pixel per level-0 voxel. On `20250108000000` the 1416×1324 grid becomes 28320×26480.

**On-surface layer.** `buildOffsetList` places layer `k` at `(k - c) * step` with `c = 0.5 * (N - 1)`, the same at both commits apart from the level factor above.

| `--num-slices` | k₀ | Note |
|---|---|---|
| 21 | 10 | File `10.tif` |
| 65 | 32 | Same as the legacy convention |
| 28 | none | **Even N puts no layer on the surface.** The two middle layers sit at ±0.5 step |
| Any odd N | (N−1)/2 | |

`vch render` records `on_surface_layer`, null for even N. The open-data README's "00.tif = Layer 0 (surface)" does not describe this renderer's output.

**Direction along the normal: measured.** `vesuvius` computes `n = dP/dV × dP/dU`, and VC3D computes `N = dP/dU × dP/dV`, so the two have opposite signs. We tested this end to end on four segments, comparing the rendered layer k₀+5 with Python samples at `p ± 5n` (run records `*.verify-io.run.json`):

| Segment | r along +n (`vesuvius`) | r along −n |
|---|---|---|
| `20260127000000` (w057) | -0.243 | 0.996 |
| `20260210000000` (w058) | -0.066 | 0.994 |
| `20260112000000` (w043) | -0.178 | 0.995 |
| `20260115000000` (w044) | 0.016 | 0.991 |

So **rising layer number runs along −n of `vesuvius`, which is +N of VC3D.** The pin's source comment says +N points to the outside of the scroll in the standard orientation, so rising layers go outward there. We did not verify a segment's orientation independently. At the pin, `--flip-normals` reverses this; the image has no such flag.

**`vc_objrefine`.** `vc_objrefine <zarr-volume> <src-surface> <out-surface> <json-params>`. The JSON takes `refine`, `start` (-2), `stop` (30), `step` (2), `low` (118/255), `high` (165/255), `border_off` (1), `r` (3), `gen_vertexcolor`, `overwrite`, `reader_scale` (0.5) and cache settings. Defaults are from the pin's `RefinementConfig`; we did not read the May version of this parser. No crop option, and no offset report at either commit.

**`vc_tifxyz_winding`.** `vc_tifxyz_winding <tiffxyz> [cropx cropy cropw croph]`, in the image only. The pin's `volume-cartographer/planning/changelog.md` lists it among CLIs removed. **Primer sections 3 and 5 name it as surviving; that now holds only for the May image.**

## 5. VC3D tag vocabulary

| Tag | In the code at the pin? | Evidence |
|---|---|---|
| `approved` | Yes | `SurfacePanelController.cpp`, `AgentBridgeHandlers_review.cpp` |
| `defective` | Yes | Same. A review precedence comment says defective outranks approved |
| `reviewed` | Yes | Same |
| `inspect` | Yes | Same |
| `partial_review` | Yes | Same. **Not in the primer's list** |
| `revisit` | **No** | Only in the docs (`scrollprize.org/docs/35_segmentation.md:154`). `vc3d_mcp/tools/segmentation.py:185` says outright that there is no "revisit" tag |

Tags are lower-case, and live under `meta.json` `tags`, as an object keyed by tag name (`{"inspect": {"date": "…"}}`) or as a list. The object store also carries them as record tags. The May image uses the same four checkbox tags plus `partial_review`.

## 6. Novelty code search for DR-002

Ten WO patterns, `rg -n -i --hidden -g '!.git'`, ripgrep 15.1.0, across the whole clone at the pin (6,703 tracked files). I added two patterns, because `fft.*shift` alone misses an FFT written without the word "shift". **All 2,483 hits are in `code-search-hits.tsv`** with path, line, judgment and reason. Source text is left out so that no GPL code enters this repo.

| Pattern | Hits | Files | Prior art | Related | Unrelated |
|---|---:|---:|---:|---:|---:|
| `phase_cross_correlation` | 0 | 0 | 0 | 0 | 0 |
| `phase.?corr` | 7 | 5 | 4 | 0 | 3 |
| `cross.?power` | 0 | 0 | 0 | 0 | 0 |
| `registration` | 819 | 196 | 2 | 63 | 754 |
| `fft.*shift` | 0 | 0 | 0 | 0 | 0 |
| `layer.?32` | 2 | 2 | 1 | 1 | 0 |
| `sharp` | 180 | 69 | 1 | 0 | 179 |
| `focus` | 1,237 | 177 | 0 | 0 | 1,237 |
| `normal.?offset` | 183 | 44 | 1 | 34 | 148 |
| `alpha.?composite` | 32 | 15 | 4 | 0 | 28 |
| Added: `fft2\|rfft2\|ifft2\|fftn` | 23 | 11 | 2 | 0 | 21 |
| Added: `phaseCorrelate\|register_translation\|normxcorr\|matchTemplate\|match_template` | 0 | 0 | 0 | 0 | 0 |

### Prior art, every hit

| Path | Lines | Judgment |
|---|---|---|
| `vesuvius/src/vesuvius/tifxyz_label_transfer/estimate_canvas_offset.py` | 9, 47, 66, 68, 261, 487 | **New to this project.** See below |
| `vesuvius/src/vesuvius/tifxyz_label_transfer/README.md` | 24, 26 | Describes that use: auditing a constant canvas offset |
| `volume-cartographer/apps/src/ObjAlphaCompRefinement.cpp` | 290 | `vc_objrefine`, the known baseline |
| `volume-cartographer/apps/VC3D/ToolDialogs.cpp` | 744 | UI for the same tool |
| `volume-cartographer/apps/VC3D/agent_bridge/SPEC.md` | 473 | API for the same tool |
| `volume-cartographer/tools/vc3d-mcp/vc3d_mcp/tools/surface_ops.py` | 86 | API for the same tool |
| `scrollprize.org/docs/20_community_projects.md` | 159 | segmata, known (DR-001) |
| `scrollprize.org/docs/20_community_projects.md` | 193 | TIFXYZ Doctor, known (DR-002) |

### The one that matters: `estimate_canvas_offset.py`

[`villa_estimate_canvas_offset`] Added by 2026-08-20 at the latest. It computes a normalised cross-power spectrum on Hann-windowed tiles, with parabolic sub-pixel peak refinement, over a tile grid of `surface` renders. It keeps the peak height, and it fits translation plus linear drift to the tile shifts. That is the same correlation primitive LPSF plans to use, applied per tile to surface renders.

It differs from LPSF in the question and in everything built on top:

| | `estimate_canvas_offset.py` | LPSF claim (DR-002) |
|---|---|---|
| Images compared | One label canvas's source render and its target projection, at the same depth | Adjacent layers along the normal |
| What the shift means | A 2-D offset of an annotation canvas relative to the mesh | Tilt of the mesh against the sheet |
| Output | One translation, with linear drift as a diagnostic | A per-patch field |
| Integration into an offset field | No | Yes |
| Curl residual | No | Yes |
| Stated limit | Its README: "only to audit a constant annotation-canvas offset" | |

**Judgment.** DR-002 items (a) to (c) are not anticipated by anything at the pin. But "phase correlation on surface renders" is no longer a novel kernel, and `method-lpsf.md` section 6 lists "phase methods" only as winding-phase. For the Planner: name this file in that table, and word the novelty claim as the *inter-layer tilt estimate and what follows from it*. `_phase_correlate` is also a candidate to reuse or compare with in WO-002 under DR-003.

### Related, grouped

Per-line detail is in the TSV.

| Paths | Hits | Why related, and why not prior art |
|---|---:|---|
| `foundation/volume-registration/*` | 24 | Volume-to-volume affine by Mattes mutual information. Different inputs and metric |
| `foundation/datasets/register-meshes-to-fibers/*` | 39 | Moves meshes to fiber skeletons by energy optimisation. No render-based error |
| `lasagna/opt_loss_station.py`, `opt_loss_pred_dt.py`, tests, docs | 14 | Normal-offset terms from predictions and winding seeds, not render texture |
| `vesuvius/.../fiber_trace_3d/cross_section.py` and its test | 8 | Image cross-sections along the normal, for fiber tracing |
| `vesuvius/.../heatmap_single_point/dataset.py` | 6 | Random normal perturbation in training. Same geometry as WO-003, different purpose |
| `scrollprize.org` `SegDemo.js`, `genGetStarted*.py`, `ink_thumb.py` | 6 | Teaching demo: renders look crisp on-surface. Illustration, no measurement |
| `deprecated/thaumato-anakalyptor/.../graph_to_mesh.py:1481` | 1 | Records the 64-layer convention with layer 32 as surface |

### Unrelated, grouped

`focus` is UI focus, CSS, prose and the Defocus augmentation; nothing measures focus or sharpness on a render. `sharp` is sharpen augmentations and prose. `registration` is mostly transform bookkeeping in `vc_reader` and `vc_object_store`, worker registration in `gpu_manager`, and winding-slab "phase registration", which is not image phase. `phase.?corr` also matches "phase correction" in winding code.

### What this search does not cover

- **Code outside the pin:** open PRs and branches are not in this text search. A GitHub search of villa PRs for "phase correlation", `phase_cross_correlation`, `phaseCorrelate`, "inter-layer" and "layer shift" found no PR with an estimator of this kind. That search covers titles and descriptions, not diffs.
- **Issues:** #2243 and #2370 mention correlation for *in-plane* alignment between renders or canvases [`villa_issue2243`, `villa_issue2370`], as does the external repo linked from #2370. Neither looks between layers. Both are related, not prior art.
- **Discord:** not searched. DR-002 assigns this to Kevin, and any public novelty claim must wait for it.
- **External tools:** segmata, TIFXYZ Doctor and the others are repo citations in `method-lpsf.md`. Reading their code was not part of this search.

## 7. Primer section 8 gaps

| Gap | Status |
|---|---|
| Villa full code text not searched | **Closed**, section 6 |
| Discord not searched | **Still unverified.** It needs Kevin's account (DR-002) |
| PR merge status #2224, #2365, #2368, #2373 | **Closed**, section 1: all open |
| November deadline | **Still unverified.** `/prizes` still shows October 31; see `data-survey.md` |
| Paris 4 reservation scope | **Closed**, see `data-survey.md` |

## 8. Primer statements to correct

For the Planner; the primer itself was not edited.

| Primer | Finding |
|---|---|
| Section 4: PR #2358 ports the offset report to `refine_surface` | `refine_surface` exists; the report does not |
| Sections 3, 5: `vc_tifxyz_winding` survives | Removed at the pin, in the image only |
| Section 4: `vesuvius.tifxyz` usable through `volume-only` | Needs `cv2`, `numba`; LZW needs `imagecodecs` |
| Section 5: layout `mesh/tifxyz/{x,y,z}.tif` | Actual layout is `mesh/<id>-on-<volume>-<res>.tifxyz/`, plus `mesh/intermediate/tifxyz_*`. Our `vch fetch` handles both |
| Section 5: 21 layers, 10 middle; 28 layers | 21 confirmed. 28 is even, so with this renderer no layer would be on the surface |
| Section 7: tags include Revisit | `revisit` is docs only; `partial_review` is real |
| `docs/data-licensing.md`: Scrolls 1–4 under EduceLab terms | Paris 4's published notice describes modified CC BY-NC 4.0 terms; see `data-survey.md` |
