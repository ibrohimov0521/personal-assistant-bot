# Personal Assistant Bot

Telegram bot: eslatmalar, namoz vaqtlari, Mini App va guruh navbatchiligi.

## Hozirgi imkoniyatlar

- Eslatma qo'shadi va vaqti kelganda Telegramga xabar yuboradi.
- Oddiy matndan eslatma vaqtini tanib oladi.
- Shahar bo'yicha namoz vaqtlarini ko'rsatadi va yoqsangiz eslatib turadi.
- Telegram Mini App orqali eslatmalar, namoz sozlamalari, profil va admin panel ko'rinadi.
- Guruh uchun musor navbati va yakshanba yig'ishtirish jadvalini eslatadi.
- OpenAI API ulangan bo'lsa, `/ai savol` orqali yordamchi javob beradi.

Moliya, kartalar, bank xabarlari, export va forwarder kodlari arxivga ko'chirilgan:

```text
archive/finance_disabled_20260517/
```

## Ishga tushirish

1. `.env` faylni oching.
2. `BOT_TOKEN=telegram_bot_tokeningiz` joyiga bot tokenini yozing.
3. PowerShell yoki CMD ochib:

```cmd
local-tools\start_all_hidden.cmd
```

Holatni ko'rish:

```cmd
local-tools\status_all.cmd
```

To'xtatish:

```cmd
local-tools\stop_all.cmd
```

## Eslatma misollari

- `1 daqiqadan keyin suv ichishni eslat`
- `ertaga 10:00 dori ichish`
- `2026-05-20 14:30`
- `juma soat 10`
- `30 daqiqadan keyin`

## Namoz vaqtlari

Bot ichida `Namoz` bo'limi yoki Mini App ichidagi `Qo'shimcha` bo'limi ishlatiladi:

- `Bugungi namoz vaqtlari`
- `Shahar tanlash`
- `Eslatmani yoqish`

Hisoblash offline bajariladi. Standart shahar `.env` ichidagi `PRAYER_DEFAULT_CITY` orqali belgilanadi.

## Guruh navbatchiligi

Botni Telegram guruhga qo'shing va admin sifatida guruh ichida:

```text
/chore_setup
```

Shundan keyin bot:

- har kuni 08:00 va 20:00 da musor navbatini eslatadi;
- har yakshanba 10:00 da kvartira yig'ishtirish juftliklarini yuboradi.

Foydali buyruqlar:

```text
/chore_status
/chore_now
/chore_off
```

## Admin buyruqlari

```text
/admin
/health
/stats
/backup
/users
/audit
/allow ID
/deny ID
```

## Mini App

Mini App Telegramning menu buttoni orqali ochiladi. Real ochilishi uchun `.env` ichidagi `MINI_APP_URL` HTTPS bo'lishi kerak.

Lokal preview:

```cmd
local-tools\run_miniapp_preview.cmd
```

Lokal browserda real user ma'lumoti kerak bo'lsa:

```env
MINIAPP_ALLOW_LOCAL_PREVIEW=1
MINIAPP_DEV_USER_ID=123456789
```

## Fayllar

```text
assistant_bot.py       - asosiy Telegram bot va Mini App server
miniapp_api.py         - Mini App API endpointlari
miniapp/               - Mini App frontend
reminders.py           - eslatma matnini tushunish
reminder_store.py      - eslatmalar bazasi
prayer_times.py        - namoz vaqtlarini hisoblash
prayer_store.py        - namoz sozlamalari
chores.py              - guruh navbatchiligi jadvali
handlers/admin.py      - admin buyruqlari
```
