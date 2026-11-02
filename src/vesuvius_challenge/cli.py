"""`vch`: one command per stage of the Vesuvius Challenge tooling."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Annotated, Any

import humanize
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import typer
from rich.traceback import install

from vesuvius_challenge import fetch as fetching
from vesuvius_challenge import render as rendering
from vesuvius_challenge import security, ui, verify
from vesuvius_challenge import selftest as selftests
from vesuvius_challenge import survey as surveying
from vesuvius_challenge.runrecord import RunRecord, load_record
from vesuvius_challenge.s3 import Bucket, IncompleteDownload
from vesuvius_challenge.security import from_repo_path, repo_path, scan_figures, scan_identity
from vesuvius_challenge.synth_cli import synth_app

install(show_locals=False)

app = typer.Typer(
    help="Vesuvius Challenge tooling: survey, fetch, render, verify-io, selftest, synth.", no_args_is_help=True
)
app.add_typer(synth_app, name="synth")

DATA_ROOT = Path("data")
Out = Annotated[Path, typer.Option(help="Directory for the Parquet table and run record.")]


def main() -> None:
    app()


@app.command()
def survey(
    sample: Annotated[str, typer.Argument(help="Sample in the bucket, e.g. PHercParis4.")],
    out: Out = DATA_ROOT / "derived" / "survey",
    legacy: Annotated[bool, typer.Option(help="Also read legacy paths/ on dl.ash2txt.org.")] = True,
    workers: Annotated[int, typer.Option(min=1, max=32, help="Parallel requests.")] = 12,
) -> None:
    """List a sample's segments from anonymous S3: meshes, tags, area and superseded status."""
    table_path = out / f"{sample}.parquet"
    ui.banner(
        "vch survey",
        "Lists every segment of one sample in the public bucket and reads each mesh's meta.json. "
        "No scroll data is downloaded, only listings and metadata.",
        {"sample": sample, "legacy paths": legacy, "workers": workers},
        table_path,
    )
    record = RunRecord("survey", {"sample": sample, "legacy": legacy, "workers": workers})
    bucket = Bucket()

    catalog = bucket.get_json("metadata.json")["samples"]
    if sample not in catalog:
        raise typer.BadParameter(f"{sample} is not in the bucket; known: {', '.join(sorted(catalog))}")
    sample_meta = catalog[sample]
    prefixes = bucket.child_prefixes(f"{sample}/segments/")
    volumes = {p.split("/")[-2].split("-")[0]: p for p in bucket.child_prefixes(f"{sample}/volumes/")}
    legacy_url = (sample_meta.get("sample", {}).get("properties") or {}).get("legacy_data_url") if legacy else None
    legacy_names: list[str] = []
    if legacy_url:
        html = bucket.get_url_bytes(legacy_url.rstrip("/") + "/paths/").decode(errors="replace")
        legacy_names = surveying.parse_autoindex(html)

    progress = ui.item_progress()
    s3_task = progress.add_task("S3 segments", total=len(prefixes), rate="- seg/s")
    legacy_task = progress.add_task("Legacy paths/", total=len(legacy_names), rate="- dir/s", visible=bool(legacy_url))
    s3_rows: list[dict[str, Any]] = []
    legacy_rows: list[dict[str, Any]] = []
    started = time.monotonic()

    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:

        def on_s3(row: dict[str, Any]) -> None:
            s3_rows.append(row)
            progress.update(
                s3_task,
                advance=1,
                rate=ui.per_second(len(s3_rows), time.monotonic() - started, "seg"),
            )
            stats = surveying.summarise(s3_rows)
            board.stats(
                segments=stats["segments_on_s3"],
                with_tifxyz=stats["with_tifxyz"],
                tagged=stats["segments_with_any_tag"],
                ink_labels=stats["with_ink_labels"],
            )

        board.explain(
            "Reading each segment's mesh folder. A segment usually has several tifxyz copies, one per "
            "registered volume, so we record which volume the primary mesh belongs to. Tags decide which "
            "segments can act as reviewed ground truth later."
        )
        surveying.run_parallel(
            prefixes,
            lambda prefix: surveying.survey_s3_segment(bucket, sample, prefix, sample_meta, volumes),
            workers,
            on_s3,
            lambda: stop.requested,
        )

        if legacy_url and not stop.requested:
            board.explain(
                "Reading the legacy volume package. Superseded folders only exist here, and the "
                "June candidate segments may survive only in this tree."
            )
            surveying.run_parallel(
                legacy_names,
                lambda name: surveying.survey_legacy_segment(bucket, sample, legacy_url, name),
                workers,
                lambda row: (legacy_rows.append(row), progress.update(legacy_task, advance=1, rate="")),
                lambda: stop.requested,
            )

    rows = surveying.merge_rows(s3_rows, legacy_rows)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=surveying.SCHEMA), table_path)
    stats = surveying.summarise(rows)
    record.results = stats
    record.outputs = [repo_path(table_path)]
    record_path = record.finish(out / f"{sample}.run.json", partial=stop.requested)

    tags = ", ".join(f"{k} {v}" for k, v in stats["tag_distribution"].items()) or "none"
    ui.summary(
        f"Survey of {sample}",
        [
            ("Segments on S3", str(stats["segments_on_s3"]), "Directories under segments/ in the bucket."),
            ("With tifxyz", str(stats["with_tifxyz"]), "Segments that have a complete x/y/z + meta.json mesh."),
            ("Legacy only", str(stats["legacy_only"]), "Folders that exist in legacy paths/ but not on S3."),
            ("Superseded", str(stats["superseded"]), "Folders renamed with the _superseded suffix."),
            ("Tags", tags, "Review tags in meta.json. Absent tags do not mean unreviewed."),
            ("Primary meshes", humanize.naturalsize(stats["mesh_bytes_primary"]), "Disk needed to fetch them all."),
        ],
        [table_path, record_path],
        record.reproduce,
        stop.requested,
    )


