"""Flash the processed image to a mounted USB stick — the only code in
cratedrop allowed to write under /Volumes.

Safety gates (all must pass):
  * target is /Volumes/<name> from an explicit --volume argument
  * not the boot volume; diskutil reports a removable/external USB device
  * filesystem is FAT32 or exFAT
  * volume is empty, or looks like a DJ stick (has PIONEER/), or carries our
    manifest marker
Deletions happen only with --prune and only for files listed in the stick's
previous cratedrop manifest.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..export.builder import MANIFEST_REL, load_manifest


class FlashRefused(RuntimeError):
    pass


@dataclass
class SyncPlan:
    copy: list[str] = field(default_factory=list)      # new or changed
    delete: list[str] = field(default_factory=list)    # --prune only
    deck_modified: list[str] = field(default_factory=list)
    unchanged: int = 0


def _diskutil_info(mount: Path) -> dict:
    out = subprocess.run(["diskutil", "info", "-plist", str(mount)],
                         capture_output=True, check=False)
    if out.returncode != 0:
        raise FlashRefused(f"diskutil cannot inspect {mount}: "
                           f"{out.stderr.decode(errors='replace').strip()}")
    return plistlib.loads(out.stdout)


def check_target(volume_name: str) -> Path:
    if "/" in volume_name:
        raise FlashRefused("--volume takes a volume NAME, not a path")
    mount = Path("/Volumes") / volume_name
    if not mount.is_dir():
        raise FlashRefused(f"{mount} is not mounted")
    if mount.resolve() == Path("/").resolve():
        raise FlashRefused("refusing to touch the boot volume")

    info = _diskutil_info(mount)
    fs = (info.get("FilesystemType") or info.get("FilesystemName") or "").lower()
    if not any(k in fs for k in ("fat", "exfat", "msdos")):
        raise FlashRefused(f"filesystem {fs!r} is not FAT32/exFAT")
    removable = (info.get("RemovableMediaOrExternalDevice")
                 or info.get("Removable") or info.get("Ejectable"))
    bus = (info.get("BusProtocol") or "").lower()
    if not removable and "usb" not in bus:
        raise FlashRefused("device does not look like a removable USB stick")

    entries = [p for p in mount.iterdir()
               if not p.name.startswith(".") and p.name != "System Volume Information"]
    looks_ours = ((mount / "PIONEER").exists()
                  or (mount / MANIFEST_REL).exists() or not entries)
    if not looks_ours:
        raise FlashRefused(
            f"{mount} is neither empty nor a DJ stick (no PIONEER/): refusing")
    return mount


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def plan_sync(processed_dir: Path, mount: Path,
              verify_audio: bool = False) -> SyncPlan:
    """Plan the copy set. Hash verification (reading the file back over USB)
    is applied only to PIONEER/ files — decks write cues/history/settings
    there but never modify audio, so Contents/ is checked by existence+size.
    verify_audio=True forces full hashing of audio too (paranoia mode)."""
    image = load_manifest(processed_dir)
    if image is None:
        raise FlashRefused("processed image has no manifest — run: cratedrop process")
    stick_manifest = load_manifest(mount) or {}
    plan = SyncPlan()
    hashed: dict[str, str] = {}

    def stick_sha(rel: str, path: Path) -> str:
        if rel not in hashed:
            hashed[rel] = _sha1(path)
        return hashed[rel]

    for rel, meta in stick_manifest.items():
        if rel.startswith("Contents/") and not verify_audio:
            continue
        on_stick = mount / rel
        if on_stick.exists() and (on_stick.stat().st_size != meta["size"]
                                  or stick_sha(rel, on_stick) != meta["sha1"]):
            plan.deck_modified.append(rel)

    for rel, meta in sorted(image.items()):
        on_stick = mount / rel
        if not on_stick.exists() or on_stick.stat().st_size != meta["size"]:
            plan.copy.append(rel)
            continue
        if rel.startswith("Contents/") and not verify_audio:
            plan.unchanged += 1
            continue
        if stick_sha(rel, on_stick) == meta["sha1"]:
            plan.unchanged += 1
        else:
            plan.copy.append(rel)

    for rel in sorted(set(stick_manifest) - set(image)):
        if (mount / rel).exists():
            plan.delete.append(rel)

    # Copy order: newest audio first (an interrupted flash of a huge library
    # has still moved the most recent tracks), then analysis files, then the
    # database last so the stick's pdb never references audio not yet copied.
    def order(rel: str) -> tuple:
        if rel.startswith("Contents/"):
            src = processed_dir / rel
            mtime = src.stat().st_mtime if src.exists() else 0
            return (0, -mtime, rel)
        if "USBANLZ" in rel:
            return (1, 0, rel)
        return (2, 0, rel)

    plan.copy.sort(key=order)
    return plan


def apply_sync(processed_dir: Path, mount: Path, plan: SyncPlan,
               prune: bool = False) -> None:
    import shutil

    for rel in plan.copy:
        src, dest = processed_dir / rel, mount / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    if prune:
        for rel in plan.delete:
            (mount / rel).unlink(missing_ok=True)
    # copy the manifest itself last, so an interrupted flash is detectable
    shutil.copy2(processed_dir / MANIFEST_REL, mount / MANIFEST_REL)


def snapshot_deck_writes(mount: Path, plan: SyncPlan, dest_dir: Path) -> list[Path]:
    """Preserve deck-modified files before overwriting (pre-harvest safety
    net): copies them into dest_dir for later parsing/merge (M3.5)."""
    saved = []
    for rel in plan.deck_modified:
        src = mount / rel
        if not src.exists():
            continue
        dest = dest_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        saved.append(dest)
    if saved:
        (dest_dir / "sync-info.json").write_text(json.dumps(
            {"volume": str(mount), "files": plan.deck_modified}, indent=1))
    return saved


def eject(mount: Path) -> bool:
    return subprocess.run(["diskutil", "eject", str(mount)],
                          capture_output=True, check=False).returncode == 0
