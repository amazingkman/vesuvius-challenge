# Layer Phase-Shift Field (LPSF): theory, assumptions, falsification tests

Status: **hypothesis**, written 2026-10-31. Nothing here is a result until WO-002 (synthetic) and WO-003 (real data with injected perturbations) say so. The method was previously called "coherence mapping". It was renamed in DR-002 because another community project already uses "spectral coherence" for segmentation QC [T3: github.com/Diego-dcv/vesuvius-topological-grid, accessed 2026-10-31].

## 1. What is measured

A segment is a mesh (tifxyz quadmesh) with points **p**(u,v) and unit normals **n**(u,v). A surface volume renders layers

  I_k(u,v) = V( **p**(u,v) + (k − k₀)·Δd·**n**(u,v) ),  k = 0…K−1

where k₀ is the nominal on-surface layer and Δd is the slice step in voxels. With VC3D this is `vc_render_tifxyz --num-slices K --slice-step Δd` [T3: villa VC3D README and FASP README, accessed 2026-10-31].

**Conventions measured in WO-001** (`reports/2026-11-wo001/upstream-audit.md` §4):
- k₀ = (K−1)/2 for odd K. Even K puts no layer on the surface, so **always use odd K**.
- With the image of record, rising k runs along **−n** of `vesuvius` (+N of VC3D); r ≈ 0.99 on four segments. In this document **n** therefore means the VC3D normal (layer-increasing direction). Code that computes normals with `vesuvius.tifxyz` must negate them.

For every patch P (default 64×64 px, 50% overlap) and every adjacent pair (k, k+1), we estimate:

- **s**ₖ(P): the sub-pixel in-plane translation between I_k and I_{k+1}, by phase correlation with upsampled-DFT peak refinement [Foroosh, Zerubia & Berthod 2002, IEEE TIP 11(3):188–200, doi:10.1109/83.988953; Guizar-Sicairos, Thurman & Fienup 2008, Opt. Lett. 33(2):156–158, doi:10.1364/OL.33.000156].
- **ρ**ₖ(P): the normalized phase-correlation peak height (how much texture the two layers share).
- **Σ**ₖ(P): a 2×2 shift covariance from the local structure tensor and the shape of the correlation peak. It captures the aperture problem (section 4).

## 2. Model: why the shift measures tilt, not offset

Model the papyrus sheet near P as a plane through **q** with unit normal **m**. Intensity is an in-plane texture times a thickness envelope:

  V(**x**) ≈ τ( Π_m **x** ) · w( **m**·(**x** − **q**) )

where Π_m projects onto the sheet plane. The key assumption is **A1**: τ does not change through the sheet thickness.

Let θ be the angle between **n** and **m**, and **t** the unit tilt direction in the sheet plane. Sampling along the mesh normal advances the in-plane coordinate by Π_m(Δd·**n**) = Δd·sin θ·**t** per layer. To first order, and assuming the flattening is locally isometric (**A2**):

  **s**ₖ ≈ Δd · sin θ · **t**

Let h(u,v) be the signed normal distance from the mesh to the sheet mid-plane. For a slowly varying sheet, ∇h = tan θ·**t**, so for small θ:

  **s**ₖ / Δd ≈ ∇h

Consequences:

