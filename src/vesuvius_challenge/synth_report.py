"""Figures, acceptance verdicts and a markdown summary from a saved `vch synth run` (no estimator runs here).

Every number in the output is computed from ``cases.parquet``, ``details-*.parquet`` and ``run.json``.
Figures show synthetic statistics only (DR-008 allows them; no render-derived images).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from vesuvius_challenge.security import FIGURE_METADATA  # noqa: E402

# Reference categorical palette (dataviz skill, light mode), fixed order; text stays in text ink.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
MARKERS = ["o", "s", "^", "D", "v", "P"]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "lines.linewidth": 2,
        "lines.markersize": 6,
        "font.size": 9,
        "legend.frameon": False,
    }
)

SLOPE_TOL = 0.05


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, index=df.index)


def _has(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].notna() if col in df else pd.Series(False, index=df.index)


def blocks(cases: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Recover the sweep blocks of configs/synth/wo002.toml from which keys each case set."""
    ok = cases[cases["status"] == "ok"]
    tilt = ok[ok["experiment"] == "tilt"]
    bump = ok[ok["experiment"] == "bump"]
    return {
        "p1p2": tilt[_has(tilt, "slice_step")],
        "mdt": tilt[_has(tilt, "max_pairs")],
        "envelope": tilt[_has(tilt, "spread_deg")],
        "thickness": tilt[_has(tilt, "thickness")],
        "patch": tilt[_has(tilt, "patch") & ~_has(tilt, "max_pairs") & ~_has(tilt, "slice_step")],
        "beta": tilt[_has(tilt, "beta")],
        "bump": bump[_has(bump, "fwhm_patches")],
        "bump_patch": bump[_has(bump, "fwhm_px") & ~_has(bump, "overlap")],
        "bump_overlap": bump[_has(bump, "overlap")],
        "offset": ok[ok["experiment"] == "offset"],
        "step": ok[ok["experiment"] == "step"],
        "sinusoid": ok[ok["experiment"] == "sinusoid"],
        "stretch": ok[ok["experiment"] == "stretch"],
        "layers": ok[ok["experiment"] == "layers"],
        "aperture": ok[ok["experiment"] == "aperture"],
        "crosscheck": ok[ok["experiment"] == "crosscheck"],
    }


