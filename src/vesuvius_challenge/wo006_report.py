"""WO-006 analysis: fit Sigma calibration on one saved run, and judge the pre-registered criteria on others.

Every number comes from saved sweeps. The calibration split (seeds 0-4) is read only by :func:`fit`; the evaluation
runs are read only by :func:`build`, after kappa and f are frozen in ``lpsf.Params``.

Definitions
-----------
- Full estimate: judged along the known tilt (+u), as in WO-002. Coverage is the share of 95% intervals containing the
  window-averaged truth. Confident wrong sign is the wrong sign with ``|g| / sigma > 1.96``.
- Directional estimate: judged along each patch's best-observed direction e. Its sign is only defined where the truth
  has a real component along e, so wrong-sign rates and slope ratios use patches with ``|e . truth| >= 0.1 |truth|``.
  At a fibre-to-tilt angle of 0, e is perpendicular to the tilt, almost no patch qualifies and the ratio is undefined.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from vesuvius_challenge import lpsf
from vesuvius_challenge.experiments import auroc
from vesuvius_challenge.synth_report import MARKERS, SERIES, _save, md_table, plt

CALIBRATION_SEEDS = (0, 1, 2, 3, 4)
COVERAGE_BAND = (0.90, 0.98)
WRONG_SIGN_MAX = 0.025
SLOPE_BAND = (0.8, 1.2)
GAIN_TOLERANCE = 0.25
GAIN_RANGE = (0.0, 1.2)
SIGN_DEFINED = 0.1  # the observed direction must carry at least this share of the truth for a sign to mean anything
FITTED_MODES = ("a1", "two_layer")
MODES = ("a1", "two_layer", "L8.0", "L4.3", "L2.0")
REALISTIC = ("L8.0", "L4.3", "L2.0")


def load_patches(run_dir: Path) -> pd.DataFrame:
    """Per-patch rows of a sweep, with its settings and the derived columns used below."""
    cases = pd.read_parquet(run_dir / "cases.parquet")
    details = pd.read_parquet(run_dir / "details-orientation.parquet")
    keep = ["case_id", "estimator", "texture", "corr_length", "fibre_tilt_deg", "theta_deg", "seed_id"]
    keep += [c for c in ("noise", "snr") if c in cases]
    frame = details.merge(cases[keep], on="case_id")
    length = frame["corr_length"].map(lambda v: f"L{v}" if pd.notna(v) else "")
    frame["mode"] = np.where(frame["texture"] == "realistic", length, frame["texture"])
    frame["error"] = frame["g_u"] - frame["truth_u"]
    frame["magnitude"] = np.hypot(frame["g_u"], frame["g_v"])
    frame["side_truth"] = frame["side_e_v"] * frame["truth_v"] + frame["side_e_u"] * frame["truth_u"]
    frame["side_g"] = frame["side_e_v"] * frame["side_g_v"] + frame["side_e_u"] * frame["side_g_u"]
    frame["truth_size"] = np.hypot(frame["truth_u"], frame["truth_v"])
    return frame


def fit(run_dir: Path) -> dict[str, Any]:
    """Fit one kappa and f on the calibration split, with A1 and two-layer as strata.

    Realistic mode reports its coverage but is not a stratum: an interval wide enough for it needs f above 0.51, and
    then ``|g| / sigma`` can never reach 1.96, so no estimate could ever count as significant.
    """
    patches = load_patches(run_dir)
    seeds = sorted(int(seed) for seed in patches["seed_id"].unique())
    if not set(seeds) <= set(CALIBRATION_SEEDS):
        raise ValueError(f"this run holds seeds {seeds}; calibration may use only {list(CALIBRATION_SEEDS)}")
    patches = patches[patches["valid"]]
    fitted = patches[patches["mode"].isin(FITTED_MODES)]
    found = lpsf.calibrate(fitted["error"], fitted["var_uu"], fitted["magnitude"], fitted["mode"])
    all_modes = patches.assign(stratum=patches["mode"] + "/" + patches["theta_deg"].astype(str))
    literal = lpsf.calibrate(
        all_modes["error"],
        all_modes["var_uu"],
        all_modes["magnitude"],
        all_modes["stratum"],
        kappas=np.arange(1.0, 14.01, 0.1),
        floors=np.arange(0.0, 0.6001, 0.01),
    )
    return {
        "kappa": found.kappa,
        "floor": found.floor,
        "coverage": found.coverage,
        "coverage_all_modes": coverage_table(patches, found.kappa, found.floor).to_dict("records"),
        "all_modes_fit": {"kappa": literal.kappa, "floor": literal.floor},
        "feasible_points": feasible_points(fitted),
        "patches": int(len(patches)),
        "seed_ids": seeds,
    }


def feasible_points(fitted: pd.DataFrame) -> int:
    """How many (kappa, f) on a fine grid put both fitted modes inside the coverage band."""
    count = 0
    groups = [group for _, group in fitted.groupby("mode")]
    for kappa in np.arange(1.0, 6.01, 0.05):
        for floor in np.arange(0.0, 0.4001, 0.0025):
            shares = [_inside(group, "error", "var_uu", "magnitude", kappa, floor).mean() for group in groups]
            count += all(COVERAGE_BAND[0] <= share <= COVERAGE_BAND[1] for share in shares)
    return count


def _inside(frame: pd.DataFrame, error: str, variance: str, magnitude: str, kappa: float, floor: float) -> np.ndarray:
    sigma = np.sqrt(lpsf.calibrated_variance(frame[variance].to_numpy(), frame[magnitude].to_numpy(), kappa, floor))
    return np.abs(frame[error].to_numpy()) <= lpsf.COVERAGE_Z * sigma


def full_stats(frame: pd.DataFrame, kappa: float, floor: float) -> pd.DataFrame:
    """Add coverage and confident-wrong-sign flags for the full estimate."""
    sigma = np.sqrt(lpsf.calibrated_variance(frame["var_uu"], frame["magnitude"], kappa, floor))
    wrong = (np.sign(frame["g_u"]) != np.sign(frame["truth_u"])) & (frame["g_u"].abs() / sigma > lpsf.COVERAGE_Z)
    return frame.assign(
        cover=frame["error"].abs() <= lpsf.COVERAGE_Z * sigma, wrong=wrong, zscore=frame["error"] / sigma
    )


def side_stats(frame: pd.DataFrame, kappa: float, floor: float) -> pd.DataFrame:
    """The directional estimate along its observed direction; patches observing nothing are dropped."""
    seen = frame[frame["side_valid"] & (frame["side_rank"] >= 1) & np.isfinite(frame["side_var"])]
    sigma = np.sqrt(lpsf.calibrated_variance(seen["side_var"], seen["side_g"].abs(), kappa, floor))
    error = seen["side_g"] - seen["side_truth"]
    signed = seen["side_truth"].abs() >= SIGN_DEFINED * seen["truth_size"]
    wrong = signed & (np.sign(seen["side_g"]) != np.sign(seen["side_truth"]))
    wrong = wrong & (seen["side_g"].abs() / sigma > lpsf.COVERAGE_Z)
    return seen.assign(cover=error.abs() <= lpsf.COVERAGE_Z * sigma, wrong=wrong, signed=signed)


def coverage_table(patches: pd.DataFrame, kappa: float, floor: float) -> pd.DataFrame:
    stats = full_stats(patches, kappa, floor)
    grouped = stats.groupby("mode", sort=False).agg(
        patches=("cover", "size"), coverage=("cover", "mean"), wrong_sign=("wrong", "mean"), sd_z=("zscore", "std")
    )
    return grouped.reset_index()


def calibration_tables(patches: pd.DataFrame, kappa: float, floor: float) -> dict[str, pd.DataFrame]:
    """Coverage and confident wrong sign, full and directional, by mode, tilt and estimator."""
    full = full_stats(patches, kappa, floor)
    side = side_stats(patches, kappa, floor)

    def summary(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        grouped = frame.groupby(keys).agg(
            patches=("cover", "size"), coverage=("cover", "mean"), wrong_sign=("wrong", "mean")
        )
        return grouped.reset_index()

    def side_summary(keys: list[str]) -> pd.DataFrame:
        table = summary(side, keys)
        signed = side[side["signed"]].groupby(keys)["wrong"].mean().rename("wrong_sign").reset_index()
        return table.drop(columns="wrong_sign").merge(signed, on=keys, how="left")

    return {
        "full_mode": summary(full, ["mode"]),
        "full_mode_estimator": summary(full, ["mode", "estimator"]),
        "full_mode_theta": summary(full, ["mode", "theta_deg"]),
        "full_mode_angle": summary(full, ["mode", "fibre_tilt_deg"]),
        "side_mode": side_summary(["mode"]),
        "side_mode_angle": side_summary(["mode", "fibre_tilt_deg"]),
        "side_mode_estimator_angle": side_summary(["mode", "estimator", "fibre_tilt_deg"]),
        "side_rank": patches[patches["side_valid"]].groupby("mode")["side_rank"].mean().reset_index(),
    }


def slope_table(patches: pd.DataFrame, kappa: float, floor: float) -> pd.DataFrame:
    """Slope ratio by mode, estimator and angle: directional against truth on e, and full against truth on the tilt."""
    side = side_stats(patches, kappa, floor)
    side = side[side["signed"]]
    rows = []
    keys = ["mode", "estimator", "fibre_tilt_deg"]
    total = patches.groupby(keys).size()
    full = patches.groupby(keys).apply(lambda g: g["g_u"].mean() / g["truth_u"].mean(), include_groups=False)
    for key, group in side.groupby(keys):
        denominator = float(np.sum(group["side_truth"] ** 2))
        rows.append(
            dict(
                zip(keys, key, strict=True),
                slope=float(np.sum(group["side_g"] * group["side_truth"]) / denominator),
                signed_share=len(group) / int(total.loc[key]),
            )
        )
    table = pd.DataFrame(rows, columns=[*keys, "slope", "signed_share"])
    merged = total.reset_index()[keys].merge(table, on=keys, how="left")
    merged["slope"] = merged["slope"].astype(float)
    merged["signed_share"] = merged["signed_share"].astype(float).fillna(0.0)
    merged["full_slope"] = [float(full.loc[tuple(key)]) for key in merged[keys].itertuples(index=False)]
    # A handful of patches at 0 degrees that clear the threshold by chance are not a slope.
    merged["estimable"] = merged["signed_share"] >= 0.5
    return merged


def gain_table(patches: pd.DataFrame) -> pd.DataFrame:
    """Predicted against measured gain per cell of the realistic grid."""
    rows = []
    keys = ["mode", "estimator", "fibre_tilt_deg", "theta_deg"]
    for key, group in patches[patches["mode"].isin(REALISTIC)].groupby(keys):
        rows.append(
            dict(
                zip(keys, key, strict=True),
                measured=float(group["g_u"].mean() / group["truth_u"].mean()),
                predicted=float(group["gain_pred"].mean()),
                predicted_true_tilt=float(group["gain_pred_true"].mean()),
                flagged=float(group["flagged"].mean()),
                L=float(group["L"].replace(np.inf, np.nan).median()),
                ell_along=float(group["ell_along"].median()),
                ell_across=float(group["ell_across"].median()),
            )
        )
    table = pd.DataFrame(rows)
    table["in_range"] = table["measured"].between(*GAIN_RANGE)
    table["error"] = (table["predicted"] - table["measured"]).abs()
    table["error_true_tilt"] = (table["predicted_true_tilt"] - table["measured"]).abs()
    return table


def verdicts(tables: dict[str, pd.DataFrame], slopes: pd.DataFrame, gains: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    full = tables["full_mode"].set_index("mode")
    held = [full.loc[m] for m in FITTED_MODES]
    in_band = all(COVERAGE_BAND[0] <= row["coverage"] <= COVERAGE_BAND[1] for row in held)
    out["Calibration, A1 and two-layer"] = {
        "verdict": "PASS" if in_band and all(row["wrong_sign"] <= WRONG_SIGN_MAX for row in held) else "FAIL",
        "detail": "; ".join(
            f"{m}: coverage {full.loc[m, 'coverage']:.3f}, wrong sign {full.loc[m, 'wrong_sign']:.4f}"
            for m in FITTED_MODES
        ),
    }
    realistic = slopes[slopes["mode"] == "L4.3"]
    estimable = realistic[realistic["estimable"]]
    by_angle = estimable.groupby("fibre_tilt_deg")["slope"]
    side = tables["side_mode_estimator_angle"]
    side = side[side["mode"] == "L4.3"]
    wrong = side[side["fibre_tilt_deg"].isin(estimable["fibre_tilt_deg"].unique())]["wrong_sign"]
    slope_ok = bool(estimable["slope"].between(*SLOPE_BAND).all())
    missing = sorted(set(realistic["fibre_tilt_deg"]) - set(estimable["fibre_tilt_deg"]))
    verdict = "FAIL"
    if slope_ok and float(wrong.max()) <= WRONG_SIGN_MAX:
        verdict = "PASS on estimable angles" if missing else "PASS"
    out["Directional estimate, realistic L = 4.3"] = {
        "verdict": verdict,
        "detail": f"slope {by_angle.min().min():.2f} to {by_angle.max().max():.2f}, worst wrong sign "
        f"{float(wrong.max()):.3f}; not estimable at {missing} degrees",
    }
    in_range = gains[gains["in_range"]]
    worst = float(in_range["error"].max())
    out["Gain prediction"] = {
        "verdict": "PASS" if worst <= GAIN_TOLERANCE else "FAIL",
        "detail": f"{(in_range['error'] <= GAIN_TOLERANCE).mean():.0%} of {len(in_range)} cells within "
        f"{GAIN_TOLERANCE}; worst {worst:.2f}. Along the true tilt: "
        f"{(in_range['error_true_tilt'] <= GAIN_TOLERANCE).mean():.0%}, worst "
        f"{float(in_range['error_true_tilt'].max()):.2f}",
    }
    return out


def processed_tables(patches: pd.DataFrame, kappa: float, floor: float) -> dict[str, pd.DataFrame]:
    """Addendum 1: gain against noise-only expectation, calibration, and whether gain_map separates the causes."""
    keys = ["noise", "snr", "mode"]
    full = full_stats(patches, kappa, floor)

    def cell_gain(group: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "measured": group["g_u"].mean() / group["truth_u"].mean(),
                "shrink": group["shrink"].mean(),
                "predicted": group["gain_pred"].mean(),
                "predicted_material": group["gain_material"].mean(),
                "noise_share": group["noise_share"].median(),
                "L": group["L"].replace(np.inf, np.nan).median(),
                "L_material": group["L_material"].replace(np.inf, np.nan).median(),
                "L_void": group["L_void"].replace(np.inf, np.nan).median(),
            }
        )

    gains = patches.groupby([*keys, "fibre_tilt_deg", "estimator"]).apply(cell_gain, include_groups=False).reset_index()
    summary = gains.groupby(keys).agg(
        measured_min=("measured", "min"),
        measured_max=("measured", "max"),
        shrink=("shrink", "mean"),
        noise_share=("noise_share", "mean"),
        L=("L", "mean"),
        L_material=("L_material", "mean"),
        L_void=("L_void", "mean"),
    )
    coverage = full.groupby(keys).agg(coverage=("cover", "mean"), wrong_sign=("wrong", "mean"))

    a1 = gains[gains["mode"] == "a1"]
    material = gains[gains["mode"] != "a1"]
    error = {
        "raw prediction": (a1["predicted"] - a1["measured"]).abs().mean(),
        "void-corrected prediction": (a1["predicted_material"] - a1["measured"]).abs().mean(),
    }
    material_error = {
        "raw prediction": (material["predicted"] - material["measured"]).abs().mean(),
        "void-corrected prediction": (material["predicted_material"] - material["measured"]).abs().mean(),
    }
    errors = pd.DataFrame(
        {"A1 (noise only)": pd.Series(error), "realistic (material)": pd.Series(material_error)}
    ).reset_index(names="mean absolute gain error")

    rows = []
    processed = patches[patches["noise"] == "processed"]
    for snr, group in processed.groupby("snr"):
        noise_only = group[group["mode"] == "a1"]
        decorrelating = group[group["mode"] == "L4.3"]
        both = pd.concat([noise_only, decorrelating])
        labels = both["mode"].to_numpy() == "L4.3"
        length = np.nan_to_num(both["L"].to_numpy(), nan=1e6, posinf=1e6)
        material_length = np.nan_to_num(both["L_material"].to_numpy(), nan=1e6, posinf=1e6)
        isotropy = length**2 / (2 * both["ell_along"].to_numpy() * both["ell_across"].to_numpy())
        rows.append(
            {
                "snr": snr,
                "AUROC, 1 / L": auroc(-length, labels),
                "AUROC, 1 / L_material": auroc(-material_length, labels),
                "AUROC, isotropy L^2 / 2 l l": auroc(-isotropy, labels),
                "AUROC, noise share": auroc(-both["noise_share"].fillna(1.0).to_numpy(), labels),
            }
        )
    return {
        "gains": gains,
        "summary": summary.join(coverage).reset_index(),
        "errors": errors,
        "separation": pd.DataFrame(rows),
    }


def figure_coverage(tables: dict[str, pd.DataFrame], side: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    frames = {"Full estimate": tables["full_mode_angle"], "Directional estimate": side}
    for axis, (title, frame) in zip(axes, frames.items(), strict=True):
        for index, mode in enumerate(MODES):
            part = frame[frame["mode"] == mode]
            axis.plot(
                part["fibre_tilt_deg"],
                part["coverage"],
                color=SERIES[index],
                marker=MARKERS[index],
                linewidth=2,
                markersize=6,
                label=mode,
            )
        axis.axhspan(*COVERAGE_BAND, color="#d9d9d9", alpha=0.5, linewidth=0)
        axis.set_title(title)
        axis.set_xlabel("Fibre-to-tilt angle (degrees)")
        axis.set_xticks(range(0, 91, 15))
    axes[0].set_ylabel("95% interval coverage")
    axes[1].legend(frameon=False, ncol=1, loc="center left", bbox_to_anchor=(1.0, 0.5))
    return _save(fig, out / "fig1-coverage.png")


def figure_gain(gains: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), sharex=True, sharey=True)
    columns = {"Predicted along measured tilt": "predicted", "Predicted along true tilt": "predicted_true_tilt"}
    span = np.array([-1.2, 1.3])
    for axis, (title, column) in zip(axes, columns.items(), strict=True):
        for index, mode in enumerate(REALISTIC):
            part = gains[gains["mode"] == mode]
            axis.scatter(
                part["measured"].clip(-1.2, 1.3),
                part[column].clip(-1.2, 1.3),
                s=18,
                color=SERIES[index + 2],
                marker=MARKERS[index + 2],
                label=mode,
                linewidths=0,
            )
        axis.plot(span, span, color="#6b6b6b", linewidth=1)
        axis.fill_between(span, span - GAIN_TOLERANCE, span + GAIN_TOLERANCE, color="#d9d9d9", alpha=0.5, linewidth=0)
        axis.set_title(title)
        axis.set_xlabel("Measured gain")
    axes[0].set_ylabel("Predicted gain")
    axes[1].legend(frameon=False, loc="lower right")
    return _save(fig, out / "fig2-gain.png")


def figure_slopes(slopes: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for axis, estimator in zip(axes, ("pc", "lk"), strict=True):
        part = slopes[(slopes["mode"] == "L4.3") & (slopes["estimator"] == estimator)]
        seen = part[part["estimable"]]
        axis.plot(
            part["fibre_tilt_deg"], part["full_slope"], color=SERIES[0], marker=MARKERS[0], label="Full, along tilt"
        )
        axis.plot(
            seen["fibre_tilt_deg"],
            seen["slope"],
            color=SERIES[1],
            marker=MARKERS[1],
            label="Directional, across fibres",
        )
        axis.axhspan(*SLOPE_BAND, color="#d9d9d9", alpha=0.5, linewidth=0)
        axis.axhline(0, color="#6b6b6b", linewidth=1)
        axis.set_title(f"Estimator {estimator}, L = 4.3")
        axis.set_xlabel("Fibre-to-tilt angle (degrees)")
        axis.set_xticks(range(0, 91, 15))
    axes[0].set_ylabel("Slope ratio")
    axes[1].legend(frameon=False, loc="lower right")
    return _save(fig, out / "fig3-slope-ratio.png")


def figure_processed(gains: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for axis, snr in zip(axes, (6, 2), strict=True):
        for index, noise in enumerate(("white", "processed")):
            part = gains[(gains["snr"] == snr) & (gains["noise"] == noise) & (gains["mode"] == "a1")]
            mean = part.groupby("fibre_tilt_deg")["measured"].mean()
            axis.plot(
                mean.index,
                mean.to_numpy(),
                color=SERIES[index],
                marker=MARKERS[index],
                label=f"Measured, {noise} noise",
            )
            if noise == "processed":
                shrink = part.groupby("fibre_tilt_deg")["shrink"].mean()
                axis.plot(
                    shrink.index,
                    shrink.to_numpy(),
                    color=SERIES[2],
                    marker=MARKERS[2],
                    linestyle="--",
                    label="Noise-only expectation",
                )
        axis.axhline(0, color="#6b6b6b", linewidth=1)
        axis.set_title(f"A1 texture, SNR {snr}")
        axis.set_xlabel("Fibre-to-tilt angle (degrees)")
        axis.set_xticks(range(0, 91, 15))
    axes[0].set_ylabel("Gain")
    axes[1].legend(frameon=False, loc="lower right")
    return _save(fig, out / "fig4-processed-noise.png")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(calibration: Path, evaluation_dir: Path, processed_dir: Path, out: Path) -> tuple[list[Path], dict[str, Any]]:
    """Write tables, figures and a markdown summary. Reads saved runs only."""
    out.mkdir(parents=True, exist_ok=True)
    fitted = json.loads(calibration.read_text())
    kappa, floor = fitted["kappa"], fitted["floor"]
    if (lpsf.Params().sigma_inflation, lpsf.Params().sigma_floor) != (kappa, floor):
        raise ValueError(f"lpsf.Params must hold the fitted values, kappa {kappa} and f {floor}")
    patches = load_patches(evaluation_dir)
    patches = patches[patches["valid"]]
    tables = calibration_tables(patches, kappa, floor)
    slopes = slope_table(patches, kappa, floor)
    gains = gain_table(patches)
    results = verdicts(tables, slopes, gains)
    processed_patches = load_patches(processed_dir)
    processed = processed_tables(processed_patches[processed_patches["valid"]], kappa, floor)

    worst = gains[gains["in_range"]].sort_values("error", ascending=False).head(10)
    sections = [
        "# WO-006 generated tables",
        f"Frozen calibration: kappa = {kappa}, f = {floor}. Evaluation seeds "
        f"{sorted(int(s) for s in patches['seed_id'].unique())}.",
        "## Verdicts",
        md_table(pd.DataFrame([{"criterion": k, **v} for k, v in results.items()])),
        "## Full estimate by mode",
        md_table(tables["full_mode"]),
        "## Full estimate by mode and estimator",
        md_table(tables["full_mode_estimator"]),
        "## Full estimate by mode and tilt",
        md_table(tables["full_mode_theta"]),
        "## Full estimate by mode and fibre angle",
        md_table(tables["full_mode_angle"]),
        "## Directional estimate by mode",
        md_table(tables["side_mode"]),
        "## Directional estimate by mode and fibre angle",
        md_table(tables["side_mode_angle"]),
        "## Mean observed rank",
        md_table(tables["side_rank"]),
        "## Slope ratio, L = 4.3",
        md_table(slopes[slopes["mode"] == "L4.3"]),
        "## Worst gain predictions in range",
        md_table(worst),
        "## Processed noise: summary",
        md_table(processed["summary"]),
        "## Processed noise: gain error with and without the void correction",
        md_table(processed["errors"]),
        "## Processed noise: patch-level separation of noise from material decorrelation",
        md_table(processed["separation"]),
    ]
    summary = out / "summary.md"
    summary.write_text("\n\n".join(sections) + "\n")
    tables_path = out / "tables.json"
    payload = {
        "calibration": {"kappa": kappa, "floor": floor},
        "verdicts": results,
        "details_sha256": {
            evaluation_dir.name: digest(evaluation_dir / "details-orientation.parquet"),
            processed_dir.name: digest(processed_dir / "details-orientation.parquet"),
        },
        "tables": {name: table.to_dict("records") for name, table in tables.items()},
        "slopes": slopes.to_dict("records"),
        "gains": gains.to_dict("records"),
        "processed": {name: table.to_dict("records") for name, table in processed.items()},
    }
    tables_path.write_text(json.dumps(payload, indent=1, default=float) + "\n")
    figures = [
        figure_coverage(tables, tables["side_mode_angle"], out),
        figure_gain(gains, out),
        figure_slopes(slopes, out),
        figure_processed(processed["gains"], out),
    ]
    return [summary, tables_path, *figures], results
