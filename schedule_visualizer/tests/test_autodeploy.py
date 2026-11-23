import unittest
from unittest.mock import patch

import h1cloud_autodeploy as deploy


class ReleaseSelectionTests(unittest.TestCase):
    def test_selects_highest_deploy_build_from_own_release_feed(self):
        older, newer = "a" * 40, "b" * 40
        feed = f"""
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><link href="https://github.com/{deploy.REPO}/releases/tag/h1cloud-7-{older}" /></entry>
          <entry><link href="https://github.com/{deploy.REPO}/releases/tag/h1cloud-8-{newer}" /></entry>
          <entry><link href="https://github.com/other/repo/releases/tag/h1cloud-9-{older}" /></entry>
          <entry><link href="https://github.com/{deploy.REPO}/releases/tag/v1.0.0" /></entry>
        </feed>
        """.encode()
        with patch.object(deploy, "read_url", return_value=feed):
            self.assertEqual(deploy.latest_build(), (8, newer))

    def test_no_deployable_release(self):
        with patch.object(deploy, "read_url", return_value=b"<feed/>"):
            self.assertIsNone(deploy.latest_build())
