# Golden fixtures: capturing Rekordbox reference exports

These snapshots of real Rekordbox USB exports are our format ground truth.
Everything cratedrop generates is diffed against them (`cratedrop diff`), and
the empty-USB export doubles as the seed template for from-scratch pdb creation.

## What to capture (one-time, ~20 minutes in Rekordbox)

Use any USB stick, FAT32 or exFAT. In Rekordbox (EXPORT mode), for each case
below: prepare the collection, connect the stick, sync/export, safely eject.
After each export, snapshot the stick before doing the next one:

```sh
# with the stick mounted as /Volumes/<NAME>:
uv run python tests/fixtures/golden/snapshot.py /Volumes/<NAME> <case-name>
```

Cases, in order:

1. `empty` — export with an EMPTY collection (no tracks): gives us the pristine
   header/table skeleton Rekordbox writes. This becomes the pdb seed template.
2. `click` — collection containing ONLY `tests/fixtures/audio/click_120bpm.wav`
   (drag it into Rekordbox, let it analyze, then export). Known ground truth:
   120.000 BPM, first beat at exactly 500 ms. Add one hot cue (A) and one
   memory cue anywhere before exporting — gives us cue byte layouts.
3. `small` — 2–3 real tracks of different genres/keys, analyzed, with a
   playlist containing them. (Stays local: real audio is gitignored.)

The `empty` and `click` cases are committed to the repo (tiny, self-made
audio). `small` lands in `tests/fixtures/golden-local/` (gitignored).

## Also note the Rekordbox version

Write it into `tests/fixtures/golden/VERSIONS.md` — format details can shift
between Rekordbox releases, and knowing which version authored the goldens
matters when interpreting diffs.

## Hardware sanity check (before trusting the snapshots)

Plug the `click` stick into the XDJ-XZ and confirm: it mounts, the track
browses under Artist/Album, loads, shows a waveform and a 120.00 BPM grid,
and the hot cue fires. If the golden stick itself doesn't behave, the
snapshot is not a valid reference.
