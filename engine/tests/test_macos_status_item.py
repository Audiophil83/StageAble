from unittest import TestCase
from unittest.mock import Mock, call

from engine.macos_status_item import keep_visible


class KeepVisibleTests(TestCase):
    def test_disables_removal_and_restores_visibility(self):
        status_item = Mock()

        keep_visible(status_item)

        self.assertEqual(
            status_item.method_calls,
            [call.setBehavior_(0), call.setVisible_(True)],
        )
