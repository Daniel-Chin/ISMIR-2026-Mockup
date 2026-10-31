"""Only the mock data's own backend may receive it (build_miniconf.sync_blocker)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import build_miniconf  # noqa: E402

PRODUCTION, REHEARSAL = 'https://live-api.example', 'https://live-api-mock.example'


class SyncBlocker(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(build_miniconf, 'read_config', return_value={'live_overview_api': PRODUCTION})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_production_data_goes_to_production(self):
        self.assertIsNone(build_miniconf.sync_blocker(False, None, PRODUCTION, 'key'))

    def test_mock_data_goes_to_the_rehearsal_backend(self):
        self.assertIsNone(build_miniconf.sync_blocker(True, None, REHEARSAL, 'key'))

    def test_mock_data_never_goes_to_production(self):
        self.assertIn('production', build_miniconf.sync_blocker(True, None, PRODUCTION, 'key'))

    def test_explicit_data_and_a_missing_key_never_sync(self):
        self.assertTrue(build_miniconf.sync_blocker(False, '/tmp/data', PRODUCTION, 'key'))
        self.assertTrue(build_miniconf.sync_blocker(True, None, REHEARSAL, ''))


if __name__ == '__main__':
    unittest.main()
