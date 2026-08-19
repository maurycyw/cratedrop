"""Environment checks for `cratedrop doctor`."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .config import CONFIG_PATH, Config


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _import_check(name: str, module: str, required: bool, detail_ok: str = "") -> Check:
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", "")
        return Check(name, True, detail_ok or version or "importable", required)
    except Exception as exc:  # noqa: BLE001 - any import failure is the finding
        return Check(name, False, f"{type(exc).__name__}: {exc}", required)


def _binary_check(name: str, binary: str, required: bool, version_args: list[str] | None = None) -> Check:
    path = shutil.which(binary)
    if not path:
        return Check(name, False, f"{binary} not on PATH", required)
    detail = path
    if version_args:
        try:
            out = subprocess.run([binary, *version_args], capture_output=True,
                                 text=True, timeout=10)
            first = (out.stdout or out.stderr).strip().splitlines()
            if first:
                detail = first[0][:60]
        except Exception:  # noqa: BLE001
            pass
    return Check(name, True, detail, required)


def run_checks() -> list[Check]:
    checks: list[Check] = []

    ver = sys.version_info
    checks.append(Check("python", ver >= (3, 12), sys.version.split()[0]))
    checks.append(_binary_check("ffmpeg", "ffmpeg", required=True, version_args=["-version"]))

    checks.append(_import_check("rekordbox-pdb (device DB)", "rekordbox_pdb", required=True))
    checks.append(_import_check("pyrekordbox (ANLZ structs)", "pyrekordbox", required=True))
    checks.append(_import_check("soundfile", "soundfile", required=True))

    # mp3 decode support comes with libsndfile >= 1.1
    try:
        import soundfile as sf
        mp3 = "MP3" in sf.available_formats()
        checks.append(Check("soundfile mp3 decode", mp3,
                            "libsndfile " + sf.__libsndfile_version__))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("soundfile mp3 decode", False, str(exc)))

    checks.append(_import_check("librosa", "librosa", required=True))
    checks.append(_import_check("mutagen", "mutagen", required=True))

    # DSP extras — required from M4 (real analysis) onward
    checks.append(_import_check("torch (dsp extra)", "torch", required=False))
    checks.append(_import_check("beat-this (dsp extra)", "beat_this", required=False,
                                detail_ok="importable"))
    checks.append(_import_check("essentia (dsp extra)", "essentia", required=False))

    # optional external validators / fallbacks
    checks.append(_binary_check("keyfinder-cli (key fallback)", "keyfinder-cli", required=False))
    checks.append(_binary_check("rekordcrate (validator)", "rekordcrate", required=False))
    checks.append(_binary_check("java (crate-digger validator)", "java", required=False))

    cfg = Config.load()
    cfg_detail = (f"staging={cfg.staging_dir or 'unset'}  "
                  f"processed={cfg.processed_dir or 'unset'}")
    checks.append(Check(f"config ({CONFIG_PATH})",
                        bool(cfg.staging_dir and cfg.processed_dir),
                        cfg_detail, required=False))
    return checks
