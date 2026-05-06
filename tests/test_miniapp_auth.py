import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from miniapp_auth import validate_telegram_init_data, validate_telegram_init_user


def signed_init_data(bot_token: str, payload: dict) -> str:
    pairs = {key: json.dumps(value, separators=(",", ":")) if isinstance(value, dict) else str(value) for key, value in payload.items()}
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(pairs)


class MiniAppAuthTests(unittest.TestCase):
    def test_valid_init_data_returns_user(self) -> None:
        token = "123456:ABC"
        init_data = signed_init_data(
            token,
            {
                "auth_date": int(time.time()),
                "query_id": "test-query",
                "user": {"id": 6388458077, "first_name": "Javohir", "username": "Javohir_Ibrohimov"},
            },
        )
        user = validate_telegram_init_user(init_data, token)
        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(int(user["id"]), 6388458077)
        self.assertEqual(validate_telegram_init_data(init_data, token), 6388458077)

    def test_invalid_hash_is_rejected(self) -> None:
        token = "123456:ABC"
        init_data = signed_init_data(token, {"auth_date": int(time.time()), "user": {"id": 1}})
        self.assertIsNone(validate_telegram_init_user(init_data.replace("hash=", "hash=x"), token))


if __name__ == "__main__":
    unittest.main()
