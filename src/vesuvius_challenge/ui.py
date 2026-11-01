"""Terminal interface shared by every `vch` command (the python-lab-ux floor)."""

from __future__ import annotations

import signal
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import FrameType
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

ACCENT = "dark_orange3"

console = Console()


def banner(title: str, what: str, settings: Mapping[str, Any], output: Path | str) -> None:
    """Print the startup panel: what runs, with which settings, and where it writes."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=ACCENT, no_wrap=True)
    grid.add_column()
    for key, value in settings.items():
        grid.add_row(key, str(value))
    grid.add_row("output", str(output))
    body = Table.grid()
    body.add_row(Text(what))
    body.add_row("")
    body.add_row(grid)
    console.print(Panel(body, title=f"[bold]{title}[/bold]", border_style=ACCENT))


def item_progress() -> Progress:
    """Progress bar for countable items: M of N, rate, elapsed and ETA."""
    return Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(complete_style=ACCENT),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.fields[rate]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    )


def byte_progress() -> Progress:
    """Progress bar for byte transfers: size done of total, speed, elapsed and ETA."""
    return Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(complete_style=ACCENT),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    )


def per_second(done: int, elapsed: float | None, unit: str) -> str:
    """Format a throughput for the `rate` progress field."""
    if not elapsed or not done:
        return f"- {unit}/s"
    return f"{done / elapsed:,.1f} {unit}/s"


class Dashboard:
    """Live layout: progress on the left, explanation and running statistics on the right."""

    def __init__(self, progress: Progress) -> None:
        self.progress = progress
        self._explain = ""
        self._stats: dict[str, str] = {}
        self._live = Live(self._render(), console=console, refresh_per_second=8, transient=False)

    def _render(self) -> Layout:
        stats = Table.grid(padding=(0, 2))
        stats.add_column(style=ACCENT, no_wrap=True)
        stats.add_column(justify="right")
        for key, value in self._stats.items():
            stats.add_row(key, value)
        layout = Layout(size=11)
        layout.split_row(
            Layout(Panel(self.progress, title="Progress", border_style=ACCENT), ratio=3),
            Layout(name="side", ratio=2),
        )
        layout["side"].split_column(
            Layout(Panel(Text(self._explain), title="What this stage does and why", border_style=ACCENT)),
            Layout(Panel(stats, title="Live statistics", border_style=ACCENT)),
        )
        return layout

    def explain(self, text: str) -> None:
        self._explain = text
        self._live.update(self._render())

    def stats(self, **values: Any) -> None:
        self._stats.update({key.replace("_", " "): str(value) for key, value in values.items()})
        self._live.update(self._render())

    def __enter__(self) -> Dashboard:
        self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._live.update(self._render())
        self._live.stop()


class GracefulStop:
    """First Ctrl-C asks the work to stop and save; a second one aborts immediately."""

    def __init__(self) -> None:
        self.requested = False
        self._previous: Any = None

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self.requested:
            raise KeyboardInterrupt
        self.requested = True
        console.print("[yellow]Stopping after the current item; partial results will be saved.[/yellow]")

    def __enter__(self) -> GracefulStop:
        self._previous = signal.signal(signal.SIGINT, self._handle)
        return self

    def __exit__(self, *exc: object) -> None:
        signal.signal(signal.SIGINT, self._previous)


def summary(
    title: str,
    rows: Iterable[tuple[str, str, str]],
    paths: Iterable[Path | str],
    reproduce: str,
    partial: bool = False,
) -> None:
    """Print the closing table with interpretations, saved paths and the reproduce command."""
    table = Table(title=title + (" [yellow](partial)[/yellow]" if partial else ""), border_style=ACCENT)
    table.add_column("Result", style=ACCENT, no_wrap=True)
    table.add_column("Value", justify="right", no_wrap=True)
    table.add_column("What it means")
    for name, value, meaning in rows:
        table.add_row(name, value, meaning)
    console.print(table)
    for path in paths:
        console.print(f"[green]saved[/green] {path}", soft_wrap=True)
    console.print(f"[{ACCENT}]reproduce[/{ACCENT}] {reproduce}", soft_wrap=True, markup=True, highlight=False)
