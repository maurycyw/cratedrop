# cratedrop

**Your music library on a USB stick that every Pioneer / AlphaTheta deck reads natively — no Rekordbox, no cloud sync, no laptop at the gig.**

![tests](https://github.com/maurycyw/cratedrop/actions/workflows/tests.yml/badge.svg)

Drop audio files in a folder. cratedrop analyzes them (BPM, beatgrid, key, hot cues, waveforms, artwork) and maintains a USB image carrying **both** device database formats, so one stick works across every current player generation. Plug it in and play.

```
~/music ──▶ analyze ──▶ USB image ──▶ flash ──▶ CDJ / XDJ
        (BPM·grid·key·cues·waveforms·art)      (plays natively)
```

## Why

Rekordbox's sync workflows fail DJs constantly: tracks missing from USBs, cloud sync errors, no laptop on hand to fix any of it. cratedrop replaces the whole pipeline with one folder and two commands — the deck can't tell the difference.

## Supported hardware

| Players | Database format | Status |
|---|---|---|
| XDJ-AZ, OPUS-QUAD, CDJ-3000X, OMNIS-DUO | OneLibrary (`exportLibrary.db`) | ✅ verified on XDJ-AZ |
| CDJ-3000, XDJ-XZ, XDJ-RX3, XDJ-RR, CDJ-2000NXS2 and older | legacy `export.pdb` + ANLZ | ✅ verified on XDJ-XZ (full 180+ track library) |

Every stick carries both formats. To our knowledge this is the first open-source from-scratch writer for OneLibrary accepted by hardware.

## Install

macOS (Apple Silicon or Intel), Python managed by [uv](https://docs.astral.sh/uv/):

```sh
brew install ffmpeg
git clone https://github.com/maurycyw/cratedrop && cd cratedrop
uv sync --extra dsp        # dsp extra = beat/key detection (torch, essentia)
uv run cratedrop doctor    # verify the environment
```

## Quickstart

```sh
uv run cratedrop config set staging-dir ~/Music/library     # where your audio lives
uv run cratedrop config set processed-dir ~/Music/cdj-image # the maintained USB image

uv run cratedrop process                  # analyze everything, build the image
uv run cratedrop flash --volume MYUSB     # sync to /Volumes/MYUSB
```

Then plug the stick into a deck. Subsequent runs are incremental: new tracks analyze once (cached by content hash), and `flash` copies only what changed — adding 5 tracks to a 10,000-track stick takes seconds.

For a hands-off library, leave the watcher running instead of calling `process`:

```sh
uv run cratedrop watch     # auto-ingests files dropped into the staging dir
```

Files are only picked up once fully written (safe for slow network copies), and every track added lands in a playlist named for the day it arrived (`10/10/2026`).

## What a track gets

- **BPM + beatgrid** — [Beat This!](https://github.com/CPJKU/beat_this) beats/downbeats fitted to a constant grid, validated against Rekordbox's own analysis (±0.05 BPM, ±20 ms phase on steady tracks); low-confidence results (edits with grid jumps, acappellas) are flagged
- **Key** — essentia's EDM-tuned profiles → Camelot, `keyfinder-cli` fallback
- **Hot cues A–D** — first kick, drop, breakdown, outro; snapped to downbeats, labeled and colored
- **Waveforms** — all formats decks use (blue, RGB, 3-band), calibrated byte-level against real Rekordbox output
- **Artwork** — embedded tag art, extracted and sized for decks; `cratedrop enrich` fills gaps from Deezer/iTunes
- **Metadata** — tags → folder structure (`Artist/Album/track`) → `Artist - Title` filenames, in that priority

## The deck writes back — nothing is lost

Decks write to the stick: hot cues, play history, settings. `flash` **harvests before it syncs**: deck-set cues merge into the library as protected user data (they survive re-analysis and every re-flash; automatic heuristics never displace them), play history archives locally (`cratedrop history`), and anything unrecognized is snapshotted raw before being touched.

## CLI reference

| command | what it does |
|---|---|
| `config set staging-dir / processed-dir` | point at your folders |
| `process` | analyze new/changed tracks, update the USB image |
| `watch [--interval 10] [--settle 15]` | daemon: auto-process drops |
| `flash --volume NAME [--dry-run] [--prune] [--eject] [--no-harvest]` | harvest deck data, then incremental sync |
| `harvest --volume NAME` | import deck-written cues/history without flashing |
| `enrich [--dry-run] [--min-score 0.72] [--force]` | fill missing art/metadata from the web (fills blanks only) |
| `override FILE --bpm X --first-beat-ms X --key 8A` | pin manual values for a track (survives re-analysis) |
| `settings import <stick-or-dir>` | ship deck preferences (waveform color mode etc.) from a Rekordbox-exported stick |
| `history` | play sessions harvested from decks |
| `status` | staging vs image: what's new |
| `doctor` | environment check |
| `inspect PATH` | pretty-print a USB tree, `.pdb`, or ANLZ file |
| `diff OURS GOLDEN` | structure-aware diff against a real Rekordbox export |

Safety: `flash` is the only code that touches `/Volumes`, and it refuses anything that isn't a removable FAT32/exFAT volume that's empty or already a DJ stick. Deletions only ever happen with `--prune`, and only for files cratedrop itself wrote.

## Current limitations

- Constant-tempo beatgrids only (fine for electronic music; live-drummed material gets a flagged best fit)
- Memory cues and loops are harvested/preserved but not yet re-written to the stick
- Developed and tested on macOS; the format writers are pure Python and portable, `flash`'s device safety checks are macOS-specific for now
- Reverse-engineered formats: a Rekordbox/firmware update could change things. Test your stick before a gig. **Use at your own risk.**

## How it's verified

Every generated file round-trips through independent parsers, and byte-level diffs run against "golden" USB exports made by real Rekordbox (see `tests/fixtures/golden/README.md` for how to capture your own). Analysis quality is cross-validated against Rekordbox's stored results for the same audio files.

## Standing on shoulders

- [Deep Symmetry's crate-digger docs](https://djl-analysis.deepsymmetry.org/) — the canonical reverse-engineering reference
- [fragmede/rekordbox-pdb](https://github.com/fragmede/rekordbox-pdb) — the DeviceSQL (`export.pdb`) read/write library we build on
- [pyrekordbox](https://github.com/dylanljones/pyrekordbox) — ANLZ structs used for read-back validation
- [Radexito/DjManager](https://github.com/Radexito/DjManager) — proof the full pipeline was possible; our ANLZ writer began as a port of theirs
- [Beat This!](https://github.com/CPJKU/beat_this) (CPJKU), [essentia](https://essentia.upf.edu/) (MTG-UPF), [libkeyfinder](https://github.com/mixxxdj/libkeyfinder) (Mixxx)
- The community research that documented the `exportLibrary.db` encryption

cratedrop is not affiliated with, endorsed by, or supported by AlphaTheta Corporation. Pioneer DJ, rekordbox, CDJ and XDJ are trademarks of their respective owners, used here only to describe compatibility.

## License

[MIT](LICENSE)
