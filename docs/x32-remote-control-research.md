# X32 remote control from StageAble

Status: first OSC implementation complete; physical-console validation remains.

## Scope

The X32 integration is optional and disabled by default. StageAble works as before until **Enable X32 control** and an X32 IP address or hostname are saved in Preferences. Once configured, an **X32** tab appears for clients that have unlocked control access.

Control uses OSC over the local network. The X-LIVE USB connection continues to carry audio between the console and Ableton; it does not provide the network control path used here.

The capture registry contains 904 settings: 32 input channels with level, mute, solo, pan, digital trim, name, polarity and 16 sends; 16 odd/even stereo links; and eight FX return legs with level, pan, mute and 16 sends. Complete captures cover this registry, not a full console backup. Older snapshots retain their original coverage.

Phantom power is a live control outside the capture registry. StageAble resolves the channel's current headamp before each write; unavailable or non-microphone sources disable the control. Physical gain, routing, processing and algorithm-specific FX editing remain outside the registry.

## Connection

The X32 listens for OSC on UDP port 10023 through its ETHERNET port. StageAble must be able to reach the console's IP address.

```text
Computer / Ableton   <-- USB audio --> X-LIVE card USB port
Computer / StageAble <-- OSC/UDP --> Wi-Fi or Ethernet network <-- cable --> X32 ETHERNET port
```

Wi-Fi works when the computer and X32 are on the same reachable network. The console itself still connects to the access point or router by Ethernet. A direct wired connection is preferable for show-critical automation because it removes the radio link. AES50 and ULTRANET are not network-control ports.

The client uses one UDP socket for sends and replies because the X32 replies to the source port. It sends `/xremote` regularly for change feedback, `/meters` for channel meters, and `/info` for model, firmware, and connection health.

## X32 tab

### Mixer

The Mixer subtab shows 32 strips with live meters, faders, numeric level entry, digital trim, pan, solo, mute, polarity inversion, odd/even stereo link and 48 V phantom power. Selecting a channel opens its 16 bus sends. Sliders and numeric fields stay synchronized. Enter or leaving a field commits an edit; polling preserves focused inputs.

Names synchronize in both directions with the console and X32-Edit. Edit the strip name to send a new name (up to 12 printable ASCII characters). Empty names show a channel-number fallback. Names are included in captures and operations.

Trim writes `/ch/NN/preamp/trim`; it is digital trim, not physical preamp gain. Phantom power resolves `/-ha/NN/index` (zero-based channel) and writes the corresponding `/headamp/NNN/phantom`. Channels sharing a headamp share phantom power. The console's routing and headamp ownership still apply.

The FX subtab provides independent left/right controls for the four stereo FX returns: level, pan, mute and bus sends. Effect algorithms and their parameters are edited in X32-Edit.

**Open X32-Edit** is available when accessing StageAble via localhost on the server computer, with control unlocked. On macOS, install X32-Edit in `/Applications` or `~/Applications`; Windows supports common installation folders, and all platforms support executables on PATH. Remote browsers cannot launch an application on the server.

### Control Event

The Control Event subtab records external edits and stores project-specific snapshots and operations.

1. **Start recording changes** captures every supported setting as the baseline.
2. Changes made at the desk, in X32-Edit, or in StageAble appear as before/after differences.
3. Individual differences can be selected for an operation.
4. **Save selected operation** stores the selected keys with their before and after values.
5. **Save snapshot** captures the complete supported parameter set.
6. After either save succeeds, StageAble captures the current complete state as the new baseline.

Unselected changes are not included in an operation. They do become part of the new baseline after a successful save, because each new recording starts from the console's current state.

Each saved operation has:

- **Apply**, which writes its stored after values;
- **Rollback**, which writes its stored before values for exactly the same keys;
- separate optional Ableton keywords for Apply and Rollback.

Rollback is an absolute inverse of the recorded operation. It does not inspect which action ran most recently and it does not undo unrelated edits made afterward. Repeating Apply or Rollback writes the same respective target values.

Each snapshot has **Load**, which writes all settings in the snapshot’s recorded coverage, and an optional Ableton keyword. Captures fail instead of silently saving an incomplete snapshot when any supported setting does not reply.

