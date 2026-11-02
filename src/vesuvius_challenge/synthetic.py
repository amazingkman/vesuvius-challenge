"""Synthetic papyrus sheets with known ground truth, for calibrating LPSF (WO-002).

Nothing here touches scroll data. Every volume is generated in-process from a seed.

Coordinates
-----------
- Volumes are indexed ``(z, y, x)``. Mesh grids are indexed ``(v, u)`` = (row, column).
- The nominal mesh is the plane ``z = z_sheet`` with ``u = x`` and ``v = y``.
- The normal **n** is the VC3D normal: the direction of rising layer index (method-lpsf §1, WO-002 addendum 4).
  For the nominal mesh it is ``+z``. Layer ``k`` samples ``p + (k - k0) * slice_step * n`` with ``k0 = (K - 1) / 2``;
  ``K`` must be odd.

Offset convention (method-lpsf rev. 2026-11-01, WO-002 addendum 2 item 1)
-----------------------------------------------------------------------
- An injected field ``h_inj(v, u)`` displaces the nominal plane by ``-h_inj`` along ``+z`` (``graph_points``), as
  WO-003 displaces vertices along their normals. Ramps use an exactly isometric tilted plane (``tilted_points``).
- The truth ``Case.h`` is the distance *along the rendered mesh normal* from the mesh point to the sheet mid-plane,
  so the sheet appears at layer ``k* = k0 + h / slice_step`` exactly, and for planar mesh and sheet the texture
  slides by ``s`` with ``g_ij s^j / slice_step = d_i h`` (``= tan(theta)`` along **t** on an isometric mesh),
  ``I[k+1](x) = I[k](x + s)``, ``s`` along ``+grad h``.

Mesh normals are recomputed from the placed grid by finite differences, as a renderer would, not taken from h.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Literal

import numpy as np
from scipy import fft as sfft
from scipy import ndimage

TextureMode = Literal["a1", "two_layer", "realistic"]
NoiseMode = Literal["white", "processed"]

# WO-001 (reports/2026-11-wo001/data-survey.md §9): Pearson r between the on-surface layer and samples d voxels
# along the normal, PHerc0139 at 2.399 µm, four segments.
MEASURED_R = {1: 0.93, 2: 0.78, 3: 0.60}

# BM18 reconstruction protocol [angelotti2026, Methods, "Phase retrieval and contrast restoration"; DR-013].
PAGANIN_DELTA_BETA = 1000.0
PAGANIN_DISTANCE_M = 0.22
PAGANIN_ENERGY_KEV = 78.0
VOXEL_UM = 2.4
UNSHARP_AMOUNT = 4.0
UNSHARP_SIGMA = 1.2
HC_KEV_M = 1.2398419843320026e-9  # h c, keV metres


# ---------------------------------------------------------------------------------------------------------------
# Texture
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Texture:
    """In-plane papyrus-like texture and how it changes through the sheet thickness.

    mode
        ``a1``: through-thickness invariant (assumption A1 holds).
        ``two_layer``: fibres along ``orientation_deg`` on the ``-n`` half of the sheet and perpendicular to it on the
        ``+n`` half (A1 violated, as in recto/verso fibre layers).
        ``realistic``: texture decorrelates through the thickness with ``r(d) = exp(-(d / corr_length) ** corr_power)``
        (addendum 1; see :func:`fit_realistic_correlation`).
    wavelength
        Dominant period across the fibres, px.
    bandwidth
        Radial spectral width as a fraction of the centre frequency.
    orientation_deg
        Fibre direction, degrees from ``+u`` toward ``+v``.
    spread_deg
        Angular spread of the spectrum around the across-fibre direction. ``None`` is isotropic; ``0`` is a 1-D
        texture (pure fibre orientation, P5).
    """

    mode: TextureMode = "a1"
    wavelength: float = 8.0
    bandwidth: float = 0.5
    orientation_deg: float = 30.0
    spread_deg: float | None = 25.0
    corr_length: float = 4.25
    corr_power: float = 2.0
    transition: float = 1.0  # two_layer: width (voxels) of the switch between fibre layers


def texture_2d(
    shape: tuple[int, int], texture: Texture, rng: np.random.Generator, orientation_deg: float | None = None
):
    """Unit-variance anisotropic band-pass noise on a ``(rows, cols)`` grid."""
    ny, nx = shape
    orientation = texture.orientation_deg if orientation_deg is None else orientation_deg
    across = np.deg2rad(orientation + 90.0)
    f0 = 1.0 / texture.wavelength
    if texture.spread_deg == 0:
        # 1-D texture: a function of the across-fibre coordinate only.
        rows, cols = np.mgrid[0:ny, 0:nx].astype(np.float64)
        coord = cols * np.cos(across) + rows * np.sin(across)
        lo, hi = coord.min() - 2, coord.max() + 2
        step = 0.25
        n = int(np.ceil((hi - lo) / step)) + 1
        freq = np.fft.rfftfreq(n, d=step)
        radial = np.exp(-0.5 * ((freq - f0) / (texture.bandwidth * f0)) ** 2)
        line = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) * radial, n=n)
        out = np.interp(coord, lo + step * np.arange(n), line)
    else:
        fy = np.fft.fftfreq(ny)[:, None]
        fx = np.fft.rfftfreq(nx)[None, :]
        f = np.hypot(fx, fy)
        weight = np.exp(-0.5 * ((f - f0) / (texture.bandwidth * f0)) ** 2)
        if texture.spread_deg is not None:
            off_axis = np.sin(np.arctan2(fy, fx) - across)
            weight = weight * np.exp(-0.5 * (off_axis / np.sin(np.deg2rad(texture.spread_deg))) ** 2)
        weight[0, 0] = 0.0
        out = np.fft.irfft2(np.fft.rfft2(rng.standard_normal(shape)) * weight, s=shape)
    out = out - out.mean()
    return out / max(out.std(), 1e-12)


def correlation_matrix(n: int, length: float, power: float) -> np.ndarray:
    """Through-thickness correlation between voxel slices: ``exp(-(|i - j| / length) ** power)``."""
    lag = np.abs(np.subtract.outer(np.arange(n), np.arange(n))).astype(np.float64)
    return np.exp(-((lag / length) ** power))


def texture_3d(shape: tuple[int, int, int], z_centre: float, texture: Texture, rng: np.random.Generator) -> np.ndarray:
    """Texture for every voxel slice of a ``(z, y, x)`` block, unit variance per slice."""
    nz, ny, nx = shape
    if texture.mode == "a1":
        return np.broadcast_to(texture_2d((ny, nx), texture, rng), shape)
    if texture.mode == "two_layer":
        first = texture_2d((ny, nx), texture, rng)
        second = texture_2d((ny, nx), texture, rng, orientation_deg=texture.orientation_deg + 90.0)
        z = np.arange(nz, dtype=np.float64)[:, None, None]
        upper = 0.5 * (1 + np.tanh((z - z_centre) / max(texture.transition, 1e-6)))
        # Independent unit-variance fields mixed with square-root weights keep unit variance.
        return np.sqrt(1 - upper) * first + np.sqrt(upper) * second
    # realistic: correlated slices via the Cholesky factor of the through-thickness correlation matrix.
    chol = np.linalg.cholesky(correlation_matrix(nz, texture.corr_length, texture.corr_power) + 1e-9 * np.eye(nz))
    fields = np.empty((nz, ny, nx), dtype=np.float32)
    for i in range(nz):
        fields[i] = texture_2d((ny, nx), texture, rng)
    chol = (chol / np.sqrt(np.sum(chol**2, axis=1))[:, None]).astype(np.float32)
    mixed = np.empty_like(fields)
    for i in range(nz):  # row by row: chol is lower triangular, and this avoids a float64 copy of the block
        mixed[i] = np.tensordot(chol[i, : i + 1], fields[: i + 1], axes=(0, 0))
    return mixed


def fit_realistic_correlation(snr: float, targets: dict[int, float] = MEASURED_R) -> tuple[float, float, float]:
    """Texture correlation ``(length, power)`` that reproduces ``targets`` on a render at this SNR.

    With voxel noise of standard deviation ``texture_std / snr``, the Pearson r a flat render measures between
    layers ``d`` apart is ``r_texture(d) * snr² / (1 + snr²)``. WO-001 measured on real data, so the targets include
    whatever noise the scan has; the fit attributes the rest to the texture. ``power`` is kept in (0, 2] so the
    correlation function stays positive definite. Returns ``(length, power, max_abs_error)``.
    """
    factor = snr**2 / (1 + snr**2)
    lags = np.array(sorted(targets), dtype=np.float64)
    want = np.array([targets[int(d)] for d in lags])
    best = (np.inf, 1.0, 1.0)
    for power in np.linspace(0.5, 2.0, 151):
        for length in np.linspace(1.0, 12.0, 551):
            got = factor * np.exp(-((lags / length) ** power))
            err = float(np.max(np.abs(got - want)))
            if err < best[0]:
                best = (err, float(length), float(power))
    return best[1], best[2], best[0]


# ---------------------------------------------------------------------------------------------------------------
# Sheet, volume and noise
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sheet:
    """Geometry and contrast of the synthetic sheet (all lengths in voxels).

    Intensity is ``background + amplitude * w(z) * (1 + contrast * tau)`` per sheet, plus noise. ``snr`` is the
    texture standard deviation at the sheet centre (``amplitude * contrast``) over the Gaussian noise standard
    deviation. ``photons``, if set, applies Poisson noise at that many counts per unit intensity first.
    ``noise`` is ``white`` (independent per voxel) or ``processed`` (:func:`processed_noise`); both are fixed in volume
    coordinates, and for both ``snr`` sets the standard deviation in the volume.
    ``gap``, if set, adds a second parallel sheet on the ``+n`` side with that many voxels between the two envelopes'
    half-maximum edges, carrying independent texture (P6).
    """

    thickness: float = 20.0
    edge: float = 1.5
    background: float = 0.1
    amplitude: float = 1.0
    contrast: float = 0.3
    snr: float | None = 6.0
    photons: float | None = None
    gap: float | None = None
    noise: NoiseMode = "white"


def envelope(distance: np.ndarray, sheet: Sheet) -> np.ndarray:
    """Thickness envelope w: flat top of FWHM ``thickness`` with tanh edges, as a function of signed distance."""
    half = sheet.thickness / 2
    return 0.5 * (np.tanh((distance + half) / sheet.edge) - np.tanh((distance - half) / sheet.edge))


def sheet_centres(z_sheet: float, sheet: Sheet) -> list[float]:
    centres = [z_sheet]
    if sheet.gap is not None:
        centres.append(z_sheet + sheet.thickness + sheet.gap)
    return centres


def paganin_length_voxels(
    delta_beta: float = PAGANIN_DELTA_BETA,
    distance_m: float = PAGANIN_DISTANCE_M,
    energy_kev: float = PAGANIN_ENERGY_KEV,
    voxel_um: float = VOXEL_UM,
) -> float:
    """The Paganin filter's characteristic length ``sqrt(z lambda (delta / beta) / (4 pi))``, in voxels (WO-006)."""
    wavelength = HC_KEV_M / energy_kev
    return float(np.sqrt(distance_m * wavelength * delta_beta / (4 * np.pi)) / (voxel_um * 1e-6))


