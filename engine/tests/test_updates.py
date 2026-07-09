from django.test import SimpleTestCase

from engine.updates import UpdateInfo, parse_appcast


APPCAST_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <item>
      <title>RemoteAble 1.1.0</title>
      <enclosure url="https://downloads.remoteable.app/RemoteAble-macOS-1.1.0.zip"
                 sparkle:version="1.1.0"
                 length="12345"
                 type="application/octet-stream" />
    </item>
  </channel>
</rss>
"""


class UpdateTests(SimpleTestCase):
    def test_parse_appcast_detects_newer_version(self):
        info = parse_appcast(APPCAST_XML, platform="macos")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.latest_version, "1.1.0")

    def test_update_info_compare(self):
        info = UpdateInfo("1.0.0", "1.1.0", "https://example.com/app.zip")
        self.assertTrue(info.update_available)
