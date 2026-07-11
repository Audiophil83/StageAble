# ShowAble Bridge

The Ableton Live **control surface** (Remote Script) that ShowAble talks to.

It is a trimmed, self-contained, rebranded fork of
[AbletonOSC](https://github.com/ideoforms/AbletonOSC) (MIT). Unlike upstream
AbletonOSC, this bundles its own copy of `pythonosc`, so there is **no separate
AbletonOSC install and no patch step** — ShowAble installs this whole folder
into Live's Remote Scripts directory.

It listens on UDP **11000** and replies on **11001**, exactly like AbletonOSC,
so it is wire-compatible with `engine/osc_client.py`.

## What it exposes

Only the Song and Track OSC endpoints ShowAble uses, plus ShowAble's own
batched endpoints:

| Address | Notes |
|---|---|
| `/live/song/get/meter_at_beats` | Batched meter/tempo sampling in one round trip |
| `/live/song/get/name` | Live set filename |
| `/live/song/get/file_path` | Full path to the `.als` |
| `/live/track/get/arrangement_clips/name_chunk` | Chunked clip-name reads |
| `/live/track/set/arrangement_clips/name` | Rename an arrangement clip |
| `/live/song/*`, `/live/track/*` | Standard AbletonOSC transport/track subset |

The AbletonOSC handlers ShowAble does not use (clip, clip_slot, device, scene,
view, application, midimap) are omitted.

## Install

From the repo root:

```bash
python scripts/install_bridge.py
```

Then in Live: **Preferences → Link / Tempo / MIDI → Control Surface**, select
**ShowAble**. (The folder is installed as `ShowAble` in
`.../User Library/Remote Scripts/`.)

## Layout

```
showable_bridge/
  __init__.py        # create_instance() entry point for Live
  manager.py         # ControlSurface: wires up OSC server + handlers
  bridge/            # handlers + OSC server (trimmed AbletonOSC)
  pythonosc/         # bundled OSC codec (python-osc, public domain)
  LICENSE            # MIT (AbletonOSC)
  NOTICE             # provenance + attribution
```

## License / attribution

MIT — see [`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
