"""Layer Phase-Shift Field (LPSF) estimator (docs/method-lpsf.md rev. 2026-11-01, WO-002 with addenda 1 and 2).

Conventions (WO-002 addendum 1 item 4, addendum 2 item 1)
---------------------------------------------------------
- A stack ``layers`` has shape ``(K, rows, cols)`` with odd ``K`` and on-surface layer ``k0 = (K - 1) / 2``. Rising
  ``k`` runs along the VC3D normal **n** (= ``-n`` of ``vesuvius``).
- Shifts and gradients are ``(row, col)`` = ``(v, u)`` pairs in render pixels.
- The shift ``s`` between layers ``k`` and ``k + 1`` is defined by ``I[k+1](x) = I[k](x + s)``.
- ``h`` is the distance along **n** from the mesh to the sheet mid-plane. For planar mesh and sheet,
  ``s = slice_step * tan(theta) * t`` in arc-length units and the covariant gradient is exactly
  ``d_i h = (1 / slice_step) * g_ij s^j`` with the mesh metric ``g_ij = d_i p . d_j p`` (identity on an isometric
  render). ``s`` points along ``+grad h`` (known-answer test in ``tests/test_lpsf.py``).

Pipeline
--------
1. Band-pass every layer in-plane (difference of Gaussians), optionally normalise its local contrast.
2. Per patch, the depth profile ``E(k)`` = band-passed variance x zero-lag correlation with the neighbours. The
   aggregation window is a contiguous run around the dominant peak of ``E(k)`` times a Gaussian prior on ``k0``,
   capped at ``w_max`` voxels (non-circular: it never uses ``s``). ``z*`` is the centroid of ``E`` in the window.
3. Shift per patch, by one of two estimators:
   ``pc``: per-pair windowed generalised phase correlation [foroosh2002] with matrix-DFT peak zooming [guizar2008],
   one resample-and-recorrelate refinement, aggregated over the window's pairs;
   ``lk``: symmetric multi-layer Lucas–Kanade [lucas1981]: normal equations summed over pixels and over the window's
   pairs before solving, iterated with resampling.
4. Metric-corrected gradient ``g``; screened, anisotropically weighted least-squares integration to ``h_hat`` with
   ``z*`` screening (Frankot–Chellappa [frankot1988] kept as a reference); consistency residual ``r = grad z* - g``;
   curl as a model-violation map.

WO-006 additions (the WO-002 defaults are unchanged):

- ``calibrate`` fits, and ``apply_calibration`` applies, the Sigma inflation ``sigma^2 <- kappa^2 sigma^2 + (f |g|)^2``;
- ``gain_map`` predicts the depth-decorrelation gain per patch (derivation in its docstring);
- ``Params(directional=True)`` keeps only across-fibre information and reports the along-fibre component as unobserved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
from scipy import fft as sfft
from scipy import ndimage, signal, sparse
from scipy.sparse.linalg import spsolve

Aggregate = Literal["rho", "information"]
Estimator = Literal["pc", "lk"]
FFT_WORKERS = -1  # scipy.fft threads; sweeps running one case per process set this to 1
RANK_TOLERANCE = 1e-9  # an eigenvalue this far below the largest is rounding error, not an observed direction


@dataclass(frozen=True)
class Params:
    """Estimator settings. Defaults are the WO-002 frozen defaults (reports/2026-11-wo002/report.md §Defaults)."""

    estimator: Estimator = "pc"
    patch: int = 64
    overlap: float = 0.5
    window: bool = True  # Hann weighting inside each patch
    # in-plane band-pass (difference of Gaussians, px): removes voxel noise / fringes and the envelope
    bp_fine: float = 1.0
    bp_coarse: float = 8.0
    normalize: bool = True  # divide by the local band-passed amplitude and weight pairs by their common support
    # phase correlation
    beta: float = 0.0  # spectral normalisation exponent: 1 = pure phase correlation, 0 = plain cross-correlation
    lowcut: float = 0.0  # cycles/px; extra exclusion of low frequencies inside the correlation
    refine: int = 1  # resample-and-recorrelate passes (pc); Gauss–Newton iterations are lk_iterations
    aggregate: Aggregate = "rho"
    max_shift: float | None = None
    # Lucas–Kanade
    lk_iterations: int = 4
    # in-sheet window rule (addendum 2 item 7)
    prior_sigma: float = 20.0  # layers, Gaussian prior on k0 used only to pick the dominant peak
    window_fraction: float = 0.9  # contiguous run with variance(k) >= fraction * variance(peak) ...
    profile_smooth: float = 1.5  # ... both profiles smoothed over depth by a Gaussian of this many layers
    w_max: float = 21.0  # voxels; maximal window width, must stay below the wrap pitch
    zstar_fraction: float = 0.5  # z*: centroid of E(k) over its contiguous half-maximum run around the peak ...
    zstar_wmax: float = 41.0  # ... capped at this many voxels (below the ~47-voxel wrap pitch)
    rho_min: float = 0.1  # pairs whose correlation is below this are ignored
    max_pairs: int | None = None  # if set, keep only this many pairs of the window, centred on its peak
    # uncertainty and integration
    kappa: float = 1.0  # covariance scale inside the raw estimate, unchanged from WO-002
    sigma_inflation: float = 1.0  # WO-006 kappa: calibrated variance = kappa^2 sigma^2 + (f |g|)^2
    sigma_floor: float = 0.0  # WO-006 f, the relative floor in the same formula
    directional: bool = False  # keep across-fibre information only (WO-006; off until the WO-003 pilot decides)
    directional_rcond: float = 0.1  # a summed direction below this fraction of the strongest counts as unobserved
    zstar_sigma: float = 1.0  # voxels; screening weight of z* in the integration
    chunk: int = 64  # pairs per FFT batch (small chunks avoid page-fault cost on large temporaries)

    @property
    def stride(self) -> int:
        return max(1, int(round(self.patch * (1 - self.overlap))))

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------------------------
# Batched phase correlation
# ---------------------------------------------------------------------------------------------------------------

_ZOOM_STAGES = (1.0, 0.25, 1 / 16, 1 / 64)  # half-widths (px) of the 9x9 zoom grids
_ZOOM_POINTS = 9


def hann2d(n: int) -> np.ndarray:
    w = np.hanning(n + 2)[1:-1]  # strictly positive Hann
    return np.outer(w, w)


@dataclass
class PairResult:
    shift: np.ndarray  # (N, 2) px, I_b(x) = I_a(x + shift)
    rho: np.ndarray  # (N,) phase-correlation peak height
    ncc: np.ndarray  # (N,) normalised cross-correlation at the shift
    curvature: np.ndarray  # (N, 2, 2) -Hessian of ncc at the shift, 1/px^2
    cov: np.ndarray  # (N, 2, 2) shift covariance, px^2


def _zoom_eval(spec: np.ndarray, freqs: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Real part of the inverse DFT of ``spec`` (B, N, N) at arbitrary points ``rows`` (B, R) x ``cols`` (B, C)."""
    er = np.exp(2j * np.pi * rows[:, :, None] * freqs[None, None, :])  # (B, R, N)
    ec = np.exp(2j * np.pi * freqs[None, :, None] * cols[:, None, :])  # (B, N, C)
    return np.real(er @ spec @ ec)


