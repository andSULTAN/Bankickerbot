# TG-Guard

Telegram kanal va unga bog'langan muhokama guruhini **spam akkauntlardan** himoya qiluvchi tizim.

Muammo: post chiqishi bilan izoh yozadigan, profil rasmi pornografik, bio/ismida
"yopiq kanal" reklamasi va havolasi bo'lgan avtomatlashtirilgan **odam akkauntlari**
(botlar emas). TG-Guard ularni topadi, ko'rib chiqish uchun taqdim etadi va
buyruq bo'yicha kanal hamda guruhdan chiqarib yuboradi. Haqiqiy obunachilarga
zarar yetkazmaslik — asosiy shart.

---

## 1. Arxitektura

Uchta komponent, bitta PostgreSQL bazasi:

| Komponent | Nima qiladi | Qayerda ishlaydi |
|---|---|---|
| `scanner/` | Telethon (MTProto), **xizmat akkaunti** orqali barcha obunachilarni sanab chiqadi, tahlil qiladi, bazaga yozadi va faqat aniq buyruq bilan ban qiladi | Sizning kompyuteringizda (CLI) |
| `bot/` | aiogram 3 bot: har bir yangi izoh va guruhga qo'shilishni real vaqtda tekshiradi, avtomatik chora ko'radi yoki review kanalga tugmalar bilan yuboradi | VPS (Docker) |
| `core/` | Umumiy kutubxona: ball hisoblash, NSFW klassifikator, baza modellari, konfiguratsiya | Ikkalasi ham import qiladi |

Stack: Python 3.11+, Telethon, aiogram 3, SQLAlchemy 2 (async) + Alembic,
PostgreSQL 16, NudeNet (lokal, CPU), Pydantic settings, structlog, pytest, Typer.

```
core/      config, db (models/repo), scoring, nsfw, policy, review, strings
scanner/   cli, service, enumeration, profiles, actions, client
bot/       main, runtime, checks, moderation, handlers/{group,review,admin}
config/    scoring.yaml   <- barcha vazn va chegaralar shu yerda
alembic/   migratsiyalar
tests/     unit testlar (tarmoqsiz, modelsiz)
scripts/   sample_scan.py — NSFW chegaralarini lokal rasmda sinash
```

---

## 2. Telegram tayyorgarligi

### 2.1 Xizmat akkaunti (scanner uchun)

1. **Alohida** Telegram akkaunt oching (o'zingizning asosiy akkauntingiz emas —
   Telegram ommaviy amallar uchun akkauntni cheklashi mumkin).
2. Bu akkauntni **kanalga ham, muhokama guruhiga ham admin** qiling
   (kamida: "Foydalanuvchilarni cheklash/ban qilish" huquqi).
3. https://my.telegram.org → **API development tools** → `api_id` va `api_hash` oling.
4. `.env` da `TG_API_ID`, `TG_API_HASH` ni to'ldiring.

> ⚠️ **Sessiya fayli sir.** `TG_SESSION_PATH` ni **repo ichida emas**, masalan
> `C:/Users/<siz>/.tgguard/service.session` qilib ko'rsating. Sessiya fayli
> akkauntga to'liq kirish huquqini beradi. `.gitignore` da `*.session` allaqachon bor.

Birinchi ishga tushirishda telefon raqami va kod so'raladi:

```bash
tgguard whoami
```

### 2.2 Bot

1. [@BotFather](https://t.me/BotFather) → `/newbot` → `BOT_TOKEN` oling.
2. Botni **kanalga** va **muhokama guruhiga** admin qiling. Kerakli huquqlar:
   *Xabarlarni o'chirish* va *Foydalanuvchilarni ban qilish*.
3. BotFather → `/setprivacy` → **Disable**. Aks holda bot guruhdagi barcha
   xabarlarni ko'rmaydi. (Bot admin bo'lsa ham barcha xabarlarni oladi, lekin
   ikkalasini ham qilib qo'ygan ma'qul.)
4. Bot ishga tushganda huquqlarni o'zi tekshiradi va yetishmasa loglarga
   xato yozib, adminlarga xabar yuboradi.

### 2.3 Review kanal

