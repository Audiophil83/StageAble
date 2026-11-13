# Recover an empty duplicate project

1. Start the updated StageAble version and keep the affected Live set open.
2. Unlock controls and go to **Admin → Projects**.
3. On the original entry with a scan date and saved setlists/presets, choose
   **Recover saved project**, then confirm.

The action appears when another active, unscanned entry has exactly the same
saved file path. It keeps the original project ID, scan, setlists, mixer presets,
and X32 data. It removes only the empty duplicate and immediately reloads the
saved application state, without sending Ableton playback commands or rescanning.

The server refuses recovery if the active entry changed, the file paths differ,
the original has no saved scan, or the duplicate has scan data or any owned data
(including X32 captures). It does not merge two populated projects. Database
changes are atomic: a validation failure leaves both records unchanged.

New identities also match an unambiguous existing saved file path before creating
a project. This handles an old `unsaved:unknown` identity when Ableton starts
reporting the real file path. Already-existing duplicates require the explicit
recovery action.
