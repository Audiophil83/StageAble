"""X-Live OSC endpoints (Maillot protocol v4.02, pp. 57, 66–71)."""
STATE_ADDRESSES = [f"/-stat/urec/{key}" for key in ("state", "etime", "rtime")] + [
    f"/-urec/{key}" for key in ("sessionmax", "markermax", "sessionlen", "sessionpos", "markerpos", "batterystate", "srate", "tracks", "sessionspan", "sessionoffs", "sd1state", "sd2state", "sd1info", "sd2info", "errormessage", "errorcode")
] + [f"/-prefs/card/UREC{key}" for key in ("sdsel", "tracks", "playb", "rout")]
# address, fixed value (None means user input), inclusive range
COMMANDS = {
    "record": ("/-stat/urec/state", 3, 0, 3),
    "stop": ("/-stat/urec/state", 0, 0, 3),
    "play": ("/-stat/urec/state", 2, 0, 3),
    "pause": ("/-stat/urec/state", 1, 0, 3),
    "addmarker": ("/-action/addmarker", 1, 0, 1),
    "clearalert": ("/-action/clearalert", 1, 0, 1),
    "formatcard": ("/-action/formatcard", 1, 0, 1),
    "setposition": ("/-action/setposition", None, 0, 86399999),
    **{key: (f"/-action/{key}", None, 1, 100) for key in ("selsession", "delsession", "selmarker", "delmarker", "savemarker")},
    **{key: (f"/-prefs/card/UREC{key}", None, 0, high) for key, high in (("sdsel", 1), ("tracks", 2), ("playb", 1), ("rout", 2))},
}

# Resolve card selection before collecting its dependent lists.
STATE_ADDRESSES.sort(key=lambda address: address != "/-prefs/card/URECsdsel")