1. **Yopiq** (private) kanal oching — bu yerga shubhali profillar tushadi.
2. Botni unga admin qiling (post yuborish + tahrirlash huquqi bilan).
3. Kanal id sini oling (masalan @username_to_id_bot orqali yoki botni qo'shib
   loglardan) → `.env` dagi `REVIEW_CHANNEL_ID` (`-100...` ko'rinishida).

### 2.4 Kanal va guruh id lari

`.env` da `CHANNEL_ID`, `DISCUSSION_GROUP_ID` va `REVIEW_CHANNEL_ID` ni
to'ldiring (uchalasi ham `-100...` bilan boshlanadi). Bot faqat shu chatlarda
ishlaydi.

Id larni olishning eng oson yo'li — skaner akkaunti ulangandan keyin:

```bash
tgguard chats
```

U akkaunt a'zo bo'lgan barcha kanal/guruhlarni nomi, username va **to'g'ridan-
to'g'ri `.env` ga qo'yiladigan `-100...` id si** bilan chiqaradi.

Muqobil: kanaldagi biror postni [@getmyid_bot](https://t.me/getmyid_bot) ga
forward qiling, yoki kanalni Telegram Web'da oching — manzil satrida
`web.telegram.org/a/#-1001234567890` ko'rinishida turadi.

> Telethon kanalni `1234567890` deb ko'rsatadi, Telegram ilovalari va Bot API
> esa `-1001234567890` deb. Baza har doim **Bot API shaklini** saqlaydi
> (`core/ids.py`), shuning uchun skaner va bot yozuvlari bir xil chatga tegishli
> bo'ladi.

---

## 3. O'rnatish (lokal, skaner uchun)

PowerShell'da (Windows) nisbiy yo'l **`.\` bilan** boshlanishi shart — aks holda
PowerShell uni buyruq deb o'ylab `CommandNotFoundException` beradi.

```powershell
cd "C:\Antigravity projects\Agentlik\tg-guard"
```
```powershell
python -m venv .venv
```
```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,nsfw]" aiosqlite
```
```powershell
copy .env.example .env
```

`.env` ni to'ldirish uchun uni Notepad'da oching (`notepad .env`) yoki
terminaldan chiqmasdan quyidagi skriptni ishlating — u har bir qiymatni
navbat bilan so'raydi va faqat kerakli qatorlarni yangilaydi:

```powershell
.\scripts\set-env.ps1
```

Baza migratsiyalari:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

O'rnatilgandan keyin `tgguard` buyrug'i paydo bo'ladi:
`.\.venv\Scripts\tgguard.exe ...`. Venv'ni aktivlashtirsangiz (`.\.venv\Scripts\Activate.ps1`)
qisqa `tgguard ...` shakli ham ishlaydi; ExecutionPolicy taqiqlasa, to'liq yo'ldan
foydalanavering.

> `[nsfw]` ekstra NudeNet ni o'rnatadi (birinchi ishga tushirishda model
> yuklab olinadi, ~100 MB). Modelsiz sinash uchun `TGGUARD_NSFW_BACKEND=stub`.

---

## 4. NSFW chegarasini avval lokal sinang

Telegram ga tegishdan **oldin** o'z rasmlaringizda chegarani tekshiring:

```bash
python scripts/sample_scan.py ./samples
python scripts/sample_scan.py ./samples --json natija.json
```

Har bir rasm uchun NSFW ehtimoli va shu rasm yagona signal bo'lgandagi ball
chiqadi. `config/scoring.yaml` dagi `nsfw.unsafe_classes` va `weights.nsfw_photo`
ni shu natijaga qarab sozlang.

---

## 5. Skaner (lokal CLI)

> Venv aktiv bo'lmasa `tgguard` o'rniga `.\.venv\Scripts\tgguard.exe` deb yozing.

```bash
tgguard whoami                       # sessiya qaysi akkaunt ekanini ko'rsatadi
tgguard chats                        # kanal/guruhlar va ularning -100... id lari
tgguard scan --channel @mychannel    # kanal + muhokama guruhi a'zolarini tekshirish
tgguard scan --limit 200             # sinov uchun faqat 200 ta
tgguard scan --force                 # keshni e'tiborsiz qoldirib qayta tekshirish
tgguard list                         # belgilangan profillar ro'yxati (havola + sabab)
tgguard report                       # umumiy hisobot
tgguard apply --dry-run              # (sukut bo'yicha) kim ban qilinishini ko'rsatadi
tgguard apply --execute              # HAQIQIY ban (yozib tasdiqlash so'raydi)
tgguard unban 123456789              # xavfsizlik klapani
```

Muhim xususiyatlar:

- **Uzilsa davom etadi.** Har bir skan `scan_runs` jadvalida checkpoint qoldiradi;
  qayta ishga tushirsangiz, ko'rilgan foydalanuvchilar qaytadan tekshirilmaydi.
- **FloodWait.** Telegram cheklovi kelsa, skaner kerakli vaqt uxlab, davom etadi.
- **10 000 chegarasi.** Telegram `getParticipants` uchun ~10k natija beradi.
  Kanal kattaroq bo'lsa, skaner harf/raqam bo'yicha qidiruv orqali to'ldiradi va
  oxirida ⚠️ ogohlantirish chiqaradi: ro'yxat 100% to'liq bo'lmasligi mumkin,
  shuning uchun skanni davriy (masalan oyiga bir marta) takrorlang.
- **Kesh.** `cache.recheck_days` (30 kun) ichida tekshirilgan foydalanuvchi
  profil rasmi o'zgarmagan bo'lsa qayta yuklab olinmaydi.
- Ball `ban` chegarasidan oshsa, skaner **avtomatik `spam` qarorini yozadi**,
  lekin **hech kimni ban qilmaydi** — ban faqat `apply --execute` da bo'ladi.
- Shubhali (review oralig'idagi) profillar bot tokeni orqali review kanalga
  tushadi, ya'ni barcha review xabarlari bitta joyda.

### `tgguard list` — ro'yxatni terminalda ko'rish

Review kanalsiz ham to'liq ro'yxatni ko'rish va Excel'ga chiqarish:

```bash
tgguard list                                  # spam deb belgilanganlar (sukut)
tgguard list --verdict review                 # shubhalilar
tgguard list --verdict all --limit 200        # hammasi
tgguard list --min-score 0.7 --undecided      # yuqori ball, hali qaror qilinmagan
tgguard list --csv spam.csv                   # Excel uchun CSV (utf-8-sig)
```

Har bir qatorda: ID, ism, **profil havolasi** (`https://t.me/<username>` yoki
`tg://user?id=...`), ball, holat (`ban`/`review`/`ignore`), qaroringiz va sabab.
Bu buyruq faqat bazadan o'qiydi — Telegram'ga ulanmaydi, ya'ni `api_id`/token
bo'lmasa ham ishlaydi. CSV faylda sabab va bio to'liq ko'rinishda bo'ladi.

