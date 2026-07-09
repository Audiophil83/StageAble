from unittest.mock import patch

from django.test import SimpleTestCase

from engine.serve import build_urls, public_host


class ServeUrlTests(SimpleTestCase):
    def test_public_host_uses_bind_host_when_specific(self):
        self.assertEqual(public_host("192.168.1.10"), "192.168.1.10")

    @patch("engine.serve.get_local_ip", return_value="10.0.0.5")
    def test_public_host_resolves_wildcard_bind(self, _mock_ip):
        self.assertEqual(public_host("0.0.0.0"), "10.0.0.5")

    @patch("engine.serve.get_local_ip", return_value="10.0.0.8")
    def test_build_urls(self, _mock_ip):
        display, url = build_urls("0.0.0.0", 8000)
        self.assertEqual(display, "10.0.0.8:8000")
        self.assertEqual(url, "http://10.0.0.8:8000")
