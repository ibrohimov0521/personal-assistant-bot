import unittest
from datetime import date

from prayer_times import OFFICIAL_PRAYER_ORDER, calculate_prayer_times, format_time_only, normalize_prayer_city


class PrayerTimesTests(unittest.TestCase):
    def test_tashkent_may_2026_uses_official_table(self) -> None:
        times = calculate_prayer_times("Toshkent", date(2026, 5, 1))
        self.assertEqual(
            [format_time_only(times[key]) for key in OFFICIAL_PRAYER_ORDER],
            ["03:52", "05:21", "12:20", "17:16", "19:24", "20:50"],
        )

    def test_other_city_is_calibrated_from_tashkent_table(self) -> None:
        times = calculate_prayer_times("Samarqand", date(2026, 5, 1))
        self.assertEqual(
            [format_time_only(times[key]) for key in OFFICIAL_PRAYER_ORDER],
            ["04:08", "05:33", "12:29", "17:23", "19:30", "20:52"],
        )

    def test_tashkent_city_alias(self) -> None:
        self.assertEqual(normalize_prayer_city("Toshkent shahri"), "Toshkent")


if __name__ == "__main__":
    unittest.main()
