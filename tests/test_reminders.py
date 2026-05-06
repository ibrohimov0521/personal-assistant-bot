import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import reminders
from reminders import detect_repeat_rule, extract_reminder_text, looks_like_reminder_request, parse_inline_reminder


class ReminderParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_now_local = reminders.now_local
        self.local_tz = ZoneInfo("Asia/Tashkent")
        self.fixed_now = datetime(2026, 5, 7, 9, 0, tzinfo=self.local_tz)
        reminders.now_local = lambda: self.fixed_now

    def tearDown(self) -> None:
        reminders.now_local = self.original_now_local

    def test_fractional_hour_reminder(self) -> None:
        parsed = parse_inline_reminder("1.5 soatdan keyin yuvunishim kerak")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        due_at, text = parsed
        self.assertEqual(due_at, (self.fixed_now + timedelta(minutes=90)).astimezone(timezone.utc))
        self.assertEqual(text, "yuvunishim kerak")

    def test_tomorrow_with_hour(self) -> None:
        parsed = parse_inline_reminder("Ertaga soat 8 da dori ichishni eslat")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        due_at, text = parsed
        self.assertEqual(due_at.astimezone(self.local_tz), datetime(2026, 5, 8, 8, 0, tzinfo=self.local_tz))
        self.assertEqual(text, "dori ichishni")

    def test_repeat_rule_detection(self) -> None:
        self.assertTrue(looks_like_reminder_request("Har kuni soat 7 da suv ichishni eslat"))
        self.assertEqual(detect_repeat_rule("Har kuni soat 7 da suv ichishni eslat"), "daily")
        self.assertEqual(extract_reminder_text("Har hafta juma soat 9 da hisobot"), "hisobot")


if __name__ == "__main__":
    unittest.main()
