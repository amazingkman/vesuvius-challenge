"""`vch synth`: synthetic parameter sweeps (run) and reports built from saved runs only (report)."""

from __future__ import annotations

import os
import time
import tomllib
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Annotated, Any

import humanize
import pyarrow as pa
import pyarrow.parquet as pq
import typer

from vesuvius_challenge import experiments, ui
from vesuvius_challenge.runrecord import RunRecord, utc_now
from vesuvius_challenge.security import repo_path

synth_app = typer.Typer(
    help="Synthetic-sheet harness for LPSF (WO-002): run sweeps, build reports.", no_args_is_help=True
)

WHY = {
    "tilt": "Tilted isometric plane: signed slope (P1/P2), small angles, estimator efficiency against the CRLB.",
    "offset": "Constant offset: z* must track it (P3) and the shift must stay ~0 (P2 null).",
    "bump": "Gaussian bump plus constant: offset recovery by screened integration, against z* alone.",
    "step": "Straight step (sheet-jump surrogate): consistency residual vs curl vs |grad h_hat| (P4).",
    "sinusoid": "Corrugation: regressing on point slopes under-reads; window-averaged truth does not.",
    "stretch": "Stretched mesh: the metric correction removes a ~2*eps bias.",
    "layers": "Two sheets: correlation in gaps and across interfaces (P6); the window must not reach the next wrap.",
    "aperture": "Oriented fibres: predicted Sigma vs empirical scatter (P5), per layer and summed.",
    "crosscheck": "Fast path vs skimage vs villa _phase_correlate on exactly shifted patches.",
    "orientation": "Fibres against tilt: full and directional estimates and the predicted decorrelation gain.",
}


def _init_worker() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from vesuvius_challenge import lpsf

    lpsf.FFT_WORKERS = 1


