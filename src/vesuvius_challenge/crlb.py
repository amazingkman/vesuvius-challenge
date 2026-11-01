"""Cramér–Rao bound for the inter-layer shift of a synthetic configuration (WO-002 addendum 2 item 3).

Derived here, not taken from a source; the general setting (registration bounds) is [robinson2004].

Model. Two adjacent layers of one patch are jointly Gaussian and stationary. Each is texture plus noise; the texture
of layer k+1 is that of layer k shifted by s and correlated with it by r (the through-thickness correlation at the
slice step). Per frequency f the coherence is

    gamma(f) = r * P_t(f) / (P_t(f) + P_n(f))

and the Fisher information for s, summed over the patch's DFT bins, is

    J = (N_eff / N^2) * sum_f (2 pi f)(2 pi f)^T * gamma^2 / (1 - gamma^2)

(the 2-D form of the classical time-delay bound for two partially coherent signals). ``N_eff / N^2`` accounts for
the Hann window's loss of effective samples. Inputs come straight from the generator:

- ``P_t``: the generator's spectral weight squared, scaled to the texture variance ``(amplitude * contrast)^2``;
- ``P_n``: voxel noise ``sigma^2`` after trilinear interpolation at generic phases, which multiplies it by
  ``(2 + cos 2 pi f)/3`` per in-plane axis and ``2/3`` along depth;
- ``r``: 1 in A1 mode, ``exp(-(slice_step / L)^p)`` in realistic mode.

Not included, so the bound is optimistic where they matter: noise shared between layers through common
interpolation voxels (``slice_step < 2``), the sheet envelope, and anything a tilt does to the sampling. The bound
for an aggregate over n pairs is quoted as ``J * n`` (independent pairs), which is an approximation, not a bound.
"""

from __future__ import annotations

import numpy as np

from vesuvius_challenge.lpsf import hann2d
from vesuvius_challenge.synthetic import Sheet, Texture


def texture_spectrum(texture: Texture, patch: int) -> np.ndarray:
    """Power spectrum of the generator's in-plane texture on a ``patch`` DFT grid, mean 1 over the bins."""
    f = np.fft.fftfreq(patch)
    fy, fx = f[:, None], f[None, :]
    radius = np.hypot(fx, fy)
    f0 = 1.0 / texture.wavelength
    weight = np.exp(-0.5 * ((radius - f0) / (texture.bandwidth * f0)) ** 2)
    if texture.spread_deg is not None:
        across = np.deg2rad(texture.orientation_deg + 90.0)
        spread = max(texture.spread_deg, 0.5)  # a 1-D texture is a spread -> 0 limit
        off_axis = np.sin(np.arctan2(fy, fx) - across)
        weight = weight * np.exp(-0.5 * (off_axis / np.sin(np.deg2rad(spread))) ** 2)
    weight[0, 0] = 0.0
    power = weight**2
    return power / power.mean()


def noise_spectrum(patch: int) -> np.ndarray:
    """Spectrum of trilinear-interpolated unit white noise on a ``patch`` DFT grid (mean = (2/3)^3)."""
    f = np.fft.fftfreq(patch)
    axis = (2 + np.cos(2 * np.pi * f)) / 3
    return (2 / 3) * axis[:, None] * axis[None, :]


def layer_correlation(texture: Texture, slice_step: float) -> float:
    if texture.mode == "a1":
        return 1.0
    if texture.mode == "realistic":
        return float(np.exp(-((slice_step / texture.corr_length) ** texture.corr_power)))
    return float("nan")  # two_layer: no single r


def fisher_pair(texture: Texture, sheet: Sheet, slice_step: float, patch: int, window: bool = True) -> np.ndarray:
    """Fisher information (1/px^2) for the shift of one adjacent pair of one patch, 2x2 in (v, u)."""
    r = layer_correlation(texture, slice_step)
    if not np.isfinite(r):
        return np.full((2, 2), np.nan)
    signal_var = (sheet.amplitude * sheet.contrast) ** 2
    pt = signal_var * texture_spectrum(texture, patch)
    noise_var = 0.0 if sheet.snr is None else (sheet.amplitude * sheet.contrast / sheet.snr) ** 2
    pn = noise_var * noise_spectrum(patch)
    with np.errstate(divide="ignore", invalid="ignore"):
        gamma = np.where(pt + pn > 0, r * pt / (pt + pn), 0.0)
    gamma2 = np.clip(gamma**2, 0, 1 - 1e-12)
    weight = gamma2 / (1 - gamma2)
    f = np.fft.fftfreq(patch)
    fy, fx = np.meshgrid(f, f, indexing="ij")
    k = np.stack([2 * np.pi * fy, 2 * np.pi * fx], axis=-1)
    info = np.einsum("ija,ijb,ij->ab", k, k, weight)
    if window:
        w = hann2d(patch)
        info = info * (w.sum() ** 2 / np.sum(w**2)) / patch**2
    return info


