import math
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))

PRAYER_NAMES = {
    "fajr": "Bomdod",
    "sunrise": "Quyosh",
    "dhuhr": "Peshin",
    "asr": "Asr",
    "maghrib": "Shom",
    "isha": "Xufton",
}
DEFAULT_PRAYER_KEYS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
DEFAULT_PRAYER_CITY = os.getenv("PRAYER_DEFAULT_CITY", "Toshkent")
PRAYER_CITIES = {
    "Toshkent": (41.2995, 69.2401),
    "Samarqand": (39.6542, 66.9597),
    "Buxoro": (39.7747, 64.4286),
    "Andijon": (40.7821, 72.3442),
    "Farg'ona": (40.3894, 71.7847),
    "Namangan": (41.0011, 71.6683),
    "Qarshi": (38.8606, 65.7890),
    "Nukus": (42.4619, 59.6166),
    "Urganch": (41.5500, 60.6333),
    "Navoiy": (40.0844, 65.3792),
    "Jizzax": (40.1250, 67.8808),
    "Guliston": (40.4897, 68.7842),
    "Termiz": (37.2242, 67.2783),
}

OFFICIAL_TASHKENT_MAY_2026 = {
    1: ("03:52", "05:21", "12:20", "17:16", "19:24", "20:50"),
    2: ("03:50", "05:20", "12:20", "17:17", "19:25", "20:51"),
    3: ("03:48", "05:18", "12:20", "17:18", "19:26", "20:53"),
    4: ("03:47", "05:17", "12:20", "17:18", "19:27", "20:54"),
    5: ("03:45", "05:16", "12:20", "17:19", "19:28", "20:56"),
    6: ("03:43", "05:15", "12:20", "17:19", "19:29", "20:57"),
    7: ("03:42", "05:13", "12:20", "17:20", "19:30", "20:59"),
    8: ("03:40", "05:12", "12:20", "17:21", "19:31", "21:00"),
    9: ("03:39", "05:11", "12:19", "17:21", "19:33", "21:02"),
    10: ("03:37", "05:10", "12:19", "17:22", "19:34", "21:03"),
    11: ("03:35", "05:09", "12:19", "17:22", "19:35", "21:05"),
    12: ("03:34", "05:08", "12:19", "17:23", "19:36", "21:06"),
    13: ("03:32", "05:07", "12:19", "17:23", "19:37", "21:07"),
    14: ("03:31", "05:06", "12:19", "17:24", "19:38", "21:09"),
    15: ("03:30", "05:05", "12:19", "17:25", "19:39", "21:10"),
    16: ("03:28", "05:04", "12:19", "17:25", "19:40", "21:12"),
    17: ("03:27", "05:03", "12:19", "17:26", "19:41", "21:13"),
    18: ("03:25", "05:02", "12:19", "17:26", "19:42", "21:15"),
    19: ("03:24", "05:01", "12:20", "17:27", "19:43", "21:16"),
    20: ("03:23", "05:00", "12:20", "17:27", "19:43", "21:17"),
    21: ("03:22", "04:59", "12:20", "17:28", "19:44", "21:19"),
    22: ("03:20", "04:59", "12:20", "17:28", "19:45", "21:20"),
    23: ("03:19", "04:58", "12:20", "17:29", "19:46", "21:21"),
    24: ("03:18", "04:57", "12:20", "17:29", "19:47", "21:23"),
    25: ("03:17", "04:56", "12:20", "17:30", "19:48", "21:24"),
    26: ("03:16", "04:56", "12:20", "17:30", "19:49", "21:25"),
    27: ("03:15", "04:55", "12:20", "17:31", "19:50", "21:26"),
    28: ("03:14", "04:54", "12:20", "17:31", "19:51", "21:28"),
    29: ("03:13", "04:54", "12:20", "17:32", "19:51", "21:29"),
    30: ("03:12", "04:53", "12:21", "17:32", "19:52", "21:30"),
    31: ("03:11", "04:53", "12:21", "17:33", "19:53", "21:31"),
}

OFFICIAL_PRAYER_ORDER = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def fix_angle(value: float) -> float:
    return value - 360.0 * math.floor(value / 360.0)


def fix_hour(value: float) -> float:
    return value - 24.0 * math.floor(value / 24.0)


def deg_sin(value: float) -> float:
    return math.sin(math.radians(value))


def deg_cos(value: float) -> float:
    return math.cos(math.radians(value))


def deg_tan(value: float) -> float:
    return math.tan(math.radians(value))


def deg_asin(value: float) -> float:
    return math.degrees(math.asin(value))


def deg_acos(value: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, value))))


def julian_day(day: date) -> float:
    year = day.year
    month = day.month
    current_day = day.day
    if month <= 2:
        year -= 1
        month += 12
    century = math.floor(year / 100)
    correction = 2 - century + math.floor(century / 4)
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + current_day
        + correction
        - 1524.5
    )