Snapshots, operations, keywords, and the current recording baseline belong to the active Ableton project. Deleting a project also deletes its X32 data.

## Ableton automation

Create a dedicated arrangement track named `X32`. Clip names on this track are keywords. A keyword may resolve to one of:

- an operation's Apply direction;
- an operation's Rollback direction;
- a snapshot load.

Keywords are trimmed, matched exactly, and must be unique within the project across all three action types. The X32 track name itself is recognized case-insensitively.

StageAble executes a keyword when continuous forward playback crosses the clip's start. It executes an event at the playback start boundary once, skips events crossed by a seek or other large playhead discontinuity, and does not reconstruct mixer state from earlier clips. Short clips still trigger because execution is based on crossing the start time, not on remaining inside the clip.

Execution happens in background work so OSC writes cannot block Ableton's transport polling. The OSC service serializes captures and writes to avoid interleaving operations.

## Permissions

All mutations use StageAble's existing client-control lock. Only an unlocked client can:

- change mixer parameters;
- start or reset a baseline;
- save, load, apply, roll back, or delete X32 items;
- test or refresh the configured connection.

The REST endpoints used for display are read-only. Playback automation runs in the server engine and does not require a browser to remain open.

## Value handling

StageAble keeps OSC values in a typed parameter registry and converts them for display:

- faders and sends use the X32's piecewise normalized-float to dB curve;
- pan maps normalized `0…1` to `L 100…C…R 100`;
- channel trim maps normalized `0…1` to `-18…+18 dB`;
- `/mix/on` is inverted for the user-facing mute state;
- solo uses its separate status/control address.

Saved data retains normalized OSC values, so an operation can write exactly the captured target in either direction.

## Development without a physical X32

StageAble includes a deterministic OSC simulator:

```bash
STAGEABLE_NO_ENGINE=1 .venv/bin/python manage.py run_x32_simulator
```

Set the X32 host in Preferences to `127.0.0.1`, enable the connection, save, and test it. The simulator supports `/info`, `/xinfo`, `/status`, query/set replies for all current parameters, multi-client `/xremote` updates, channel names, and synthetic meters. It exercises the real UDP client and same-socket reply behavior. X32-Edit can discover its identity but cannot complete synchronization because the simulator does not implement the console's full `/node` surface. Use a full X32 protocol emulator when X32-Edit interoperability is required.

The simulator validates application behavior, not audio or console firmware. Final acceptance on the real X32 should verify:

- the console's network settings and firmware identity;
- fader calibration, mute direction, solo behavior, trim range, and send levels;
- meter packet layout and the intended measurement point;
- desk and X32-Edit changes appearing through `/xremote`;
- complete capture under real network load;
- snapshot, Apply, and Rollback writes changing only their expected settings;
- Ableton playback, stop/start, loops, seeks, and closely spaced events;
- recovery after a disconnected network cable.

## Future parameter coverage

### Routing

Routing can use the same baseline and operation model: record a routing edit, select its changed settings, then save forward and rollback values. Routing settings often work in blocks and can change the meaning of channel-source or headamp controls. The registry must describe these dependencies and refuse combinations that cannot be restored safely. Unsupported routing keys must never be omitted from something labeled complete.

### Physical preamp gain

The X32 schema exposes headamp controls separately from channel trim. Before offering physical gain, StageAble must resolve a channel's current source to its actual local or stagebox headamp and account for ownership. A USB card-return source has no microphone preamp to adjust.

### Channel processing and FX

Channel EQ, dynamics, gates, inserts, and shared FX slots can be added as typed parameter groups. FX parameter numbers depend on the algorithm loaded in the slot. A safe operation therefore stores or checks the expected algorithm before writing algorithm-specific values.

Console scenes and snippets can be exposed later as explicit recall actions. StageAble's snapshots and operations do not consume console scene slots.

Useful protocol references for the expansion work are Patrick-Gilles Maillot's [X32 OSC documentation and utilities](https://sites.google.com/site/patrickmaillot/x32), including the published [channel schema](https://github.com/pmaillot/X32-Behringer/blob/master/X32Channel.h), [headamp schema](https://github.com/pmaillot/X32-Behringer/blob/master/X32Headamp.h), and [FX schema](https://github.com/pmaillot/X32-Behringer/blob/master/X32Fx.h).