def to_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Rows to Arrow; columns with mixed types become strings (e.g. spread_deg = 25 or "iso")."""
    if not rows:
        return pa.table({})
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    columns = {}
    for key in keys:
        values = [row.get(key) for row in rows]
        values = [list(v) if isinstance(v, tuple) else v for v in values]
        kinds = {type(v) for v in values if v is not None}
        if kinds <= {int, float, bool} and len(kinds - {bool}) and bool in kinds:
            values = [None if v is None else float(v) for v in values]
        elif len(kinds) > 1 and not kinds <= {int, float}:
            values = [None if v is None else str(v) for v in values]
        elif any(isinstance(v, list) for v in values):
            values = [None if v is None else str(v) for v in values]
        columns[key] = values
    return pa.table(columns)


def write_outputs(out: Path, rows: list[dict], details: list[dict]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    rows = sorted(rows, key=lambda r: r["case_id"])
    pq.write_table(to_table(rows), out / "cases.parquet")
    paths.append(out / "cases.parquet")
    by_exp: dict[str, list[dict]] = {}
    for d in details:
        by_exp.setdefault(d["experiment"], []).append(d)
    for name, items in sorted(by_exp.items()):
        path = out / f"details-{name}.parquet"
        pq.write_table(to_table(items), path)
        paths.append(path)
    return paths


@synth_app.command("run")
def run(
    config: Annotated[Path, typer.Option("--config", help="TOML sweep file ([[sweep]] blocks).", exists=True)],
    out: Annotated[Path, typer.Option(help="Parent directory for the run directory.")] = Path("runs") / "synth",
    workers: Annotated[int, typer.Option(min=1, max=64, help="Parallel processes, one case each.")] = os.cpu_count()
    or 1,
    only: Annotated[str | None, typer.Option(help="Run only these experiments (comma-separated).")] = None,
) -> None:
    """Run a parameter sweep of synthetic experiments; write Parquet tables and a JSON run record."""
    spec = tomllib.loads(config.read_text())
    cases = experiments.expand(spec)
    if only:
        keep = set(only.split(","))
        cases = [c for c in cases if c["experiment"] in keep]
    name = spec.get("name", config.stem)
    run_dir = out / f"{name}-{utc_now().replace(':', '').replace('-', '')[:15]}"
    record_path = run_dir / "run.json"
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["experiment"]] = counts.get(c["experiment"], 0) + 1
    ui.banner(
        "vch synth run",
        "Builds synthetic papyrus sheets with known ground truth, renders them with the reference trilinear "
        "renderer and runs the LPSF estimator on each. No scroll data, no container, CPU only.",
        {"config": config, "cases": len(cases), "experiments": counts, "workers": workers, "seed": spec.get("seed")},
        run_dir,
    )
    record = RunRecord(
        "synth-run",
        {"config_path": repo_path(config), "config": spec, "workers": workers, "only": only, "n_cases": len(cases)},
        seed=int(spec.get("seed", 2026)),
    )
    rows: list[dict] = []
    details: list[dict] = []
    errors = 0
    started = time.monotonic()
    progress = ui.item_progress()
    task = progress.add_task("Cases", total=len(cases), rate="")
    queue = list(cases)
    crashes: dict[int, int] = {}
    last_checkpoint = 0

    def record_row(case: dict, row: dict, det: list[dict]) -> None:
        nonlocal errors
        rows.append(row)
        details.extend(det)
        errors += row["status"] != "ok"
        progress.advance(task)
        progress.update(task, rate=ui.per_second(len(rows), time.monotonic() - started, "case"))

    try:
        with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
            while queue and not stop.requested:
                pending: dict[Future, dict] = {}
                with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
                    broken = False
                    while (queue or pending) and not broken:
                        while queue and len(pending) < 2 * workers and not stop.requested:
                            case = queue.pop(0)
                            pending[pool.submit(experiments.run_case, case)] = case
                        if stop.requested and not pending:
                            break
                        done, _ = wait(list(pending), timeout=0.5, return_when=FIRST_COMPLETED)
                        for future in done:
                            case = pending.pop(future)
                            try:
                                row, det = future.result()
                            except BrokenProcessPool:
                                # A worker died (e.g. out of memory). Retry each in-flight case once in a fresh pool.
                                broken = True
                                crashes[case["case_id"]] = crashes.get(case["case_id"], 0) + 1
                                if crashes[case["case_id"]] > 1:
                                    record_row(
                                        case,
                                        {**case, "status": "error", "error": "worker crashed twice", "seconds": 0.0},
                                        [],
                                    )
                                else:
                                    queue.insert(0, case)
                                continue
                            record_row(case, row, det)
                            board.explain(f"{case['experiment']}: {WHY.get(case['experiment'], '')}")
                            board.stats(
                                done=f"{len(rows)} / {len(cases)}",
                                errors=errors,
                                last=f"{case['experiment']} #{case['case_id']} in {row['seconds']:.1f} s",
                                cpu_time=humanize.naturaldelta(sum(r["seconds"] for r in rows)),
                            )
                        if len(rows) - last_checkpoint >= 50:
                            write_outputs(run_dir, rows, details)
                            last_checkpoint = len(rows)
                        if stop.requested:
                            for future in list(pending):
                                if future.cancel():
                                    pending.pop(future)
                    if broken:
                        for future, case in pending.items():
                            if not future.done() or future.exception() is not None:
                                queue.insert(0, case)
                            else:
                                record_row(case, *future.result())
                        board.explain("A worker died; restarting the pool and retrying the in-flight cases once.")
    finally:
        write_outputs(run_dir, rows, details)
    partial = len(rows) < len(cases)
    paths = write_outputs(run_dir, rows, details)
    wall = time.monotonic() - started
    record.results = {
        "cases_done": len(rows),
        "cases_planned": len(cases),
        "errors": errors,
        "wall_seconds": wall,
        "cpu_seconds_in_cases": sum(r["seconds"] for r in rows),
        "per_experiment": counts,
        "compute": {"cpus": os.cpu_count(), "workers": workers, "gpu": None},
    }
    record.outputs = [repo_path(p) for p in paths]
    record_path = record.finish(record_path, partial=partial)
    ui.summary(
        "Synthetic sweep",
        [
            ("cases", f"{len(rows)} / {len(cases)}", "Cases finished; a partial run keeps what finished."),
            ("errors", str(errors), "Cases that raised; their message is in cases.parquet `error`."),
            ("wall time", humanize.precisedelta(wall), f"On {workers} worker processes, CPU only."),
        ],
        [*paths, record_path],
        record.reproduce,
        partial,
    )
    if errors:
        raise typer.Exit(1)


@synth_app.command("report")
def report(
    run_dirs: Annotated[
        list[Path], typer.Argument(help="Run directories written by `vch synth run` (first = main sweep).", exists=True)
    ],
    out: Annotated[
        Path | None, typer.Option(help="Where to write figures and the summary (default: run/report).")
    ] = None,
) -> None:
    """Build figures and a markdown summary from a saved run (reads only its Parquet and run record)."""
    from vesuvius_challenge import synth_report

    out = out or run_dirs[0] / "report"
    ui.banner(
        "vch synth report",
        "Reads a saved sweep (cases.parquet, details-*.parquet, run.json) and writes figures, acceptance verdicts "
        "and a markdown summary. It runs no estimator.",
        {"runs": ", ".join(str(r) for r in run_dirs)},
        out,
    )
    record = RunRecord("synth-report", {"run_dirs": [repo_path(r) for r in run_dirs]})
    written, verdicts = synth_report.build(run_dirs, out)
    record.results = {"verdicts": verdicts}
    record.outputs = [repo_path(p) for p in written]
    record_path = record.finish(out / "report.run.json")
    ui.summary(
        "Synthetic report",
        [(name, v["verdict"], v["detail"]) for name, v in verdicts.items()],
        [*written, record_path],
        record.reproduce,
    )
