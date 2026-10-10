# Changelog

## v0.1.1 — 2026-10-10

- **Rekordbox library import**: `cratedrop import-rekordbox rekordbox.xml` —
  cues, loops, playlists (and beatgrids with `--with-grids`) migrate as
  protected user data; nothing is lost switching over
- **Write-back completeness**: memory cues and loops now round-trip (written
  to the stick, harvested back, survive every re-flash)
- **Variable-tempo beatgrids**: segmented piecewise-constant grids for DJ
  edits and multi-tempo material (PQTZ stores per-beat tempo)
- **`cratedrop verify`**: pre-gig integrity check of the image or a stick
- **`cratedrop dupes`**: near-duplicate detection via chromaprint
  fingerprints (report-only, quality-ranked)
- **Phrase analysis (PSSI)** for CDJ-3000-era structure displays
- **Configurable playlists**: date playlists toggleable, .m3u/.m3u8 files in
  staging become playlists, opt-in folder crates
- Packaging/CI: vendored pdb library, dsp-extra test job, weekly dependency
  canary, tag/version guard, auto GitHub releases, SHA-pinned actions

## v0.1.0 — 2026-10-10

First public release.

- Legacy `export.pdb` + ANLZ (DAT/EXT/2EX) and OneLibrary (`exportLibrary.db`)
  writers — one stick covers every current Pioneer/AlphaTheta player
  generation; hardware-verified on XDJ-XZ and XDJ-AZ
- Analysis: Beat This! beatgrids (constant + segmented multi-tempo), essentia
  key → Camelot, heuristic hot cues, golden-calibrated waveforms (all
  formats), phrase analysis (PSSI), embedded + web-enriched artwork
- Deck write-back: flash harvests deck-set hot cues, memory cues, loops and
  play history before every sync; user data always survives
- Library automation: watch daemon with upload-settle detection, incremental
  sha1-cached analysis, newest-first processing with resumable checkpoints,
  date/M3U/folder playlists, near-duplicate detection (chromaprint),
  per-track manual overrides, deck-settings shipping
- Safety: flash gates (removable FAT/exFAT only, manifest-scoped deletes),
  pre-gig `verify`, golden-diff tooling against real Rekordbox exports