@app.command()
def fetch(
    sample: Annotated[str, typer.Argument(help="Sample in the bucket.")],
    segment_id: Annotated[str, typer.Argument(help="Segment timestamp or full directory name.")],
    volume: Annotated[str | None, typer.Option(help="Volume id of the mesh variant to fetch.")] = None,
    root: Annotated[Path, typer.Option(help="Data root (gitignored).")] = DATA_ROOT,
    manifests: Annotated[Path, typer.Option(help="Directory for the committed manifest copy.")] = Path("manifests"),
) -> None:
    """Download a segment's tifxyz mesh with resume, and write a SHA-256 manifest."""
    bucket = Bucket()
    prefix = fetching.resolve_segment_prefix(bucket, sample, segment_id)
    identifier = surveying.segment_id(prefix.rstrip("/").rpartition("/")[2])
    catalog = bucket.get_json("metadata.json")["samples"].get(sample, {})
    original = catalog.get("segments", {}).get(identifier, {}).get("original_volume_id")
    variants = surveying.find_mesh_variants(bucket.list(prefix + "mesh/")[0])
    variant = fetching.select_variant(variants, original, volume)
    dest = root / "segments" / sample / identifier
    total = sum(obj.size for obj in variant.objects)

    ui.banner(
        "vch fetch",
        "Downloads one tifxyz mesh and its meta.json, resuming any partial file, then records the "
        "URL, size and SHA-256 of each file. The data stays under data/, which git ignores.",
        {
            "sample": sample,
            "segment": identifier,
            "mesh": variant.prefix.rstrip("/").rpartition("/")[2],
            "size": humanize.naturalsize(total),
        },
        dest,
    )
    record = RunRecord("fetch", {"sample": sample, "segment": identifier, "volume": volume})
    progress = ui.byte_progress()
    task = progress.add_task("Mesh files", total=total)
    partial = False
    hashes: dict[str, str] = {}
    fetched: list[Any] = []

    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
        board.explain(
            "x.tif, y.tif and z.tif hold the 3D position of each mesh grid point. They are saved "
            "flat in one folder because that folder is what the renderer reads as a tifxyz."
        )
        board.stats(files=len(variant.objects), resumed_bytes=humanize.naturalsize(fetching.part_bytes(dest)))
        try:
            hashes, fetched = fetching.download_variant(
                bucket, variant, dest, lambda n: progress.advance(task, n), lambda: stop.requested
            )
        except IncompleteDownload:
            partial = True

    outputs: list[Path] = []
    results: dict[str, Any] = {"bytes": total, "mesh": variant.prefix, "volume_id": variant.volume_id}
    if not partial:
        volume_prefix = fetching.find_volume_prefix(bucket, sample, variant.volume_id)
        manifest = fetching.build_manifest(sample, identifier, variant, bucket, hashes, volume_prefix)
        outputs = [
            fetching.write_manifest(manifest, dest / fetching.MANIFEST),
            fetching.write_manifest(manifest, manifests / sample / f"{identifier}.json"),
        ]
        results["files_downloaded"] = len(fetched)
        results["volume_path"] = volume_prefix
    record.results = results
    record.outputs = [repo_path(path) for path in outputs]
    record_path = record.finish(dest / "fetch.run.json", partial=partial)
    ui.summary(
        f"Fetch of {identifier}",
        [
            ("Size", humanize.naturalsize(total), "Mesh bytes on disk."),
            ("Downloaded", f"{len(fetched)} of {len(variant.objects)}", "Files already complete are not fetched."),
            ("Voxel size", f"{variant.voxel_um} um", "The mesh coordinates are in voxels of this volume."),
            ("Volume", str(variant.volume_id), "Render with this volume, or the geometry will not line up."),
        ],
        [*outputs, record_path],
        record.reproduce,
        partial,
    )


