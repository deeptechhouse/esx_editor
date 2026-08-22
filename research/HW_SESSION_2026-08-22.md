# Hardware Checklist — Batch Session Log (2026-08-22)

Baseline extracted from the two banks currently on the card
(`/Volumes/Untitled/e4.esx`, `e5.esx`) using `spike_a/hw_session.py`.

## One-command loop

```bash
cd esx_editor/spike_a
python3 hw_session.py                 # scans /Volumes/Untitled automatically
# ...do a save on the ESX-1, name it with the tag below, re-run...
```

Tag each save's filename so the runner routes it to the right item
(case-insensitive substring): `pitch`, `stereo`, `rename`, `psg`,
`twicea`, `twiceb`.

## Baseline status (from e4/e5 only)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Pitch value mapping | NEEDS_HW | No Pitch motion slot present. Needs a PITCH-knob sweep recording. |
| 2 | Stereo sample header | NEEDS_HW | Both banks mono-only (0 stereo). Needs a stereo bank. |
| 3 | Displayable char set | PARTIAL | 43 printable bytes seen (from imported WAV names, not typed). **No `#` observed.** Needs a machine RENAME. |
| 4 | PSG save variant | NEEDS_HW | No short/no-sample-area file supplied. Needs a Save-PSG. |
| 5 | Unchanged double-save | NEEDS_HW | Needs two unchanged Save-All files (`twicea`/`twiceb`). |
| 6 | Stale sample headers | PARTIAL | **e4.esx has 16/18 headers pointing outside its 2.08 MB PCM region** (highest end 7,291,680). Load it on the ESX-1 to see tolerate/refuse. |

Charset observed so far (from file, not dial):
`0123456789ABCDEFHKNRV_abcdeiklmnoprstuvwxz`

## Irreducibly physical steps (cannot be done from the computer)

All six require button presses / card saves on the ESX-1. Do them in one
sitting, saving each with the tag in its name, then re-run `hw_session.py`
once to evaluate the whole batch. `e4.esx` already on the card is the item-6
test bank — just load it.
