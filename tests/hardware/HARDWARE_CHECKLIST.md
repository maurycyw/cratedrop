# XDJ-XZ hardware test checklist

Run at milestone gates M1 / M2 / M3 / M3.5 / M5. Record results per run at the
bottom (date, milestone, stick contents, Rekordbox-free build hash).

## Mount & browse
- [ ] Stick mounts with no error message on the player
- [ ] Library browse works by Folder, Artist, Album
- [ ] Title / Artist / BPM / Key columns show correct values

## Load & play
- [ ] Track loads on deck 1 and deck 2
- [ ] Preview waveform visible in the browser list
- [ ] Full waveform + detail waveform render on deck (colors look sane)
- [ ] Audio plays cleanly start to end; needle search works

## Beatgrid & sync
- [ ] Displayed BPM matches expected value exactly
- [ ] Beatgrid markers land on the kicks (check at the drop, not just the intro)
- [ ] Downbeat (bar line) is on the actual "1"
- [ ] Beat-sync against a second track locks correctly

## Cues
- [ ] Hot cues show in the expected slots with the expected colors
- [ ] Hot cues jump to the right positions (grid-accurate)
- [ ] Memory cue visible on the waveform and recallable

## Write-back (M3.5+)
- [ ] Set a new hot cue + memory cue on the deck; save; power off; re-insert on
      the Mac: `cratedrop harvest` imports them
- [ ] Re-flash the stick; on the deck, the deck-set cues are still there
- [ ] History playlist from the session was harvested

## Robustness
- [ ] Stick survives player power cycle with USB inserted
- [ ] Re-insert after clean stop: still browses
- [ ] (bonus) Stick still opens correctly in Rekordbox

## Runs

| date | milestone | notes |
|------|-----------|-------|