def _peak_parabola(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sub-grid offset of the centre of a (B, 3, 3) neighbourhood, by separable parabolas."""
    out = []
    for axis in (1, 2):
        centre = values[:, 1, 1]
        before = values[:, 0, 1] if axis == 1 else values[:, 1, 0]
        after = values[:, 2, 1] if axis == 1 else values[:, 1, 2]
        denom = before - 2 * centre + after
        with np.errstate(divide="ignore", invalid="ignore"):
            off = np.where(np.abs(denom) > 1e-15, 0.5 * (before - after) / denom, 0.0)
        out.append(np.clip(off, -0.5, 0.5))
    return out[0], out[1]


def _correlate_chunk(a: np.ndarray, b: np.ndarray, params: Params) -> PairResult:
    n_batch, n, _ = a.shape
    a = a - a.mean(axis=(1, 2), keepdims=True)
    b = b - b.mean(axis=(1, 2), keepdims=True)
    energy_a = np.sum(a * a, axis=(1, 2))
    energy_b = np.sum(b * b, axis=(1, 2))
    if params.window:
        w = hann2d(n)
        a = a * w
        b = b * w
        n_eff = w.sum() ** 2 / np.sum(w**2)
    else:
        n_eff = float(n * n)
    fa = sfft.fft2(a, workers=FFT_WORKERS)
    fb = sfft.fft2(b, workers=FFT_WORKERS)
    cross = fa * np.conj(fb)
    power_a = fa.real**2 + fa.imag**2
    power_b = fb.real**2 + fb.imag**2
    mag = np.sqrt(power_a * power_b)  # = |cross|
    scale = mag.max(axis=(1, 2), keepdims=True)
    flat = (energy_a < 1e-12 * n * n) | (energy_b < 1e-12 * n * n) | (scale[:, 0, 0] <= 0)
    keep = mag > 1e-9 * np.maximum(scale, 1e-300)
    freqs = np.fft.fftfreq(n)
    if params.lowcut > 0:
        keep &= (np.hypot(freqs[:, None], freqs[None, :]) >= params.lowcut)[None]
    # Generalised phase correlation: weight |C|^(1-beta); normalised so a perfect match peaks at 1.
    weight = np.where(keep, np.where(keep, mag, 1.0) ** (1.0 - params.beta), 0.0)
    inv = np.where(keep, weight / np.where(keep, mag, 1.0), 0.0)
    inv /= np.maximum(weight.sum(axis=(1, 2)), 1e-300)[:, None, None]
    spec = cross * inv
    surface = np.real(sfft.ifft2(spec, workers=FFT_WORKERS)) * (n * n)  # value at lag 0 = sum(spec)
    # The peak of IDFT(A conj B / |.|) sits at +s for I_b(x) = I_a(x + s); see module docstring.
    if params.max_shift is not None:
        signed = np.fft.fftfreq(n, 1.0 / n)
        out_of_range = (np.abs(signed)[:, None] > params.max_shift) | (np.abs(signed)[None, :] > params.max_shift)
        surface = np.where(out_of_range[None], -np.inf, surface)
    flat_idx = np.argmax(surface.reshape(n_batch, -1), axis=1)
    peak_r, peak_c = np.unravel_index(flat_idx, (n, n))
    centre = np.stack([np.where(peak_r > n // 2, peak_r - n, peak_r), np.where(peak_c > n // 2, peak_c - n, peak_c)], 1)
    centre = centre.astype(np.float64)

    grid = np.linspace(-1, 1, _ZOOM_POINTS)
    batch = np.arange(n_batch)
    for half in _ZOOM_STAGES:
        rows = centre[:, :1] + half * grid[None, :]
        cols = centre[:, 1:] + half * grid[None, :]
        values = _zoom_eval(spec, freqs, rows, cols)
        best = np.argmax(values.reshape(n_batch, -1), axis=1)
        br, bc = np.unravel_index(best, values.shape[1:])
        centre = np.stack([rows[batch, br], cols[batch, bc]], 1)
    step = _ZOOM_STAGES[-1] * (grid[1] - grid[0])
    rows = centre[:, :1] + step * np.array([-1.0, 0.0, 1.0])[None, :]
    cols = centre[:, 1:] + step * np.array([-1.0, 0.0, 1.0])[None, :]
    local = _zoom_eval(spec, freqs, rows, cols)
    dr, dc = _peak_parabola(local)
    shift = centre + step * np.stack([dr, dc], 1)
    rho = local[:, 1, 1]

    # Normalised cross-correlation and its curvature at the shift, from the unwhitened spectrum. The phase ramp is
    # separable, so every moment sum_f f_v^a f_u^b C(f) e^{2πi f·s} is (e_v f_v^a)^T C (e_u f_u^b).
    ev = np.exp(2j * np.pi * shift[:, :1] * freqs[None, :])  # (B, N)
    eu = np.exp(2j * np.pi * shift[:, 1:] * freqs[None, :])
    powers = np.stack([np.ones(n), freqs, freqs**2])  # (3, N)
    left = ev[:, None, :] * powers[None]  # (B, 3, N)
    right = eu[:, None, :] * powers[None]
    moments = np.real(left @ cross @ np.swapaxes(right, 1, 2))  # (B, 3, 3): [a, b] = sum f_v^a f_u^b ...
    norm = np.sqrt(power_a.sum(axis=(1, 2)) * power_b.sum(axis=(1, 2)))
    norm = np.where(norm > 0, norm, np.inf)
    ncc = moments[:, 0, 0] / norm
    k2 = (2 * np.pi) ** 2
    cyy = k2 * moments[:, 2, 0] / norm
    cxx = k2 * moments[:, 0, 2] / norm
    cxy = k2 * moments[:, 1, 1] / norm
    curvature = np.stack([np.stack([cyy, cxy], -1), np.stack([cxy, cxx], -1)], -2)
    cov = shift_covariance(curvature, ncc, n_eff, n, params.kappa)

    rho = np.where(flat, 0.0, rho)
    ncc = np.where(flat, 0.0, ncc)
    shift = np.where(flat[:, None], 0.0, shift)
    cov = np.where(flat[:, None, None], cov_cap(n) * np.eye(2), cov)
    return PairResult(shift=shift, rho=rho, ncc=ncc, curvature=curvature, cov=cov)


def cov_cap(patch: int) -> float:
    """Largest reported shift variance (px^2): a shift is never less known than a quarter of the patch."""
    return (patch / 4) ** 2


def shift_covariance(curvature: np.ndarray, ncc: np.ndarray, n_eff: float, patch: int, kappa: float) -> np.ndarray:
    """Shift covariance from peak curvature and correlation: ``kappa * 2 (1 - ncc) / n_eff * curvature^-1``.

    Two layers sharing a fraction ``ncc`` of their variance, the rest independent, give a Cramér–Rao-like covariance
    of this form; the curvature of the cross-correlation peak is the cross structure tensor of the two layers, so the
    aperture problem shows up as a near-zero eigenvalue and a huge variance along the fibres. Eigenvalues are clipped
    to ``[1e-8, cov_cap(patch)]`` px^2 so flat or noise patches report a large, finite uncertainty.
    """
    cap = cov_cap(patch)
    sym = 0.5 * (curvature + np.swapaxes(curvature, -1, -2))
    evals, evecs = np.linalg.eigh(sym)
    good = np.clip(ncc, 0.0, 1.0)
    numer = kappa * 2 * np.clip(1 - good, 1e-6, None) / n_eff
    with np.errstate(divide="ignore", invalid="ignore"):
        var = np.where(evals > 0, numer[:, None] / evals, cap)
    var = np.where(good[:, None] > 0, var, cap)
    var = np.clip(np.nan_to_num(var, nan=cap, posinf=cap), 1e-8, cap)
    return np.einsum("bij,bj,bkj->bik", evecs, var, evecs)


def phase_correlate(a: np.ndarray, b: np.ndarray, params: Params | None = None) -> PairResult:
    """Batched sub-pixel phase correlation of square patches ``a``, ``b`` of shape ``(..., P, P)``.

    Returns ``shift`` with ``b(x) ≈ a(x + shift)``, peak height ``rho``, ``ncc``, peak curvature and covariance.
    """
    params = params or Params()
    lead = a.shape[:-2]
    n = a.shape[-1]
    if a.shape[-2] != n or b.shape != a.shape:
        raise ValueError(f"need matching square patches, got {a.shape} and {b.shape}")
    fa = a.reshape(-1, n, n).astype(np.float64)
    fb = b.reshape(-1, n, n).astype(np.float64)
    parts = [
        _correlate_chunk(fa[i : i + params.chunk], fb[i : i + params.chunk], params)
        for i in range(0, len(fa), params.chunk)
    ]
    if not parts:
        empty = np.zeros((0,))
        return PairResult(
            empty.reshape(*lead, 2),
            empty.reshape(lead),
            empty.reshape(lead),
            empty.reshape(*lead, 2, 2),
            empty.reshape(*lead, 2, 2),
        )
    cat = {key: np.concatenate([getattr(p, key) for p in parts]) for key in ("shift", "rho", "ncc", "curvature", "cov")}
    return PairResult(
        shift=cat["shift"].reshape(*lead, 2),
        rho=cat["rho"].reshape(lead),
        ncc=cat["ncc"].reshape(lead),
        curvature=cat["curvature"].reshape(*lead, 2, 2),
        cov=cat["cov"].reshape(*lead, 2, 2),
    )


# ---------------------------------------------------------------------------------------------------------------
# Tiling and per-patch estimation
# ---------------------------------------------------------------------------------------------------------------


def patch_origins(size: int, patch: int, stride: int) -> np.ndarray:
    if size < patch:
        return np.zeros(0, dtype=int)
    return np.arange(0, size - patch + 1, stride)


def extract_patches(layers: np.ndarray, rows: np.ndarray, cols: np.ndarray, patch: int) -> np.ndarray:
    """``(K, R, C, P, P)`` patches at the given origins."""
    view = np.lib.stride_tricks.sliding_window_view(layers, (patch, patch), axis=(1, 2))
    return view[:, rows][:, :, cols]


def _bspline_weights(frac: np.ndarray) -> np.ndarray:
    """Cubic B-spline basis weights for taps -1, 0, 1, 2 at fractional offset ``frac``. (N, 4)."""
    f = frac[:, None]
    return np.concatenate(
        [(1 - f) ** 3 / 6, (3 * f**3 - 6 * f**2 + 4) / 6, (-3 * f**3 + 3 * f**2 + 3 * f + 1) / 6, f**3 / 6], axis=1
    )


def spline_coefficients(layers: np.ndarray) -> np.ndarray:
    """Cubic B-spline interpolation coefficients of every layer (mirror boundaries), float32."""
    out = np.empty(layers.shape, dtype=np.float32)
    for k, layer in enumerate(layers):
        out[k] = ndimage.spline_filter(np.asarray(layer, dtype=np.float64), order=3, mode="mirror")
    return out


def resample_patches(
    coefficients: np.ndarray, layer_idx: np.ndarray, row0: np.ndarray, col0: np.ndarray, patch: int, shift: np.ndarray
) -> np.ndarray:
    """Patches read at ``x - shift`` by cubic B-spline interpolation of prefiltered ``coefficients``
    (:func:`spline_coefficients`): ``out[n](x) = layer[idx[n]](origin[n] + x - shift[n])``.

    One shift per patch, so the interpolation is a separable 4-tap filter on a gathered (P+3)^2 block. Used for
    iterative refinement: a pair already aligned by ``shift`` leaves only a small residual, so the fixed window no
    longer pulls the estimate toward zero. The interpolator must be phase-accurate at the texture's frequencies:
    Keys cubic convolution (used first) biased the refined slope by +10% for 8-px texture across the tilt
    (reports/2026-11-wo002/diagnosis-overshoot.json); prefiltered B-splines do not.
    """
    height, width = coefficients.shape[1:]
    out = np.empty((layer_idx.size, patch, patch), dtype=np.float32)
    taps = np.arange(-1, patch + 2)
    for start in range(0, layer_idx.size, 256):
        sl = slice(start, start + 256)
        t = -shift[sl]
        whole = np.floor(t)
        frac = t - whole
        rr = np.clip(row0[sl, None] + whole[:, :1].astype(int) + taps[None, :], 0, height - 1)
        cc = np.clip(col0[sl, None] + whole[:, 1:].astype(int) + taps[None, :], 0, width - 1)
        block = coefficients[layer_idx[sl, None, None], rr[:, :, None], cc[:, None, :]].astype(np.float64)
        wr = _bspline_weights(frac[:, 0])
        wc = _bspline_weights(frac[:, 1])
        rows_done = sum(wr[:, m, None, None] * block[:, m : m + patch, :] for m in range(4))
        out[sl] = sum(wc[:, m, None, None] * rows_done[:, :, m : m + patch] for m in range(4))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Pre-filtering
# ---------------------------------------------------------------------------------------------------------------


def bandpass(layers: np.ndarray, fine: float, coarse: float) -> np.ndarray:
    """In-plane difference-of-Gaussians band-pass of every layer (addendum 2 item 2)."""
    out = np.empty(layers.shape, dtype=np.float32)
    for k, layer in enumerate(np.asarray(layers, dtype=np.float64)):
        low = ndimage.gaussian_filter(layer, fine, mode="reflect") if fine > 0 else layer
        # coarse <= 0 disables the low cut (only the mean is removed): the unfiltered reference of item 2
        out[k] = low - (ndimage.gaussian_filter(layer, coarse, mode="reflect") if coarse > 0 else layer.mean())
    return out


def local_amplitude(band: np.ndarray, sigma: float) -> np.ndarray:
    """Local standard deviation of a band-passed stack, Gaussian ``sigma`` px."""
    out = np.empty(band.shape, dtype=np.float32)
    for k, layer in enumerate(np.asarray(band, dtype=np.float64)):
        out[k] = np.sqrt(ndimage.gaussian_filter(layer * layer, sigma, mode="reflect"))
    return out


def common_support(a: np.ndarray, amp_a: np.ndarray, b: np.ndarray, amp_b: np.ndarray):
    """Weight both patches by one mask, the geometric mean of their texture amplitudes (normalised to max 1).

    A texture strip that moves between layers (a tilted mesh crossing the sheet edge) then cannot drag the
    correlation peak with it; the remaining pull is toward zero, and refinement removes it.
    """
    mask = np.sqrt(amp_a * amp_b)
    mask = mask / np.maximum(mask.max(axis=(-2, -1), keepdims=True), 1e-12)
    return a * mask, b * mask, mask


# ---------------------------------------------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Field:
    """Per-patch LPSF field. Arrays are indexed ``[row, col]`` over the patch grid; vectors are ``(v, u)``."""

    params: Params
    slice_step: float
    k0: int
    centres_v: np.ndarray  # (R,) patch centre rows, px
    centres_u: np.ndarray  # (C,)
    profile: np.ndarray  # (K, R, C) E(k): band-passed variance x neighbour correlation
    variance: np.ndarray  # (K, R, C) band-passed variance
    rho0: np.ndarray  # (K-1, R, C) zero-lag correlation of adjacent band-passed layers
    in_window: np.ndarray  # (K, R, C) bool, layers in the aggregation window
    pair_shift: np.ndarray  # (K-1, R, C, 2); zero outside the window
    pair_rho: np.ndarray  # (K-1, R, C); NaN outside the window
    pair_cov: np.ndarray  # (K-1, R, C, 2, 2); cap outside the window
    pair_used: np.ndarray  # (K-1, R, C) bool
    shift: np.ndarray  # (R, C, 2) aggregated shift, px
    cov: np.ndarray  # (R, C, 2, 2) its covariance, px^2
    rho: np.ndarray  # (R, C) mean correlation of the used pairs
    valid: np.ndarray  # (R, C) bool
    kstar: np.ndarray  # (R, C) fractional layer index of the sheet
    kstar_censored: np.ndarray  # (R, C) bool: the window touches an end of the stack
    metric: np.ndarray  # (R, C, 2, 2) mesh metric g_ij at the patch centres
    # Directional estimates only. Zero information along a direction means infinite variance: that direction is
    # unobserved, and `shift` holds no estimate along it. `cov` then carries the cap there, only to stay finite.
    information: np.ndarray | None = None  # (R, C, 2, 2) shift information, 1/px^2, rank 0, 1 or 2

    @property
    def spacing(self) -> float:
        return float(self.params.stride)

    @property
    def grad(self) -> np.ndarray:
        """Covariant ``grad h`` = ``g_ij s^j / slice_step`` (addendum 2 item 1). Dimensionless (voxel per px)."""
        return np.einsum("rcij,rcj->rci", self.metric, self.shift) / self.slice_step

    @property
    def grad_cov(self) -> np.ndarray:
        return np.einsum("rcij,rcjk,rclk->rcil", self.metric, self.cov, self.metric) / self.slice_step**2

    @property
    def calibrated_grad_cov(self) -> np.ndarray:
        """``grad_cov`` with the WO-006 calibration applied."""
        return apply_calibration(self.grad_cov, self.grad, self.params.sigma_inflation, self.params.sigma_floor)

    @property
    def grad_information(self) -> np.ndarray | None:
        """Calibrated information on ``grad h`` for a directional estimate; ``None`` for a full estimate.

        A direction with zero information stays at zero: calibration cannot create or remove an observation.
        """
        if self.information is None:
            return None
        inverse = np.linalg.inv(self.metric)
        raw = np.einsum("rcji,rcjk,rckl->rcil", inverse, self.information, inverse) * self.slice_step**2
        evals, evecs = np.linalg.eigh(raw)
        speed = np.linalg.norm(self.grad, axis=-1, keepdims=True)
        with np.errstate(divide="ignore"):
            var = np.where(evals > 0, 1 / evals, np.inf)
        var = self.params.sigma_inflation**2 * var + (self.params.sigma_floor * speed) ** 2
        out = np.where(np.isfinite(var), 1 / var, 0.0)
        return np.einsum("rcij,rcj,rckj->rcik", evecs, out, evecs)

    def observed_rank(self) -> np.ndarray:
        """Number of directions observed per patch: 2 for a full estimate, 0 to 2 for a directional one."""
        if self.information is None:
            return np.where(self.valid, 2, 0)
        evals = np.linalg.eigvalsh(self.information)
        return np.sum(evals > RANK_TOLERANCE * evals[..., -1:], axis=-1) * (evals[..., -1] > 0)

    @property
    def zstar(self) -> np.ndarray:
        """Sheet position along **n** from the depth profile: ``(k* - k0) * slice_step`` voxels."""
        return (self.kstar - self.k0) * self.slice_step

    @property
    def zstar_ok(self) -> np.ndarray:
        return np.isfinite(self.kstar) & ~self.kstar_censored


def metric_from_points(points: np.ndarray) -> np.ndarray:
    """Mesh metric ``g_ij = d_i p . d_j p`` (voxel^2 per px^2) of a ``(v, u, 3)`` point grid, shape ``(v, u, 2, 2)``."""
    d_v = np.gradient(points, axis=0)
    d_u = np.gradient(points, axis=1)
    tangents = np.stack([d_v, d_u], axis=-2)  # (v, u, 2, 3)
    return np.einsum("...ia,...ja->...ij", tangents, tangents)


def _metric_at_patches(metric: np.ndarray | None, shape: tuple[int, int], rows, cols, patch: int) -> np.ndarray:
    if metric is None:
        return np.broadcast_to(np.eye(2), (rows.size, cols.size, 2, 2)).copy()
    metric = np.asarray(metric, dtype=np.float64)
    if metric.shape == (2, 2):
        return np.broadcast_to(metric, (rows.size, cols.size, 2, 2)).copy()
    if metric.shape[:2] != shape:
        raise ValueError(f"metric must be (2, 2) or {shape} + (2, 2), got {metric.shape}")
    w = hann2d(patch)
    w = (w / w.sum())[::-1, ::-1]
    out = np.empty((rows.size, cols.size, 2, 2))
    for i in range(2):
        for j in range(2):
            out[..., i, j] = signal.fftconvolve(metric[..., i, j], w, mode="valid")[np.ix_(rows, cols)]
    return out


# ---------------------------------------------------------------------------------------------------------------
# Depth profile and window (addendum 2 item 7)
# ---------------------------------------------------------------------------------------------------------------


def zero_lag_rho(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Window-weighted Pearson correlation at zero lag of patch stacks ``(..., P, P)``."""
    w = w / w.sum()
    am = a - np.einsum("...ij,ij->...", a, w)[..., None, None]
    bm = b - np.einsum("...ij,ij->...", b, w)[..., None, None]
    cov = np.einsum("...ij,...ij,ij->...", am, bm, w)
    va = np.einsum("...ij,...ij,ij->...", am, am, w)
    vb = np.einsum("...ij,...ij,ij->...", bm, bm, w)
    denom = np.sqrt(va * vb)
    return np.where(denom > 0, cov / np.where(denom > 0, denom, 1), 0.0)


def depth_window(
    peak_profile: np.ndarray,
    k0: int,
    slice_step: float,
    prior_sigma: float,
    fraction: float,
    w_max: float,
    run_profile: np.ndarray | None = None,
) -> np.ndarray:
    """Contiguous aggregation window around the dominant peak of ``peak_profile x prior``. ``(K, ...)`` bool.

    The Gaussian prior on ``k0`` (``prior_sigma`` layers) only selects which peak. Within ``w_max`` voxels centred
    on the peak, the window is the hull (first to last layer) of the layers with
    ``run_profile >= fraction * max(run_profile)`` (``run_profile`` defaults to ``peak_profile``). The hull is
    contiguous, stops where the sheet envelope falls off, and does not split at an interior dip such as the
    recto/verso fibre interface. A neighbouring wrap cannot enter while ``w_max`` stays below the wrap pitch. The
    rule never looks at the shifts.
    """
    run = peak_profile if run_profile is None else run_profile
    n = peak_profile.shape[0]
    k = np.arange(n, dtype=np.float64).reshape(-1, *([1] * (peak_profile.ndim - 1)))
    prior = np.exp(-0.5 * ((k - k0) / prior_sigma) ** 2)
    peak = np.argmax(np.nan_to_num(peak_profile, nan=-np.inf) * prior, axis=0)
    span = np.abs(k - peak) <= 0.5 * w_max / slice_step
    level = fraction * np.where(span, run, -np.inf).max(axis=0)
    above = span & (run >= level)
    lo = np.where(above, k, n).min(axis=0)
    hi = np.where(above, k, -1).max(axis=0)
    return span & (k >= np.minimum(lo, peak)) & (k <= np.maximum(hi, peak))


# ---------------------------------------------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------------------------------------------


def structure_covariance(a: np.ndarray, b: np.ndarray, ncc: np.ndarray, w: np.ndarray, kappa: float) -> np.ndarray:
    """Shift covariance from the structure tensor of an aligned pair: ``kappa * 2 (1 - ncc) / n_eff * T^-1``.

    ``T = sym(sum w^2 grad a grad b^T) / sum w^2 a b`` (a cross structure tensor of the aligned, zero-mean pair).
    Noise independent between the layers cancels from T in expectation, and unlike the curvature of the windowed
    correlation peak T does not contain the window's own curvature, so a 1-D texture gives a near-zero eigenvalue
    along the fibres (the aperture problem) and the variance there goes to the cap.
    """
    patch = a.shape[-1]
    w2 = w**2
    wn = w2 / w2.sum()
    a = a - np.einsum("nij,ij->n", a, wn)[:, None, None]
    b = b - np.einsum("nij,ij->n", b, wn)[:, None, None]
    ga = np.stack([np.gradient(a, axis=-2), np.gradient(a, axis=-1)], axis=-1)
    gb = np.stack([np.gradient(b, axis=-2), np.gradient(b, axis=-1)], axis=-1)
    tensor = np.einsum("ij,nija,nijb->nab", w2, ga, gb)
    tensor = 0.5 * (tensor + np.swapaxes(tensor, -1, -2))
    energy = np.einsum("ij,nij->n", w2, a * b)
    tensor = tensor / np.where(energy > 0, energy, np.inf)[:, None, None]
    n_eff = w.sum() ** 2 / np.sum(w2)
    return shift_covariance(tensor, ncc, n_eff, patch, kappa)


def _estimate_pc(tex_view, amp_view, tex_coef, amp_coef, kk, rr, cc, rows, cols, params):
    p = params.patch
    w = hann2d(p) if params.window else np.ones((p, p))
    ta, aa = tex_view[kk, rows[rr], cols[cc]], amp_view[kk, rows[rr], cols[cc]]
    a, b, _ = common_support(ta, aa, tex_view[kk + 1, rows[rr], cols[cc]], amp_view[kk + 1, rows[rr], cols[cc]])
    found = phase_correlate(a, b, params)
    for _ in range(params.refine):
        moved = resample_patches(tex_coef, kk + 1, rows[rr], cols[cc], p, found.shift)
        moved_amp = resample_patches(amp_coef, kk + 1, rows[rr], cols[cc], p, found.shift)
        a, b, _ = common_support(ta, aa, moved, moved_amp)
        residual = phase_correlate(a, b, params)
        residual.shift = found.shift + residual.shift
        found = residual
    if a.shape[0]:
        found.cov = structure_covariance(a.astype(np.float64), b.astype(np.float64), found.ncc, w, params.kappa)
    return found


def across_fibre(pair_cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best-determined direction of each pair and its variance. Peak curvature is high across fibres, so this is the
    across-fibre direction wherever the texture is oriented. ``pair_cov`` is ``(..., 2, 2)``."""
    evals, evecs = np.linalg.eigh(pair_cov)
    return evecs[..., 0], evals[..., 0]


def solve_observed(summed: np.ndarray, rhs: np.ndarray, rcond: float, cap: float):
    """Solve ``J s = rhs`` keeping only directions with ``eigenvalue >= rcond * largest``.

    Returns the solution, ``J`` restricted to those directions (zero along the rest, i.e. infinite variance) and a
    finite covariance with ``cap`` along the rest.
    """
    evals, evecs = np.linalg.eigh(summed)
    keep = (evals > 0) & (evals >= rcond * evals[..., -1:])
    safe = np.where(keep, evals, 1.0)
    inverse = np.where(keep, 1 / safe, 0.0)
    shift = np.einsum("...ij,...j,...kj,...k->...i", evecs, inverse, evecs, rhs)
    information = np.einsum("...ij,...j,...kj->...ik", evecs, np.where(keep, evals, 0.0), evecs)
    cov = np.einsum("...ij,...j,...kj->...ik", evecs, np.where(keep, 1 / safe, cap), evecs)
    return shift, information, cov


def directional_summary(pair_shift, pair_cov, used, rcond: float, cap: float):
    """Project every pair onto its across-fibre direction, sum information over layers, then solve.

    Summing before solving lets recto and verso cover two directions when both are in the window. A patch that sees
    one direction stays rank 1: nothing is estimated along the fibres, and the integrator leaves that direction to
    neighbouring patches and the z* screening term.
    """
    across, variance = across_fibre(pair_cov)
    weight = np.where(used, 1 / np.maximum(variance, 1e-300), 0.0)
    summed = np.einsum("krc,krci,krcj->rcij", weight, across, across)
    rhs = np.einsum("krc,krci,krcj,krcj->rci", weight, across, across, pair_shift)
    return solve_observed(summed, rhs, rcond, cap)


def _lk_terms(a: np.ndarray, b: np.ndarray, weight: np.ndarray):
    """Per-pair symmetric Lucas–Kanade terms: information A, right-hand side c, residual energy, weights."""
    mean = 0.5 * (a + b)
    gv = np.gradient(mean, axis=-2)
    gu = np.gradient(mean, axis=-1)
    diff = b - a
    grads = np.stack([gv, gu], axis=-1)  # (N, P, P, 2)
    info = np.einsum("nij,nija,nijb->nab", weight, grads, grads)
    rhs = np.einsum("nij,nija,nij->na", weight, grads, diff)
    meat = np.einsum("nij,nija,nijb->nab", weight**2, grads, grads)
    return info, rhs, meat, diff, grads


def _estimate_lk(tex_view, amp_view, tex_coef, amp_coef, kk, rr, cc, rows, cols, params, n_patches_shape):
    """Multi-layer symmetric LK: one shift per patch from normal equations summed over the window's pairs."""
    p = params.patch
    w = hann2d(p) if params.window else np.ones((p, p))
    n_rc = n_patches_shape[0] * n_patches_shape[1]
    patch_id = rr * n_patches_shape[1] + cc
    shift = np.zeros((n_rc, 2))
    a_raw = tex_view[kk, rows[rr], cols[cc]].astype(np.float64)
    amp_a = amp_view[kk, rows[rr], cols[cc]]
    pair_info = None
    for _ in range(max(1, params.lk_iterations)):
        s_pair = shift[patch_id]
        moved = resample_patches(tex_coef, kk + 1, rows[rr], cols[cc], p, s_pair).astype(np.float64)
        moved_amp = resample_patches(amp_coef, kk + 1, rows[rr], cols[cc], p, s_pair)
        a, b, mask = common_support(a_raw, amp_a, moved, moved_amp)
        weight = w[None] * (mask if params.normalize else 1.0)
        info, rhs, meat, diff, grads = _lk_terms(a, b, weight)
        pair_info = info
        if params.directional:
            # Keep each pair's across-fibre direction, the eigenvector with the most gradient energy.
            across = np.linalg.eigh(info)[1][..., 1]
            energy = np.einsum("na,nab,nb->n", across, info, across)
            info = energy[:, None, None] * np.einsum("na,nb->nab", across, across)
            rhs = np.einsum("na,nb,nb->na", across, across, rhs)
            meat = np.einsum("na,nc,ncd,nd,ne->nae", across, across, meat, across, across)
        info_sum = np.zeros((n_rc, 2, 2))
        rhs_sum = np.zeros((n_rc, 2))
        np.add.at(info_sum, patch_id, info)
        np.add.at(rhs_sum, patch_id, rhs)
        ridge = 1e-9 * np.trace(info_sum, axis1=1, axis2=2)[:, None, None] * np.eye(2) + 1e-12 * np.eye(2)
        if params.directional:
            delta = solve_observed(info_sum, rhs_sum, params.directional_rcond, 0.0)[0]
        else:
            delta = np.linalg.solve(info_sum + ridge, rhs_sum[..., None])[..., 0]
        has = np.bincount(patch_id, minlength=n_rc) > 0
        shift = shift + np.where(has[:, None], delta, 0.0)
    # Sandwich covariance with the residual variance of the final linearisation.
    resid = diff - np.einsum("nija,na->nij", grads, delta[patch_id])
    res_sum = np.zeros(n_rc)
    wsum = np.zeros(n_rc)
    np.add.at(res_sum, patch_id, np.einsum("nij,nij->n", weight, resid**2))
    np.add.at(wsum, patch_id, weight.sum(axis=(1, 2)))
    sigma2 = res_sum / np.maximum(wsum, 1e-12)
    meat_sum = np.zeros((n_rc, 2, 2))
    np.add.at(meat_sum, patch_id, meat)
    if params.directional:
        inv = solve_observed(info_sum, np.zeros((n_rc, 2)), params.directional_rcond, 0.0)[2]
    else:
        inv = np.linalg.inv(info_sum + ridge)
    cov = params.kappa * sigma2[:, None, None] * np.einsum("nab,nbc,ncd->nad", inv, meat_sum, inv)
    # Per-pair covariance (for reporting the aperture problem per layer): sigma2 * A_k^-1 * M_k * A_k^-1.
    pair_inv = np.linalg.pinv(pair_info)
    pair_cov = params.kappa * sigma2[patch_id][:, None, None] * np.einsum("nab,nbc,ncd->nad", pair_inv, meat, pair_inv)
    rho = zero_lag_rho(a, b, w)
    return shift, cov, pair_cov, rho


# ---------------------------------------------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------------------------------------------


def estimate(
    layers: np.ndarray, slice_step: float, params: Params | None = None, metric: np.ndarray | None = None
) -> Field:
    """Per-patch LPSF estimate on a ``(K, rows, cols)`` stack. ``metric`` is the mesh metric (identity if None)."""
    params = params or Params()
    layers = np.asarray(layers, dtype=np.float32)
    n_layers = layers.shape[0]
    if n_layers % 2 == 0 or n_layers < 3:
        raise ValueError(f"need an odd number of layers >= 3 (WO-002 addendum 1 item 4), got {n_layers}")
    k0 = (n_layers - 1) // 2
    p = params.patch
    rows = patch_origins(layers.shape[1], p, params.stride)
    cols = patch_origins(layers.shape[2], p, params.stride)
    if rows.size == 0 or cols.size == 0:
        raise ValueError(f"stack {layers.shape[1:]} is smaller than one {p}-px patch")

    band = bandpass(layers, params.bp_fine, params.bp_coarse)
    amplitude = local_amplitude(band, params.bp_coarse if params.bp_coarse > 0 else 8.0)
    if params.normalize:
        texture = band / np.maximum(amplitude, 1e-6 * (float(np.median(amplitude)) + 1e-12))
    else:
        texture, amplitude = band, np.ones_like(band)
    tex_view = np.lib.stride_tricks.sliding_window_view(texture, (p, p), axis=(1, 2))
    amp_view = np.lib.stride_tricks.sliding_window_view(amplitude, (p, p), axis=(1, 2))

    # Depth profile E(k) = band-passed variance x mean zero-lag correlation with the neighbouring layers, from
    # window-weighted moments computed by FFT convolution (no patch copies).
    w = hann2d(p) if params.window else np.ones((p, p))
    wn = w / w.sum()

    def moment(img: np.ndarray) -> np.ndarray:
        return signal.fftconvolve(img, wn[::-1, ::-1], mode="valid")[np.ix_(rows, cols)]

    b64 = band.astype(np.float64)
    mean = np.stack([moment(b) for b in b64])
    second = np.stack([moment(b * b) for b in b64])
    cross = np.stack([moment(b64[k] * b64[k + 1]) for k in range(n_layers - 1)])
    variance = np.clip(second - mean**2, 0, None)
    covar = cross - mean[:-1] * mean[1:]
    denom = np.sqrt(variance[:-1] * variance[1:])
    rho0 = np.where(denom > 0, covar / np.where(denom > 0, denom, 1), 0.0)
    rho_layer = np.zeros_like(variance)
    count = np.zeros_like(variance)
    rho_layer[:-1] += np.clip(rho0, 0, None)
    rho_layer[1:] += np.clip(rho0, 0, None)
    count[:-1] += 1
    count[1:] += 1
    profile = variance * rho_layer / count
    # Peak from E x prior; contiguity from texture presence (smoothed band-passed variance), so a decorrelating
    # interface inside one sheet (recto/verso fibre layers) does not split the window; wraps are kept out by w_max.
    sm = params.profile_smooth
    presence = ndimage.gaussian_filter1d(variance, sm, axis=0, mode="nearest") if sm else variance
    peak_e = ndimage.gaussian_filter1d(profile, sm, axis=0, mode="nearest") if sm else profile
    in_window = depth_window(
        peak_e, k0, slice_step, params.prior_sigma, params.window_fraction, params.w_max, run_profile=presence
    )
    zwin = depth_window(profile, k0, slice_step, params.prior_sigma, params.zstar_fraction, params.zstar_wmax)
    kgrid = np.arange(n_layers, dtype=np.float64).reshape(-1, 1, 1)
    mass = np.where(zwin, profile, 0.0)
    total_mass = mass.sum(axis=0)
    kstar = np.where(total_mass > 0, (mass * kgrid).sum(axis=0) / np.where(total_mass > 0, total_mass, 1), np.nan)
    censored = zwin[0] | zwin[-1]

    if params.max_pairs is not None:
        # keep max_pairs + 1 consecutive layers of the window, centred on its middle (minimum-detectable-tilt runs)
        idx = np.arange(n_layers).reshape(-1, 1, 1)
        lo = np.where(in_window, idx, n_layers).min(axis=0)
        hi = np.where(in_window, idx, -1).max(axis=0)
        start = np.maximum(lo, (lo + hi - params.max_pairs) // 2)
        in_window = in_window & (idx >= start) & (idx <= start + params.max_pairs)
    candidate = in_window[:-1] & in_window[1:]
    kk, rr, cc = np.nonzero(candidate)
    needed = np.zeros(n_layers, dtype=bool)
    needed[np.unique(kk + 1)] = True
    tex_coef = np.zeros_like(texture)
    amp_coef = np.zeros_like(amplitude)
    if needed.any():
        tex_coef[needed] = spline_coefficients(texture[needed])
        amp_coef[needed] = spline_coefficients(amplitude[needed])
    cap = cov_cap(p)
    shape_rc = (rows.size, cols.size)
    pair_shift = np.zeros((*candidate.shape, 2))
    pair_rho = np.full(candidate.shape, np.nan)
    pair_cov = np.broadcast_to(cap * np.eye(2), (*candidate.shape, 2, 2)).copy()

    information = None
    if params.estimator == "lk":
        shift_flat, cov_flat, pc_cov, pc_rho = _estimate_lk(
            tex_view, amp_view, tex_coef, amp_coef, kk, rr, cc, rows, cols, params, shape_rc
        )
        pair_shift[kk, rr, cc] = shift_flat[rr * shape_rc[1] + cc]
        pair_rho[kk, rr, cc] = pc_rho
        pair_cov[kk, rr, cc] = pc_cov
        used = candidate & (np.nan_to_num(pair_rho, nan=-1.0) >= params.rho_min)
        valid = used.any(axis=0)
        shift = np.where(valid[..., None], shift_flat.reshape(*shape_rc, 2), 0.0)
        cov = np.where(valid[..., None, None], cov_flat.reshape(*shape_rc, 2, 2), cap * np.eye(2))
        if params.directional:
            # LK's patch shift has no along-fibre part by construction. Its sandwich covariance is what is reported.
            evals, evecs = np.linalg.eigh(cov)
            seen = evals > RANK_TOLERANCE * np.maximum(evals[..., -1:], 1e-300)
            inverse = np.where(seen, 1 / np.where(seen, evals, 1.0), 0.0)
            information = np.einsum("rcij,rcj,rckj->rcik", evecs, inverse, evecs)
            information = np.where(valid[..., None, None], information, 0.0)
            cov = np.einsum("rcij,rcj,rckj->rcik", evecs, np.where(seen, evals, cap), evecs)
        n_used = used.sum(axis=0)
        rho = np.where(valid, np.where(used, np.nan_to_num(pair_rho), 0.0).sum(axis=0) / np.maximum(n_used, 1), 0.0)
    else:
        found = _estimate_pc(tex_view, amp_view, tex_coef, amp_coef, kk, rr, cc, rows, cols, params)
        pair_shift[kk, rr, cc] = found.shift
        pair_rho[kk, rr, cc] = found.rho
        pair_cov[kk, rr, cc] = found.cov
        used = candidate & (np.nan_to_num(pair_rho, nan=-1.0) >= params.rho_min)
        weight = np.where(used, np.clip(np.nan_to_num(pair_rho), 0, None), 0.0)
        total = weight.sum(axis=0)
        valid = total > 0
        safe = np.where(valid, total, 1.0)
        if params.directional:
            shift, information, cov = directional_summary(pair_shift, pair_cov, used, params.directional_rcond, cap)
        elif params.aggregate == "information":
            info = np.where(used[..., None, None], np.linalg.inv(pair_cov), 0.0)
            cov = np.linalg.inv(info.sum(axis=0) + np.eye(2) / cap**2)
            shift = np.einsum("rcij,rcj->rci", cov, np.einsum("krcij,krcj->rci", info, pair_shift))
        else:
            shift = np.einsum("krc,krci->rci", weight, pair_shift) / safe[..., None]
            cov = np.einsum("krc,krcij->rcij", weight**2, pair_cov) / (safe**2)[..., None, None]
        shift = np.where(valid[..., None], shift, 0.0)
        cov = np.where(valid[..., None, None], cov, cap * np.eye(2))
        rho = np.where(valid, np.einsum("krc,krc->rc", weight, np.nan_to_num(pair_rho)) / safe, 0.0)

    return Field(
        params=params,
        slice_step=float(slice_step),
        k0=k0,
        centres_v=rows + (p - 1) / 2,
        centres_u=cols + (p - 1) / 2,
        profile=profile,
        variance=variance,
        rho0=rho0,
        in_window=in_window,
        pair_shift=pair_shift,
        pair_rho=pair_rho,
        pair_cov=pair_cov,
        pair_used=used,
        shift=shift,
        cov=cov,
        rho=rho,
        valid=valid,
        kstar=kstar,
        kstar_censored=censored,
        metric=_metric_at_patches(metric, layers.shape[1:], rows, cols, p),
        information=information,
    )


# ---------------------------------------------------------------------------------------------------------------
# Integration, consistency residual, curl
# ---------------------------------------------------------------------------------------------------------------


def frankot_chellappa(gv: np.ndarray, gu: np.ndarray, spacing: float = 1.0) -> np.ndarray:
    """Least-squares integrable surface from a gradient field [frankot1988], zero mean. Reference only.

    The field is mirrored to twice its size (even extension of h) so the periodic solution has no wrap-around jump.
    """
    gv = np.nan_to_num(gv)
    gu = np.nan_to_num(gu)
    ev = np.concatenate([np.concatenate([gv, gv[:, ::-1]], 1), -np.concatenate([gv, gv[:, ::-1]], 1)[::-1]], 0)
    eu = np.concatenate([np.concatenate([gu, -gu[:, ::-1]], 1), np.concatenate([gu, -gu[:, ::-1]], 1)[::-1]], 0)
    rows, cols = ev.shape
    wv = 2 * np.pi * np.fft.fftfreq(rows, d=spacing)[:, None]
    wu = 2 * np.pi * np.fft.fftfreq(cols, d=spacing)[None, :]
    denom = wu**2 + wv**2
    denom[0, 0] = 1.0
    h = (-1j * wu * np.fft.fft2(eu) - 1j * wv * np.fft.fft2(ev)) / denom
    h[0, 0] = 0
    out = np.real(np.fft.ifft2(h))[: gv.shape[0], : gv.shape[1]]
    return out - out.mean()


def screened_lsq(
    gv: np.ndarray,
    gu: np.ndarray,
    cov: np.ndarray,
    spacing: float,
    mask: np.ndarray,
    zstar: np.ndarray | None = None,
    zstar_mask: np.ndarray | None = None,
    zstar_sigma: float = 1.0,
    information: np.ndarray | None = None,
) -> np.ndarray:
    """Screened, anisotropically weighted least squares (addendum 2 item 5).

    Minimises ``sum_cells (D h - g)^T Sigma^-1 (D h - g) + sum_patches (h - z*)^2 / zstar_sigma^2``. Each cell joins
    four patch centres; its bilinear gradient is compared with the mean of the corner gradients, whitened by the
    full 2x2 covariance of that mean (the aperture direction gets little weight). Only cells whose four corners are
    in ``mask`` contribute, which gives natural Neumann boundaries on irregular masks. Without ``z*`` the result has
    zero mean. A 1e-6 relative Laplacian only removes the bilinear checkerboard null space.

    With ``information`` (rank-deficient, from a directional estimate) each cell sums its corners' information instead
    of averaging their covariances, so a direction no corner observes gets zero weight. That direction is then set
    only by neighbouring cells and the z* screening term.
    """
    rows, cols = gv.shape
    n = rows * cols
    idx = np.arange(n).reshape(rows, cols)
    gv = np.nan_to_num(gv)
    gu = np.nan_to_num(gu)
    eq_r, eq_c, eq_v, rhs = [], [], [], []
    count = 0
    if rows > 1 and cols > 1:
        cell_ok = (mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]).ravel()
        cell_g = (
            0.25
            * np.stack(
                [
                    gv[:-1, :-1] + gv[:-1, 1:] + gv[1:, :-1] + gv[1:, 1:],
                    gu[:-1, :-1] + gu[:-1, 1:] + gu[1:, :-1] + gu[1:, 1:],
                ],
                -1,
            ).reshape(-1, 2)[cell_ok]
        )
        if information is None:
            cell_cov = ((cov[:-1, :-1] + cov[:-1, 1:] + cov[1:, :-1] + cov[1:, 1:]) / 16).reshape(-1, 2, 2)[cell_ok]
            evals, evecs = np.linalg.eigh(cell_cov)
            whiten = np.einsum("nij,nj,nkj->nik", evecs, 1 / np.sqrt(np.clip(evals, 1e-12, None)), evecs)
        else:
            corners_info = [information[:-1, :-1], information[:-1, 1:], information[1:, :-1], information[1:, 1:]]
            corners_g = [
                np.stack([values[..., 0], values[..., 1]], -1)
                for values in (
                    np.stack([gv[:-1, :-1], gu[:-1, :-1]], -1),
                    np.stack([gv[:-1, 1:], gu[:-1, 1:]], -1),
                    np.stack([gv[1:, :-1], gu[1:, :-1]], -1),
                    np.stack([gv[1:, 1:], gu[1:, 1:]], -1),
                )
            ]
            cell_info = sum(corners_info).reshape(-1, 2, 2)[cell_ok]
            weighted = sum(np.einsum("rcij,rcj->rci", j, g) for j, g in zip(corners_info, corners_g, strict=True))
            evals, evecs = np.linalg.eigh(cell_info)
            evals = np.clip(evals, 0.0, None)
            inverse = np.where(evals > 1e-12 * evals[..., -1:], 1 / np.where(evals > 0, evals, 1.0), 0.0)
            pinv = np.einsum("nij,nj,nkj->nik", evecs, inverse, evecs)
            cell_g = np.einsum("nij,nj->ni", pinv, weighted.reshape(-1, 2)[cell_ok])
            whiten = np.einsum("nij,nj,nkj->nik", evecs, np.sqrt(evals), evecs)
        corners = {
            (0, 0): idx[:-1, :-1].ravel()[cell_ok],
            (0, 1): idx[:-1, 1:].ravel()[cell_ok],
            (1, 0): idx[1:, :-1].ravel()[cell_ok],
            (1, 1): idx[1:, 1:].ravel()[cell_ok],
        }
        m = int(cell_ok.sum())
        for out_axis in range(2):
            for (dv, du), corner in corners.items():
                coef_v = (0.5 if dv else -0.5) / spacing
                coef_u = (0.5 if du else -0.5) / spacing
                eq_r.append(count + np.arange(m))
                eq_c.append(corner)
                eq_v.append(whiten[:, out_axis, 0] * coef_v + whiten[:, out_axis, 1] * coef_u)
            rhs.append(whiten[:, out_axis, 0] * cell_g[:, 0] + whiten[:, out_axis, 1] * cell_g[:, 1])
            count += m
    scale = float(np.median(np.abs(np.concatenate(eq_v)))) if eq_v else 1.0
    lam = 1e-3 * scale  # sqrt(1e-6) relative
    for axis in range(2):
        if (rows, cols)[axis] < 3:
            continue
        a = idx[:-2] if axis == 0 else idx[:, :-2]
        b = idx[1:-1] if axis == 0 else idx[:, 1:-1]
        c = idx[2:] if axis == 0 else idx[:, 2:]
        m = a.size
        for corner, coef in ((a, 1.0), (b, -2.0), (c, 1.0)):
            eq_r.append(count + np.arange(m))
            eq_c.append(corner.ravel())
            eq_v.append(np.full(m, lam * coef))
        rhs.append(np.zeros(m))
        count += m
    screened = zstar is not None and zstar_mask is not None and bool(np.any(zstar_mask))
    if screened:
        sel = idx[zstar_mask]
        eq_r.append(count + np.arange(sel.size))
        eq_c.append(sel)
        eq_v.append(np.full(sel.size, 1.0 / zstar_sigma))
        rhs.append(np.asarray(zstar)[zstar_mask] / zstar_sigma)
        count += sel.size
    else:
        eq_r.append(np.full(n, count))
        eq_c.append(idx.ravel())
        eq_v.append(np.full(n, scale / n))
        rhs.append(np.zeros(1))
        count += 1
    design = sparse.csr_matrix((np.concatenate(eq_v), (np.concatenate(eq_r), np.concatenate(eq_c))), shape=(count, n))
    h = spsolve((design.T @ design).tocsc(), design.T @ np.concatenate(rhs))
    h = np.asarray(h).reshape(rows, cols)
    return h if screened else h - h.mean()


def integrate(field: Field, method: Literal["lsq", "fc"] = "lsq") -> np.ndarray:
    """``h_hat`` on the patch grid. ``lsq``: screened by z*. ``fc``: reference; constant set to the mean z* offset."""
    grad = field.grad
    if method == "fc":
        h = frankot_chellappa(grad[..., 0], grad[..., 1], field.spacing)
        ok = field.zstar_ok & field.valid
        if ok.any():
            h = h + float(np.mean(field.zstar[ok] - h[ok]))
        return h
    # Calibrated, as DR-011 item 4 requires of integration weights. The defaults kappa = 1, f = 0 reduce to grad_cov.
    return screened_lsq(
        grad[..., 0],
        grad[..., 1],
        field.calibrated_grad_cov,
        field.spacing,
        field.valid,
        field.zstar,
        field.zstar_ok,
        field.params.zstar_sigma,
        information=field.grad_information,
    )


def consistency_residual(field: Field) -> np.ndarray:
    """``r = grad z* - g`` on the patch grid, ``(R, C, 2)`` (addendum 2 item 6). Large where the sheet jumps."""
    z = np.where(field.zstar_ok, field.zstar, np.nan)
    z = np.where(np.isfinite(z), z, np.nanmean(z) if np.isfinite(z).any() else 0.0)
    dz = np.stack([np.gradient(z, field.spacing, axis=0), np.gradient(z, field.spacing, axis=1)], axis=-1)
    return dz - field.grad


def curl(gv: np.ndarray, gu: np.ndarray, spacing: float = 1.0) -> np.ndarray:
    """Curl ``d(g_u)/dv - d(g_v)/du`` (1/px). Zero for a true gradient, including along a straight step's interior."""
    return np.gradient(np.nan_to_num(gu), spacing, axis=0) - np.gradient(np.nan_to_num(gv), spacing, axis=1)


def field_curl(field: Field) -> np.ndarray:
    grad = field.grad
    return curl(grad[..., 0], grad[..., 1], field.spacing)


def patch_average(values: np.ndarray, field: Field, power: int = 2) -> np.ndarray:
    """Window-weighted mean of a per-pixel field (``(H, W)`` or ``(H, W, ...)``) over each patch, with the
    estimator's own weighting. Ground truth must be compared at this scale (addendum 2 item 8).

    Both layers of a pair are windowed, so the shift estimators weight pixels by ``hann^2`` (``power=2``, the
    default, for gradients); the depth-profile moments behind z* weight by ``hann`` (``power=1``, for h).
    """
    p = field.params.patch
    w = hann2d(p) ** power if field.params.window else np.ones((p, p))
    w = w / w.sum()
    rows = np.rint(field.centres_v - (p - 1) / 2).astype(int)
    cols = np.rint(field.centres_u - (p - 1) / 2).astype(int)
    view = np.lib.stride_tricks.sliding_window_view(values, (p, p), axis=(0, 1))[rows][:, cols]
    return np.einsum("rc...ij,ij->rc...", view, w)


# ---------------------------------------------------------------------------------------------------------------
# Sigma calibration (WO-006)
# ---------------------------------------------------------------------------------------------------------------


def calibrated_variance(variance, magnitude, kappa: float, floor: float):
    """``kappa^2 sigma^2 + (f |g|)^2``."""
    return kappa**2 * np.asarray(variance) + (floor * np.asarray(magnitude)) ** 2


def apply_calibration(cov: np.ndarray, grad: np.ndarray, kappa: float, floor: float) -> np.ndarray:
    """Calibrated covariance ``(..., 2, 2)``: the floor is isotropic, so it applies along every direction."""
    magnitude2 = np.sum(np.asarray(grad) ** 2, axis=-1)
    return kappa**2 * cov + floor**2 * magnitude2[..., None, None] * np.eye(2)


@dataclass(frozen=True)
class Calibration:
    kappa: float
    floor: float
    loss: float
    coverage: dict[str, float]


COVERAGE_Z = 1.96
COVERAGE_TARGET = 0.94  # centre of the accepted band 0.90-0.98


def stratum_coverage(error, variance, magnitude, strata, kappa: float, floor: float) -> dict[str, float]:
    """Share of 95% intervals containing the truth, per stratum."""
    inside = np.abs(error) <= COVERAGE_Z * np.sqrt(calibrated_variance(variance, magnitude, kappa, floor))
    return {str(name): float(inside[strata == name].mean()) for name in np.unique(strata)}


def calibrate(
    error: np.ndarray,
    variance: np.ndarray,
    magnitude: np.ndarray,
    strata: np.ndarray,
    kappas: np.ndarray | None = None,
    floors: np.ndarray | None = None,
) -> Calibration:
    """Fit ``kappa`` and ``f`` by grid search on a calibration split.

    Loss: the mean over strata of ``(coverage - target)^2``, where each stratum is weighted equally, so that a mode
    with many patches does not decide the fit. Ties go to the smallest intervals. ``error`` is estimate minus truth
    along the evaluated direction, ``variance`` the raw Sigma there, ``magnitude`` ``|g|``. All are 1-D and aligned.
    """
    kappas = np.arange(1.0, 6.01, 0.05) if kappas is None else np.asarray(kappas)
    floors = np.arange(0.0, 0.4001, 0.005) if floors is None else np.asarray(floors)
    error, variance, magnitude, strata = map(np.asarray, (error, variance, magnitude, strata))
    names = np.unique(strata)
    masks = [strata == name for name in names]
    abs_error = np.abs(error)
    best = (np.inf, np.inf, 1.0, 0.0)
    for kappa in kappas:
        for floor in floors:
            inside = abs_error <= COVERAGE_Z * np.sqrt(calibrated_variance(variance, magnitude, kappa, floor))
            loss = float(np.mean([(inside[mask].mean() - COVERAGE_TARGET) ** 2 for mask in masks]))
            width = float(np.mean(calibrated_variance(variance, magnitude, kappa, floor)))
            if (round(loss, 9), width) < (round(best[0], 9), best[1]):
                best = (loss, width, float(kappa), float(floor))
    loss, _, kappa, floor = best
    return Calibration(kappa, floor, loss, stratum_coverage(error, variance, magnitude, strata, kappa, floor))


# ---------------------------------------------------------------------------------------------------------------
# Decorrelation-gain diagnostic (WO-006)
# ---------------------------------------------------------------------------------------------------------------

GAIN_CLIP = (-1.0, 1.0)
R_MIN = 0.02  # correlations below this are not used in the fit of L
VOID_MARGIN = 6  # layers kept clear of the window on each side before a layer can count as void
DIRECTION_SMOOTH = 2.0  # patches: tilt direction comes from a Sigma-weighted mean over about this radius
VOID_VARIANCE = 0.5  # a void layer has less than this share of the window's mean band-passed variance


@dataclass
class GainMap:
    """Per-patch fields of :func:`gain_map`, all ``(R, C)`` unless noted."""

    length: np.ndarray  # L, through-depth correlation length, voxels; inf when r does not fall with depth
    ell_along: np.ndarray  # in-plane correlation length along the fibres, px
    ell_across: np.ndarray  # ... across the fibres, px
    fibre_angle: np.ndarray  # fibre direction, radians from +u toward +v, in [0, pi)
    gain: np.ndarray  # predicted gain along the measured tilt direction (`tilt_direction`), clipped to GAIN_CLIP
    gain_along: np.ndarray  # predicted gain for a tilt along the fibres
    gain_across: np.ndarray  # predicted gain for a tilt across the fibres
    flagged: np.ndarray  # bool: the first-order model cannot be trusted here
    lags: np.ndarray  # (M,) depth lags, voxels
    lag_r: np.ndarray  # (M, R, C) r(lag), inside the window, with the in-plane slide removed
    tensor: np.ndarray  # (R, C, 2, 2) normalised structure tensor, 1/px^2
    # From void layers, NaN if the stack has none. Volume-fixed noise appears there and material texture does not.
    noise_share: np.ndarray  # share of the window's band-passed variance that the void level explains
    length_void: np.ndarray  # L measured in the void layers, voxels
    length_material: np.ndarray  # L after subtracting the void correlation from r(lag), voxels
    shrink: np.ndarray  # noise-only gain along the measured tilt: fixed noise pulls toward zero shift, never past it
    gain_material: np.ndarray  # first-order gain from length_material, times shrink, clipped to GAIN_CLIP


def fit_depth_length(r: np.ndarray, lags: np.ndarray) -> np.ndarray:
    """L from ``r(z) = A exp(-z^2 / L^2)``, where a free A absorbs independent noise. ``r`` is ``(M, ...)``.

    A straight-line fit of log r on z^2. Infinite if r does not fall with depth, NaN with fewer than two usable lags.
    """
    x = np.asarray(lags, dtype=np.float64).reshape(-1, *([1] * (r.ndim - 1))) ** 2
    use = np.nan_to_num(r, nan=0.0) > R_MIN
    y = np.log(np.where(use, r, 1.0))
    count = use.sum(axis=0)
    mx = np.sum(x * use, axis=0) / np.maximum(count, 1)
    my = np.sum(y * use, axis=0) / np.maximum(count, 1)
    sxx = np.sum(use * (x - mx) ** 2, axis=0)
    sxy = np.sum(use * (x - mx) * (y - my), axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(sxx > 0, sxy / sxx, np.nan)
        length = np.where(slope < 0, np.sqrt(-1 / slope), np.inf)
    return np.where((count >= 2) & np.isfinite(slope), length, np.nan)


def _derivative(image: np.ndarray, axis: int) -> np.ndarray:
    """Five-point central difference; a two-point one under-reads gradients of 8-px texture by about 10%."""
    return ndimage.correlate1d(image, np.array([1, -8, 0, 8, -1]) / 12.0, axis=axis, mode="reflect")


def tilt_direction(field: Field, sigma: float = DIRECTION_SMOOTH) -> np.ndarray:
    """Unit measured tilt direction per patch, ``(R, C, 2)``.

    A single patch's g is a poor direction: noise along the fibres is large, so it swings toward the fibres even when
    the tilt runs across them (at 90 degrees that alone turned a true gain of 1 into a prediction of 0.2). Weighting g
    by its own information over neighbouring patches lets the well-measured component set the direction.
    """
    info = np.linalg.pinv(field.grad_cov) * field.valid[..., None, None]
    weighted = np.einsum("rcij,rcj->rci", info, field.grad)
    smooth = lambda values: ndimage.gaussian_filter(values, sigma, mode="nearest", axes=(0, 1))  # noqa: E731
    mean = np.einsum("rcij,rcj->rci", np.linalg.pinv(smooth(info)), smooth(weighted))
    speed = np.linalg.norm(mean, axis=-1, keepdims=True)
    return mean / np.where(speed > 0, speed, 1.0)


def gain_map(layers: np.ndarray, field: Field) -> GainMap:
    """Predict the depth-decorrelation gain per patch from the layers alone. Diagnostic only; nothing is corrected.

    Derivation. Let texture correlation be ``C(x, z) = exp(-x^T T x / 2) exp(-z^2 / L^2)``, with in-plane offset x and
    depth offset z in the sheet, where T is the normalised structure tensor ``<grad I grad I^T> / <I^2>``. For a small
    tilt along unit t, the layer pair offset by Delta along the normal has ``x = s + Delta tan(theta) t`` and
    ``z = Delta``, minus ``s . t tan(theta)``. The match s maximises C, so to first order in tan(theta)

        s = Delta tan(theta) (I - (2 / L^2) T^-1) t   (sign as for A1, where s = Delta tan(theta) t)

    The gain is therefore a tensor ``G = I - (2 / L^2) T^-1`` with the eigenvectors of T, and along t it is
    ``1 - 2 l(t)^2 / L^2`` with ``l(t)^2 = t^T T^-1 t = cos^2 l_along^2 + sin^2 l_across^2``. This corrects the 1-D form
    of the WO-002 report (section 4) only for tilts between the principal directions.
    """
    params = field.params
    p = params.patch
    rows = np.rint(field.centres_v - (p - 1) / 2).astype(int)
    cols = np.rint(field.centres_u - (p - 1) / 2).astype(int)
    w = hann2d(p) if params.window else np.ones((p, p))
    wn = (w / w.sum())[::-1, ::-1]

    def moment(image: np.ndarray) -> np.ndarray:
        return signal.fftconvolve(image, wn, mode="valid")[np.ix_(rows, cols)]

    band = bandpass(np.asarray(layers, dtype=np.float32), params.bp_fine, params.bp_coarse).astype(np.float64)
    means = np.stack([moment(b) for b in band])
    variance = np.clip(np.stack([moment(b * b) for b in band]) - means**2, 0, None)
    grad_v = [_derivative(b, 0) for b in band]
    grad_u = [_derivative(b, 1) for b in band]

    def pair_tensor(k: int) -> np.ndarray:
        """Structure moments of layers k and k + 1: independent noise averages out of a cross product."""
        vv = moment(grad_v[k] * grad_v[k + 1])
        uu = moment(grad_u[k] * grad_u[k + 1])
        vu = 0.5 * (moment(grad_v[k] * grad_u[k + 1]) + moment(grad_u[k] * grad_v[k + 1]))
        return np.stack([np.stack([vv, vu], -1), np.stack([vu, uu], -1)], -2)

    def correlations(mask: np.ndarray, steps: np.ndarray) -> np.ndarray:
        """r at each lag over layer pairs that both lie in ``mask`` ``(K, R, C)``."""
        out = np.full((steps.size, *mask.shape[1:]), np.nan)
        for index, step in enumerate(steps):
            both = mask[:-step] & mask[step:]
            cross = np.zeros(mask.shape[1:])
            scale = np.zeros(mask.shape[1:])
            for k in np.flatnonzero(both.any(axis=(1, 2))):
                covariance = moment(band[k] * band[k + step]) - means[k] * means[k + step]
                cross += both[k] * covariance
                scale += both[k] * np.sqrt(variance[k] * variance[k + step])
            with np.errstate(divide="ignore", invalid="ignore"):
                out[index] = np.where(scale > 0, cross / scale, np.nan)
        return out

    def tensor_over(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Summed structure moments over adjacent pairs in ``mask``, and the same normalised by their covariance."""
        both = mask[:-1] & mask[1:]
        moments = np.zeros((*mask.shape[1:], 2, 2))
        energy = np.zeros(mask.shape[1:])
        for k in np.flatnonzero(both.any(axis=(1, 2))):
            moments += both[k][..., None, None] * pair_tensor(k)
            energy += both[k] * (moment(band[k] * band[k + 1]) - means[k] * means[k + 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            normal = np.where((energy > 0)[..., None, None], moments / energy[..., None, None], np.nan)
        return moments, normal

    steps = np.arange(1, max(2, int(round(3 / field.slice_step))) + 1)
    lags = steps * field.slice_step
    window = field.in_window
    moments, tensor = tensor_over(window)
    tensor = np.nan_to_num(tensor)
    evals, evecs = np.linalg.eigh(tensor)  # ascending: the first eigenvector runs along the fibres
    with np.errstate(divide="ignore"):
        ell_along = np.where(evals[..., 0] > 0, 1 / np.sqrt(np.clip(evals[..., 0], 1e-12, None)), np.inf)
        ell_across = np.where(evals[..., 1] > 0, 1 / np.sqrt(np.clip(evals[..., 1], 1e-12, None)), np.inf)
    along = evecs[..., 0]  # (v, u)
    fibre_angle = np.mod(np.arctan2(along[..., 0], along[..., 1]), np.pi)

    # A tilted mesh slides texture between layers, which lowers zero-lag r without any depth decorrelation. Remove it
    # to second order: a slide d multiplies r by exp(-d^T T d / 2).
    slide = np.einsum("rci,rcij,rcj->rc", field.shift, tensor, field.shift)
    lag_r = correlations(window, steps) * np.exp(np.clip(0.5 * slide * (steps.reshape(-1, 1, 1) ** 2), 0, 1))
    length = fit_depth_length(lag_r, lags)

    direction = tilt_direction(field)
    cos2 = np.sum(direction * along, axis=-1) ** 2
    ell2 = cos2 * ell_along**2 + (1 - cos2) * ell_across**2
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = 1 - 2 * ell2 / length**2
        raw_along = 1 - 2 * ell_along**2 / length**2
        raw_across = 1 - 2 * ell_across**2 / length**2
    gain = np.clip(np.nan_to_num(raw, nan=np.nan), *GAIN_CLIP)
    flagged = (
        ~np.isfinite(raw) | (raw < GAIN_CLIP[0]) | (raw > GAIN_CLIP[1]) | (ell_along > p / 4) | ~np.isfinite(length)
    )
    flagged = flagged & ~(length == np.inf)  # L = inf is the A1 limit, a gain of exactly 1

    nans = np.full(length.shape, np.nan)
    noise_share, length_void, length_material, shrink, gain_material = nans, nans, nans, nans, nans
    near = ndimage.binary_dilation(window, structure=np.ones((2 * VOID_MARGIN + 1, 1, 1), dtype=bool))
    level = np.sum(window * variance, axis=0) / np.maximum(window.sum(axis=0), 1)
    void = ~near & (variance < VOID_VARIANCE * level)
    if void.sum(axis=0).max() >= steps.max() + 2:
        noise_share = np.sum(void * variance, axis=0) / np.maximum(void.sum(axis=0), 1) / np.maximum(level, 1e-30)
        noise_share = np.where(void.any(axis=0), np.clip(noise_share, 0, 1), np.nan)
        void_r = correlations(void, steps)
        length_void = fit_depth_length(void_r, lags)
        share = np.where(np.isfinite(noise_share), noise_share, 0.0)
        material_r = (lag_r - share * np.nan_to_num(void_r)) / np.maximum(1 - share, 1e-6)
        length_material = fit_depth_length(material_r, lags)
        void_moments, _ = tensor_over(void)
        void_pairs = np.maximum((void[:-1] & void[1:]).sum(axis=0), 1)
        window_pairs = np.maximum((window[:-1] & window[1:]).sum(axis=0), 1)
        tilt = np.einsum("rci,rcij,rcj->rc", direction, void_moments, direction) / void_pairs
        total = np.einsum("rci,rcij,rcj->rc", direction, moments, direction) / window_pairs
        with np.errstate(divide="ignore", invalid="ignore"):
            shrink = np.clip(1 - tilt / total, 0.0, 1.0)
            material = 1 - 2 * ell2 / length_material**2
        gain_material = np.clip(material * shrink, *GAIN_CLIP)
    return GainMap(
        length=length,
        ell_along=ell_along,
        ell_across=ell_across,
        fibre_angle=fibre_angle,
        gain=gain,
        gain_along=raw_along,
        gain_across=raw_across,
        flagged=flagged,
        lags=lags,
        lag_r=lag_r,
        tensor=tensor,
        noise_share=noise_share,
        length_void=length_void,
        length_material=length_material,
        shrink=shrink,
        gain_material=gain_material,
    )