1. **A constant offset gives zero shift.** Offset is invisible to the shift field. It is observable only through the depth profile of the envelope w: the layer index k* where ρₖ and the mean intensity peak satisfies k* ≈ k₀ + h/Δd.
2. **Orientation error is visible directly.** Brightness-based methods (segmata's "maximize bright pixels count", sheet-snap to the brightest layer) observe offset directly, and see tilt only through finite differences of noisy offsets. LPSF observes tilt directly and recovers offset by integration. The two are complementary signals. This is a hypothesis to test, not a claim.
3. **Integration.** Solve for h from the gradient field **g** = **s**/Δd by weighted least squares, using Fourier integration [Frankot & Chellappa 1988, IEEE TPAMI 10(4):439–451, doi:10.1109/34.3909] or a sparse Poisson solve with weights Σ⁻¹. Fix the integration constant with k*.
4. **Integrability residual.** A true gradient field is curl-free. The residual curl of the measured field is a model-violation map: sheet jumps, texture that is not through-thickness, render artifacts. This diagnostic is free once you have **g**. It is a candidate QC signal in its own right, and WO-003 must test it.

## 3. Falsifiable predictions (WO-002 tests these on synthetic sheets; WO-003 on real data)

| ID | Prediction | Test |
|---|---|---|
| P1 | \|**s**\| scales linearly with Δd at fixed θ | Synthetic: Δd = 0.5, 1, 2. Real: subsample one 81-layer step-1 render at Δd = 1, 2, 4 (no extra renders); slope ≈ sin θ |
| P2 | **s** ∥ **t** and \|**s**\|/Δd = sin θ; pure offset → **s** ≈ 0 | Synthetic tilt sweep 0–30°; offset sweep at θ = 0 |
| P3 | k* tracks the injected constant offset | Offset sweep ±10 layers |
| P4 | Curl residual ≈ 0 for smooth h; large at a step (sheet jump) | Smooth bump vs step discontinuity |
| P5 | Along-fiber component unobservable for 1D texture; Σ reflects it | Pure-orientation texture; compare Σ to the empirical scatter |
| P6 | ρ collapses when adjacent layers leave the sheet or cross into the neighbouring sheet | Two stacked sheets with a gap |

If P1 or P2 fail on synthetic sheets that satisfy A1, the model is wrong and LPSF stops there. That outcome gets recorded in decisions.md and reported, not hidden.

## 4. Known failure modes and threats to validity

- **A1 violated.** Papyrus has two fiber layers (horizontal and vertical) at different depths. Texture changes through the thickness, so ρ drops and **s** can bias. Expect the estimate to be best within one fiber layer, where the slice step is smaller than the fiber-layer thickness.
  - **Measured scale (WO-001, PHerc0139, 2.399 µm, four segments):** texture correlation between the on-surface layer and samples ±d voxels along the normal falls to r ≈ 0.93 at 1 voxel, 0.78 at 2 and 0.60 at 3 (`data-survey.md` §9). A1 therefore holds only over a few voxels (~5–7 µm) at this resolution.
  - **Consequences:** use adjacent pairs at Δd = 1. A larger step trades a bigger signal (Δd·sin θ) for faster decorrelation, so P1 must be tested on real data and not assumed. WO-002's synthetic texture should match this correlation length.
- **Aperture problem.** Strongly oriented fiber texture constrains only the shift component perpendicular to the fibers. Patches need Σ, and the solver must down-weight the unobservable direction instead of trusting it.
- **A2 violated.** Flattening and UV stretch turn pixel shifts into non-isometric quantities. Convert using the tifxyz grid scale and the local metric.
- **Texture confound.** Low-contrast or damaged papyrus lowers ρ even when the surface is correct. WO-003 stratifies by contrast and structure-tensor coherence, and uses *paired* comparisons (section 5), which cancel texture.
- **Prior negative result.** offset-sweep found that snapping to the brightest layer failed its pre-registered criteria [T3: github.com/LynnHenry/offset-sweep, accessed 2026-10-31]. LPSF must beat that baseline, not just exist.

## 5. Validation principle: injected perturbations on real segments

Start from a published tifxyz segment. Displace its vertices along **n** by a known field h_inj(u,v): sinusoidal corrugations (controlled local tilt), Gaussian bumps and steps (synthetic sheet jumps). Re-render with the same renderer and estimate h. The unknown pre-existing error h₀ cancels in the difference:

  ĥ(perturbed) − ĥ(original) ≈ h_inj

This gives ground truth on real texture without trusting any label. WO-001 found that no public segment carries an Approved or Defective tag, so "published" replaces the earlier "reviewed". The paired design does not need review status.

**The perturbed render must come from re-rendering the perturbed mesh. Never shift the original stack along its layer axis instead.** Displacing vertices tilts the mesh normals, and the tilt is exactly what produces the in-plane slide (§2). Resampling the original stack at depth k + h/Δd keeps the old normals, so it removes the signal and makes LPSF look blind.

Tag-based checks are skipped (no public tags). FASP `state.tif` almost certainly covers PHerc. Paris 4, which is under a publication reservation until 2027-06-25, so it is excluded (DR-008).

## 6. Relation to prior work (cite all of these in any report)

| Work | What it does | Our relation |
|---|---|---|
| segmata (S. Gouttebroze), khartes fork; $1K Apr 2025 [T1 winners; T3 github.com/sgoutteb/segmata] | Vertex displacement along normals to maximize bright pixel count; "sharpening the layers rendering… optimizing the layer 32" | Direct prior art for render-driven normal refinement. LPSF is a different signal (inter-layer registration) for the same goal |
| `vc_objrefine` (VC3D); offset report proposed in villa PR #2224 (ChaseHendrick), open and not at our pin [T3] | Per-vertex alpha-composite normal offset | Primary baseline, run as a black box: its correction = refined mesh − input mesh along **n**. Integration target |
| Lasagna local-correction mode [T1 Open Problems] | Moves a draft surface toward prediction volumes | Prediction-based alternative; possible consumer of our offsets |
| recto-offset (TAUIL Abd Elilah) [T3] | Learned per-pixel normal offset from 25 layers | Learned baseline |
| `vesuvius.snap_labels`, villa PR #2368 [T3] | Moves labels onto the recto face | Related; merge status unverified |
| TIFXYZ Doctor v0.2, $1K Jul 2026 [T1 winners] | Localizes synthetic normal-offset steps | Partial prior art for QC; baseline |
| offset-sweep (LynnHenry) [T3] | Ink-AUC cost of normal offsets; negative sheet-snap result | Baseline and context |
| winding-phase (millerandmuller) [T3] | Riesz-transform phase along normals, used for winding | Phase methods are used here, but not for layer registration |
| `vesuvius/tifxyz_label_transfer/estimate_canvas_offset.py`, in villa by 2026-08-20 [T3: `villa_estimate_canvas_offset`] | Hann-windowed tile-wise normalized cross-power spectrum on surface renders, with parabolic sub-pixel refinement; keeps peak height; fits translation plus drift to audit a constant 2-D annotation-canvas offset, at one depth | **Prior art for the correlation primitive on renders.** LPSF uses the same primitive along a different axis (between layers), for a different quantity (mesh tilt), and builds what that one does not (a per-patch field, integration, curl). Reuse or cross-check its `_phase_correlate` (MIT) under DR-003 |
| villa issues #2243, #2370 [T3] | Correlation for in-plane alignment between renders or canvases | Related; not between layers |

**Novelty claim, exactly (revised 2026-11-01 after the WO-001 code search):** phase correlation on surface renders is **not** new; villa already uses it in `estimate_canvas_offset.py`. What no source we searched contains is correlation *between adjacent layers along the normal* used to:
- estimate a mesh-tilt field;
- integrate that field into a normal-offset field;
- use its curl residual as a diagnostic.

**Searched:** scrollprize.org, the Substack, villa issues and PR titles and descriptions, PyPI, community repos found by search, and the full villa code text at `d57c28e` (2,483 hits judged; `reports/2026-11-wo001/upstream-audit.md` §6).
**Not searched:** Discord, and diffs of open PRs. No public novelty claim until Kevin has checked Discord (DR-002).
