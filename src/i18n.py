"""
Tiny dict-based localisation for bot replies (en / ru / uz).

Each key keeps its translations side by side so they are easy to keep in
sync; `tests/test_i18n.py` checks every key has every language and the same
{placeholders}. Values passed to `t()` must already be HTML-safe where the
text is sent as HTML.
"""
from __future__ import annotations

from typing import Optional

LANGUAGES: tuple[str, ...] = ("en", "ru", "uz")
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "ru": "Русский", "uz": "Oʻzbekcha"}

CATALOG: dict[str, dict[str, str]] = {
    # ── general ────────────────────────────────────────────────────────────────
    "help": {
        "en": (
            "👋 <b>Sentry → Telegram Bot</b>\n\n"
            "I forward Sentry webhook events to Telegram chats.\n\n"
            "<b>Commands:</b>\n"
            "• /subscribe — route Sentry events to this chat\n"
            "• /routes — view and remove routing rules; /routes verbose — details + recent changes\n"
            "• /add_route &lt;slug|pattern&gt; [env] — add a route (wildcards: backend-*, *)\n"
            "• /filter &lt;slug|all&gt; level=&lt;min&gt; actions=&lt;a,b&gt; — noise control\n"
            "• /mute &lt;30m|2h|1d&gt; [slug] and /unmute [slug] — pause alerts\n"
            "• /digest &lt;slug|all&gt; &lt;minutes|off&gt; — batch events into periodic digests\n"
            "• /settings, /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt; — chat preferences\n"
            "• Run /subscribe or /add_route inside a forum topic to post there\n"
            "• /export — download this chat's routes as JSON; /import — load them (attach or reply to the file)\n"
            "• /test [issue|error|event_alert|metric_alert|release] — post a sample alert here\n"
            "• /last — show the last events delivered to this chat; /stats — counts per project; /retry_failed [N] — re-send failed ones\n"
            "• /chat_id — show this chat's id (for DEFAULT_CHAT_ID); /whoami — your id and permissions\n"
            "• /sentry_user &lt;username|email&gt; — who “Assign to me” assigns issues to\n"
            "• /help — show this message"
        ),
        "ru": (
            "👋 <b>Sentry → Telegram бот</b>\n\n"
            "Я пересылаю события из вебхуков Sentry в чаты Telegram.\n\n"
            "<b>Команды:</b>\n"
            "• /subscribe — направлять события Sentry в этот чат\n"
            "• /routes — просмотр и удаление маршрутов; /routes verbose — подробности и последние изменения\n"
            "• /add_route &lt;slug|шаблон&gt; [env] — добавить маршрут (шаблоны: backend-*, *)\n"
            "• /filter &lt;slug|all&gt; level=&lt;мин&gt; actions=&lt;a,b&gt; — фильтрация шума\n"
            "• /mute &lt;30m|2h|1d&gt; [slug] и /unmute [slug] — приостановить оповещения\n"
            "• /digest &lt;slug|all&gt; &lt;минуты|off&gt; — собирать события в периодические сводки\n"
            "• /settings, /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt; — настройки чата\n"
            "• Запустите /subscribe или /add_route внутри темы форума, чтобы писать туда\n"
            "• /export — скачать маршруты чата в JSON; /import — загрузить их (приложите файл или ответьте на него)\n"
            "• /test [issue|error|event_alert|metric_alert|release] — отправить пример оповещения\n"
            "• /last — последние доставки в этот чат; /stats — статистика по проектам; /retry_failed [N] — повторить неудачные\n"
            "• /chat_id — id этого чата (для DEFAULT_CHAT_ID); /whoami — ваш id и права\n"
            "• /sentry_user &lt;username|email&gt; — на кого назначать по кнопке «Назначить на меня»\n"
            "• /help — показать это сообщение"
        ),
        "uz": (
            "👋 <b>Sentry → Telegram bot</b>\n\n"
            "Men Sentry vebxuk hodisalarini Telegram chatlariga yuboraman.\n\n"
            "<b>Buyruqlar:</b>\n"
            "• /subscribe — Sentry hodisalarini shu chatga yoʻnaltirish\n"
            "• /routes — yoʻnalishlarni koʻrish va oʻchirish; /routes verbose — tafsilotlar va soʻnggi oʻzgarishlar\n"
            "• /add_route &lt;slug|shablon&gt; [env] — yoʻnalish qoʻshish (shablonlar: backend-*, *)\n"
            "• /filter &lt;slug|all&gt; level=&lt;min&gt; actions=&lt;a,b&gt; — shovqinni kamaytirish\n"
            "• /mute &lt;30m|2h|1d&gt; [slug] va /unmute [slug] — ogohlantirishlarni toʻxtatib turish\n"
            "• /digest &lt;slug|all&gt; &lt;daqiqa|off&gt; — hodisalarni davriy jamlanmaga yigʻish\n"
            "• /settings, /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt; — chat sozlamalari\n"
            "• Forum mavzusiga yozish uchun /subscribe yoki /add_route ni oʻsha mavzu ichida yuboring\n"
            "• /export — chat yoʻnalishlarini JSON qilib yuklab olish; /import — ularni yuklash (fayl biriktiring yoki unga javob bering)\n"
            "• /test [issue|error|event_alert|metric_alert|release] — namuna ogohlantirish yuborish\n"
            "• /last — shu chatga soʻnggi yetkazishlar; /stats — loyihalar boʻyicha statistika; /retry_failed [N] — muvaffaqiyatsizlarini qayta yuborish\n"
            "• /chat_id — shu chat id si (DEFAULT_CHAT_ID uchun); /whoami — sizning id va huquqlaringiz\n"
            "• /sentry_user &lt;username|email&gt; — “Menga biriktirish” tugmasi kimga biriktirishi\n"
            "• /help — ushbu xabarni koʻrsatish"
        ),
    },
    "denied": {
        "en": "⛔ You are not allowed to do that.",
        "ru": "⛔ У вас нет прав на это действие.",
        "uz": "⛔ Sizda bu amal uchun ruxsat yoʻq.",
    },
    "yes": {"en": "yes", "ru": "да", "uz": "ha"},
    "no": {"en": "no", "ru": "нет", "uz": "yoʻq"},
    "off": {"en": "off", "ru": "выкл.", "uz": "oʻchiq"},
    "none": {"en": "<i>none</i>", "ru": "<i>нет</i>", "uz": "<i>yoʻq</i>"},
    "no_matching_routes": {
        "en": "No matching routes in this chat.",
        "ru": "В этом чате нет подходящих маршрутов.",
        "uz": "Bu chatda mos yoʻnalishlar yoʻq.",
    },
    "chat_id": {
        "en": "This chat's id: <code>{chat_id}</code>",
        "ru": "Id этого чата: <code>{chat_id}</code>",
        "uz": "Bu chat id si: <code>{chat_id}</code>",
    },
    # ── routes ─────────────────────────────────────────────────────────────────
    "routes.none": {
        "en": "No routing rules for this chat. Use /subscribe or /add_route to add one.",
        "ru": "Для этого чата нет маршрутов. Добавьте через /subscribe или /add_route.",
        "uz": "Bu chat uchun yoʻnalishlar yoʻq. /subscribe yoki /add_route orqali qoʻshing.",
    },
    "routes.prompt": {
        "en": "Routes for this chat — tap a button to remove it:",
        "ru": "Маршруты этого чата — нажмите кнопку, чтобы удалить:",
        "uz": "Bu chat yoʻnalishlari — oʻchirish uchun tugmani bosing:",
    },
    "routes.verbose_title": {
        "en": "<b>Routes for this chat ({n}):</b>",
        "ru": "<b>Маршруты этого чата ({n}):</b>",
        "uz": "<b>Bu chat yoʻnalishlari ({n}):</b>",
    },
    "routes.recent_changes": {
        "en": "<b>Recent changes:</b>",
        "ru": "<b>Последние изменения:</b>",
        "uz": "<b>Soʻnggi oʻzgarishlar:</b>",
    },
    "route.any_env": {"en": "any environment", "ru": "любое окружение", "uz": "istalgan muhit"},
    "route.digest": {"en": "digest {n}m", "ru": "сводка {n} мин", "uz": "jamlanma {n} daq"},
    "route.topic": {"en": "topic {id}", "ru": "тема {id}", "uz": "mavzu {id}"},
    "route.muted": {"en": "🔇 until {when}", "ru": "🔇 до {when}", "uz": "🔇 {when} gacha"},
    "route.added_at": {"en": "added {when}", "ru": "добавлен {when}", "uz": "qoʻshilgan {when}"},
    "route.by": {"en": " by <code>{user}</code>", "ru": " пользователем <code>{user}</code>", "uz": ", <code>{user}</code> tomonidan"},
    "route.added": {
        "en": "✅ Route added: {label} → this chat.",
        "ru": "✅ Маршрут добавлен: {label} → этот чат.",
        "uz": "✅ Yoʻnalish qoʻshildi: {label} → shu chat.",
    },
    "route.exists": {
        "en": "ℹ️ Route already exists: {label} → this chat.",
        "ru": "ℹ️ Маршрут уже существует: {label} → этот чат.",
        "uz": "ℹ️ Yoʻnalish allaqachon mavjud: {label} → shu chat.",
    },
    "kb.any_env": {"en": "🌐 Any environment", "ru": "🌐 Любое окружение", "uz": "🌐 Istalgan muhit"},
    "kb.any_env_short": {"en": "any env", "ru": "любое", "uz": "istalgan"},
    # ── whoami / last ──────────────────────────────────────────────────────────
    "whoami.user": {
        "en": "👤 {name}\nUser id: <code>{id}</code>",
        "ru": "👤 {name}\nId пользователя: <code>{id}</code>",
        "uz": "👤 {name}\nFoydalanuvchi id si: <code>{id}</code>",
    },
    "whoami.admin": {"en": "🔑 Admin: {answer}", "ru": "🔑 Администратор: {answer}", "uz": "🔑 Administrator: {answer}"},
    "whoami.chat": {
        "en": "💬 Chat id: <code>{id}</code> ({type})",
        "ru": "💬 Id чата: <code>{id}</code> ({type})",
        "uz": "💬 Chat id si: <code>{id}</code> ({type})",
    },
    "whoami.topic": {
        "en": "🧵 Topic id: <code>{id}</code>",
        "ru": "🧵 Id темы: <code>{id}</code>",
        "uz": "🧵 Mavzu id si: <code>{id}</code>",
    },
    "last.empty": {
        "en": "Nothing has been delivered to this chat yet.",
        "ru": "В этот чат пока ничего не доставлялось.",
        "uz": "Bu chatga hali hech narsa yetkazilmagan.",
    },
    "last.title": {
        "en": "<b>Last deliveries to this chat:</b>",
        "ru": "<b>Последние доставки в этот чат:</b>",
        "uz": "<b>Shu chatga soʻnggi yetkazishlar:</b>",
    },
    # ── subscribe / add_route ──────────────────────────────────────────────────
    "subscribe.no_projects": {
        "en": (
            "No Sentry projects seen yet.\n\n"
            "Once Sentry sends the first webhook event the project will appear here.\n\n"
            "You can also add a route right now with:\n"
            "<code>/add_route &lt;project-slug&gt; [environment]</code>"
        ),
        "ru": (
            "Пока не видно ни одного проекта Sentry.\n\n"
            "Проект появится здесь, когда Sentry пришлёт первое событие.\n\n"
            "Маршрут можно добавить и сейчас:\n"
            "<code>/add_route &lt;project-slug&gt; [environment]</code>"
        ),
        "uz": (
            "Hali birorta Sentry loyihasi koʻrinmadi.\n\n"
            "Sentry birinchi hodisani yuborgach, loyiha shu yerda paydo boʻladi.\n\n"
            "Yoʻnalishni hozir ham qoʻshishingiz mumkin:\n"
            "<code>/add_route &lt;project-slug&gt; [environment]</code>"
        ),
    },
    "subscribe.prompt": {
        "en": "Select a Sentry project to route to this chat:",
        "ru": "Выберите проект Sentry для этого чата:",
        "uz": "Shu chat uchun Sentry loyihasini tanlang:",
    },
    "subscribe.unknown_project": {
        "en": "Unknown project — run /subscribe again.",
        "ru": "Неизвестный проект — запустите /subscribe ещё раз.",
        "uz": "Nomaʼlum loyiha — /subscribe ni qayta ishga tushiring.",
    },
    "subscribe.unknown_env": {
        "en": "Unknown environment — run /subscribe again.",
        "ru": "Неизвестное окружение — запустите /subscribe ещё раз.",
        "uz": "Nomaʼlum muhit — /subscribe ni qayta ishga tushiring.",
    },
    "subscribe.expired": {
        "en": "This menu has expired — run /subscribe again.",
        "ru": "Это меню устарело — запустите /subscribe ещё раз.",
        "uz": "Bu menyu eskirgan — /subscribe ni qayta ishga tushiring.",
    },
    "subscribe.choose_env": {
        "en": "Project: <b>{project}</b>\n\nChoose an environment:",
        "ru": "Проект: <b>{project}</b>\n\nВыберите окружение:",
        "uz": "Loyiha: <b>{project}</b>\n\nMuhitni tanlang:",
    },
    "add_route.usage": {
        "en": "Usage: <code>/add_route &lt;project-slug&gt; [environment]</code>",
        "ru": "Использование: <code>/add_route &lt;project-slug&gt; [environment]</code>",
        "uz": "Foydalanish: <code>/add_route &lt;project-slug&gt; [environment]</code>",
    },
    "add_route.invalid": {
        "en": "Invalid project slug or environment.\n{usage}",
        "ru": "Неверный slug проекта или окружение.\n{usage}",
        "uz": "Loyiha slugi yoki muhit notoʻgʻri.\n{usage}",
    },
    # ── filter / mute / digest ─────────────────────────────────────────────────
    "filter.usage": {
        "en": (
            "Usage: <code>/filter &lt;project-slug|all&gt; [level=&lt;min&gt;] [actions=&lt;a,b&gt;]</code>\n"
            "or <code>/filter &lt;project-slug|all&gt; clear</code>\n\n"
            "Levels: {levels}. Actions e.g. created,resolved,assigned."
        ),
        "ru": (
            "Использование: <code>/filter &lt;project-slug|all&gt; [level=&lt;мин&gt;] [actions=&lt;a,b&gt;]</code>\n"
            "или <code>/filter &lt;project-slug|all&gt; clear</code>\n\n"
            "Уровни: {levels}. Действия, напр. created,resolved,assigned."
        ),
        "uz": (
            "Foydalanish: <code>/filter &lt;project-slug|all&gt; [level=&lt;min&gt;] [actions=&lt;a,b&gt;]</code>\n"
            "yoki <code>/filter &lt;project-slug|all&gt; clear</code>\n\n"
            "Darajalar: {levels}. Amallar, masalan created,resolved,assigned."
        ),
    },
    "filter.cleared": {
        "en": "🧹 Filters cleared on {n} route(s).",
        "ru": "🧹 Фильтры сброшены (маршрутов: {n}).",
        "uz": "🧹 Filtrlar tozalandi (yoʻnalishlar: {n}).",
    },
    "filter.unknown_level": {
        "en": "Unknown level <code>{value}</code>.\n{usage}",
        "ru": "Неизвестный уровень <code>{value}</code>.\n{usage}",
        "uz": "Nomaʼlum daraja <code>{value}</code>.\n{usage}",
    },
    "filter.no_routes": {
        "en": "No matching routes in this chat. Add one first with /subscribe.",
        "ru": "В этом чате нет подходящих маршрутов. Сначала добавьте маршрут через /subscribe.",
        "uz": "Bu chatda mos yoʻnalishlar yoʻq. Avval /subscribe orqali qoʻshing.",
    },
    "filter.updated": {
        "en": "🔧 Updated {n} route(s): <code>{desc}</code>",
        "ru": "🔧 Обновлено маршрутов: {n}: <code>{desc}</code>",
        "uz": "🔧 Yangilangan yoʻnalishlar: {n}: <code>{desc}</code>",
    },
    "mute.usage": {
        "en": "Usage: <code>/mute &lt;30m|2h|1d&gt; [project-slug]</code>",
        "ru": "Использование: <code>/mute &lt;30m|2h|1d&gt; [project-slug]</code>",
        "uz": "Foydalanish: <code>/mute &lt;30m|2h|1d&gt; [project-slug]</code>",
    },
    "mute.done": {
        "en": "🔇 Muted {n} route(s) until <code>{until} UTC</code>. Use /unmute to resume.",
        "ru": "🔇 Заглушено маршрутов: {n} до <code>{until} UTC</code>. Возобновить: /unmute.",
        "uz": "🔇 {n} ta yoʻnalish <code>{until} UTC</code> gacha ovozsiz. Qayta yoqish: /unmute.",
    },
    "unmute.usage": {
        "en": "Usage: <code>/unmute [project-slug]</code>",
        "ru": "Использование: <code>/unmute [project-slug]</code>",
        "uz": "Foydalanish: <code>/unmute [project-slug]</code>",
    },
    "unmute.done": {
        "en": "🔔 Unmuted {n} route(s).",
        "ru": "🔔 Оповещения возобновлены (маршрутов: {n}).",
        "uz": "🔔 Ogohlantirishlar qayta yoqildi (yoʻnalishlar: {n}).",
    },
    "digest.usage": {
        "en": "Usage: <code>/digest &lt;project-slug|all&gt; &lt;minutes|off&gt;</code>  (e.g. /digest all 60)",
        "ru": "Использование: <code>/digest &lt;project-slug|all&gt; &lt;минуты|off&gt;</code>  (напр. /digest all 60)",
        "uz": "Foydalanish: <code>/digest &lt;project-slug|all&gt; &lt;daqiqa|off&gt;</code>  (masalan /digest all 60)",
    },
    "digest.range": {
        "en": "Minutes must be between 1 and 1440.\n{usage}",
        "ru": "Количество минут должно быть от 1 до 1440.\n{usage}",
        "uz": "Daqiqalar 1 dan 1440 gacha boʻlishi kerak.\n{usage}",
    },
    "digest.off": {
        "en": "⚡ {n} route(s) switched back to instant delivery.",
        "ru": "⚡ Мгновенная доставка снова включена (маршрутов: {n}).",
        "uz": "⚡ Darhol yetkazish qayta yoqildi (yoʻnalishlar: {n}).",
    },
    "digest.on": {
        "en": "📰 {n} route(s) will now send a digest every {minutes} min.",
        "ru": "📰 Сводка каждые {minutes} мин (маршрутов: {n}).",
        "uz": "📰 Har {minutes} daqiqada jamlanma yuboriladi (yoʻnalishlar: {n}).",
    },
    # ── settings ───────────────────────────────────────────────────────────────
    "settings.text": {
        "en": (
            "<b>Chat settings</b>\n"
            "🕒 Timezone: <code>{tz}</code>\n"
            "🌙 Quiet hours: <code>{quiet}</code> (fatal events still delivered)\n"
            "🗣 Language: <code>{language}</code>\n"
            "📝 Format: <code>{format}</code>\n\n"
            "Change with /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt;, /format &lt;html|plain&gt;"
        ),
        "ru": (
            "<b>Настройки чата</b>\n"
            "🕒 Часовой пояс: <code>{tz}</code>\n"
            "🌙 Тихие часы: <code>{quiet}</code> (события уровня fatal доставляются всегда)\n"
            "🗣 Язык: <code>{language}</code>\n"
            "📝 Формат: <code>{format}</code>\n\n"
            "Изменить: /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt;, /format &lt;html|plain&gt;"
        ),
        "uz": (
            "<b>Chat sozlamalari</b>\n"
            "🕒 Vaqt mintaqasi: <code>{tz}</code>\n"
            "🌙 Sokin soatlar: <code>{quiet}</code> (fatal hodisalar baribir yetkaziladi)\n"
            "🗣 Til: <code>{language}</code>\n"
            "📝 Format: <code>{format}</code>\n\n"
            "Oʻzgartirish: /tz &lt;Area/City&gt;, /quiet &lt;22:00-08:00|off&gt;, /lang &lt;en|ru|uz&gt;, /format &lt;html|plain&gt;"
        ),
    },
    "tz.usage": {
        "en": "Usage: <code>/tz Asia/Tashkent</code>",
        "ru": "Использование: <code>/tz Asia/Tashkent</code>",
        "uz": "Foydalanish: <code>/tz Asia/Tashkent</code>",
    },
    "tz.unknown": {
        "en": "Unknown timezone <code>{tz}</code>. Use an IANA name like Europe/Berlin.",
        "ru": "Неизвестный часовой пояс <code>{tz}</code>. Укажите имя IANA, напр. Europe/Moscow.",
        "uz": "Nomaʼlum vaqt mintaqasi <code>{tz}</code>. IANA nomini kiriting, masalan Asia/Tashkent.",
    },
    "tz.set": {
        "en": "🕒 Timezone set to <code>{tz}</code>.",
        "ru": "🕒 Часовой пояс: <code>{tz}</code>.",
        "uz": "🕒 Vaqt mintaqasi: <code>{tz}</code>.",
    },
    "quiet.usage": {
        "en": "Usage: <code>/quiet 22:00-08:00</code> or <code>/quiet off</code> (times in the chat's timezone)",
        "ru": "Использование: <code>/quiet 22:00-08:00</code> или <code>/quiet off</code> (время в часовом поясе чата)",
        "uz": "Foydalanish: <code>/quiet 22:00-08:00</code> yoki <code>/quiet off</code> (vaqt chat mintaqasida)",
    },
    "quiet.disabled": {
        "en": "🔔 Quiet hours disabled.",
        "ru": "🔔 Тихие часы отключены.",
        "uz": "🔔 Sokin soatlar oʻchirildi.",
    },
    "quiet.set": {
        "en": "🌙 Quiet hours set: <code>{start}–{end}</code>. Non-fatal events are held and sent as a digest when they end.",
        "ru": "🌙 Тихие часы: <code>{start}–{end}</code>. События (кроме fatal) придержим и пришлём сводкой по окончании.",
        "uz": "🌙 Sokin soatlar: <code>{start}–{end}</code>. Fatal boʻlmagan hodisalar ushlab turiladi va tugagach jamlanma sifatida yuboriladi.",
    },
    "format.usage": {
        "en": "Usage: <code>/format &lt;html|plain&gt;</code> — plain sends alerts without formatting or links",
        "ru": "Использование: <code>/format &lt;html|plain&gt;</code> — plain отправляет оповещения без форматирования и ссылок",
        "uz": "Foydalanish: <code>/format &lt;html|plain&gt;</code> — plain ogohlantirishlarni formatlash va havolalarsiz yuboradi",
    },
    "format.set": {
        "en": "📝 Alert format set to <code>{format}</code>.",
        "ru": "📝 Формат оповещений: <code>{format}</code>.",
        "uz": "📝 Ogohlantirish formati: <code>{format}</code>.",
    },
    "lang.usage": {
        "en": "Usage: <code>/lang &lt;en|ru|uz&gt;</code>",
        "ru": "Использование: <code>/lang &lt;en|ru|uz&gt;</code>",
        "uz": "Foydalanish: <code>/lang &lt;en|ru|uz&gt;</code>",
    },
    "lang.set": {
        "en": "🗣 Language set to {name}.",
        "ru": "🗣 Язык: {name}.",
        "uz": "🗣 Til: {name}.",
    },
    # ── export / import ────────────────────────────────────────────────────────
    "export.empty": {
        "en": "No routing rules to export in this chat.",
        "ru": "В этом чате нет маршрутов для экспорта.",
        "uz": "Bu chatda eksport qilinadigan yoʻnalishlar yoʻq.",
    },
    "export.caption": {
        "en": "📦 {n} route(s). Send this file with the caption /import (or reply /import to it) in any chat to load them.",
        "ru": "📦 Маршрутов: {n}. Отправьте этот файл с подписью /import (или ответьте на него /import) в любом чате, чтобы загрузить их.",
        "uz": "📦 Yoʻnalishlar: {n}. Ularni yuklash uchun bu faylni istalgan chatga /import izohi bilan yuboring (yoki unga /import deb javob bering).",
    },
    "import.usage": {
        "en": (
            "Usage: send an exported JSON file with the caption <code>/import</code>, "
            "reply <code>/import</code> to such a file, or paste the JSON after the command."
        ),
        "ru": (
            "Использование: отправьте экспортированный JSON-файл с подписью <code>/import</code>, "
            "ответьте <code>/import</code> на такой файл или вставьте JSON после команды."
        ),
        "uz": (
            "Foydalanish: eksport qilingan JSON faylni <code>/import</code> izohi bilan yuboring, "
            "bunday faylga <code>/import</code> deb javob bering yoki JSON ni buyruqdan keyin joylang."
        ),
    },
    "import.too_large": {
        "en": "❌ File is larger than {kb} KB.",
        "ru": "❌ Файл больше {kb} КБ.",
        "uz": "❌ Fayl {kb} KB dan katta.",
    },
    "import.errors": {
        "en": "❌ Nothing imported:\n{errors}",
        "ru": "❌ Ничего не импортировано:\n{errors}",
        "uz": "❌ Hech narsa import qilinmadi:\n{errors}",
    },
    "import.more_errors": {
        "en": "…and {n} more",
        "ru": "…и ещё {n}",
        "uz": "…va yana {n} ta",
    },
    "import.empty": {
        "en": "The document contains no routes.",
        "ru": "В документе нет маршрутов.",
        "uz": "Hujjatda yoʻnalishlar yoʻq.",
    },
    "import.done": {
        "en": "📥 Imported {n} route(s): {added} added, {updated} updated.",
        "ru": "📥 Импортировано маршрутов: {n} (добавлено: {added}, обновлено: {updated}).",
        "uz": "📥 Import qilingan yoʻnalishlar: {n} (qoʻshildi: {added}, yangilandi: {updated}).",
    },
    # ── stats ──────────────────────────────────────────────────────────────────
    "stats.title": {
        "en": "<b>Delivery stats for this chat</b>",
        "ru": "<b>Статистика доставок в этот чат</b>",
        "uz": "<b>Shu chatga yetkazishlar statistikasi</b>",
    },
    "stats.period": {
        "en": "<b>{period}</b>: {total} event(s) — {breakdown}",
        "ru": "<b>{period}</b>: событий {total} — {breakdown}",
        "uz": "<b>{period}</b>: {total} ta hodisa — {breakdown}",
    },
    "stats.24h": {"en": "Last 24 hours", "ru": "За 24 часа", "uz": "Soʻnggi 24 soat"},
    "stats.7d": {"en": "Last 7 days", "ru": "За 7 дней", "uz": "Soʻnggi 7 kun"},
    "stats.top": {
        "en": "<b>Top projects (7 days):</b>",
        "ru": "<b>Самые активные проекты (7 дней):</b>",
        "uz": "<b>Eng faol loyihalar (7 kun):</b>",
    },
    "stats.empty": {
        "en": "No events for this chat in the last 7 days.",
        "ru": "За последние 7 дней событий для этого чата не было.",
        "uz": "Soʻnggi 7 kunda bu chat uchun hodisalar boʻlmadi.",
    },
    "status.sent": {"en": "sent", "ru": "доставлено", "uz": "yetkazildi"},
    "status.failed": {"en": "failed", "ru": "ошибки", "uz": "xato"},
    "status.skipped": {"en": "skipped", "ru": "пропущено", "uz": "oʻtkazib yuborildi"},
    "status.digest": {"en": "in digests", "ru": "в сводках", "uz": "jamlanmada"},
    "status.retried": {"en": "retried", "ru": "повторено", "uz": "qayta yuborildi"},
    # ── issue action buttons ───────────────────────────────────────────────────
    "btn.resolve": {"en": "✅ Resolve", "ru": "✅ Решено", "uz": "✅ Hal qilindi"},
    "btn.ignore": {"en": "🙈 Ignore", "ru": "🙈 Игнорировать", "uz": "🙈 Eʼtiborsiz qoldirish"},
    "btn.assign": {"en": "👤 Assign to me", "ru": "👤 Назначить на меня", "uz": "👤 Menga biriktirish"},
    "btn.open": {"en": "🔗 Open in Sentry", "ru": "🔗 Открыть в Sentry", "uz": "🔗 Sentryda ochish"},
    "issue.unknown": {
        "en": "This chat has no alert for that issue.",
        "ru": "В этом чате нет оповещения об этой проблеме.",
        "uz": "Bu chatda ushbu muammo haqida ogohlantirish yoʻq.",
    },
    "issue.no_api": {
        "en": "Sentry API access isn't configured for this organisation.",
        "ru": "Доступ к API Sentry для этой организации не настроен.",
        "uz": "Bu tashkilot uchun Sentry API ruxsati sozlanmagan.",
    },
    "issue.need_identity": {
        "en": "Tell me your Sentry username or email first: /sentry_user you@example.com",
        "ru": "Сначала укажите имя пользователя или email в Sentry: /sentry_user you@example.com",
        "uz": "Avval Sentry foydalanuvchi nomi yoki emailingizni kiriting: /sentry_user you@example.com",
    },
    "issue.done_resolve": {"en": "✅ Resolved in Sentry", "ru": "✅ Отмечено решённым в Sentry", "uz": "✅ Sentryda hal qilindi"},
    "issue.done_ignore": {"en": "🙈 Ignored in Sentry", "ru": "🙈 Проигнорировано в Sentry", "uz": "🙈 Sentryda eʼtiborsiz qoldirildi"},
    "issue.done_assign": {"en": "👤 Assigned to you", "ru": "👤 Назначено на вас", "uz": "👤 Sizga biriktirildi"},
    "issue.failed": {
        "en": "Sentry refused: {error}",
        "ru": "Sentry отклонил запрос: {error}",
        "uz": "Sentry rad etdi: {error}",
    },
    "sentry_user.usage": {
        "en": "Usage: <code>/sentry_user &lt;username|email&gt;</code> or <code>/sentry_user off</code>",
        "ru": "Использование: <code>/sentry_user &lt;username|email&gt;</code> или <code>/sentry_user off</code>",
        "uz": "Foydalanish: <code>/sentry_user &lt;username|email&gt;</code> yoki <code>/sentry_user off</code>",
    },
    "sentry_user.set": {
        "en": "👤 “Assign to me” will assign issues to <code>{user}</code> in Sentry.",
        "ru": "👤 «Назначить на меня» будет назначать проблемы на <code>{user}</code> в Sentry.",
        "uz": "👤 “Menga biriktirish” muammolarni Sentryda <code>{user}</code> ga biriktiradi.",
    },
    "sentry_user.current": {
        "en": "👤 Your Sentry user: <code>{user}</code>. Change with /sentry_user &lt;username|email&gt;.",
        "ru": "👤 Ваш пользователь Sentry: <code>{user}</code>. Изменить: /sentry_user &lt;username|email&gt;.",
        "uz": "👤 Sentry foydalanuvchingiz: <code>{user}</code>. Oʻzgartirish: /sentry_user &lt;username|email&gt;.",
    },
    "sentry_user.none": {
        "en": "No Sentry user linked. Set one with /sentry_user &lt;username|email&gt;.",
        "ru": "Пользователь Sentry не привязан. Укажите: /sentry_user &lt;username|email&gt;.",
        "uz": "Sentry foydalanuvchisi bogʻlanmagan. Kiriting: /sentry_user &lt;username|email&gt;.",
    },
    "sentry_user.cleared": {
        "en": "👤 Sentry user unlinked.",
        "ru": "👤 Пользователь Sentry отвязан.",
        "uz": "👤 Sentry foydalanuvchisi uzildi.",
    },
    # ── test ───────────────────────────────────────────────────────────────────
    "test.usage": {
        "en": "Usage: <code>/test [{kinds}]</code>",
        "ru": "Использование: <code>/test [{kinds}]</code>",
        "uz": "Foydalanish: <code>/test [{kinds}]</code>",
    },
    "test.no_routes": {
        "en": "ℹ️ This chat has no routes yet — real events will only arrive after /subscribe or /add_route.",
        "ru": "ℹ️ У этого чата пока нет маршрутов — настоящие события начнут приходить после /subscribe или /add_route.",
        "uz": "ℹ️ Bu chatda hali yoʻnalishlar yoʻq — haqiqiy hodisalar /subscribe yoki /add_route dan keyin keladi.",
    },
    "test.no_match": {
        "en": "no route in this chat matches this project",
        "ru": "ни один маршрут этого чата не подходит к этому проекту",
        "uz": "bu chatdagi hech bir yoʻnalish ushbu loyihaga mos emas",
    },
    "test.deliver": {
        "en": "✅ This chat's filters would deliver an event like this.",
        "ru": "✅ Фильтры этого чата пропустят такое событие.",
        "uz": "✅ Bu chat filtrlari bunday hodisani yetkazadi.",
    },
    "test.skip": {
        "en": "⏭ This chat's filters would skip it: {reason}",
        "ru": "⏭ Фильтры этого чата его пропустят: {reason}",
        "uz": "⏭ Bu chat filtrlari uni oʻtkazib yuboradi: {reason}",
    },
    "test.footer": {
        "en": "🧪 That was a test message.\n{verdict}",
        "ru": "🧪 Это было тестовое сообщение.\n{verdict}",
        "uz": "🧪 Bu sinov xabari edi.\n{verdict}",
    },
    # ── retry ──────────────────────────────────────────────────────────────────
    "retry.usage": {
        "en": "Usage: <code>/retry_failed [N]</code> (1–50, default 10)",
        "ru": "Использование: <code>/retry_failed [N]</code> (1–50, по умолчанию 10)",
        "uz": "Foydalanish: <code>/retry_failed [N]</code> (1–50, standart 10)",
    },
    "retry.nothing": {
        "en": "Nothing to retry — no failed deliveries with stored text in this chat.",
        "ru": "Нечего повторять — в этом чате нет неудачных доставок с сохранённым текстом.",
        "uz": "Qayta yuboriladigan narsa yoʻq — bu chatda saqlangan matnli muvaffaqiyatsiz yetkazishlar yoʻq.",
    },
    "retry.done": {
        "en": "🔁 Retried {total} delivery(ies): {sent} sent.",
        "ru": "🔁 Повторено доставок: {total}, отправлено: {sent}.",
        "uz": "🔁 Qayta urinilgan yetkazishlar: {total}, yuborildi: {sent}.",
    },
    "retry.done_failed": {
        "en": "🔁 Retried {total} delivery(ies): {sent} sent, {failed} failed again (see /last).",
        "ru": "🔁 Повторено доставок: {total}, отправлено: {sent}, снова не удалось: {failed} (см. /last).",
        "uz": "🔁 Qayta urinilgan yetkazishlar: {total}, yuborildi: {sent}, yana muvaffaqiyatsiz: {failed} (/last ga qarang).",
    },
    # ── route removal ──────────────────────────────────────────────────────────
    "del.expired": {
        "en": "This menu has expired — run /routes again.",
        "ru": "Это меню устарело — запустите /routes ещё раз.",
        "uz": "Bu menyu eskirgan — /routes ni qayta ishga tushiring.",
    },
    "del.all_removed": {
        "en": "✅ All routes removed for this chat.",
        "ru": "✅ Все маршруты этого чата удалены.",
        "uz": "✅ Bu chatning barcha yoʻnalishlari oʻchirildi.",
    },
    "del.removed": {"en": "Route removed.", "ru": "Маршрут удалён.", "uz": "Yoʻnalish oʻchirildi."},
    "del.gone": {
        "en": "Route was already gone.",
        "ru": "Маршрут уже был удалён.",
        "uz": "Yoʻnalish allaqachon oʻchirilgan.",
    },
    # ── event formatting (src/sentry/formatters.py) ────────────────────────────
    # Sentry's action tokens (CREATED, RESOLVED, …) are kept as-is.
    # Plural entries ("w." prefix) hold "|"-separated forms, see `plural()`.
    "fmt.by": {"en": " by {actor}", "ru": " — {actor}", "uz": " — {actor}"},
    "fmt.issue": {
        "en": "{emoji} <b>Issue {action}</b>{by}: {title}",
        "ru": "{emoji} <b>Проблема {action}</b>{by}: {title}",
        "uz": "{emoji} <b>Muammo {action}</b>{by}: {title}",
    },
    "fmt.project": {"en": "📁 Project: {project}", "ru": "📁 Проект: {project}", "uz": "📁 Loyiha: {project}"},
    "fmt.regression": {"en": "↩️ <b>Regression</b>", "ru": "↩️ <b>Регрессия</b>", "uz": "↩️ <b>Regressiya</b>"},
    "fmt.level": {"en": "Level: <b>{level}</b>", "ru": "Уровень: <b>{level}</b>", "uz": "Daraja: <b>{level}</b>"},
    "fmt.status": {"en": "Status: {status}", "ru": "Статус: {status}", "uz": "Holat: {status}"},
    "fmt.assigned": {"en": "👤 Assigned: {who}", "ru": "👤 Назначено: {who}", "uz": "👤 Biriktirilgan: {who}"},
    "fmt.counts": {
        "en": "📊 Events: {count} | Users: {users}",
        "ru": "📊 События: {count} | Пользователи: {users}",
        "uz": "📊 Hodisalar: {count} | Foydalanuvchilar: {users}",
    },
    "fmt.event_alert": {
        "en": "{emoji} <b>Event Alert</b>: {title}",
        "ru": "{emoji} <b>Оповещение о событии</b>: {title}",
        "uz": "{emoji} <b>Hodisa ogohlantirishi</b>: {title}",
    },
    "fmt.rule": {"en": "📋 Rule: <i>{rule}</i>", "ru": "📋 Правило: <i>{rule}</i>", "uz": "📋 Qoida: <i>{rule}</i>"},
    "fmt.env": {"en": "🌍 Env: <code>{env}</code>", "ru": "🌍 Окружение: <code>{env}</code>", "uz": "🌍 Muhit: <code>{env}</code>"},
    "fmt.release_line": {
        "en": "📦 Release: <code>{release}</code>",
        "ru": "📦 Релиз: <code>{release}</code>",
        "uz": "📦 Reliz: <code>{release}</code>",
    },
    "fmt.user": {"en": "👤 User: {user}", "ru": "👤 Пользователь: {user}", "uz": "👤 Foydalanuvchi: {user}"},
    "fmt.platform": {"en": "🖥️ Platform: {platform}", "ru": "🖥️ Платформа: {platform}", "uz": "🖥️ Platforma: {platform}"},
    "fmt.metric_alert": {
        "en": "{emoji} <b>Metric Alert</b>: {title}",
        "ru": "{emoji} <b>Оповещение по метрике</b>: {title}",
        "uz": "{emoji} <b>Metrika ogohlantirishi</b>: {title}",
    },
    "fmt.error": {"en": "{emoji} <b>Error</b>: {title}", "ru": "{emoji} <b>Ошибка</b>: {title}", "uz": "{emoji} <b>Xato</b>: {title}"},
    "fmt.id": {"en": "🆔 ID: <code>{id}</code>", "ru": "🆔 ID: <code>{id}</code>", "uz": "🆔 ID: <code>{id}</code>"},
    "fmt.comment": {
        "en": "{emoji} <b>Comment {action}</b>{by}",
        "ru": "{emoji} <b>Комментарий {action}</b>{by}",
        "uz": "{emoji} <b>Izoh {action}</b>{by}",
    },
    "fmt.issue_ref": {"en": "🔗 Issue: #{id}", "ru": "🔗 Проблема: #{id}", "uz": "🔗 Muammo: #{id}"},
    "fmt.integration": {
        "en": "{emoji} <b>Integration {action}</b>",
        "ru": "{emoji} <b>Интеграция {action}</b>",
        "uz": "{emoji} <b>Integratsiya {action}</b>",
    },
    "fmt.app": {"en": "App: <code>{app}</code>", "ru": "Приложение: <code>{app}</code>", "uz": "Ilova: <code>{app}</code>"},
    "fmt.org": {"en": "Org: <code>{org}</code>", "ru": "Организация: <code>{org}</code>", "uz": "Tashkilot: <code>{org}</code>"},
    "fmt.release": {
        "en": "{emoji} <b>Release {action}</b>: {head}",
        "ru": "{emoji} <b>Релиз {action}</b>: {head}",
        "uz": "{emoji} <b>Reliz {action}</b>: {head}",
    },
    "fmt.unknown_version": {"en": "(unknown version)", "ru": "(версия неизвестна)", "uz": "(versiya nomaʼlum)"},
    "fmt.commits": {"en": "🔀 Commits: {n}", "ru": "🔀 Коммиты: {n}", "uz": "🔀 Kommitlar: {n}"},
    "fmt.by_line": {"en": "by {actor}", "ru": "автор: {actor}", "uz": "muallif: {actor}"},
    "fmt.footer_to": {"en": "to {who}", "ru": "→ {who}", "uz": "→ {who}"},
    "fmt.footer_by": {"en": "by {actor}", "ru": "({actor})", "uz": "({actor})"},
    "fmt.no_title": {"en": "(no title)", "ru": "(без названия)", "uz": "(nomsiz)"},
    "fmt.burst": {
        "en": "🔁 <b>+{count} more</b> {events} for {title}{where} in the last {minutes} min",
        "ru": "🔁 <b>Ещё +{count}</b> {events} по {title}{where} за последние {minutes} мин",
        "uz": "🔁 <b>Yana +{count}</b> {events}: {title}{where}, soʻnggi {minutes} daqiqada",
    },
    "fmt.digest": {
        "en": "📰 <b>Digest</b>: {total} {events} across {groups} {issues}",
        "ru": "📰 <b>Сводка</b>: {total} {events} в {groups} {issues}",
        "uz": "📰 <b>Jamlanma</b>: {total} {events}, {groups} {issues}",
    },
    "fmt.digest_more": {
        "en": "… and {n} more issues",
        "ru": "… и ещё проблем: {n}",
        "uz": "… va yana {n} ta muammo",
    },
    "w.events": {"en": "event|events", "ru": "событие|события|событий", "uz": "ta hodisa"},
    "w.issues": {"en": "issue|issues", "ru": "проблеме|проблемах|проблемах", "uz": "ta muammo"},
}


def plural(lang: Optional[str], key: str, n: int) -> str:
    """
    Pick the plural form of a "w." catalog word for count `n`:
    English one|other, Russian one|few|many, Uzbek has a single form.
    """
    forms = t(lang, key).split("|")
    if len(forms) == 1:
        return forms[0]
    if len(forms) == 2:
        return forms[0] if n == 1 else forms[1]
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def normalize_language(code: Optional[str]) -> Optional[str]:
    """'ru', 'RU', 'ru-RU' → 'ru'; None for unsupported codes."""
    if not code:
        return None
    base = code.strip().lower().replace("_", "-").split("-")[0]
    return base if base in LANGUAGES else None


def t(lang: Optional[str], key: str, **kwargs: object) -> str:
    """Translate `key` into `lang` (falling back to English) and fill placeholders."""
    entry = CATALOG[key]
    text = entry.get(lang or DEFAULT_LANGUAGE) or entry[DEFAULT_LANGUAGE]
    return text.format(**kwargs) if kwargs else text