`apply --execute` bosqichma-bosqich: avval nechta foydalanuvchi ban qilinishini
aytadi, so'ng `yes` deb yozishni talab qiladi, keyin sekundiga ~1 ta (sozlanadi:
`actions.bans_interval_seconds`) tezlikda ban qiladi va har bir amalni
`actions` jadvaliga yozadi.

---

## 6. Bot (VPS)

```bash
git clone <repo> && cd tg-guard
cp .env.example .env      # to'ldiring (POSTGRES_PASSWORD ham!)
docker compose up -d --build
docker compose logs -f bot
```

Konteyner ishga tushganda avval `alembic upgrade head`, keyin bot ishga tushadi.
Loglar JSON formatida stdout ga chiqadi; `restart: unless-stopped` o'rnatilgan.

Bot buyruqlari (**shaxsiy chatda**, faqat `ADMIN_IDS` ro'yxatidagilar uchun):

| Buyruq | Vazifasi |
|---|---|
| `/stats` | Statistika: foydalanuvchilar, qarorlar, amallar, rejim |
| `/pending` | Kutayotgan review elementlari soni |
| `/ban <id>` | Kanal va guruhdan ban + qora ro'yxat |
| `/unban <id>` | Banni bekor qilish + oq ro'yxat |
| `/whitelist <id>` | Oq ro'yxatga qo'shish |
| `/mode` / `/mode enforce` | Rejimni ko'rish / almashtirish |
| `/health` | Baza va sozlamalar holati |
| `/report` | To'liq hisobot (terminalsiz) |
| `/check <id>` | Bitta foydalanuvchini sinovdan o'tkazish |

### Botni sinash (chora ko'rilmaydi)

- **Rasm yuboring** (shaxsiy chatda, admin sifatida) — bot NSFW ehtimolini,
  shu rasm beradigan ballni, chegaralarni va model topgan belgilar ro'yxatini
  qaytaradi. Chegaralarni sozlash uchun eng qulay yo'l.
- **Xabarni forward qiling** — o'sha odamning profili (rasm + bio + ism)
  baholanadi va ball sababi bilan chiqadi.
- `/check <id>` — id bo'yicha bitta profilni tekshirish.

Bularning hech biri hech kimni ban qilmaydi va bazadagi qarorlarni
o'zgartirmaydi — faqat ko'rsatadi.

### Skanerdan Telegram'ga xulosa

`tgguard scan` tugagach, adminlarga formatlangan xulosa yuboriladi
(ko'rilgan / spam / review / toza / davomiylik). O'chirish: `--no-notify`.
Buning uchun `BOT_TOKEN` va `ADMIN_IDS` to'ldirilgan bo'lishi va siz botga
bir marta `/start` bosgan bo'lishingiz kifoya (review kanal shart emas).

Review kanaldagi har bir xabarda 3 ta tugma: **🚫 Spam** (hamma joyda ban +
qo'lda qaror), **✅ Haqiqiy** (oq ro'yxat, ban bo'lgan bo'lsa bekor qilinadi),
**⏭ O'tkazish**. Tugmalar faqat `ADMIN_IDS` uchun ishlaydi; bosilgandan keyin
xabar tahrirlanib, kim qanday qaror qabul qilgani yoziladi.

### Profil havolasi haqida

Review xabarida ism **bosiladigan havola** bo'ladi:
- username bo'lsa — `https://t.me/<username>`;
- bo'lmasa — `tg://user?id=<id>` ko'rinishidagi HTML mention. Bu havola
  **faqat foydalanuvchini allaqachon "ko'rgan" klientlarda** ochiladi, shuning
  uchun xabarda **har doim raqamli id ham** ko'rsatiladi (`/ban <id>` uchun).

### Webhook (ixtiyoriy)

v1 uchun long polling yetarli. Webhook kerak bo'lsa: `bot/main.py` dagi
`start_polling` o'rniga aiogram ning `SimpleRequestHandler` + aiohttp
server'ini qo'ying, TLS ni reverse proxy (nginx/caddy) orqali bering va
`bot.set_webhook(...)` chaqiring. Bunda Docker Compose ga 8080 portini va
proxy'ni qo'shish kerak bo'ladi.

---

## 7. Skanerni VPS bazasiga ulash

Skaner lokalda ishlaydi, baza esa VPS da. Ikki variant:

**A) SSH tunnel (tavsiya etiladi).** Compose faylida port `127.0.0.1:5432` ga
bog'langan, ya'ni tashqaridan ochiq emas:

```bash
ssh -N -L 5432:localhost:5432 user@vps-ip
```

Keyin lokal `.env` da:

```
DATABASE_URL=postgresql+asyncpg://tgguard:PAROL@localhost:5432/tgguard
```

**B) Portni ochish (kamroq xavfsiz).** `docker-compose.yml` da portni
`"5432:5432"` ga o'zgartiring, kuchli parol qo'ying va **albatta** VPS
firewall'ida faqat o'z IP'ingizga ruxsat bering:

