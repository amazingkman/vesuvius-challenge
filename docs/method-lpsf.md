# Layer Phase-Shift Field (LPSF): theory, assumptions, falsification tests

Status: **hypothesis**, written 2026-10-31. Nothing here is a result until WO-002 (synthetic) and WO-003 (real data with injected perturbations) say so. The method was previously called "coherence mapping". It was renamed in DR-002 because another community project already uses "spectral coherence" for segmentation QC [T3: github.com/Diego-dcv/vesuvius-topological-grid, accessed 2026-10-31].

## 1. What is measured

A segment is a mesh (tifxyz quadmesh) with points **p**(u,v) and unit normals **n**(u,v). A surface volume renders layers

  I_k(u,v) = V( **p**(u,v) + (k − k₀)·Δd·**n**(u,v) ),  k = 0…K−1

where k₀ is the nominal on-surface layer and Δd is the slice step in voxels. With VC3D this is `vc_render_tifxyz --num-slices K --slice-step Δd` [T3: villa VC3D README and FASP README, accessed 2026-10-31].

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
| P1 | \|**s**\| scales linearly with Δd at fixed θ | Render with slice step 0.5, 1 and 2; slope ≈ sin θ |
| P2 | **s** ∥ **t** and \|**s**\|/Δd = sin θ; pure offset → **s** ≈ 0 | Synthetic tilt sweep 0–30°; offset sweep at θ = 0 |
| P3 | k* tracks the injected constant offset | Offset sweep ±10 layers |
| P4 | Curl residual ≈ 0 for smooth h; large at a step (sheet jump) | Smooth bump vs step discontinuity |
| P5 | Along-fiber component unobservable for 1D texture; Σ reflects it | Pure-orientation texture; compare Σ to the empirical scatter |
| P6 | ρ collapses when adjacent layers leave the sheet or cross into the neighbouring sheet | Two stacked sheets with a gap |

If P1 or P2 fail on synthetic sheets that satisfy A1, the model is wrong and LPSF stops there. That outcome gets recorded in decisions.md and reported, not hidden.

## 4. Known failure modes and threats to validity

- **A1 violated.** Papyrus has two fiber layers (horizontal and vertical) at different depths. Texture changes through the thickness, so ρ drops and **s** can bias. Expect the estimate to be best within one fiber layer, where the slice step is smaller than the fiber-layer thickness.
- **Aperture problem.** Strongly oriented fiber texture constrains only the shift component perpendicular to the fibers. Patches need Σ, and the solver must down-weight the unobservable direction instead of trusting it.
- **A2 violated.** Flattening and UV stretch turn pixel shifts into non-isometric quantities. Convert using the tifxyz grid scale and the local metric.
- **Texture confound.** Low-contrast or damaged papyrus lowers ρ even when the surface is correct. WO-003 stratifies by contrast and structure-tensor coherence, and uses *paired* comparisons (section 5), which cancel texture.
- **Prior negative result.** offset-sweep found that snapping to the brightest layer failed its pre-registered criteria [T3: github.com/LynnHenry/offset-sweep, accessed 2026-10-31]. LPSF must beat that baseline, not just exist.

## 5. Validation principle: injected perturbations on real segments

Start from a published, reviewed tifxyz segment. Displace its vertices along **n** by a known field h_inj(u,v): ramps (pure tilt), Gaussian bumps, and steps (synthetic sheet jumps). Re-render with the same renderer and estimate h. The unknown pre-existing error h₀ cancels in the difference:

  ĥ(perturbed) − ĥ(original) ≈ h_inj

This gives ground truth on real texture without trusting any label. Tag- and mask-based AUROC (VC3D Approved/Defective, FASP `state.tif` if still hosted) are secondary, observational checks.

## 6. Relation to prior work (cite all of these in any report)

| Work | What it does | Our relation |
|---|---|---|
| segmata (S. Gouttebroze), khartes fork; $1K Apr 2025 [T1 winners; T3 github.com/sgoutteb/segmata] | Vertex displacement along normals to maximize bright pixel count; "sharpening the layers rendering… optimizing the layer 32" | Direct prior art for render-driven normal refinement. LPSF is a different signal (inter-layer registration) for the same goal |
| `vc_objrefine` + offset report, villa PR #2224 (ChaseHendrick) [T3] | Per-vertex alpha-composite normal offset | Primary baseline; integration target |
| Lasagna local-correction mode [T1 Open Problems] | Moves a draft surface toward prediction volumes | Prediction-based alternative; possible consumer of our offsets |
| recto-offset (TAUIL Abd Elilah) [T3] | Learned per-pixel normal offset from 25 layers | Learned baseline |
| `vesuvius.snap_labels`, villa PR #2368 [T3] | Moves labels onto the recto face | Related; merge status unverified |
| TIFXYZ Doctor v0.2, $1K Jul 2026 [T1 winners] | Localizes synthetic normal-offset steps | Partial prior art for QC; baseline |
| offset-sweep (LynnHenry) [T3] | Ink-AUC cost of normal offsets; negative sheet-snap result | Baseline and context |
| winding-phase (millerandmuller) [T3] | Riesz-transform phase along normals, used for winding | Phase methods are used here, but not for layer registration |

**Novelty claim, exactly:** no prior use was found of patchwise sub-pixel phase correlation *between adjacent rendered layers* to estimate a tilt-error field, integrate it into a normal-offset field, or use its curl residual as a diagnostic. The search covered scrollprize.org, the Substack, villa issues and PR search, PyPI and community repos found by search. **Discord was not searched, and neither was villa's full code text.** Before any public claim, WO-001 includes a code search of villa, and Kevin checks Discord by hand (DR-002).
