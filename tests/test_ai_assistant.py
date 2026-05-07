import unittest

from ai_assistant import extract_output_text, friendly_ai_error, AiRequestError


class AiAssistantTests(unittest.TestCase):
    def test_extract_output_text_direct(self) -> None:
        self.assertEqual(extract_output_text({"output_text": "salom"}), "salom")

    def test_extract_output_text_nested(self) -> None:
        payload = {
            "output": [
                {"content": [{"type": "output_text", "text": "bir"}, {"type": "output_text", "text": "ikki"}]},
            ]
        }
        self.assertEqual(extract_output_text(payload), "bir\nikki")

    def test_friendly_quota_error(self) -> None:
        text = friendly_ai_error(AiRequestError(429, "You exceeded your quota", "insufficient_quota"))
        self.assertIn("quota", text.lower())

    def test_friendly_archived_project_error(self) -> None:
        text = friendly_ai_error(
            AiRequestError(401, "The project you are requesting has been archived", "not_authorized_invalid_project")
        )
        self.assertIn("arxivlangan", text.lower())


if __name__ == "__main__":
    unittest.main()
