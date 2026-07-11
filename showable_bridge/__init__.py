"""ShowAble Bridge — an Ableton Live control surface for ShowAble.

This is a trimmed, rebranded fork of AbletonOSC (https://github.com/ideoforms/AbletonOSC,
MIT licensed — see LICENSE). It exposes the subset of the OSC API that ShowAble
needs, plus ShowAble's own batched endpoints, over the same UDP ports (11000/11001)
so the desktop app can drive Live directly with no separate AbletonOSC install.

Live loads this package as a Remote Script and calls ``create_instance``.
"""

try:
    from .manager import Manager
except ImportError:
    # Allows importing this package outside Live (e.g. for tooling/tests) without
    # pulling in the Live-only ``ableton``/``_Framework`` modules.
    Manager = None


def create_instance(c_instance):
    return Manager(c_instance)
