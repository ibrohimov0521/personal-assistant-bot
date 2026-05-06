# Personal Assistant Bot

Telegram bot: eslatmalar va shaxsiy moliya hisobi.

## Nima qiladi

- Eslatma qo'shadi va vaqti kelganda Telegramga xabar yuboradi.
- Asosiy menyuda yozilgan eslatma matnini o'zi tanib saqlaydi.
- UZCARD/HUMO xabarlarini forward yoki copy-paste qilsangiz kirim/xarajat yoki balans sifatida saqlaydi.
- Haftalik va oylik hisobot chiqaradi.
- Mini App ichida operatsiyani tahrirlash/o'chirish, kunlik limit, CSV export va ma'lumotlarni tozalash bor.
- Shahar bo'yicha namoz vaqtlarini ko'rsatadi va yoqsangiz eslatib turadi.
- Telegram Mini App dashboard: balanslar, moliya, eslatmalar va namoz vaqtlari bitta web interfeysda.
- Har bir foydalanuvchi ma'lumotlari `telegram user_id` bo'yicha alohida saqlanadi.

## Ishga tushirish

1. `.env` faylni oching.
2. `BOT_TOKEN=telegram_bot_tokeningiz` joyiga yangi bot tokeningizni yozing.
3. CMD yoki PowerShell ochib yozing:

```cmd
cd /d "C:\Users\Javohir\Documents\Codex\2026-04-27\personal-assistant-bot"
local-tools\start_all_hidden.cmd
```

Bu bot, forwarder va Mini App tunnelni bitta buyruq bilan yashirin oynalarda ishga tushiradi.
Holatni ko'rish:

```cmd
local-tools\status_all.cmd
```

## Ruxsat

`.env` ichida:

```env
ALLOWED_USER_IDS=
```

Bo'sh bo'lsa hamma foydalana oladi. Bot baribir har bir foydalanuvchining ma'lumotini alohida saqlaydi.

Faqat ayrim odamlarga ruxsat bermoqchi bo'lsangiz:

```env
ALLOWED_USER_IDS=6388458077,123456789
```

Ruxsat berilmagan odam botga yozsa, bot unga o'z Telegram ID sini ko'rsatadi. U ID ni adminga yuboradi, admin esa Mini App ichidagi `Admin` bo'limidan yoki `/allow ID` buyrug'i bilan qo'shadi.

Ruxsat berilgan odam o'z ID sini ko'rmoqchi bo'lsa:

```text
/id
```

Avtomatik bank xabarlarini xavfsiz ulash yo'riqnomasi:

```text
/connect
```

## Eslatma misollari

- `1 daqiqadan keyin suv ichishni eslat`
- `ertaga 10:00 dori ichish`
- `2026-05-03 14:30`
- `03.05 09:00`
- `ertaga 10:00`
- `2 kundan keyin 18:00`
- `30 daqiqadan keyin`

## Moliya misollari

Bank xabarini asosiy menyuda turib botga forward qiling yoki copy-paste qiling. Alohida "qo'shish" bo'limiga kirish shart emas.

Qo'lda yozish:

- `plus 500000 oylik`
- `minus 45000 ovqat`
- `minus 12000 taxi`

Balans xabarlari ham qo'llab-quvvatlanadi:

- HUMO botdagi `VISA SMART BANK *2871 / 0.00 UZS`
- UZCARD botdagi `Umumiy balans`, `Karta`, `Bank`, `so'm` bloklari

Bot bunday xabarlarni xarajat yoki kirimga qo'shmaydi, `Kartalar balansi` bo'limida saqlaydi.

## Namoz vaqtlari

Bot ichida `Namoz` bo'limini oching:

- `Bugungi namoz vaqtlari` - tanlangan shahar bo'yicha vaqtlarni ko'rsatadi.
- `Shahar tanlash` - Toshkent, Samarqand, Buxoro, Andijon va boshqa shaharlarni tanlash.
- `Eslatmani yoqish` - Bomdod, Peshin, Asr, Shom, Xufton vaqtida xabar yuboradi.

Hisoblash offline bajariladi, internet/API shart emas. Standart shahar: Toshkent.

## Telegram Mini App

