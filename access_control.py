import logging
import os
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ALLOWED_USERS_FILE = BASE_DIR / "allowed_users.txt"
BLOCKED_USERS_FILE = BASE_DIR / "blocked_users.txt"


def parse_user_id_set(raw: str) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for item in re.split(r"[\s,;]+", raw):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result


def user_ids_from_file(path: Path) -> set[int]:
    if not path.exists():
        return set()
    try:
        return parse_user_id_set(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logging.warning("User ID faylini o'qib bo'lmadi (%s): %s", path, exc)
        return set()


def blocked_user_ids() -> set[int]:
    return user_ids_from_file(BLOCKED_USERS_FILE)


def configured_allowed_user_ids() -> set[int]:
    return parse_user_id_set(os.getenv("ALLOWED_USER_IDS", "")) | user_ids_from_file(ALLOWED_USERS_FILE)


def admin_user_ids() -> set[int]:
    return parse_user_id_set(os.getenv("ADMIN_USER_IDS", ""))


def allowed_user_ids() -> set[int]:
    return (configured_allowed_user_ids() | admin_user_ids()) - blocked_user_ids()


def is_admin_user(user_id: int) -> bool:
    admins = admin_user_ids()
    return bool(admins) and user_id in admins


def permitted_user_ids() -> set[int]:
    return allowed_user_ids() | admin_user_ids()


def write_allowed_user_file(user_ids: set[int]) -> None:
    ALLOWED_USERS_FILE.write_text("\n".join(str(item) for item in sorted(user_ids)) + "\n", encoding="utf-8")


def add_allowed_user(user_id: int) -> None:
    ids = user_ids_from_file(ALLOWED_USERS_FILE)
    ids.add(user_id)
    write_allowed_user_file(ids)


def remove_allowed_user(user_id: int) -> bool:
    ids = user_ids_from_file(ALLOWED_USERS_FILE)
    if user_id not in ids:
        return False
    ids.remove(user_id)
    write_allowed_user_file(ids)
    return True


def write_blocked_user_file(user_ids: set[int]) -> None:
    BLOCKED_USERS_FILE.write_text("\n".join(str(item) for item in sorted(user_ids)) + "\n", encoding="utf-8")


def block_user(user_id: int) -> bool:
    if user_id in admin_user_ids():
        return False
    ids = blocked_user_ids()
    ids.add(user_id)
    write_blocked_user_file(ids)
    return True


def unblock_user(user_id: int) -> bool:
    ids = blocked_user_ids()
    if user_id not in ids:
        return False
    ids.remove(user_id)
    write_blocked_user_file(ids)
    return True


def grant_user_access(user_id: int) -> tuple[str, str]:
    was_blocked = user_id in blocked_user_ids()
    was_admin = user_id in admin_user_ids()
    was_allowed = user_id in configured_allowed_user_ids() or was_admin

    add_allowed_user(user_id)
    if was_blocked:
        unblock_user(user_id)

    if was_blocked:
        return "allow_user", "User blokda edi, blokdan chiqarildi va ruxsat berildi."
    if was_admin:
        return "allow_user", "Bu user allaqachon admin."
    if was_allowed:
        return "allow_user", "Bu user oldin qo'shilgan."
    return "allow_user", "User qo'shildi."