def fit_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """OLS slope and intercept."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    keep = np.isfinite(x) & np.isfinite(y)
    if keep.sum() < 2:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(x[keep], y[keep], 1)
    return float(slope), float(intercept)


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3g}") -> str:
    if df.empty:
        return "_(no rows)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            cells.append(floatfmt.format(v) if isinstance(v, float | np.floating) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata=FIGURE_METADATA)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------------------------------------------


def p1p2(b: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, Path | None]:
    if b.empty:
        return pd.DataFrame(), None
    b = b.assign(theta=_num(b, "theta_deg"), dd=_num(b, "slice_step"), snr_=_num(b, "snr"))
    rows = []
    for (est, tex, dd, snr), g in b.groupby(["estimator", "texture", "dd", "snr_"]):
        sel = g[g["theta"] <= 20]
        slope, icpt = fit_slope(sel["truth_window"], sel["g_par_mean"])
        null = g[g["theta"] == 0]
        rows.append(
            {
                "estimator": est,
                "texture": tex,
                "slice_step": dd,
                "snr": snr,
                "slope_theta_le_20": slope,
                "intercept": icpt,
                "slope_ok": abs(slope - 1) <= SLOPE_TOL,
                "ratio_at_30": float((g[g["theta"] == 30]["g_par_mean"] / g[g["theta"] == 30]["truth_window"]).mean()),
                "null_shift_px": float((null["g_par_mean"].abs() * null["dd"]).mean()),
            }
        )
    table = pd.DataFrame(rows)
    textures = list(dict.fromkeys(b["texture"]))
    fig, axes = plt.subplots(2, len(textures), figsize=(3.6 * len(textures), 6.4), sharex=True, squeeze=False)
    for j, tex in enumerate(textures):
        for i, est in enumerate(["pc", "lk"]):
            ax = axes[i, j]
            sub = b[(b["texture"] == tex) & (b["estimator"] == est) & (b["snr_"] == 6)]
            lim = np.tan(np.deg2rad(30)) * 1.05
            ax.plot([0, lim], [0, lim], color=MUTED, lw=1, ls="--", label="identity")
            for k, dd in enumerate(sorted(sub["dd"].unique())):
                s = sub[sub["dd"] == dd].sort_values("theta")
                ax.plot(s["truth_window"], s["g_par_mean"], marker=MARKERS[k], color=SERIES[k], label=f"Δd = {dd:g}")
            ax.set_title(f"{tex}, {'phase corr.' if est == 'pc' else 'Lucas–Kanade'}, SNR 6", fontsize=9)
            ax.set_ylim(-0.4, 0.75)
            if i == 1:
                ax.set_xlabel("window-averaged tan θ (truth)")
            if j == 0:
                ax.set_ylabel("estimated (s·t)/Δd, metric-corrected")
    axes[0, 0].legend(loc="upper left")
    return table, _save(fig, out / "fig1-p1p2-slope.png")


def mdt(b: pd.DataFrame, details: pd.DataFrame | None, out: Path) -> tuple[pd.DataFrame, Path | None]:
    if b.empty or details is None:
        return pd.DataFrame(), None
    d = details.merge(b[["case_id", "estimator", "texture", "theta_deg", "max_pairs"]], on="case_id")
    d = d[d["valid"].astype(bool)]
    d["mag"] = np.hypot(d["g_par"], d["g_perp"])
    rows = []
    curves = {}
    for (est, tex, mp), g in d.groupby(["estimator", "texture", "max_pairs"]):
        null = g[g["theta_deg"] == 0]
        t_mag = float(np.quantile(null["mag"], 0.95))
        t_par = float(np.quantile(null["g_par"], 0.95))
        thetas = sorted(g["theta_deg"].unique())
        p_mag = [float((g[g["theta_deg"] == t]["mag"] > t_mag).mean()) for t in thetas]
        p_par = [float((g[g["theta_deg"] == t]["g_par"] > t_par).mean()) for t in thetas]

        def cross(power, thetas=thetas):
            for t0, t1, a, c in zip(thetas[:-1], thetas[1:], power[:-1], power[1:], strict=True):
                if a < 0.8 <= c:
                    return t0 + (0.8 - a) * (t1 - t0) / (c - a)
            return 0.0 if power and power[0] >= 0.8 else float("nan")

        label = "single pair" if int(mp) == 1 else "window (all pairs)"
        rows.append(
            {
                "estimator": est,
                "texture": tex,
                "pairs": label,
                "null_sd_g": float(null["g_par"].std()),
                "n_null_patches": len(null),
                "MDT_deg_unknown_direction": cross(p_mag),
                "MDT_deg_known_direction": cross(p_par),
            }
        )
        curves[(est, tex, label)] = (thetas, p_mag)
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, tex in zip(axes, ["a1", "realistic"], strict=True):
        k = 0
        for (est, t, label), (th, pw) in curves.items():
            if t != tex:
                continue
            ax.plot(th, pw, marker=MARKERS[k], color=SERIES[k], label=f"{est}, {label}")
            k += 1
        ax.axhline(0.8, color=MUTED, lw=1, ls="--")
        ax.set_title(f"{tex}, SNR 6, Δd = 1", fontsize=9)
        ax.set_xlabel("true tilt θ (degrees)")
    axes[0].set_ylabel("detection power at 5% false alarms (|g|)")
    axes[0].legend(loc="lower right", fontsize=7)
    return pd.DataFrame(rows), _save(fig, out / "fig2-min-detectable-tilt.png")


def bumps(b: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, Path | None]:
    if b.empty:
        return pd.DataFrame(), None
    b = b.assign(amp=_num(b, "amplitude"), width=_num(b, "fwhm_patches"))
    table = b[["estimator", "texture", "amp", "width", "rmse_lsq", "rmse_fc", "rmse_zstar", "shape_rmse_lsq"]]
    table = table.sort_values(["texture", "estimator", "width", "amp"]).reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, tex in zip(axes, ["a1", "realistic"], strict=True):
        sub = b[(b["texture"] == tex) & (b["estimator"] == "pc")]
        for k, w in enumerate(sorted(sub["width"].unique())):
            s = sub[sub["width"] == w].sort_values("amp")
            ax.plot(s["amp"], s["rmse_lsq"], marker=MARKERS[k], color=SERIES[k], label=f"h_hat, FWHM {w:g} patches")
            ax.plot(
                s["amp"],
                s["rmse_zstar"],
                marker=MARKERS[k],
                color=SERIES[k],
                ls=":",
                alpha=0.8,
                label=f"z* only, FWHM {w:g}",
            )
        ax.axhline(0.5, color=MUTED, lw=1, ls="--")
        ax.set_title(f"{tex}, phase corr., SNR 6", fontsize=9)
        ax.set_xlabel("bump amplitude (voxels)")
    axes[0].set_ylabel("RMSE vs window-averaged h (voxels)")
    axes[0].legend(fontsize=7)
    return table, _save(fig, out / "fig3-offset-recovery.png")


def steps(b: pd.DataFrame, details: pd.DataFrame | None, out: Path) -> tuple[pd.DataFrame, Path | None]:
    if b.empty:
        return pd.DataFrame(), None
    b = b.assign(amp=_num(b, "amplitude"))
    scores = ["residual", "curl", "grad_hhat", "grad_zstar"]
    agg = b.groupby(["estimator", "texture", "amp"])[[f"auroc_{s}" for s in scores]].mean().reset_index()
    # curl null from the amplitude-0 cases (Monte Carlo on the same patch layout)
    curl_null = {}
    if details is not None:
        d = details.merge(b[["case_id", "estimator", "texture", "amp"]], on="case_id")
        for (est, tex), g in d.groupby(["estimator", "texture"]):
            null = g[g["amp"] == 0]["curl"]
            q = float(np.quantile(null, 0.95)) if len(null) else np.nan
            for amp, gg in g[g["label"] == 1].groupby("amp"):
                curl_null[(est, tex, amp)] = float((gg["curl"] > q).mean())
    agg["curl_pos_above_null_q95"] = [curl_null.get((r.estimator, r.texture, r.amp), np.nan) for r in agg.itertuples()]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, tex in zip(axes, ["a1", "realistic"], strict=True):
        sub = agg[(agg["texture"] == tex) & (agg["estimator"] == "pc") & (agg["amp"] > 0)]
        for k, s in enumerate(scores):
            ax.plot(sub["amp"], sub[f"auroc_{s}"], marker=MARKERS[k], color=SERIES[k], label=s)
        ax.axhline(0.9, color=MUTED, lw=1, ls="--")
        ax.set_title(f"{tex}, phase corr., SNR 6", fontsize=9)
        ax.set_xlabel("step amplitude (voxels)")
        ax.set_ylim(0.3, 1.02)
    axes[0].set_ylabel("step localisation AUROC")
    axes[0].legend(fontsize=7, loc="lower right")
    return agg, _save(fig, out / "fig4-step-detection.png")


def envelope(b: pd.DataFrame, out: Path) -> tuple[pd.DataFrame, Path | None]:
    if b.empty:
        return pd.DataFrame(), None
    b = b.assign(theta=_num(b, "theta_deg"), snr_=_num(b, "snr"), spread=b["spread_deg"].astype(str))
    b = b.assign(ratio=b["g_par_mean"] / b["truth_window"], cv=b["g_par_sd"] / b["truth_window"].abs())
    b = b.assign(eff=b["crlb_stack_var"] / b["g_par_sd"] ** 2)
    table = b[["estimator", "texture", "theta", "snr_", "spread", "ratio", "cv", "eff"]]
    table = table.rename(columns={"snr_": "snr"}).sort_values(["texture", "estimator", "theta", "spread", "snr"])
    order = ["0", "10", "25", "iso"]
    fig, axes = plt.subplots(2, 2, figsize=(8, 6), sharex=True, sharey=True)
    for i, tex in enumerate(["a1", "realistic"]):
        for j, est in enumerate(["pc", "lk"]):
            ax = axes[i, j]
            sub = table[(table["texture"] == tex) & (table["estimator"] == est) & (table["theta"] == 5)]
            for k, sp in enumerate(order):
                s = sub[sub["spread"].str.replace(".0", "", regex=False) == sp].sort_values("snr")
                ax.plot(s["snr"], s["ratio"], marker=MARKERS[k], color=SERIES[k], label=f"spread {sp}")
            ax.axhspan(0.95, 1.05, color=GRID, alpha=0.6)
            ax.set_xscale("log")
            ax.set_ylim(-1.5, 1.6)
            ax.set_title(f"{tex}, {est}, θ = 5°", fontsize=9)
            if i == 1:
                ax.set_xlabel("SNR (texture sd / noise sd)")
            if j == 0:
                ax.set_ylabel("slope ratio (estimate / truth)")
    axes[0, 0].legend(fontsize=7)
    return table, _save(fig, out / "fig5-failure-envelope.png")


def patch_size(tilt: pd.DataFrame, bump: pd.DataFrame, overlap: pd.DataFrame, out: Path):
    if tilt.empty:
        return pd.DataFrame(), pd.DataFrame(), None
    t = tilt.assign(P=_num(tilt, "patch"), theta=_num(tilt, "theta_deg"))
    t = t.assign(ratio=t["g_par_mean"] / t["truth_window"])
    rows = []
    for (est, tex, P), g in t.groupby(["estimator", "texture", "P"]):

        def at(th, col, g=g):
            v = g[g["theta"] == th][col]
            return float(v.mean()) if len(v) else np.nan

        rows.append(
            {
                "estimator": est,
                "texture": tex,
                "patch": int(P),
                "sd_g_theta0": at(0, "g_par_sd"),
                "ratio_theta2": at(2, "ratio"),
                "ratio_theta10": at(10, "ratio"),
                "ratio_theta20": at(20, "ratio"),
                "seconds_per_patch": float((g["estimate_seconds"] / g["n_patches"]).mean()),
            }
        )
    table = pd.DataFrame(rows)
    if not bump.empty:
        bb = bump.assign(P=_num(bump, "patch"))
        table = table.merge(
            bb[["estimator", "P", "rmse_lsq"]].rename(columns={"P": "patch", "rmse_lsq": "bump_rmse_256px"}),
            on=["estimator", "patch"],
            how="left",
        )
    ov = (
        overlap.assign(ov=_num(overlap, "overlap"))[["ov", "rmse_lsq", "seconds"]]
        if not overlap.empty
        else pd.DataFrame()
    )
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.2))
    for k, (est, tex) in enumerate([("pc", "a1"), ("lk", "a1"), ("pc", "realistic"), ("lk", "realistic")]):
        s = table[(table["estimator"] == est) & (table["texture"] == tex)].sort_values("patch")
        lab = f"{est}, {tex}"
        axes[0].plot(s["patch"], s["sd_g_theta0"], marker=MARKERS[k], color=SERIES[k], label=lab)
        axes[1].plot(s["patch"], s["ratio_theta10"], marker=MARKERS[k], color=SERIES[k], label=lab)
        if "bump_rmse_256px" in s and tex == "a1":
            axes[2].plot(s["patch"], s["bump_rmse_256px"], marker=MARKERS[k], color=SERIES[k], label=lab)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("sd of g across patches, θ = 0")
    axes[1].set_ylabel("slope ratio at θ = 10°")
    axes[1].axhspan(0.95, 1.05, color=GRID, alpha=0.6)
    axes[2].set_ylabel("bump RMSE (voxels), FWHM 256 px")
    for ax in axes:
        ax.set_xlabel("patch size (px), 50% overlap")
    axes[0].legend(fontsize=7)
    return table, ov, _save(fig, out / "fig6-patch-size.png")


def efficiency(p1: pd.DataFrame, env: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Estimator benchmark: CRLB / variance across patches (addendum 2 item 3)."""
    frames = []
    for df in (p1, env):
        if df.empty:
            continue
        d = df.assign(
            eff=df["crlb_stack_var"] / df["g_par_sd"] ** 2, eff_pair=df["crlb_pair_var"] / df["g_par_sd"] ** 2
        )
        frames.append(d[["estimator", "texture", "eff", "eff_pair", "snr", "theta_deg"]])
    if not frames:
        return pd.DataFrame(), {}
    d = pd.concat(frames)
    d = d[np.isfinite(d["eff"])]
    table = d.groupby(["texture", "estimator"])["eff"].agg(["median", "mean", "count"]).reset_index()
    real = d[d["texture"] == "realistic"].groupby("estimator")["eff"].mean()
    pc, lk = float(real.get("pc", np.nan)), float(real.get("lk", np.nan))
    choice = "lk" if lk > 1.1 * pc else "pc"
    return table, {
        "pc_mean_eff_realistic": pc,
        "lk_mean_eff_realistic": lk,
        "chosen": choice,
        "rule": "lk only if its mean efficiency over realistic configurations exceeds pc's by >10%; ties to pc",
    }