def sun_position(day: date) -> tuple[float, float]:
    days_from_epoch = julian_day(day) - 2451545.0
    mean_anomaly = fix_angle(357.529 + 0.98560028 * days_from_epoch)
    mean_longitude = fix_angle(280.459 + 0.98564736 * days_from_epoch)
    ecliptic_longitude = fix_angle(
        mean_longitude
        + 1.915 * deg_sin(mean_anomaly)
        + 0.020 * deg_sin(2 * mean_anomaly)
    )
    obliquity = 23.439 - 0.00000036 * days_from_epoch
    right_ascension = math.degrees(
        math.atan2(deg_cos(obliquity) * deg_sin(ecliptic_longitude), deg_cos(ecliptic_longitude))
    ) / 15.0
    right_ascension = fix_hour(right_ascension)
    declination = deg_asin(deg_sin(obliquity) * deg_sin(ecliptic_longitude))
    equation_of_time = mean_longitude / 15.0 - right_ascension
    return declination, equation_of_time


def timezone_hours(day: date) -> float:
    midday = datetime(day.year, day.month, day.day, 12, 0, tzinfo=LOCAL_TZ)
    offset = midday.utcoffset() or timedelta(hours=5)
    return offset.total_seconds() / 3600.0


def sun_hour_angle(angle: float, latitude: float, declination: float) -> float:
    numerator = -deg_sin(angle) - deg_sin(latitude) * deg_sin(declination)
    denominator = deg_cos(latitude) * deg_cos(declination)
    return deg_acos(numerator / denominator) / 15.0


def local_datetime_from_hour(day: date, hour_value: float) -> datetime:
    hour_value = fix_hour(hour_value)
    hour = int(hour_value)
    minute_float = (hour_value - hour) * 60
    minute = int(round(minute_float))
    if minute >= 60:
        hour += 1
        minute -= 60
    if hour >= 24:
        hour -= 24
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)


def local_datetime_from_time_text(day: date, value: str) -> datetime:
    hour, minute = map(int, value.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)


def calculate_astronomical_prayer_times(city: str, target_day: date) -> dict[str, datetime]:
    latitude, longitude = PRAYER_CITIES.get(city, PRAYER_CITIES["Toshkent"])
    declination, equation = sun_position(target_day)
    noon = 12 + timezone_hours(target_day) - longitude / 15.0 - equation
    asr_shadow_factor = 2
    asr_angle = math.degrees(math.atan(1 / (asr_shadow_factor + deg_tan(abs(latitude - declination)))))

    times = {
        "fajr": noon - sun_hour_angle(18.0, latitude, declination),
        "sunrise": noon - sun_hour_angle(0.833, latitude, declination),
        "dhuhr": noon,
        "asr": noon + sun_hour_angle(-asr_angle, latitude, declination),
        "maghrib": noon + sun_hour_angle(0.833, latitude, declination),
        "isha": noon + sun_hour_angle(17.0, latitude, declination),
    }
    return {key: local_datetime_from_hour(target_day, value) for key, value in times.items()}


def official_tashkent_may_2026_times(target_day: date) -> dict[str, datetime] | None:
    if target_day.year != 2026 or target_day.month != 5:
        return None
    values = OFFICIAL_TASHKENT_MAY_2026.get(target_day.day)
    if not values:
        return None
    return {
        key: local_datetime_from_time_text(target_day, value)
        for key, value in zip(OFFICIAL_PRAYER_ORDER, values)
    }


def calculate_prayer_times(city: str, day: date | None = None) -> dict[str, datetime]:
    target_day = day or datetime.now(LOCAL_TZ).date()
    official_tashkent = official_tashkent_may_2026_times(target_day)
    if not official_tashkent:
        return calculate_astronomical_prayer_times(city, target_day)
    if city == "Toshkent" or city not in PRAYER_CITIES:
        return official_tashkent

    tashkent_calculated = calculate_astronomical_prayer_times("Toshkent", target_day)
    city_calculated = calculate_astronomical_prayer_times(city, target_day)
    calibrated: dict[str, datetime] = {}
    for key in OFFICIAL_PRAYER_ORDER:
        delta_minutes = round((city_calculated[key] - tashkent_calculated[key]).total_seconds() / 60)
        calibrated[key] = official_tashkent[key] + timedelta(minutes=delta_minutes)
    return calibrated


def normalize_prayer_city(text: str) -> str | None:
    raw = text.strip().lower().replace("'", "").replace("`", "")
    aliases = {
        "tashkent": "Toshkent",
        "toshkent": "Toshkent",
        "toshkent shahar": "Toshkent",
        "toshkent shahri": "Toshkent",
        "samarkand": "Samarqand",
        "samarqand": "Samarqand",
        "bukhara": "Buxoro",
        "buxoro": "Buxoro",
        "andijon": "Andijon",
        "andijan": "Andijon",
        "fargona": "Farg'ona",
        "fargana": "Farg'ona",
        "fergana": "Farg'ona",
        "namangan": "Namangan",
        "qarshi": "Qarshi",
        "karshi": "Qarshi",
        "nukus": "Nukus",
        "urganch": "Urganch",
        "urgench": "Urganch",
        "navoiy": "Navoiy",
        "navoi": "Navoiy",
        "jizzax": "Jizzax",
        "jizzakh": "Jizzax",
        "guliston": "Guliston",
        "termiz": "Termiz",
        "termez": "Termiz",
    }
    if raw in aliases:
        return aliases[raw]
    for city in PRAYER_CITIES:
        if city.lower().replace("'", "") == raw:
            return city
    return None


def format_time_only(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%H:%M")
