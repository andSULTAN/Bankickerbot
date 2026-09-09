"""All user-facing text, in Uzbek (Latin script). Edit here, nowhere else."""

from __future__ import annotations

# --- review channel ---------------------------------------------------------

BTN_SPAM = "🚫 Spam"
BTN_REAL = "✅ Haqiqiy"
BTN_SKIP = "⏭ O'tkazish"

REVIEW_TITLE_REVIEW = "🔎 <b>Tekshirish kerak</b>"
REVIEW_TITLE_AUTOBAN = "⛔️ <b>Avtomatik ban qilindi</b>"
REVIEW_TITLE_OBSERVE = "👀 <b>Kuzatuv (observe): ban qilinmadi</b>"
REVIEW_TITLE_BLACKLIST = "📛 <b>Qora ro'yxatdagi foydalanuvchi qaytdi</b>"
REVIEW_TITLE_SCANNER_SPAM = "🚨 <b>Skaner: spam (ban <code>apply</code> buyrug'ida)</b>"

REVIEW_NO_PHOTO = "🖼 Profil rasmi yo'q"
REVIEW_DECIDED = "\n\n<b>Qaror:</b> {verdict} — {who} ({when})"

VERDICT_LABEL = {
    "spam": "🚫 Spam",
    "real": "✅ Haqiqiy",
    "skip": "⏭ O'tkazildi",
}

CB_NOT_ADMIN = "Sizda bu tugmani bosish huquqi yo'q."
CB_ALREADY_DECIDED = "Bu profil bo'yicha qaror allaqachon qabul qilingan."
CB_DONE_SPAM = "Spam deb belgilandi va ban qilindi."
CB_DONE_REAL = "Haqiqiy foydalanuvchi — oq ro'yxatga qo'shildi."
CB_DONE_SKIP = "O'tkazib yuborildi."
CB_ERROR = "Xatolik: {error}"

# --- admin commands ---------------------------------------------------------

NOT_ADMIN = "Bu buyruq faqat adminlar uchun."

START = (
    "🛡 <b>TG-Guard</b>\n"
    "Kanal va muhokama guruhini spam akkauntlardan himoya qiladi.\n\n"
    "Buyruqlar:\n"
    "/stats — statistika\n"
    "/pending — kutayotgan tekshiruvlar soni\n"
    "/ban &lt;id&gt; — ban qilish\n"
    "/unban &lt;id&gt; — banni bekor qilish\n"
    "/whitelist &lt;id&gt; — oq ro'yxatga qo'shish\n"
    "/mode [observe|enforce] — rejimni ko'rish yoki almashtirish\n"
    "/health — holat"
)

STATS = (
    "📊 <b>Statistika</b>\n"
    "Foydalanuvchilar: <b>{users}</b> (rasmsiz: {photoless})\n"
    "Oxirgi tekshiruvlar: ban <b>{ban}</b> / review <b>{review}</b> / toza <b>{ignore}</b>\n"
    "Qarorlar: spam <b>{spam}</b> / haqiqiy <b>{real}</b>\n"
    "Kutayotgan review: <b>{pending}</b>\n"
    "Amallar: {actions}\n"
    "Rejim: <b>{mode}</b>"
)

PENDING = "⏳ Kutayotgan tekshiruvlar: <b>{count}</b>"

MODE_CURRENT = (
    "Joriy rejim: <b>{mode}</b>\n"
    "<code>/mode observe</code> — faqat kuzatadi, hech kimni ban qilmaydi\n"
    "<code>/mode enforce</code> — chegaradan oshganlarni avtomatik ban qiladi"
)
MODE_CHANGED = "Rejim o'zgardi: <b>{mode}</b>"
MODE_INVALID = "Noto'g'ri rejim. Faqat: observe yoki enforce."

USAGE_ID = "Foydalanish: <code>{command} &lt;user_id&gt;</code>"
BAD_ID = "user_id butun son bo'lishi kerak."

BANNED_OK = "🚫 <code>{user_id}</code> ban qilindi (kanal + guruh)."
BANNED_FAIL = "Ban qilishda xatolik: {error}"
UNBANNED_OK = "♻️ <code>{user_id}</code> banni bekor qilindi va oq ro'yxatga o'tkazildi."
UNBANNED_FAIL = "Banni bekor qilishda xatolik: {error}"
WHITELIST_OK = "✅ <code>{user_id}</code> oq ro'yxatga qo'shildi."

HEALTH_OK = (
    "✅ Bot ishlayapti.\n"
    "Rejim: <b>{mode}</b>\n"
    "Baza: <b>{db}</b>\n"
    "Kanal: <code>{channel}</code>\n"
    "Guruh: <code>{group}</code>\n"
    "Review kanal: <code>{review}</code>"
)

RIGHTS_WARNING = (
    "⚠️ Bot <code>{chat}</code> chatida yetarli huquqlarga ega emas "
    "(o'chirish/ban kerak). Tekshiring: {detail}"
)

AUTO_BAN_NOTICE = (
    "⛔️ <b>Avtomatik ban</b>\n"
    "{profile}\n"
    "Ball: <b>{score:.2f}</b>\n"
    "Sabab: <code>{reasons}</code>\n"
    "Bekor qilish: <code>/unban {user_id}</code>"
)


def profile_line(name: str, user_id: int, username: str | None) -> str:
    """Clickable profile link + the numeric id (tg://user only resolves on
    clients that have already seen the user, so we always print the id too)."""
    safe_name = name or "(ismsiz)"
    if username:
        link = f'<a href="https://t.me/{username}">{safe_name}</a> (@{username})'
    else:
        link = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    return f"{link}\nID: <code>{user_id}</code>"
