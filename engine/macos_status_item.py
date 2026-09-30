"""Small, testable helpers for the native macOS menu-bar item."""

from __future__ import annotations

from typing import Any


def keep_visible(status_item: Any) -> None:
    """Make a status item non-removable and restore it if macOS hid it.

    ``rumps`` does not expose these NSStatusItem properties.  Keeping this
    PyObjC interaction in a separate module lets it be tested off macOS too.
    """
    # A zero behavior omits NSStatusItemBehaviorRemovalAllowed.  This matters
    # because a removed item's invisible state can otherwise persist.
    status_item.setBehavior_(0)
    status_item.setVisible_(True)