```bash
ufw allow from <sizning-ip> to any port 5432 proto tcp
```

Keyin `DATABASE_URL` da `localhost` o'rniga VPS IP sini yozing.

---

## 8. `config/scoring.yaml` ni sozlash

Barcha vazn va chegaralar shu faylda — kodga tegish shart emas
(o'zgartirgandan keyin bot/skanerni qayta ishga tushiring).

```yaml
thresholds:
  ban: 0.85      # >= ban   -> spam
  review: 0.50   # >= review -> qo'lda ko'rib chiqish
weights:
  nsfw_photo: 0.90     # eng kuchli signal
  bio_links: 0.45
  name_pattern: 0.35
  comment_pattern: 0.45
  comment_timing: 0.10
  no_username: 0.05
  premium: -0.10       # premium akkaunt "haqiqiy" tomonga suradi
  id_magnitude: 0.05
```

Signallar:

| Signal | Ma'nosi |
|---|---|
| `nsfw_photo` | Oxirgi 3 ta profil rasmidagi maksimal NSFW ehtimoli |
| `bio_links` | Bio da `t.me/`, `http`, `@kanal` yoki kalit so'zlar (uz/ru/en ro'yxati YAML da) |
| `name_pattern` | Ism/familiyada `18+`, havola yoki shu spam to'lqiniga xos emojilar |
| `comment_pattern` | (bot) izohda havola yoki boshqa flagged foydalanuvchilarda ko'rilgan shablon |
| `comment_timing` | (bot) post chiqqandan keyin N soniya ichida yozilgan izoh |
| `no_username`, `premium`, `id_magnitude` | Zaif evristikalar (past vazn) |

