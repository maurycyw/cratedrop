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

    from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                               TextColumn, TimeRemainingColumn)

    cfg = Config.load()
    staging = cfg.require("staging-dir")
    processed = cfg.require("processed-dir")
    with Progress(TextColumn("processing"), BarColumn(), MofNCompleteColumn(),
                  TimeRemainingColumn(), TextColumn("{task.fields[name]}"),
                  console=console) as progress:
        task = progress.add_task("process", total=None, name="scanning…")

        def on_track(i: int, total: int, name: str) -> None:
            progress.update(task, total=total, completed=i, name=name[:50])

        report = build_image(staging, processed, template_dir=template,
                             on_track=on_track)
        progress.update(task, completed=report.tracks, name="writing database…")
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
          eject: bool = typer.Option(False, "--eject"),
          no_harvest: bool = typer.Option(False, "--no-harvest")) -> None:
    """Sync the processed image to a USB stick (harvesting deck-written data first)."""
    import datetime

    from .deploy import usb
    from .deploy.harvest import harvest as run_harvest

    cfg = Config.load()
    processed = cfg.require("processed-dir")
    try:
        mount = usb.check_target(volume)
        with console.status("checking stick (verifying PIONEER files)…"):
            plan = usb.plan_sync(processed, mount)
    except usb.FlashRefused as exc:
        console.print(f"[red]refused:[/red] {exc}")
        raise typer.Exit(1)

    if plan.deck_modified and not no_harvest and not dry_run:
        report = run_harvest(mount, processed)
        _print_harvest(report)
        if report.tracks_updated:
            from .export.builder import build_image
            staging = cfg.require("staging-dir")
            build_image(staging, processed)
            console.print("[green]image rebuilt with harvested cues[/green]")
            plan = usb.plan_sync(processed, mount)

    if plan.deck_modified:
        console.print(f"[yellow]{len(plan.deck_modified)} deck-modified file(s):[/yellow] "
                      "raw copies snapshotted before overwrite")
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
    from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                               TimeRemainingColumn, TransferSpeedColumn)

    total_bytes = sum((processed / rel).stat().st_size for rel in plan.copy
                      if (processed / rel).exists())
    with Progress(TextColumn("copying"), BarColumn(), DownloadColumn(),
                  TransferSpeedColumn(), TimeRemainingColumn(),
                  TextColumn("{task.fields[name]}"), console=console) as progress:
        task = progress.add_task("flash", total=total_bytes, name="")

        def on_file(rel: str, size: int) -> None:
            progress.update(task, advance=size, name=rel.rsplit("/", 1)[-1][:40])

        usb.apply_sync(processed, mount, plan, prune=prune, on_file=on_file)
    console.print(f"[green]flashed[/green] {mount}")
    if eject:
        ok = usb.eject(mount)
        console.print("[green]ejected[/green]" if ok
                      else "[yellow]eject failed — eject manually[/yellow]")


@app.command()
def harvest(volume: str = typer.Option(..., "--volume")) -> None:
    """Import deck-written cues/history from a stick without flashing."""
    from .deploy import usb
    from .deploy.harvest import harvest as run_harvest

    cfg = Config.load()
    processed = cfg.require("processed-dir")
    try:
        mount = usb.check_target(volume)
    except usb.FlashRefused as exc:
        console.print(f"[red]refused:[/red] {exc}")
        raise typer.Exit(1)
    report = run_harvest(mount, processed)
    _print_harvest(report)


def _print_harvest(report) -> None:
    console.print(f"harvest: {report.cues_found} deck cue(s), "
                  f"{len(report.tracks_updated)} track(s) updated, "
                  f"{report.history_playlists} history playlist(s) archived")
    for title in report.tracks_updated[:20]:
        console.print(f"  [green]cues merged:[/green] {title}")
    if report.loops_skipped:
        console.print(f"  [yellow]{report.loops_skipped} loop cue(s) skipped "
                      "(loops not modeled yet)[/yellow]")
    for rel in report.unmatched_anlz[:10]:
        console.print(f"  [dim]unmatched analysis file: {rel}[/dim]")