def processing_transfer(k2: np.ndarray, length: float, amount: float, sigma: float) -> np.ndarray:
    """Paganin low-pass ``1 / (1 + l^2 k^2)`` times unsharp mask ``(1 + c) - c exp(-sigma^2 k^2 / 2)``, in k^2."""
    return ((1 + amount) - amount * np.exp(-0.5 * sigma**2 * k2)) / (1 + length**2 * k2)


def processed_noise(
    shape: tuple[int, int, int],
    rng: np.random.Generator,
    length: float | None = None,
    amount: float = UNSHARP_AMOUNT,
    sigma: float = UNSHARP_SIGMA,
) -> np.ndarray:
    """White noise through the 3-D Paganin filter and then the unsharp mask (WO-006 addendum 1). Unit variance.

    The array is the volume, so the noise is fixed in volume coordinates and does not follow the sheet.
    """
    length = paganin_length_voxels() if length is None else length
    white = rng.standard_normal(shape, dtype=np.float32)
    spectrum = sfft.rfftn(white, workers=1)  # sweeps run one case per process
    del white
    grids = [2 * np.pi * sfft.fftfreq(n).astype(np.float32) for n in shape[:-1]]
    grids.append(2 * np.pi * sfft.rfftfreq(shape[-1]).astype(np.float32))
    k2 = grids[0][:, None, None] ** 2 + grids[1][None, :, None] ** 2 + grids[2][None, None, :] ** 2
    spectrum *= processing_transfer(k2, length, amount, sigma).astype(np.float32)
    out = sfft.irfftn(spectrum, s=shape, workers=1)
    out -= out.mean()
    return (out / max(float(out.std()), 1e-12)).astype(np.float32)


