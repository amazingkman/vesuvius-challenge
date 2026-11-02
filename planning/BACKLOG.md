# Backlog (not yet issued)

Each item becomes a WO only when its precondition is met.

| Item | Precondition | Notes |
|---|---|---|
| **LPSF → `vc_objrefine` / `refine_surface` integration**: supply ĥ (and Σ) as an error signal for the existing refinement path; measure the improvement on held-out perturbations and reviewed segments | WO-003 gate: S1 + S3 pass | Extends `vc_objrefine_pr2224` / PR #2358. Upstream only after the team shows interest on Discord (DR-012); otherwise standalone |
| **VC3D-loadable QC overlay**: LPSF fields written on the tifxyz canvas (Zarr/TIFF) so the Annotation Team can view them in VC3D | WO-003 gate | Adoption by the Annotation Team is an explicit prize criterion |
| **Progress-prize submission** | Gate pass, plus Planner review and Kevin's Discord novelty check (DR-002) | Confirm the live deadline and form on /prizes |
| **DR-002 novelty addendum** | WO-001 code search, plus Kevin's Discord check | Planner writes it |
| **Method B as a winding-tool evidence channel** | DR-003 justification exists (named tool to extend) | Parked (DR-006) |
| **Capstone write-up** (LaTeX paper or Zenodo report) | Gate pass, plus at least one real-data result | Citation discipline per `docs/citations.bib` |
| **Kevin's Discord asks**, three questions in one post: (1) prior art for inter-layer phase correlation or tilt estimation; (2) where the team's review tags live, and whether they can be shared; (3) whether a QC-method report on Paris 4 counts as a "formal analysis", and whether `state.tif` covers Paris 4 | None. Do it now | Answers feed the DR-002 addendum, tag-based validation, and Paris 4 permission (DR-008) |
| **Tag-based secondary validation** (Approved vs. Defective) | Tags obtainable (Discord ask) | Dropped from WO-003 rev 2 |
| **Build VC3D from source at the pin** | A WO needs a flag the May image lacks (e.g. `--flip-normals`) | DR-008 item 4 |
| **Report: `vc_render_tifxyz` silently skips when outputs exist** (existing issue or Discord only, per DR-012) | Only if the team confirms it affects them | Found in WO-001; it can make reproduction checks pass falsely. Small, useful upstream report |
| **Optional history rewrite** (`git filter-repo --replace-text`, then a force-push, plus a GitHub Support request to purge cached PR refs) | Kevin decides (DR-010) | Removes the old username path and hostname from branch history only |
| **Decorrelation-gain correction** (divide by predicted gain, or a joint model) | WO-006 gain prediction within ±0.25, and the pilot showing it holds on real data | New method; needs its own validation (DR-003) |
| **Approval-mask validation** (approved vs. unapproved regions, exploratory) | WO-003 step 0(f) finds published approval masks | Replaces the dropped tag-based analysis (DR-008, DR-013) |
