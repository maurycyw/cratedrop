# cratedrop

Headless CDJ USB builder: analyze audio files and write a Pioneer-native USB stick
(legacy `export.pdb` + `USBANLZ` analysis files) that CDJ/XDJ players browse and
play natively — metadata, BPM, key, beatgrid, waveforms, hot cues — without
Rekordbox ever touching it.

Stage 1 targets: XDJ-XZ, CDJ-3000, and all older legacy-format players.
(XDJ-AZ / Opus Quad need the encrypted OneLibrary format — out of scope for now.)

## Workflow

```sh
cratedrop config set staging-dir ~/Music/cratedrop/staging
cratedrop config set processed-dir ~/Music/cratedrop/processed
# drop audio files into the staging dir, then:
cratedrop process              # analyze + build/update the USB image
cratedrop flash --volume DJ    # sync image to /Volumes/DJ (harvests deck-written cues first)
```

## Setup (dev)

```sh
brew install ffmpeg
uv sync                        # core deps
uv sync --extra dsp            # + analysis deps (torch/beat-this/essentia), needed from M4
uv run cratedrop doctor
```