def make_volume(
    shape: tuple[int, int, int], z_sheet: float, sheet: Sheet, texture: Texture, rng: np.random.Generator
) -> np.ndarray:
    """A ``(z, y, x)`` float32 volume holding one sheet (two with ``gap``) centred at ``z_sheet``."""
    nz, ny, nx = shape
    z = np.arange(nz, dtype=np.float64)
    volume = np.full(shape, sheet.background, dtype=np.float32)
    for centre in sheet_centres(z_sheet, sheet):
        w = envelope(z - centre, sheet)
        support = np.flatnonzero(w > 1e-4)
        if support.size == 0:
            continue
        lo, hi = support[0], support[-1] + 1
        tau = texture_3d((hi - lo, ny, nx), centre - lo, texture, rng)
        volume[lo:hi] += (sheet.amplitude * w[lo:hi, None, None] * (1 + sheet.contrast * tau)).astype(np.float32)
    if sheet.photons is not None:
        volume = (rng.poisson(np.clip(volume, 0, None) * sheet.photons) / sheet.photons).astype(np.float32)
    if sheet.snr is not None:
        sigma = np.float32(sheet.amplitude * sheet.contrast / sheet.snr)
        if sheet.noise == "processed":
            volume += sigma * processed_noise(shape, rng)
        else:
            for z in range(shape[0]):  # slab by slab in float32 keeps the peak memory near one volume
                volume[z] += sigma * rng.standard_normal(shape[1:], dtype=np.float32)
    return volume.astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------
