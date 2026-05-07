import unittest

import assistant_bot


class AssistantImportTests(unittest.TestCase):
    def test_dashboard_prayer_keys_are_available(self) -> None:
        self.assertIn("fajr", assistant_bot.DEFAULT_PRAYER_KEYS)
        self.assertIn("isha", assistant_bot.DEFAULT_PRAYER_KEYS)


if __name__ == "__main__":
    unittest.main()