@app.command()
def render(
    segment_dir: Annotated[Path, typer.Argument(help="Folder from `vch fetch`.", exists=True, file_okay=False)],
    num_slices: Annotated[int, typer.Option("--num-slices", "-n", min=1, help="Layers to render.")],
    slice_step: Annotated[float, typer.Option("--slice-step", "-s", min=0.0, help="Voxels between layers.")],
    crop: Annotated[str | None, typer.Option(help="x,y,width,height in output pixels.")] = None,
    volume_url: Annotated[str | None, typer.Option(help="Zarr URL; defaults to the manifest's.")] = None,
    scale: Annotated[float, typer.Option(help="Output pixels per level voxel.")] = 1.0,
    group_idx: Annotated[int, typer.Option(min=0, help="OME-Zarr pyramid level.")] = 0,
    cache_gb: Annotated[int, typer.Option(min=1, help="Renderer chunk cache in GB.")] = 4,
    root: Annotated[Path, typer.Option(help="Data root, mounted at /data in the container.")] = DATA_ROOT,
    overwrite: Annotated[bool, typer.Option(help="Delete existing layers and render again.")] = False,
    dry_run: Annotated[bool, typer.Option(help="Print the command and stop.")] = False,
) -> None:
    """Render a surface volume with VC3D's vc_render_tifxyz in Podman, with explicit layer flags."""
    manifest = fetching.read_manifest(segment_dir)
    url = volume_url or manifest.get("volume_url")
    if not url:
        raise typer.BadParameter("the manifest names no volume on S3; pass --volume-url")
    window = rendering.Crop.parse(crop) if crop else None
    tag = f"n{num_slices}_s{slice_step:g}_" + (window.tag() if window else "full")
    output_dir = root / "renders" / manifest["sample"] / manifest["segment"] / tag
    k0 = rendering.on_surface_layer(num_slices)
    try:
        digest = rendering.image_digest()
    except (OSError, subprocess.CalledProcessError) as error:
        if not dry_run:
            raise typer.BadParameter(f"cannot read the image digest from Podman: {error}") from error
        digest = None
    container = f"vch-render-{os.getpid()}"
    try:
        command = rendering.build_command(
            digest=digest,
            data_root=root,
            segment_dir=segment_dir,
            output_dir=output_dir,
            volume_url=url,
            num_slices=num_slices,
            slice_step=slice_step,
            scale=scale,
            group_idx=group_idx,
            cache_gb=cache_gb,
            crop=window,
            container_name=container,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    params = {
        "segment_dir": repo_path(segment_dir),
        "num_slices": num_slices,
        "slice_step": slice_step,
        "crop": window.__dict__ if window else None,
        "volume_url": url,
        "scale": scale,
        "group_idx": group_idx,
        "cache_gb": cache_gb,
    }
    record = RunRecord("render", params, image_digest=digest)
    if dry_run:
        shell = rendering.shell_command(command)
        record.results = {"dry_run": True, "command": command, "command_shell": shell, "on_surface_layer": k0}
        record_path = record.finish(output_dir / "render.dry-run.run.json", partial=True)
        ui.console.print(shell, soft_wrap=True, highlight=False, markup=False)
        ui.console.print(f"[green]saved[/green] {record_path}", soft_wrap=True)
        return

    try:
        rendering.prepare_output(output_dir, overwrite)
    except FileExistsError as error:
        raise typer.BadParameter(str(error)) from error

    ui.banner(
        "vch render",
        "Streams the volume from S3 through VC3D's renderer and writes one TIFF per layer. Each "
        "layer is the volume sampled at a fixed distance along the mesh normal.",
        {
            "layers": num_slices,
            "step": f"{slice_step:g} voxels",
            "on-surface layer": k0 if k0 is not None else "none (even layer count)",
            "crop": window or "full surface",
            "image": digest,
        },
        output_dir,
    )
    progress = ui.item_progress()
    bands = progress.add_task("Rendering bands", total=None, rate="- band/s")
    stats_task = progress.add_task("Layer statistics", total=num_slices, rate="- layer/s", visible=False)
    started = time.monotonic()
    rendered_bands = [0]

    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
        board.explain(
            "The renderer walks the surface in horizontal bands, fetching only the volume chunks each "
            "band touches. Explicit flags matter here: community datasets disagree on layer conventions."
        )
        board.stats(on_surface_layer=k0, layers=num_slices)

        def on_line(line: str) -> None:
            if found := rendering.BAND_PROGRESS.search(line):
                done, total = int(found[1]), int(found[2])
                rendered_bands[0] = done
                elapsed = time.monotonic() - started
                progress.update(bands, completed=done, total=total, rate=ui.per_second(done, elapsed, "band"))
                board.stats(bands=f"{done} of {total}")

        code, log = rendering.run_streaming(rendering.expand_pwd(command), on_line, lambda: stop.requested, container)
        render_seconds = time.monotonic() - started
        files = rendering.layer_files(output_dir)
        layers: list[dict[str, Any]] = []
        board.explain(
            "Checking the output and hashing every layer. The pixel hashes let a later run prove it "
            "reproduced this render exactly."
        )
        progress.update(stats_task, visible=True, total=len(files) or 1)
        for path in files:
            layers.append(rendering.layer_statistics(path))
            progress.update(stats_task, advance=1, rate="")
            board.stats(last_layer_std=f"{layers[-1]['std']:.2f}")

    partial = stop.requested or code != 0 or len(files) != num_slices
    record.results = {
        "exit_code": code,
        "command": command,
        "command_shell": rendering.shell_command(command),
        "num_slices": num_slices,
        "slice_step": slice_step,
        "on_surface_layer": k0,
        "offsets_voxels": rendering.layer_offsets(num_slices, slice_step),
        "render_seconds": render_seconds,
        "voxel_um": manifest.get("voxel_um"),
        "volume_id": manifest.get("volume_id"),
        "shape": layers[0]["shape"] if layers else None,
        "dtype": layers[0]["dtype"] if layers else None,
        "layers": layers,
        "renderer_log": log.splitlines()[-40:],
    }
    record.outputs = [repo_path(path) for path in files]
    record_path = record.finish(output_dir / "render.run.json", partial=partial)
    if code != 0:
        ui.console.print(f"[red]Renderer exited with code {code}[/red]\n{log[-2000:]}", markup=True)
    shape = "x".join(str(n) for n in layers[0]["shape"]) if layers else "-"
    ui.summary(
        f"Render of {manifest['segment']}",
        [
            ("Layers", f"{len(files)} of {num_slices}", "One TIFF per layer in layers/."),
            ("On-surface layer", str(k0), "Zero offset along the normal; layer files are numbered from 0."),
            ("Shape, dtype", f"{shape} {layers[0]['dtype'] if layers else '-'}", "Pixels per layer."),
            ("Voxel size", f"{manifest.get('voxel_um')} um", "One step of 1 moves this far along the normal."),
            ("Time", humanize.precisedelta(render_seconds), "Render only, streaming from S3."),
        ],
        [output_dir / "layers", record_path],
        record.reproduce,
        partial,
    )
    if code != 0:
        raise typer.Exit(code)


@app.command("verify-io")
def verify_io(
    render_dir: Annotated[Path, typer.Argument(help="Render folder holding render.run.json.", exists=True)],
    stride: Annotated[int, typer.Option(min=1, help="Sample every Nth pixel.")] = 4,
    probe: Annotated[int, typer.Option(min=1, help="Layers from k0 for the normal-sign test.")] = 5,
    figure: Annotated[bool, typer.Option(help="Also save layers k0-1, k0, k0+1 under data/.")] = False,
    root: Annotated[Path, typer.Option(help="Data root (gitignored).")] = DATA_ROOT,
) -> None:
    """Prove the I/O path: compare a render with the same surface read through `vesuvius`."""
    from vesuvius import Volume

    saved = load_record(render_dir / "render.run.json")
    params, results = saved["params"], saved["results"]
    segment_dir = from_repo_path(params["segment_dir"])
    if not params["crop"]:
        raise typer.BadParameter("verify-io needs a cropped render")
    crop = rendering.Crop(**params["crop"])
    k0 = results["on_surface_layer"]
    if k0 is None:
        raise typer.BadParameter("verify-io needs an odd layer count so that a layer sits on the surface")
    layers = rendering.layer_files(render_dir)
    output = render_dir / "verify-io.run.json"
    ui.banner(
        "vch verify-io",
        "Reads the mesh with vesuvius.tifxyz, streams the same voxels with vesuvius.Volume, and "
        "correlates them with the render. Two independent code paths that agree prove the I/O.",
        {"render": render_dir.name, "stride": stride, "sign probe": f"+/-{probe} layers", "figure": figure},
        output,
    )
    record = RunRecord("verify-io", {"render_dir": repo_path(render_dir), "stride": stride, "probe": probe})
    record.image_digest = saved.get("image_digest")
    progress = ui.item_progress()
    task = progress.add_task("I/O proof", total=4, rate="")
    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
        board.explain("Reading the mesh through vesuvius.tifxyz and interpolating it to full resolution.")
        started = time.monotonic()
        surface = verify.surface_points(segment_dir, crop, stride)
        progress.advance(task)
        board.stats(mesh_seconds=f"{time.monotonic() - started:.1f}", valid=f"{surface['valid_fraction']:.1%}")

        board.explain("Streaming only the volume block under this crop from S3 through vesuvius.Volume.")
        started = time.monotonic()
        volume = Volume(type="zarr", path=Bucket.s3_uri(params["volume_url"]), anon=True, verbose=False)
        bounds = verify.block_bounds(surface["points"], volume.shape(0), pad=probe + 6)
        block = np.asarray(volume[slice(*bounds[0]), slice(*bounds[1]), slice(*bounds[2])])
        block_seconds = time.monotonic() - started
        progress.advance(task)
        board.stats(block=f"{block.shape}", block_seconds=f"{block_seconds:.1f}")

        board.explain(
            "Correlating the rendered on-surface layer with Python samples at the same points, then at "
            "small offsets along the normal. The best offset should be zero."
        )
        origin = np.array([bound[0] for bound in bounds], dtype=np.float32)
        comparison = verify.compare_with_render(
            block, origin, surface["points"], surface["normals"], layers, k0, stride, probe
        )
        progress.advance(task)
        board.stats(pearson_k0=f"{comparison['pearson_k0']:.3f}", best_offset=comparison["best_python_offset"])
        figure_path = None
        if figure:
            name = f"{Path(params['segment_dir']).name}_{render_dir.name}_layers.png"
            figure_path = verify.save_layer_figure(layers, k0, root / "derived" / "figures" / name)
        progress.advance(task)

    plus, minus = comparison["pearson_probe_plus_normal"], comparison["pearson_probe_minus_normal"]
    record.results = {
        **comparison,
        "volume_shape_level0": list(volume.shape(0)),
        "block_shape": list(block.shape),
        "block_seconds": block_seconds,
        "mesh_stored_shape": surface["stored_shape"],
        "mesh_full_shape": surface["full_shape"],
        "mesh_scale": surface["scale"],
        "valid_fraction": surface["valid_fraction"],
        "layer_above_k0_is": "plus_normal" if plus > minus else "minus_normal",
    }
    if figure_path:
        record.outputs = [repo_path(figure_path)]
    record_path = record.finish(output, partial=stop.requested)
    ui.summary(
        "I/O proof",
        [
            (
                "r at k0",
                f"{comparison['pearson_k0']:.4f}",
                "Render against vesuvius at the same points; near 1 is good.",
            ),
            ("Best offset", str(comparison["best_python_offset"]), "Voxels along the normal; 0 means aligned."),
            (
                "Layer above k0",
                record.results["layer_above_k0_is"],
                "Direction of rising layer index, vesuvius normal.",
            ),
            (
                "r plus, minus",
                f"{plus:.3f}, {minus:.3f}",
                f"Layer {comparison['probe_layer']} against both directions.",
            ),
        ],
        [path for path in (record_path, figure_path) if path],
        record.reproduce,
        stop.requested,
    )


@app.command()
def scan() -> None:
    """Check tracked files for machine identity, key headers and unregistered images."""
    output = Path("runs") / "scan.run.json"
    checks = [
        ("Identity and paths", scan_identity, "Looks for home paths, this machine's names and key headers."),
        ("Figure register", scan_figures, "Every tracked image must be listed in FIGURES.md, and none render-derived."),
    ]
    ui.banner(
        "vch scan",
        "Runs the same checks as the pre-commit hooks and CI over every tracked file. "
        "It reports where a problem is, not the matched text, so its output cannot repeat a leak.",
        {"checks": len(checks), "root": "<repo>"},
        output,
    )
    record = RunRecord("scan", {"checks": [name for name, _, _ in checks]})
    progress = ui.item_progress()
    task = progress.add_task("Checks", total=len(checks), rate="")
    findings: list[Any] = []
    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
        for _, check, why in checks:
            if stop.requested:
                break
            board.explain(why)
            findings += check(security.REPO_ROOT)
            progress.advance(task)
            board.stats(findings=len(findings))
    record.results = {"findings": [str(finding) for finding in findings]}
    record_path = record.finish(output, partial=stop.requested)
    for finding in findings:
        ui.console.print(f"[red]{finding}[/red]", soft_wrap=True, markup=True, highlight=False)
    ui.summary(
        "Security scan",
        [("Findings", str(len(findings)), "Zero means a commit would pass these checks.")],
        [record_path],
        record.reproduce,
        stop.requested,
    )
    if findings:
        raise typer.Exit(1)


@app.command("selftest")
def selftest() -> None:
    """Check the fast paths against slow references, on synthetic data only."""
    output = Path("runs") / "selftest.run.json"
    ui.banner(
        "vch selftest",
        "Runs every fast path against a slow reference on data generated in-process. "
        "Needs no scroll data, no network and no container.",
        {"checks": len(selftests.CHECKS), "seed": 2026},
        output,
    )
    record = RunRecord("selftest", {"checks": len(selftests.CHECKS)}, seed=2026)
    progress = ui.item_progress()
    task = progress.add_task("Checks", total=len(selftests.CHECKS), rate="")
    outcomes: list[tuple[str, str, str]] = []
    failed = 0
    with ui.GracefulStop() as stop, ui.Dashboard(progress) as board:
        for name, check in selftests.CHECKS:
            if stop.requested:
                break
            board.explain(f"Checking: {name}.")
            started = time.monotonic()
            try:
                check()
            except Exception as error:  # noqa: BLE001 - a selftest reports every failure
                failed += 1
                outcomes.append((name, "[red]FAIL[/red]", f"{type(error).__name__}: {error}"))
            else:
                outcomes.append((name, "[green]pass[/green]", f"{time.monotonic() - started:.2f} s"))
            progress.advance(task)
            board.stats(passed=len(outcomes) - failed, failed=failed)
    record.results = {"passed": len(outcomes) - failed, "failed": failed, "checks": [list(row) for row in outcomes]}
    record_path = record.finish(output, partial=stop.requested)
    ui.summary("Selftest", outcomes, [record_path], record.reproduce, stop.requested)
    if failed:
        raise typer.Exit(1)