Mini App Telegramning pastdagi menu buttoni orqali ochiladi. Oddiy reply keyboardda faqat `Yordam` qolgan, shunda bot ichi ixcham turadi.

Oddiy browser preview:

```cmd
cd /d "C:\Users\Javohir\Documents\Codex\2026-04-27\personal-assistant-bot"
local-tools\run_miniapp_preview.cmd
```

Telegram ichida real ochilishi uchun `.env` ichidagi `MINI_APP_URL` HTTPS manzil bo'lishi kerak. `start_all_hidden.cmd` cloudflared ishlayotgan bo'lsa eski URLni qayta ishlatadi, shuning uchun Open tugmasi kamroq buziladi. Cloudflared butunlay o'chirilsa yangi `trycloudflare.com` URL chiqadi.

Maxfiylik uchun local browser (`127.0.0.1:8080`) real bank ma'lumotlarini ko'rsatmaydi. Lokal previewda real data kerak bo'lsa `.env` ichida buni ataylab yoqing:

```env
MINIAPP_ALLOW_LOCAL_PREVIEW=1
MINIAPP_DEV_USER_ID=6388458077
```

Doimiy Mini App uchun eng yaxshi yechim: bepul quick tunnel o'rniga doimiy Cloudflare Tunnel + o'z domeningiz yoki VPS ishlatish.

## To'xtatish

```cmd
local-tools\stop_all.cmd
```

## UZCARD/HUMO xabarlarini avtomatik yuborish

Oddiy Telegram bot boshqa botlardan kelgan xabarlarni o'zi ko'ra olmaydi. Shuning uchun `forwarder.py` user account session orqali UZCARD/HUMO botlardan kelgan xabarni assistant botga yuboradi.

Ko'p foydalanuvchida ham ma'lumotlar aralashmaydi: bank xabarini qaysi Telegram akkaunt forwarder orqali yuborsa, assistant bot uni o'sha `telegram user_id` ga yozadi.

Muhim: userlardan Telegram login kodi yoki 2FA parolini bot ichida so'ramang. Har bir foydalanuvchi avtomatik forwarder xohlasa, `run_forwarder.cmd` ni o'z kompyuterida yoki o'zi ishonadigan serverda ishga tushirib, o'z Telegram akkaunti bilan login qilishi kerak.

`.env` ichida to'ldiring:

```env
TG_API_ID=my.telegram.org_api_id
TG_API_HASH=my.telegram.org_api_hash
ASSISTANT_BOT_USERNAME=@sizning_assistant_botingiz
SOURCE_BOT_USERNAMES=@UzcardBot,@HumoBot
```

`TG_API_ID` va `TG_API_HASH` olish:

1. `https://my.telegram.org` ga kiring.
2. `API development tools` ni oching.
3. App yarating va `api_id`, `api_hash` ni oling.

Forwarderni alohida CMD oynada ishga tushiring. U yangi kelgan xabarlarni ham, bank botlari edit qilgan balans xabarlarini ham assistant botga yuboradi:

```cmd
cd /d "C:\Users\Javohir\Documents\Codex\2026-04-27\personal-assistant-bot"
local-tools\run_forwarder.cmd
```

Yangi foydalanuvchi uchun eng oson yo'l:

```cmd
local-tools\setup_forwarder.cmd
```

Bu script `forwarder.local.env` faylini yaratadi. U GitHubga qo'shilmaydi va har bir user o'z kompyuterida alohida login qiladi.

Birinchi marta telefon raqam va Telegram login kodi so'raydi. Kod va session faylni hech kimga bermang.
Bu joyda bot token yozmang. Forwarder oddiy Telegram akkauntingiz bilan kirishi kerak, chunki bot akkaunt boshqa botlardan kelgan xabarlarni o'qiy olmaydi.

Forwarderni to'xtatish:

```cmd
powershell -ExecutionPolicy Bypass -File .\local-tools\stop_forwarder.ps1
```

Hozirgi tavsiya: kundalik foydalanishda alohida `run_bot.cmd` va `run_forwarder.cmd` o'rniga `local-tools\start_all_hidden.cmd`, `local-tools\status_all.cmd`, `local-tools\stop_all.cmd` uchligini ishlating.

## Admin va tezkor buyruqlar

