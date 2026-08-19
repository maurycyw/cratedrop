"""cratedrop CLI. Thin layer: commands parse args, call into modules, render."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import SETTING_KEYS, Config

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Headless CDJ USB builder (export.pdb + ANLZ, no Rekordbox).")
config_app = typer.Typer(no_args_is_help=True, help="Get/set staging and processed dirs.")
app.add_typer(config_app, name="config")

console = Console()


@config_app.command("set")
def config_set(key: str = typer.Argument(help=f"one of: {', '.join(SETTING_KEYS)}"),
               value: str = typer.Argument(help="directory path")) -> None:
    cfg = Config.load()
    try:
        cfg.set(key, value)
    except KeyError as exc:
        console.print(f"[red]{exc.args[0]}[/red]")
        raise typer.Exit(1)
    path = Path(value).expanduser().resolve()
    if not path.exists():
        path.mkdir(parents=True)
        console.print(f"created {path}")
    cfg.save()
    console.print(f"[green]{key}[/green] = {path}")


@config_app.command("show")
def config_show() -> None:
    cfg = Config.load()
    console.print(f"staging-dir   = {cfg.staging_dir or '[dim]unset[/dim]'}")
    console.print(f"processed-dir = {cfg.processed_dir or '[dim]unset[/dim]'}")


@app.command()
def doctor() -> None:
    """Check the environment: binaries, libraries, config."""
    from .doctor import run_checks

    table = Table(title="cratedrop doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    failures = 0
    for c in run_checks():
        if c.ok:
            status = "[green]ok[/green]"
        elif c.required:
            status = "[red]MISSING[/red]"
            failures += 1
        else:
            status = "[yellow]absent[/yellow]"
        table.add_row(c.name, status, c.detail)
    console.print(table)
    if failures:
        console.print(f"[red]{failures} required check(s) failed[/red]")
        raise typer.Exit(1)


@app.command()
def inspect(path: Path = typer.Argument(help="USB root, processed dir, .pdb file, or ANLZ file")) -> None:
    """Pretty-print a device database or analysis file."""
    from .inspect import inspect_path

    inspect_path(console, path)


@app.command()
def diff(ours: Path, golden: Path,
         raw: bool = typer.Option(False, "--raw", help="include masked/expected differences")) -> None:
    """Structure-aware diff of two .pdb or ANLZ files (or USB trees)."""
    from .verify.diff import diff_paths

    changed = diff_paths(console, ours, golden, show_masked=raw)
    raise typer.Exit(1 if changed else 0)


@app.command()
def process(template: Path = typer.Option(
        None, "--template",
        help="golden USB capture dir to seed export.pdb from")) -> None:
    """Analyze staged tracks and update the processed USB image."""
    from .export.builder import build_image

    cfg = Config.load()
    staging = cfg.require("staging-dir")
    processed = cfg.require("processed-dir")
    report = build_image(staging, processed, template_dir=template)
    for warning in report.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")
    console.print(f"tracks in image: [bold]{report.tracks}[/bold]  "
                  f"(analyzed {len(report.analyzed)}, cached {len(report.cached)}, "
                  f"audio copied {len(report.copied)})")
    console.print(f"image: {processed}")


@app.command()
def flash(volume: str = typer.Option(..., "--volume", help="mounted volume name under /Volumes"),
          dry_run: bool = typer.Option(False, "--dry-run"),
          prune: bool = typer.Option(False, "--prune"),
          eject: bool = typer.Option(False, "--eject")) -> None:
    """Sync the processed image to a USB stick (preserving deck-written data)."""
    import datetime

    from .deploy import usb

    cfg = Config.load()
    processed = cfg.require("processed-dir")
    try:
        mount = usb.check_target(volume)
        plan = usb.plan_sync(processed, mount)
    except usb.FlashRefused as exc:
        console.print(f"[red]refused:[/red] {exc}")
        raise typer.Exit(1)

    if plan.deck_modified:
        console.print(f"[yellow]deck-modified files detected "
                      f"({len(plan.deck_modified)}):[/yellow] "
                      "snapshotting before overwrite (harvest/merge lands in M3.5)")
    for rel in plan.copy[:30]:
        console.print(f"  [green]copy[/green] {rel}")
    if len(plan.copy) > 30:
        console.print(f"  … +{len(plan.copy) - 30} more")
    for rel in plan.delete:
        console.print(f"  [red]{'delete' if prune else 'would delete (--prune)'}[/red] {rel}")
    console.print(f"{len(plan.copy)} to copy, {plan.unchanged} unchanged, "
                  f"{len(plan.delete)} prunable")
    if dry_run:
        console.print("[dim]dry run: nothing written[/dim]")
        return

    if plan.deck_modified:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        saved = usb.snapshot_deck_writes(
            mount, plan, processed / ".cratedrop" / "deck-writes" / stamp)
        console.print(f"snapshotted {len(saved)} deck-modified file(s)")
    usb.apply_sync(processed, mount, plan, prune=prune)
    console.print(f"[green]flashed[/green] {mount}")
    if eject:
        ok = usb.eject(mount)
        console.print("[green]ejected[/green]" if ok
                      else "[yellow]eject failed — eject manually[/yellow]")


@app.command()
def harvest(volume: str = typer.Option(..., "--volume")) -> None:
    """Import deck-written cues/history from a stick without flashing. (M3.5)"""
    console.print("[yellow]not implemented yet (milestone M3.5)[/yellow]")
    raise typer.Exit(2)


@app.command()
def status() -> None:
    """Show staging vs processed: new / changed / ingested."""
    from .audio.tags import sha1_file
    from .export.builder import load_manifest, scan_staging

    cfg = Config.load()
    staging = cfg.require("staging-dir")
    processed = cfg.require("processed-dir")
    staged = scan_staging(staging)
    manifest = load_manifest(processed) or {}
    known = {entry.get("sha1") for entry in manifest.values()}
    new = [p for p in staged if sha1_file(p) not in known]
    console.print(f"staging: {len(staged)} audio files "
                  f"([bold]{len(new)}[/bold] not yet in image)")
    for p in new[:20]:
        console.print(f"  [yellow]new[/yellow] {p.relative_to(staging)}")
    console.print(f"image: {len(manifest)} files at {processed}"
                  if manifest else "image: not built yet (run: cratedrop process)")


if __name__ == "__main__":
    app()