CASE_OFFSET = 1_000_000  # case ids restart in every run; run i's ids are shifted by i * CASE_OFFSET


def load_runs(run_dirs: list[Path]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], list[dict]]:
    """Concatenate several saved runs. Adds ``run`` (directory name) and makes ``case_id`` unique."""
    frames, records = [], []
    detail_frames: dict[str, list[pd.DataFrame]] = {}
    for i, run_dir in enumerate(run_dirs):
        cases = pd.read_parquet(run_dir / "cases.parquet")
        cases["case_id"] = cases["case_id"] + i * CASE_OFFSET
        cases["run"] = run_dir.name
        frames.append(cases)
        records.append(json.loads((run_dir / "run.json").read_text()))
        for path in sorted(run_dir.glob("details-*.parquet")):
            d = pd.read_parquet(path)
            d["case_id"] = d["case_id"] + i * CASE_OFFSET
            detail_frames.setdefault(path.stem.removeprefix("details-"), []).append(d)
    cases = pd.concat(frames, ignore_index=True)
    for col, default in (("estimator", "pc"), ("texture", "a1"), ("snr", 6.0)):
        cases[col] = cases[col].fillna(default) if col in cases else default
    return cases, {k: pd.concat(v, ignore_index=True) for k, v in detail_frames.items()}, records