Adminlar faqat `.env` ichida `ADMIN_USER_IDS` orqali beriladi. Xavfsizlik uchun bu qator bo'sh qolsa hech kim admin bo'lmaydi.

Mini App ichida `Admin` bo'limi faqat adminlarga ko'rinadi. Bu bo'limda user profillari, Telegram ID, username, moliya statistikasi ko'rinadi. User botga yozganidan yoki Mini App'ni ochganidan keyin profili yangilanadi.

Admin Mini App orqali:

- yangi user ID qo'shishi;
- user oldin qo'shilgan yoki blokda bo'lsa, aniq ogohlantirish olishi;
- userni bloklashi;
- bloklangan userni qayta ochishi;
- admin harakatlari audit tarixini ko'rishi;
- ruxsatli va bloklangan userlar sonini ko'rishi mumkin.

```text
/admin       - admin panel
/health      - bot, DB, Mini App va service holati
/stats       - umumiy statistika
/backup      - assistant.db backup faylini yaratib yuborish
/users       - ruxsat berilgan userlar
/audit       - admin harakatlari tarixi
/allow ID    - userga ruxsat berish
/deny ID     - allowed_users.txt ichidan olib tashlash
```

Moliya uchun tezkor buyruqlar:

```text
/exportcsv              - o'z operatsiyalaringizni CSV qilib olish
/undo                   - oxirgi operatsiyani o'chirish
/setcat 15 Ovqat        - 15-ID operatsiya kategoriyasini o'zgartirish
/limit Ovqat 1000000    - kategoriya bo'yicha oylik signal limiti
/limits                 - limitlar ro'yxati
```

Bot oddiy savollarga ham API'siz javob beradi: `balansim qancha`, `bugungi xarajat`, `haftalik hisobot`, `namoz vaqtlari`, `oxirgi operatsiyalar` kabi matnlarni yozish kifoya.

Mini App ichida moliya bo'limidan:

- qo'lda kirim yoki chiqim qo'shish;
- operatsiyani tahrirlash yoki o'chirish;
- kategoriya bo'yicha oylik limit qo'shish yoki o'chirish;
- CSV export olish mumkin.

FSM holatlar `assistant.db` ichida saqlanadi, shuning uchun bot restart bo'lsa ham wizard holatlari MemoryStorage kabi darhol yo'qolmaydi.

## Kod tuzilmasi

Asosiy fayl hali `assistant_bot.py`, lekin eng ko'p o'zgaradigan qismlar ajratilgan:

```text
db.py                  - SQLite ulanishi va vaqt helperlari
db_schema.py           - SQLite jadval va indekslarini yaratish
access_control.py      - user/admin ruxsatlari, allow/block fayllari
finance.py             - UZCARD/HUMO parserlari
finance_store.py       - moliya DB saqlash, balans, limit va export funksiyalari
user_store.py          - profil, admin user ro'yxati va audit log DB funksiyalari
reminder_store.py      - eslatmalarni DBga yozish/o'qish va repeat logikasi
prayer_store.py        - namoz eslatma sozlamalarini DBda saqlash
reminders.py           - eslatma matnini tushunish parserlari
prayer_times.py        - namoz vaqti hisoblash va shaharlar
miniapp_auth.py        - Telegram Mini App auth va JSON helperlari
miniapp_api.py         - Mini App API endpointlari va route ro'yxati
fsm_sqlite_storage.py  - aiogram FSM uchun SQLite storage
handlers/              - Telegram command handler registratorlari
tests/                 - parser testlari
miniapp/               - Telegram Mini App frontend
```

Parser testlarini ishga tushirish:

```cmd
python -m unittest discover -s tests
```

Serverga yangilash:

```powershell
powershell -ExecutionPolicy Bypass -File .\local-tools\deploy_server.ps1
```

## Backup va monitoring

Serverda bot o'zi DB backup qiladi. Sozlamalar `.env` orqali:

```env
BACKUP_CHECK_SECONDS=900
BACKUP_HOUR=3
BACKUP_KEEP_LAST=14
HEALTH_CHECK_SECONDS=300
```

Backup fayllar `backups/` papkasida saqlanadi va GitHubga chiqmaydi.
