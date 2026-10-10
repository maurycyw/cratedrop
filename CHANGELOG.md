# Changelog

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
