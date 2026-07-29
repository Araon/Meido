"""Telegram text and inline-keyboard builders for Meido."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def home_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎬 Get anime",
                    callback_data="menu:getanime",
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 My requests",
                    callback_data="menu:status",
                ),
                InlineKeyboardButton(
                    "❓ Help",
                    callback_data="menu:help",
                ),
            ],
        ]
    )


def navigation_keyboard(*, back_callback="menu:home"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "‹ Back",
                    callback_data=back_callback,
                ),
                InlineKeyboardButton(
                    "Cancel",
                    callback_data="request:cancel",
                ),
            ]
        ]
    )


def season_keyboard():
    rows = []
    for start in (1, 4):
        rows.append(
            [
                InlineKeyboardButton(
                    str(season),
                    callback_data=f"season:{season}",
                )
                for season in range(start, start + 3)
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "⌨ Type another season",
                callback_data="season:custom",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "‹ Back",
                callback_data="request:back:title",
            ),
            InlineKeyboardButton(
                "Cancel",
                callback_data="request:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def episode_keyboard(start=1, page_size=12):
    episodes = range(start, start + page_size)
    rows = []
    current_row = []
    for episode in episodes:
        current_row.append(
            InlineKeyboardButton(
                str(episode),
                callback_data=f"episode:{episode}",
            )
        )
        if len(current_row) == 4:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    page_row = []
    if start > 1:
        page_row.append(
            InlineKeyboardButton(
                "‹ Previous",
                callback_data=f"episode_page:{max(1, start - page_size)}",
            )
        )
    page_row.append(
        InlineKeyboardButton(
            "Next ›",
            callback_data=f"episode_page:{start + page_size}",
        )
    )
    rows.append(page_row)
    rows.append(
        [
            InlineKeyboardButton(
                "⌨ Type episode",
                callback_data="episode:custom",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "‹ Season",
                callback_data="request:back:season",
            ),
            InlineKeyboardButton(
                "Cancel",
                callback_data="request:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def confirmation_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Prepare episode",
                    callback_data="request:confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Start over",
                    callback_data="request:back:title",
                ),
                InlineKeyboardButton(
                    "Cancel",
                    callback_data="request:cancel",
                ),
            ],
        ]
    )


def job_cancel_keyboard(job_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Stop updates",
                    callback_data=f"job:cancel:{job_id}",
                )
            ]
        ]
    )


def failed_job_keyboard(job_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "↻ Try again",
                    callback_data=f"job:retry:{job_id}",
                ),
                InlineKeyboardButton(
                    "⌂ Home",
                    callback_data="menu:home",
                ),
            ]
        ]
    )


def ready_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎬 Get another",
                    callback_data="menu:getanime",
                ),
                InlineKeyboardButton(
                    "📋 Requests",
                    callback_data="menu:status",
                ),
            ]
        ]
    )


def status_keyboard(jobs):
    rows = [
        [
            InlineKeyboardButton(
                f"Stop {job['series_name'][:22]} "
                f"S{int(job['season_id']):02d}E{int(job['episode_id']):02d}",
                callback_data=f"job:cancel:{job['job_id']}",
            )
        ]
        for job in jobs[:5]
    ]
    rows.append(
        [
            InlineKeyboardButton(
                "🎬 New request",
                callback_data="menu:getanime",
            ),
            InlineKeyboardButton(
                "⌂ Home",
                callback_data="menu:home",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)