# Offset fields h(v, u)
# ---------------------------------------------------------------------------------------------------------------


def _grid(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, float, float]:
    v, u = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float64)
    return v, u, (shape[0] - 1) / 2, (shape[1] - 1) / 2


def offset_constant(shape: tuple[int, int], value: float) -> np.ndarray:
    return np.full(shape, float(value))


def offset_ramp(shape: tuple[int, int], theta_deg: float, azimuth_deg: float = 0.0) -> np.ndarray:
    """Planar tilt by ``theta_deg``; ``grad h`` along ``azimuth_deg`` (from +u toward +v); h = 0 at the centre."""
    v, u, vc, uc = _grid(shape)
    a = np.deg2rad(azimuth_deg)
    return np.tan(np.deg2rad(theta_deg)) * ((u - uc) * np.cos(a) + (v - vc) * np.sin(a))


def offset_bump(shape: tuple[int, int], amplitude: float, fwhm: float, centre: tuple[float, float] | None = None):
    """Gaussian bump of peak ``amplitude`` voxels and full width at half maximum ``fwhm`` px."""
    v, u, vc, uc = _grid(shape)
    if centre is not None:
        vc, uc = centre
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    return amplitude * np.exp(-((u - uc) ** 2 + (v - vc) ** 2) / (2 * sigma**2))


