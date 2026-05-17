import unittest

from finance import parse_balance_message, parse_bank_message


class FinanceParserTests(unittest.TestCase):
    def test_humo_income_without_balance(self) -> None:
        text = """🎉 To'ldirish
+ 5.000,0 UZS
📍 PAYME P2P UZCARD NA
💳 HUMOCARD *3954
🕘 21:16 01.05.2026"""
        tx = parse_bank_message(text)
        self.assertIsNotNone(tx)
        assert tx is not None
        self.assertEqual(tx.type, "income")
        self.assertEqual(tx.amount, 5000)
        self.assertEqual(tx.card_last4, "3954")
        self.assertEqual(tx.source, "HUMO")

    def test_card_expense_with_available_balance_line(self) -> None:
        text = """🔴 Platezh
– 5 055.00 UZS
💳 ***3936
📍 CLICK P2P, UZ
🕘 01.05.26 20:43
💵 71 613.79 UZS"""
        tx = parse_bank_message(text)
        balances = parse_balance_message(text)
        self.assertIsNotNone(tx)
        assert tx is not None
        self.assertEqual(tx.type, "expense")
        self.assertEqual(tx.amount, 5055)
        self.assertEqual(tx.card_last4, "3936")
        self.assertEqual([(item.card_last4, item.amount) for item in balances], [("3936", 71614)])

    def test_uzcard_balance_list(self) -> None:
        text = """💳 Umumiy balans:
   💰 82 255.60 so'm

💳 Karta: 561468******3936
🏦 Bank: HAMKORBANK
👤 IBROHIMOV JAVOHIR
 💸 81 668.79 so'm

💳 Karta: 561468******8536
🏦 Bank: Uzagroeksportbank
👤 JAVOHIR IBROHIMOV
 💸 586.81 so'm"""
        balances = parse_balance_message(text)
        self.assertEqual(
            [(item.source, item.bank, item.card_last4, item.amount) for item in balances],
            [
                ("UZCARD", "HAMKORBANK", "3936", 81669),
                ("UZCARD", "Uzagroeksportbank", "8536", 587),
            ],
        )

    def test_humo_balance_list(self) -> None:
        text = """🔹 VISA SMART BANK *2871
💵 0.00 UZS

🔹 HUMOCARD TBCBANK *3954
💵 5 000.00 UZS"""
        balances = parse_balance_message(text)
        self.assertEqual(
            [(item.source, item.bank, item.card_last4, item.amount) for item in balances],
            [
                ("VISA", "SMART BANK", "2871", 0),
                ("HUMO", "TBCBANK", "3954", 5000),
            ],
        )


if __name__ == "__main__":
    unittest.main()
