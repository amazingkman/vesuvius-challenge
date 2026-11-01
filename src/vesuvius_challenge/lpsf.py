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
    kappa: float = 1.0  # covariance calibration factor
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
        info_sum = np.zeros((n_rc, 2, 2))
        rhs_sum = np.zeros((n_rc, 2))
        np.add.at(info_sum, patch_id, info)
        np.add.at(rhs_sum, patch_id, rhs)
        ridge = 1e-9 * np.trace(info_sum, axis1=1, axis2=2)[:, None, None] * np.eye(2) + 1e-12 * np.eye(2)
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
        if params.aggregate == "information":
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
) -> np.ndarray:
    """Screened, anisotropically weighted least squares (addendum 2 item 5).

    Minimises ``sum_cells (D h - g)^T Sigma^-1 (D h - g) + sum_patches (h - z*)^2 / zstar_sigma^2``. Each cell joins
    four patch centres; its bilinear gradient is compared with the mean of the corner gradients, whitened by the
    full 2x2 covariance of that mean (the aperture direction gets little weight). Only cells whose four corners are
    in ``mask`` contribute, which gives natural Neumann boundaries on irregular masks. Without ``z*`` the result has
    zero mean. A 1e-6 relative Laplacian only removes the bilinear checkerboard null space.
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
        cell_cov = ((cov[:-1, :-1] + cov[:-1, 1:] + cov[1:, :-1] + cov[1:, 1:]) / 16).reshape(-1, 2, 2)[cell_ok]
        evals, evecs = np.linalg.eigh(cell_cov)
        whiten = np.einsum("nij,nj,nkj->nik", evecs, 1 / np.sqrt(np.clip(evals, 1e-12, None)), evecs)
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
    return screened_lsq(
        grad[..., 0],
        grad[..., 1],
        field.grad_cov,
        field.spacing,
        field.valid,
        field.zstar,
        field.zstar_ok,
        field.params.zstar_sigma,
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