def offset_sinusoid(shape: tuple[int, int], amplitude: float, wavelength: float, azimuth_deg: float = 0.0):
    """Corrugation ``amplitude * sin(2 pi d / wavelength)`` along ``azimuth_deg`` (WO-003's perturbation shape)."""
    v, u, vc, uc = _grid(shape)
    a = np.deg2rad(azimuth_deg)
    d = (u - uc) * np.cos(a) + (v - vc) * np.sin(a)
    return amplitude * np.sin(2 * np.pi * d / wavelength)


def step_distance(shape: tuple[int, int], angle_deg: float = 20.0, offset: float = 0.0) -> np.ndarray:
    """Signed distance (px) to a straight line through the centre (+ ``offset``) whose normal is at ``angle_deg``."""
    v, u, vc, uc = _grid(shape)
    a = np.deg2rad(angle_deg)
    return (u - uc) * np.cos(a) + (v - vc) * np.sin(a) - offset


def offset_step(
    shape: tuple[int, int], amplitude: float, angle_deg: float = 20.0, width: float = 2.0, offset: float = 0.0
) -> np.ndarray:
    """A step of ``amplitude`` voxels across a straight line, smoothed over ``width`` px (a sheet jump)."""
    d = step_distance(shape, angle_deg, offset)
    return amplitude * 0.5 * (1 + np.tanh(d / max(width / 2, 1e-6)))


# ---------------------------------------------------------------------------------------------------------------
# Mesh and reference renderer
# ---------------------------------------------------------------------------------------------------------------


# A generic placement of the mesh grid in the voxel grid. Real meshes are oblique to the voxel axes, so the sub-voxel
# phase of trilinear sampling varies from pixel to pixel. An axis-aligned grid at integer positions makes that phase
# constant over a patch, and trilinear interpolation then biases measured shifts toward whole voxels coherently
# (pixel locking). ``rotation_deg=0, subvoxel=(0, 0, 0)`` reproduces that worst case on purpose.
GENERIC_ROTATION_DEG = 23.7
GENERIC_SUBVOXEL = (0.29, 0.37, 0.61)


def graph_points(h: np.ndarray, stretch: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
    """Local mesh points ``(v, u, 3)`` = ``(z, y, x)`` relative to the sheet mid-plane: the nominal plane displaced
    by ``-h`` along ``+z``. ``stretch`` scales the grid spacing along ``(v, u)``: 1 is isometric, ``1 + eps`` is a
    stretched (non-isometric) parameterisation (addendum 2 item 1)."""
    v, u = np.mgrid[0 : h.shape[0], 0 : h.shape[1]].astype(np.float64)
    vc, uc = (h.shape[0] - 1) / 2, (h.shape[1] - 1) / 2
    return np.stack([-np.asarray(h, dtype=np.float64), (v - vc) * stretch[0], (u - uc) * stretch[1]], axis=-1)


def tilted_points(shape: tuple[int, int], theta_deg: float, azimuth_deg: float = 0.0) -> np.ndarray:
    """Local points of an *isometric* plane tilted by ``theta_deg`` against the sheet, crossing it at the centre.

    ``grad h`` (h along the mesh normal) is ``tan(theta)`` along the azimuth, exactly, in pixel units.
    """
    v, u = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float64)
    vc, uc = (shape[0] - 1) / 2, (shape[1] - 1) / 2
    th, a = np.deg2rad(theta_deg), np.deg2rad(azimuth_deg)
    along = (u - uc) * np.cos(a) + (v - vc) * np.sin(a)
    across = -(u - uc) * np.sin(a) + (v - vc) * np.cos(a)
    e_t = np.array([-np.sin(th), np.cos(th) * np.sin(a), np.cos(th) * np.cos(a)])  # (z, y, x)
    e_p = np.array([0.0, np.cos(a), -np.sin(a)])
    return along[..., None] * e_t + across[..., None] * e_p