**Rasmsiz foydalanuvchilar uchun maxsus qoida** (`photoless:` bo'limi):
profil rasmi yo'q odam sukut bo'yicha **haqiqiy** deb qaraladi. `nsfw_photo`
= 0, zaif signallar umuman hisobga olinmaydi, va agar kuchli matn/havola
signallari (`bio_links`, `name_pattern`, `comment_pattern`) umuman ishlamasa,
ball `0.49` dan oshmaydi — ya'ni bunday odam hech qachon zaif belgilar bilan
ban qilinmaydi.

Har bir tekshiruv **sababi bilan** saqlanadi (`nsfw_photo=0.97 (…), bio_links=0.80 (t.me/, 18+)`)
va review kanalda ko'rsatiladi.

Kalit so'zlar ro'yxatini (`bio.keywords`) bemalol kengaytiring — bu YAML sizniki.

---

## 9. observe → enforce (birinchi kunlar)

- Sukut bo'yicha bot **`observe`** rejimida ishlaydi: **hech kimni avtomatik
  ban qilmaydi**, faqat review kanalga xabar beradi (shu jumladan "enforce
  bo'lganda ban qilinardi" belgisi bilan).
- Bir necha kun kuzating: review kanalga tushayotganlar haqiqatan spammi?
  Chegara/vaznlarni `scoring.yaml` da sozlang.
- Ishonch hosil qilgach: `/mode enforce`. Rejim bazada saqlanadi va
  qayta ishga tushirishdan keyin ham saqlanib qoladi.
- Xato bo'lsa: `/unban <id>` yoki `tgguard unban <id>` — har qanday amal qaytariladi.

**Ban qilish qoidasi:** ban faqat (a) qo'lda qaror, (b) qora ro'yxat, yoki
(c) `enforce` rejimida chegaradan oshgan ball asosida bo'ladi. `observe` rejimida
avtomatik ban umuman yo'q (qora ro'yxatdagilar ham faqat xabar qilinadi).

---

## 10. Maxfiylik va xavfsizlik

- Profil rasmlari **diskda saqlanmaydi**: tahlildan keyin darhol o'chiriladi;
  faqat review kanalga yuboriladigan vaqtinchalik nusxa istisno (u ham
  yuborilgach o'chiriladi). Bazada faqat rasm id si, ball va sabablar qoladi.
- Barcha sirlar `.env` da: `BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH`,
  `DATABASE_URL`, `ADMIN_IDS`, `REVIEW_CHANNEL_ID`. Namuna — `.env.example`.
- Telethon sessiya fayli repo tashqarisida saqlanadi (`TG_SESSION_PATH`).
- Har bir buzuvchi amal `actions` jadvaliga sabab bilan yoziladi va qaytariladi.
- Qora ro'yxat **global**: bitta kanalda spam deb topilgan foydalanuvchi tizim
  himoya qiladigan barcha kanallarda spam hisoblanadi.

---

## 11. Testlar

```bash
pytest -q
```

62 ta test: ball hisoblash (spam / haqiqiy / rasmsiz + havolali / rasmsiz toza),
qaror ustuvorligi (oq ro'yxat > qora ro'yxat > ball), observe/enforce siyosati,
review holat mashinasi, kesh, izoh shablonlari, hisobot va `list` filtrlari, review xabari
formati va **soxta Bot API** bilan to'liq real-vaqt quvuri (ban / observe /
oq ro'yxat / qora ro'yxat + vaqtinchalik rasmlar o'chirilishi).
NSFW klassifikator testlarda **mock** qilingan — CI da model yuklanmaydi
(`TGGUARD_NSFW_BACKEND=stub`).

---

## 12. Tez-tez uchraydigan muammolar

| Belgi | Sabab / yechim |
|---|---|
| Bot guruhdagi izohlarni ko'rmayapti | BotFather → `/setprivacy` → Disable; bot admin ekanini tekshiring |
| `rights_problem` logi | Bot kanalda/guruhda admin emas yoki delete/ban huquqi yo'q |
| Review kanalga xabar tushmayapti | `REVIEW_CHANNEL_ID` noto'g'ri yoki bot u yerda admin emas |
| `bio` bo'sh chiqyapti (bot tomonda) | Bot API foydalanuvchi bio sini har doim bermaydi — skaner (Telethon) buni to'ldiradi |
| `FloodWaitError` juda uzun | Skaner 1 soatgacha kutadi, undan uzoq bo'lsa to'xtaydi — keyinroq qayta ishga tushiring |
| Kanal 10k dan katta | Skaner qidiruv orqali to'ldiradi; skanni davriy takrorlang |
| `apply` hech kimni topmayapti | Avval `scan` qiling; `apply` faqat oxirgi qarori `spam` bo'lganlarni oladi |

---

## 13. Litsenziya / mas'uliyat

Bu vosita **o'z kanalingizni** himoya qilish uchun. Har bir avtomatik qaror
xato bo'lishi mumkin — shuning uchun sukut bo'yicha `observe` rejimi,
review kanal va `unban` mavjud. Ban qilishdan oldin hisobotga qarang.
