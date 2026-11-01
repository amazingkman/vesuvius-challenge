"""Synthetic generator and reference renderer: known-answer tests (WO-002 §3.4)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from vesuvius_challenge import synthetic as syn


def test_even_stacks_are_refused() -> None:
    with pytest.raises(ValueError, match="odd"):
        syn.on_surface_layer(20)
    assert syn.on_surface_layer(21) == 10


def test_renderer_is_exact_on_a_linear_volume() -> None:
    """Trilinear sampling reproduces a linear field exactly, at any position and along any normal."""
    z, y, x = np.mgrid[0:20, 0:30, 0:30].astype(np.float64)
    volume = (0.5 * z - 0.25 * y + 0.125 * x + 3).astype(np.float32)
    local = syn.tilted_points((8, 8), 12.0, 35.0)
    points = syn.place(local, 10.0, (15.0, 15.0))
    normals = syn.mesh_normals(points)
    layers = syn.render(volume, points, normals, 5, 1.5)
    for k in range(5):
        p = points + (k - 2) * 1.5 * normals
        want = 0.5 * p[..., 0] - 0.25 * p[..., 1] + 0.125 * p[..., 2] + 3
        np.testing.assert_allclose(layers[k], want, atol=1e-4)


def test_flat_mesh_on_the_voxel_grid_renders_volume_slices() -> None:
    rng = np.random.default_rng(0)
    volume = rng.random((12, 16, 16)).astype(np.float32)
    points = syn.place(syn.graph_points(np.zeros((8, 8))), 6.0, (7.5, 7.5), rotation_deg=0, subvoxel=(0, 0, 0))
    layers = syn.render(volume, points, syn.mesh_normals(points), 5, 1.0)
    for k in range(5):
        np.testing.assert_allclose(layers[k], volume[4 + k, 4:12, 4:12], atol=1e-6)


def test_normals_point_along_rising_layers() -> None:
    """VC3D convention (addendum 1 item 4): n points to rising layer index, +z for the nominal plane."""
    points = syn.place(syn.graph_points(np.zeros((5, 5))), 0.0, (0.0, 0.0))
    np.testing.assert_allclose(syn.mesh_normals(points)[..., 0], 1.0)


def test_truth_h_is_measured_along_the_mesh_normal() -> None:
    """Tilted isometric plane: grad h = tan(theta) along the azimuth, exactly; constant offset: h = c."""
    theta, azimuth = 10.0, 30.0
    points = syn.place(syn.tilted_points((40, 40), theta, azimuth), 0.0, (0.0, 0.0))
    h = syn.normal_offset(points, syn.mesh_normals(points), 0.0)
    gv, gu = np.gradient(h)
    t = np.tan(np.deg2rad(theta))
    np.testing.assert_allclose(gu[5:-5, 5:-5], t * np.cos(np.deg2rad(azimuth)), rtol=1e-6)
    np.testing.assert_allclose(gv[5:-5, 5:-5], t * np.sin(np.deg2rad(azimuth)), rtol=1e-6)
    flat = syn.place(syn.graph_points(np.full((6, 6), 4.0)), 0.0, (0.0, 0.0), subvoxel=(0, 0, 0))
    np.testing.assert_allclose(syn.normal_offset(flat, syn.mesh_normals(flat), 0.0), 4.0)


def test_metric_of_a_stretched_mesh() -> None:
    points = syn.place(syn.graph_points(np.zeros((6, 6)), stretch=(1.0, 1.1)), 0.0, (0.0, 0.0))
    g = syn.mesh_metric(points)
    np.testing.assert_allclose(g[..., 0, 0], 1.0, atol=1e-9)
    np.testing.assert_allclose(g[..., 1, 1], 1.21, atol=1e-9)


def test_texture_is_unit_variance_and_one_dimensional_when_asked() -> None:
    rng = np.random.default_rng(1)
    iso = syn.texture_2d((128, 128), syn.Texture(spread_deg=None), rng)
    assert abs(iso.std() - 1) < 1e-6
    line = syn.texture_2d((64, 64), syn.Texture(spread_deg=0, orientation_deg=0.0), rng)
    # fibres along +u: constant along each row
    assert np.abs(np.diff(line, axis=1)).max() < 1e-9


def test_realistic_mode_reproduces_wo001_correlation() -> None:
    """Addendum 1 item 1: r = 0.93 / 0.78 / 0.60 at 1 / 2 / 3 voxels, measured as WO-001 measured it."""
    sheet = syn.Sheet(snr=6.0)
    case = syn.make_case(
        np.zeros((256, 256)), syn.realistic_texture(6.0), sheet, 21, 1.0, seed=4, rotation_deg=0, subvoxel=(0, 0, 0)
    )
    r = syn.through_thickness_r(case.layers)
    for d, want in syn.MEASURED_R.items():
        assert abs(r[d] - want) < 0.04, (d, r[d], want)


def test_second_sheet_carries_independent_texture() -> None:
    sheet = syn.Sheet(snr=None, gap=10.0)
    case = syn.make_case(np.zeros((64, 64)), syn.Texture(), sheet, 61, 1.0, seed=2, rotation_deg=0, subvoxel=(0, 0, 0))
    k0 = case.k0
    first = case.layers[k0].ravel()
    second = case.layers[k0 + 30].ravel()  # 30 voxels: centre of the second sheet (20 + 10)
    assert abs(np.corrcoef(first, second)[0, 1]) < 0.2
    assert case.layers[k0 + 15].std() < 0.1 * case.layers[k0].std()  # the gap is empty


def test_texture_slides_by_tan_theta_along_plus_grad_h() -> None:
    """Sign known-answer test at the data level: I[k+1](x) = I[k](x + s), s = +tan(theta) along the tilt."""
    theta = 8.0
    case = syn.make_case(
        None,
        syn.Texture(spread_deg=None),
        syn.Sheet(snr=None, thickness=60),
        5,
        1.0,
        seed=3,
        points=syn.tilted_points((48, 96), theta, 0.0),
    )
    a, b = case.layers[2].astype(np.float64), case.layers[3].astype(np.float64)
    trials = np.linspace(-0.4, 0.4, 81)
    err = [np.mean((ndimage.shift(a, (0, -s), order=3)[8:-8, 8:-8] - b[8:-8, 8:-8]) ** 2) for s in trials]
    best = trials[int(np.argmin(err))]
    assert abs(best - np.tan(np.deg2rad(theta))) < 0.03, best