def place(
    local: np.ndarray,
    z_sheet: float,
    origin: tuple[float, float],
    rotation_deg: float = GENERIC_ROTATION_DEG,
    subvoxel: tuple[float, float, float] = GENERIC_SUBVOXEL,
) -> np.ndarray:
    """Local points into volume coordinates: rotate in-plane about the grid centre, then translate.

    The sheet is z-invariant in-plane, so the rotation and sub-voxel offset change nothing but the sampling phase.
    """
    a = np.deg2rad(rotation_deg)
    z, y, x = local[..., 0], local[..., 1], local[..., 2]
    yr = x * np.sin(a) + y * np.cos(a)
    xr = x * np.cos(a) - y * np.sin(a)
    return np.stack([z_sheet + z + subvoxel[0], origin[0] + yr + subvoxel[1], origin[1] + xr + subvoxel[2]], axis=-1)


def graph_mesh(
    h: np.ndarray,
    z_sheet: float,
    origin: tuple[float, float] = (0.0, 0.0),
    rotation_deg: float = GENERIC_ROTATION_DEG,
    subvoxel: tuple[float, float, float] = GENERIC_SUBVOXEL,
) -> np.ndarray:
    """Mesh points ``(v, u, 3)`` in volume coordinates for a nominal plane displaced by ``-h`` (grid centre at
    ``origin``)."""
    return place(graph_points(h), z_sheet, origin, rotation_deg, subvoxel)


def mesh_normals(points: np.ndarray) -> np.ndarray:
    """Unit normals from grid finite differences, oriented toward ``+z`` (the VC3D layer direction here)."""
    d_v = np.gradient(points, axis=0)
    d_u = np.gradient(points, axis=1)
    # (z, y, x) components; cross product in (x, y, z) order, then reorder.
    n = np.cross(d_u[..., ::-1], d_v[..., ::-1])[..., ::-1]
    n = n / np.linalg.norm(n, axis=-1, keepdims=True)
    return np.where(n[..., :1] < 0, -n, n)


def mesh_metric(points: np.ndarray) -> np.ndarray:
    """``g_ij = d_i p . d_j p`` over ``(v, u)``, shape ``(v, u, 2, 2)``."""
    tangents = np.stack([np.gradient(points, axis=0), np.gradient(points, axis=1)], axis=-2)
    return np.einsum("...ia,...ja->...ij", tangents, tangents)


def normal_offset(points: np.ndarray, normals: np.ndarray, z_sheet: float) -> np.ndarray:
    """Truth h: distance along each mesh normal from the mesh point to the sheet mid-plane ``z = z_sheet``."""
    return (z_sheet - points[..., 0]) / normals[..., 0]


def on_surface_layer(num_slices: int) -> int:
    if num_slices % 2 == 0 or num_slices < 1:
        raise ValueError(f"num_slices must be odd and positive (WO-002 addendum 1 item 4), got {num_slices}")
    return (num_slices - 1) // 2


def render(
    volume: np.ndarray, points: np.ndarray, normals: np.ndarray, num_slices: int, slice_step: float
) -> np.ndarray:
    """Reference renderer: trilinear samples at ``p + (k - k0) * slice_step * n``. Returns ``(K, v, u)`` float32.

    Synthetic tests only. Real renders come from ``vc_render_tifxyz``.
    """
    k0 = on_surface_layer(num_slices)
    out = np.empty((num_slices, *points.shape[:2]), dtype=np.float32)
    for k in range(num_slices):
        coords = points + (k - k0) * slice_step * normals
        out[k] = ndimage.map_coordinates(volume, np.moveaxis(coords, -1, 0), order=1, mode="nearest")
    return out


