import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from engine.licensing import (
    LicenseMode,
    activate_license,
    clear_license,
    generate_license_key,
    get_status,
    is_entitled,
    validate_license_key,
)


class LicensingTests(TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        patcher = patch(
            "engine.licensing.app_data_dir",
            return_value=Path(self._tempdir.name),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        clear_license()

    def test_generate_and_validate_license_key(self):
        key = generate_license_key()
        self.assertTrue(validate_license_key(key))

    def test_activate_license_persists(self):
        key = generate_license_key()
        status = activate_license(key)
        self.assertEqual(status.mode, LicenseMode.LICENSED)
        self.assertTrue(is_entitled())

    def test_trial_mode_counts_down(self):
        started = time.time() - (16 * 60)
        now = started + (16 * 60)
        with patch("engine.licensing._load_store", return_value={"trial_started_at": started}):
            status = get_status(now=now)
            self.assertEqual(status.mode, LicenseMode.TRIAL_EXPIRED)
            self.assertFalse(is_entitled())