def crlb_pair(texture: Texture, sheet: Sheet, slice_step: float, patch: int, direction_deg: float = 0.0) -> float:
    """Lower bound on the variance (px^2) of one pair's shift along ``direction_deg`` (from +u toward +v)."""
    info = fisher_pair(texture, sheet, slice_step, patch)
    if not np.all(np.isfinite(info)):
        return float("nan")
    a = np.deg2rad(direction_deg)
    t = np.array([np.sin(a), np.cos(a)])  # (v, u)
    return float(t @ np.linalg.pinv(info) @ t)


def fisher_stack(
    texture: Texture, sheet: Sheet, slice_step: float, patch: int, n_layers: int, window: bool = True
) -> np.ndarray:
    """Fisher information (1/px^2) for a common per-layer shift s seen in ``n_layers`` consecutive layers.

    Per frequency the layers' cross-spectral matrix is ``C = P_t * R o exp(2 pi i f.s (k - j)) + P_n * I`` with
    ``R_kj`` the through-thickness correlation at ``|k - j| * slice_step``; for a real field
    ``J_ab = 1/2 sum_f tr(C^-1 dC/ds_a C^-1 dC/ds_b)``. With two layers this equals :func:`fisher_pair`. Assumes
    independent noise per layer (see the module note).
    """
    if texture.mode == "two_layer":
        return np.full((2, 2), np.nan)
    signal_var = (sheet.amplitude * sheet.contrast) ** 2
    pt = (signal_var * texture_spectrum(texture, patch)).ravel()
    noise_var = 0.0 if sheet.snr is None else (sheet.amplitude * sheet.contrast / sheet.snr) ** 2
    pn = (noise_var * noise_spectrum(patch)).ravel() + 1e-12 * signal_var
    k = np.arange(n_layers)
    lag = np.abs(k[:, None] - k[None, :]) * slice_step
    if texture.mode == "a1":
        r = np.ones_like(lag)
    else:
        r = np.exp(-((lag / texture.corr_length) ** texture.corr_power))
    diff = (k[:, None] - k[None, :]).astype(np.float64)
    f = np.fft.fftfreq(patch)
    fy, fx = np.meshgrid(f, f, indexing="ij")
    freqs = np.stack([fy.ravel(), fx.ravel()], axis=-1)  # (F, 2)
    keep = pt > 1e-9 * pt.max()
    pt, pn, freqs = pt[keep], pn[keep], freqs[keep]
    cov = pt[:, None, None] * r[None] + pn[:, None, None] * np.eye(n_layers)[None]
    inv = np.linalg.inv(cov)
    base = pt[:, None, None] * r[None] * diff[None]  # dC/ds_a = i 2 pi f_a * base
    m = inv @ base  # (F, n, n); C^-1 dC_a = i 2 pi f_a m
    tr = np.einsum("fij,fji->f", m, m).real  # tr(m m); the i^2 gives a minus sign
    info = 0.5 * np.einsum("fa,fb,f->ab", 2 * np.pi * freqs, 2 * np.pi * freqs, -tr)
    if window:
        w = hann2d(patch)
        info = info * (w.sum() ** 2 / np.sum(w**2)) / patch**2
    return info


def crlb_stack(
    texture: Texture, sheet: Sheet, slice_step: float, patch: int, n_layers: int, direction_deg: float = 0.0
) -> float:
    """Lower bound on the variance (px^2) of the common shift along ``direction_deg`` from ``n_layers`` layers."""
    info = fisher_stack(texture, sheet, slice_step, patch, n_layers)
    if not np.all(np.isfinite(info)):
        return float("nan")
    a = np.deg2rad(direction_deg)
    t = np.array([np.sin(a), np.cos(a)])
    return float(t @ np.linalg.pinv(info) @ t)