# ---------------------------------------------------------------------------------------------------------------
# Whole cases
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class Case:
    """A rendered synthetic stack and its ground truth."""

    layers: np.ndarray  # (K, v, u)
    h: np.ndarray  # (v, u) truth: distance along the mesh normal from mesh to sheet mid-plane, voxels
    metric: np.ndarray  # (v, u, 2, 2) mesh metric g_ij
    slice_step: float
    texture: Texture
    sheet: Sheet
    volume_shape: tuple[int, int, int]
    extra: dict = field(default_factory=dict)

    @property
    def k0(self) -> int:
        return on_surface_layer(self.layers.shape[0])

    @property
    def grad_h(self) -> np.ndarray:
        """Covariant gradient of the truth h per pixel, ``(v, u, 2)``."""
        return np.stack([np.gradient(self.h, axis=0), np.gradient(self.h, axis=1)], axis=-1)

    def describe(self) -> dict:
        return {
            "texture": asdict(self.texture),
            "sheet": asdict(self.sheet),
            "num_slices": int(self.layers.shape[0]),
            "slice_step": self.slice_step,
            "volume_shape": list(self.volume_shape),
        }


def make_case(
    h: np.ndarray | None,
    texture: Texture,
    sheet: Sheet,
    num_slices: int = 21,
    slice_step: float = 1.0,
    seed: int | np.random.Generator = 0,
    rotation_deg: float = GENERIC_ROTATION_DEG,
    subvoxel: tuple[float, float, float] = GENERIC_SUBVOXEL,
    points: np.ndarray | None = None,
    stretch: tuple[float, float] = (1.0, 1.0),
) -> Case:
    """Build the volume a mesh needs, render it, and keep the truth.

    The mesh is either the nominal plane displaced by ``h`` along its nominal normal (``graph_points``, optionally
    stretched), or explicit local ``points`` (e.g. ``tilted_points``). The truth ``Case.h`` is always the distance
    along the rendered mesh normal to the sheet mid-plane, which is what LPSF measures.
    """
    rng = seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)
    local = points if points is not None else graph_points(np.asarray(h, dtype=np.float64), stretch)
    reach = (num_slices - 1) / 2 * slice_step
    rows, cols = local.shape[:2]
    span_y = np.ptp(local[..., 1]) if rows > 1 else 0.0
    span_x = np.ptp(local[..., 2]) if cols > 1 else 0.0
    half = int(np.ceil(np.hypot(span_y, span_x) / 2)) + int(np.ceil(reach)) + 4
    second = sheet.thickness + (sheet.gap or 0.0) if sheet.gap is not None else 0.0
    z_lo = min(float(local[..., 0].min()) - reach - 3, -sheet.thickness / 2 - 4 * sheet.edge)
    z_hi = max(float(local[..., 0].max()) + reach + 3, second + sheet.thickness / 2 + 4 * sheet.edge)
    z0 = int(np.floor(z_lo))
    nz = int(np.ceil(z_hi)) - z0 + 1
    z_sheet = float(-z0)
    shape = (nz, 2 * half + 1, 2 * half + 1)
    volume = make_volume(shape, z_sheet, sheet, texture, rng)
    placed = place(local, z_sheet, (float(half), float(half)), rotation_deg, subvoxel)
    normals = mesh_normals(placed)
    layers = render(volume, placed, normals, num_slices, slice_step)
    return Case(
        layers=layers,
        h=normal_offset(placed, normals, z_sheet),
        metric=mesh_metric(placed),
        slice_step=slice_step,
        texture=texture,
        sheet=sheet,
        volume_shape=shape,
    )


def through_thickness_r(layers: np.ndarray, max_lag: int = 3) -> dict[int, float]:
    """Pearson r between the on-surface layer and layers ±d away, averaged over both sides (WO-001's measure)."""
    k0 = on_surface_layer(layers.shape[0])
    centre = layers[k0].ravel().astype(np.float64)
    out = {}
    for d in range(1, max_lag + 1):
        rs = [float(np.corrcoef(centre, layers[k0 + sign * d].ravel())[0, 1]) for sign in (1, -1)]
        out[d] = float(np.mean(rs))
    return out


def realistic_texture(snr: float = 6.0, **overrides) -> Texture:
    """The addendum-1 texture: through-thickness correlation fitted to WO-001's r at this SNR."""
    length, power, _ = fit_realistic_correlation(snr)
    return replace(Texture(mode="realistic", corr_length=length, corr_power=power), **overrides)