def calibration(cases: pd.DataFrame, tilt_details: pd.DataFrame | None) -> pd.DataFrame:
    """Sigma calibration along the tilt direction over every tilt case (θ > 0 for the sign check).

    coverage95: share of patches whose 95% interval (± 1.96 sqrt(Sigma_tt)) contains the window-averaged truth.
    confident_wrong_sign: share of patches with the wrong sign and |g| / sigma > 1.96.
    """
    if tilt_details is None:
        return pd.DataFrame()
    keep = ["case_id", "estimator", "texture", "theta_deg", "fibre_deg", "run"]
    d = tilt_details.merge(cases[[c for c in keep if c in cases]], on="case_id")
    d = d[d["valid"].astype(bool)]
    sigma = np.sqrt(d["pred_var_par"].clip(lower=1e-30))
    d = d.assign(z=(d["g_par"] - d["truth_par"]) / sigma, zg=d["g_par"] / sigma)
    d = d.assign(
        cover=d["z"].abs() <= 1.96,
        wrong=(np.sign(d["g_par"]) != np.sign(d["truth_par"])) & (d["zg"].abs() > 1.96) & (d["theta_deg"] > 0),
    )
    rows = []
    for (tex, est), g in d.groupby(["texture", "estimator"]):
        pos = g[g["theta_deg"] > 0]
        rows.append(
            {
                "texture": tex,
                "estimator": est,
                "patches": len(g),
                "coverage95": float(g["cover"].mean()),
                "z_sd": float(g["z"].std()),
                "z_median_abs": float(g["z"].abs().median()),
                "confident_wrong_sign": float(pos["wrong"].mean()) if len(pos) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def orientation(cases: pd.DataFrame, tilt_details: pd.DataFrame | None, out: Path):
    """Bias and coverage against the fibre-to-tilt angle (follow-up sweep with ``fibre_deg``)."""
    if tilt_details is None or "fibre_deg" not in cases:
        return pd.DataFrame(), None
    c = cases[(cases["experiment"] == "tilt") & cases["fibre_deg"].notna() & (cases["status"] == "ok")].copy()
    if c.empty:
        return pd.DataFrame(), None
    from vesuvius_challenge.synthetic import GENERIC_ROTATION_DEG

    c["angle"] = (pd.to_numeric(c["fibre_deg"]) - GENERIC_ROTATION_DEG).round(1)
    d = tilt_details.merge(c[["case_id", "estimator", "texture", "theta_deg", "angle"]], on="case_id")
    d = d[d["valid"].astype(bool)]
    sigma = np.sqrt(d["pred_var_par"].clip(lower=1e-30))
    d = d.assign(
        cover=((d["g_par"] - d["truth_par"]).abs() <= 1.96 * sigma),
        wrong=(np.sign(d["g_par"]) != np.sign(d["truth_par"])) & ((d["g_par"] / sigma).abs() > 1.96),
    )
    table = (
        d.groupby(["texture", "estimator", "theta_deg", "angle"])
        .agg(
            ratio=("g_par", "mean"),
            truth=("truth_par", "mean"),
            coverage95=("cover", "mean"),
            confident_wrong_sign=("wrong", "mean"),
            patches=("g_par", "size"),
        )
        .reset_index()
    )
    table["ratio"] = table["ratio"] / table["truth"]
    table = table.drop(columns="truth")
    textures = list(dict.fromkeys(table["texture"]))
    fig, axes = plt.subplots(2, len(textures), figsize=(3.6 * len(textures), 6), sharex=True, squeeze=False)
    for j, tex in enumerate(textures):
        k = 0
        for est in ("pc", "lk"):
            for th in sorted(table["theta_deg"].unique()):
                s = table[(table["texture"] == tex) & (table["estimator"] == est) & (table["theta_deg"] == th)]
                lab = f"{est}, θ = {th:g}°"
                axes[0, j].plot(s["angle"], s["ratio"], marker=MARKERS[k % 6], color=SERIES[k % 6], label=lab)
                axes[1, j].plot(s["angle"], s["coverage95"], marker=MARKERS[k % 6], color=SERIES[k % 6], label=lab)
                k += 1
        axes[0, j].axhspan(0.95, 1.05, color=GRID, alpha=0.6)
        axes[0, j].axhline(0, color=MUTED, lw=1)
        axes[0, j].set_title(f"{tex}, SNR 6", fontsize=9)
        axes[1, j].axhspan(0.90, 0.98, color=GRID, alpha=0.6)
        axes[1, j].set_ylim(-0.02, 1.02)
        axes[1, j].set_xlabel("fibre direction relative to tilt (degrees)")
    axes[0, 0].set_ylabel("slope ratio (estimate / truth)")
    axes[1, 0].set_ylabel("95% interval coverage")
    axes[0, 0].legend(fontsize=6)
    return table, _save(fig, out / "fig7-orientation.png")


def build(run_dirs: Path | list[Path], out: Path) -> tuple[list[Path], dict[str, dict[str, Any]]]:
    out.mkdir(parents=True, exist_ok=True)
    run_dirs = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    cases, all_details, records = load_runs(run_dirs)
    run_dir = run_dirs[0]
    record = records[0]
    main_ids = cases["run"] == run_dir.name

    def details(name: str) -> pd.DataFrame | None:
        return all_details.get(name)

    b = blocks(cases[main_ids & ~_has(cases, "fibre_deg")])
    written: list[Path] = []
    sections: list[str] = []
    verdicts: dict[str, dict[str, Any]] = {}

    t1, f1 = p1p2(b["p1p2"], out)
    t2, f2 = mdt(b["mdt"], details("tilt"), out)
    t3, f3 = bumps(b["bump"], out)
    t4, f4 = steps(b["step"], details("step"), out)
    t5, f5 = envelope(b["envelope"], out)
    t6, t6o, f6 = patch_size(b["patch"], b["bump_patch"], b["bump_overlap"], out)
    t7, choice = efficiency(b["p1p2"], b["envelope"])
    t8 = calibration(cases[cases["experiment"] == "tilt"], details("tilt"))
    t9, f9 = orientation(cases, details("tilt"), out)
    written += [f for f in (f1, f2, f3, f4, f5, f6, f9) if f]

    # ---- verdicts (addendum 2 item 9) ----
    if not t1.empty:
        acc = t1[(t1["texture"] == "a1") & (t1["snr"] == 6)]
        for est, g in acc.groupby("estimator"):
            ok = bool(g["slope_ok"].all())
            verdicts[f"P1/P2 slope, A1, SNR 6, {est}"] = {
                "verdict": "PASS" if ok else "FAIL",
                "detail": "slopes by Δd: "
                + ", ".join(f"{r.slice_step:g}: {r.slope_theta_le_20:.3f}" for r in g.itertuples())
                + f" (need 1 ± {SLOPE_TOL})",
            }
    if not t6.empty:
        for P in (64, 32):
            g = t6[(t6["texture"] == "a1") & (t6["patch"] == P)]
            if g.empty:
                continue
            worst = float((g["ratio_theta20"] - 1).abs().max())
            verdicts[f"A1 slope at θ = 20°, P = {P} (SNR 6)"] = {
                "verdict": "PASS" if worst <= SLOPE_TOL else "FAIL",
                "detail": "ratio "
                + ", ".join(f"{r.estimator}: {r.ratio_theta20:.3f}" for r in g.itertuples())
                + f"; patch depth span P·tan 20° = {P * np.tan(np.deg2rad(20)):.1f} voxels vs sheet thickness 20",
            }
    if not t8.empty:
        for r in t8.itertuples():
            ok = 0.90 <= r.coverage95 <= 0.98 and (np.isnan(r.confident_wrong_sign) or r.confident_wrong_sign <= 0.025)
            verdicts[f"Sigma calibrated, {r.texture}, {r.estimator}"] = {
                "verdict": "PASS" if ok else "FAIL",
                "detail": f"coverage {r.coverage95:.3f} (need 0.90-0.98), "
                f"confident wrong sign {r.confident_wrong_sign:.3f} (need <= 0.025), {r.patches} patches",
            }
    off = b["offset"]
    if not off.empty:
        for tex, g in off.groupby("texture"):
            worst = float(_num(g, "shift_mag_max").max())
            verdicts[f"pure offset |s| < 0.05 px, {tex}"] = {
                "verdict": "PASS" if worst < 0.05 else "FAIL",
                "detail": f"max per-patch |s| over offsets -10..10: {worst:.4f} px",
            }
    if not t3.empty:
        crit = t3[(t3["amp"] >= 2) & (t3["width"] >= 4)]
        for (est, tex), g in crit.groupby(["estimator", "texture"]):
            worst = float(g["rmse_lsq"].max())
            verdicts[f"offset recovery RMSE <= 0.5, {tex}, {est}"] = {
                "verdict": "PASS" if worst <= 0.5 else "FAIL",
                "detail": f"worst RMSE {worst:.3f} voxels (amp >= 2, width >= 4 patches)",
            }
    if not t4.empty:
        crit = t4[t4["amp"] >= 3]
        for (est, tex), g in crit.groupby(["estimator", "texture"]):
            worst = float(g["auroc_residual"].min())
            verdicts[f"P4 ||r|| AUROC >= 0.9, {tex}, {est}"] = {
                "verdict": "PASS" if worst >= 0.9 else "FAIL",
                "detail": f"lowest AUROC at amp >= 3: {worst:.3f}",
            }

    # ---- markdown ----
    res = record.get("results", {})
    sections.append(
        f"# WO-002 synthetic sweep: generated summary\n\nRun `{run_dir.name}`; {res.get('cases_done')} of "
        f"{res.get('cases_planned')} cases, {res.get('errors')} errors; wall {res.get('wall_seconds', 0) / 60:.1f} "
        f"min on {res.get('compute', {}).get('workers')} CPU workers (case CPU time "
        f"{res.get('cpu_seconds_in_cases', 0) / 3600:.2f} h). villa `{record.get('villa_sha')}`, source "
        f"`{record.get('source_sha256', '')[:12]}`, partial = {record.get('partial')}.\n\n"
        f"Reproduce: `{record.get('reproduce')}`\n"
    )
    sections.append(
        "## Acceptance verdicts (addendum 2 item 9)\n\n"
        + md_table(pd.DataFrame([{"criterion": k, **v} for k, v in verdicts.items()]))
    )
    sections.append(
        "## P1/P2: signed slope against window-averaged tan θ (θ ≤ 20°)\n\n![](fig1-p1p2-slope.png)\n\n" + md_table(t1)
    )
    sections.append(
        "## Minimum detectable tilt (power 0.8 at 5% false alarms)\n\n![](fig2-min-detectable-tilt.png)\n\n"
        + md_table(t2)
    )
    sections.append(
        "## Estimator benchmark (efficiency = multi-layer CRLB / variance across patches)\n\n"
        + md_table(t7)
        + f"\nDecision: **{choice.get('chosen')}** ({choice.get('rule')}; "
        f"pc {choice.get('pc_mean_eff_realistic', np.nan):.3g}, "
        f"lk {choice.get('lk_mean_eff_realistic', np.nan):.3g}).\n"
    )
    sections.append("## Sigma calibration along the tilt (all tilt cases, all runs)\n\n" + md_table(t8))
    if not t9.empty:
        sections.append("## Fibre orientation relative to the tilt\n\n![](fig7-orientation.png)\n\n" + md_table(t9))
    sections.append("## Offset recovery (bumps)\n\n![](fig3-offset-recovery.png)\n\n" + md_table(t3))
    sections.append("## Step detection (P4)\n\n![](fig4-step-detection.png)\n\n" + md_table(t4))
    sections.append("## Failure envelope (θ, SNR, anisotropy)\n\n![](fig5-failure-envelope.png)\n\n" + md_table(t5))
    sections.append("## Patch size and overlap\n\n![](fig6-patch-size.png)\n\n" + md_table(t6) + "\n" + md_table(t6o))
    for name, cols in {
        "thickness": ["estimator", "variant", "theta_deg", "thickness", "g_par_mean", "truth_window", "pairs_mean"],
        "beta": ["texture", "theta_deg", "beta", "refine", "g_par_mean", "truth_window", "g_par_sd"],
        "offset": [
            "texture",
            "offset",
            "num_slices",
            "zstar_err_mean",
            "zstar_err_rms",
            "shift_mag_max",
            "censored_fraction",
        ],
        "sinusoid": ["wavelength_px", "slope_vs_point", "slope_vs_window", "hann_transfer", "sinc"],
        "stretch": ["estimator", "eps", "ratio_with_metric", "ratio_without_metric", "predicted_without"],
        "layers": [
            "texture",
            "thickness",
            "gap",
            "rho_in_sheet",
            "rho_in_gap",
            "rho_interface",
            "window_leak_fraction",
            "window_layers_mean",
        ],
        "aperture": [
            "texture",
            "estimator",
            "aggregate",
            "window_fraction",
            "emp_var_along",
            "pred_var_along",
            "emp_var_across",
            "pred_var_across",
            "bias_along",
            "cond_pair_median",
            "cond_summed_median",
        ],
        "crosscheck": [
            "noise",
            "err_fast_max",
            "err_fast_default_mean",
            "err_skimage_max",
            "err_villa_mean",
            "err_villa_max",
            "villa_vs_skimage_mean",
        ],
    }.items():
        df = b[name]
        if df.empty:
            continue
        keep = [c for c in cols if c in df]
        sections.append(f"## {name}\n\n" + md_table(df[keep].reset_index(drop=True)))
    summary = out / "summary.md"
    summary.write_text("\n".join(sections))
    written.append(summary)
    tables = out / "tables.json"
    tables.write_text(json.dumps({"verdicts": verdicts, "estimator_choice": choice}, indent=2, default=str) + "\n")
    written.append(tables)
    return written, verdicts