@app.command()
def enrich(min_score: float = typer.Option(0.72, "--min-score"),
           dry_run: bool = typer.Option(False, "--dry-run"),
           force: bool = typer.Option(False, "--force", help="re-query tracks that already have a sidecar")) -> None:
    """Fill missing artwork/metadata from Deezer/iTunes (never overwrites
    existing tags, folder names, or manual data). Run process afterwards."""
    import json as _json

    from rich.table import Table

    from . import enrich as en
    from .audio.artwork import extract_embedded_art
    from .cache import cache_dir
    from .model import TrackMeta

    cfg = Config.load()
    processed = cfg.require("processed-dir")
    entries = sorted(cache_dir(processed).glob("*.json"))
    if not entries:
        console.print("no analyzed tracks yet — run: cratedrop process")
        raise typer.Exit(1)

    table = Table(title="enrichment")
    for col in ("track", "needs", "match", "score", "src"):
        table.add_column(col, overflow="fold")
    found = skipped = 0
    for entry in entries:
        raw = _json.loads(entry.read_text())
        meta = TrackMeta(**raw["meta"])
        src_path = Path(meta.source_path)
        needs = []
        if not meta.artist:
            needs.append("artist")
        if src_path.exists() and extract_embedded_art(src_path) is None \
                and not en.art_path(processed, meta.sha1).exists():
            needs.append("art")
        if not needs:
            continue
        if en.load(processed, meta.sha1) is not None and not force:
            skipped += 1
            continue
        match = en.find_match(meta, min_score=min_score)
        if match is None:
            table.add_row(meta.title[:40], "+".join(needs),
                          "[dim]no confident match[/dim]", "", "")
            continue
        art = None
        if not dry_run:
            art = en.download(match.art_url)
            en.store(processed, meta.sha1, match, art)
        table.add_row(meta.title[:40], "+".join(needs),
                      f"{match.artist} — {match.title}",
                      f"{match.score:.2f}", match.source)
        found += 1
    console.print(table)
    console.print(f"{found} match(es)" + (f", {skipped} already enriched (use --force to redo)" if skipped else ""))
    if found and not dry_run:
        console.print("run [bold]cratedrop process[/bold] to apply to the image")


settings_app = typer.Typer(no_args_is_help=True,
                           help="Deck settings files (waveform color mode, jog mode...) shipped on every stick.")
app.add_typer(settings_app, name="settings")


@settings_app.command("import")
def settings_import(source: str = typer.Argument(help="volume name (e.g. MOMO) or a PIONEER dir path")) -> None:
    """Copy DEVSETTING/MYSETTING files from a Rekordbox-exported stick into config."""
    import shutil

    from .config import CONFIG_DIR
    from .export.builder import SETTINGS_FILES

    root = Path(source).expanduser()
    if not root.exists():
        root = Path("/Volumes") / source
    pioneer = root if (root / "DEVSETTING.DAT").exists() or root.name == "PIONEER" else root / "PIONEER"
    dest = CONFIG_DIR / "mysettings"
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for name in SETTINGS_FILES:
        src = pioneer / name
        if src.exists():
            shutil.copy2(src, dest / name)
            got.append(name)
    if not got:
        console.print(f"[red]no settings files found under {pioneer}[/red]")
        raise typer.Exit(1)
    console.print(f"imported {', '.join(got)} -> {dest}")
    console.print("run [bold]cratedrop process[/bold] then flash to ship them")


@settings_app.command("show")
def settings_show() -> None:
    from .config import CONFIG_DIR
    from .export.builder import SETTINGS_FILES

    dest = CONFIG_DIR / "mysettings"
    for name in SETTINGS_FILES:
        path = dest / name
        console.print(f"{name}: {'[green]present[/green]' if path.exists() else '[dim]absent[/dim]'}")


@app.command()
def watch(interval: float = typer.Option(10.0, "--interval", help="poll seconds"),
          settle: float = typer.Option(15.0, "--settle", help="quiet seconds before a new file is ingested")) -> None:
    """Watch the staging dir; rebuild the image whenever new audio settles."""
    from .watch import watch as run_watch

    cfg = Config.load()
    staging = cfg.require("staging-dir")
    processed = cfg.require("processed-dir")

    def on_event(msg: str) -> None:
        import datetime
        console.print(f"[dim]{datetime.datetime.now():%H:%M:%S}[/dim] {msg}")

    try:
        run_watch(staging, processed, interval=interval,
                  quiet_seconds=settle, on_event=on_event)
    except KeyboardInterrupt:
        console.print("\nstopped")


@app.command()
def override(file: Path = typer.Argument(help="audio file (staging or anywhere)"),
             bpm: float = typer.Option(None, "--bpm"),
             first_beat_ms: float = typer.Option(None, "--first-beat-ms"),
             key: str = typer.Option(None, "--key", help="Camelot, e.g. 8A")) -> None:
    """Pin manual analysis values for one track (survives re-analysis)."""
    from . import cache, overrides
    from .audio.tags import sha1_file

    cfg = Config.load()
    processed = cfg.require("processed-dir")
    sha = sha1_file(file.expanduser())
    ov = overrides.store(processed, sha, bpm=bpm, first_beat_ms=first_beat_ms, key=key)
    console.print(f"overrides for {file.name}: {ov}")
    analysis = cache.load_any(processed, sha)
    if analysis is not None:
        cache.store(processed, overrides.apply(analysis, ov))
        console.print("applied to cached analysis — run [bold]cratedrop process[/bold] "
                      "to rebuild the image")
    else:
        console.print("not analyzed yet — will apply on next process")


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
