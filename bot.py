"""Unpacked UTM bot — makes consistently tagged Substack links inside one Telegram group.

Flow: /utm <link>  →  pick source (or Other → type it)  →  pick medium  →  tagged link.
Every link is logged to a Google Sheet.
"""
import asyncio
import html
import itertools
import json
import logging
import os
import time
from datetime import datetime

import gspread
from telegram import (ForceReply, InlineKeyboardButton, InlineKeyboardMarkup,
                      Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import utm

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("utm-bot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROUP_ID = int(os.environ["ALLOWED_GROUP_ID"]) if os.environ.get("ALLOWED_GROUP_ID") else None
ALLOWED_HOSTS = {h.strip().lower() for h in os.environ["ALLOWED_HOSTS"].split(",") if h.strip()}
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
SA_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

FLOW_TTL = 15 * 60  # seconds before an unfinished link request expires
HEADER = ["timestamp_sgt", "user", "username", "user_id", "original_url",
          "tagged_url", "utm_source", "utm_medium", "utm_campaign", "source_type"]

flows: dict[str, dict] = {}         # flow_id -> state
other_prompts: dict[int, str] = {}  # prompt message_id -> flow_id
_ids = itertools.count(1)


# ---------- Google Sheet ----------
_sheet = None


def _get_sheet():
    global _sheet
    if _sheet is None:
        gc = gspread.service_account_from_dict(json.loads(SA_JSON))
        ws = gc.open_by_key(SHEET_ID).sheet1
        if ws.row_values(1) != HEADER:
            ws.insert_row(HEADER, 1)
        _sheet = ws
    return _sheet


def _append(row: list) -> None:
    _get_sheet().append_row(row, value_input_option="RAW")


async def log_to_sheet(row: list) -> bool:
    if not (SHEET_ID and SA_JSON):
        log.warning("Sheet not configured; skipping log")
        return False
    try:
        await asyncio.to_thread(_append, row)
        return True
    except Exception:
        log.exception("Sheet logging failed")
        global _sheet
        _sheet = None  # reconnect next time
        return False


# ---------- helpers ----------
def in_group(update: Update) -> bool:
    return GROUP_ID is not None and update.effective_chat and update.effective_chat.id == GROUP_ID


def prune() -> None:
    cutoff = time.time() - FLOW_TTL
    for fid in [f for f, s in flows.items() if s["created"] < cutoff]:
        flows.pop(fid, None)
    for mid in [m for m, f in other_prompts.items() if f not in flows]:
        other_prompts.pop(mid, None)


def keyboard(prefix: str, fid: str, values: list[str], other: bool = False) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(v, callback_data=f"{prefix}|{fid}|{i}") for i, v in enumerate(values)]
    if other:
        buttons.append(InlineKeyboardButton("Other…", callback_data=f"{prefix}|{fid}|other"))
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"x|{fid}|0")])
    return InlineKeyboardMarkup(rows)


def medium_prompt(state: dict) -> str:
    return (f"Link for {html.escape(state['user_name'])}\n"
            f"Source: <b>{html.escape(state['source'])}</b>\n\nNow pick the medium:")


# ---------- commands ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not in_group(update):
        return
    await update.effective_message.reply_text(
        "Send <code>/utm &lt;Unpacked link&gt;</code>, or reply to a message containing a link with "
        "<code>/utm</code>. Then pick a source and a medium and I'll give you the tagged link.",
        parse_mode="HTML")


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Setup helper: tells you the ID to put in ALLOWED_GROUP_ID."""
    await update.effective_message.reply_text(f"Chat ID: <code>{update.effective_chat.id}</code>",
                                              parse_mode="HTML")


async def cmd_utm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not in_group(update):
        await msg.reply_text("This bot only works in the Unpacked group.")
        return
    prune()
    raw = utm.find_url(" ".join(ctx.args)) or utm.find_url(
        msg.reply_to_message and (msg.reply_to_message.text or msg.reply_to_message.caption))
    if not raw:
        await msg.reply_text("Send it as <code>/utm https://…</code>, or reply to a message with a link.",
                             parse_mode="HTML")
        return
    try:
        url = utm.check_url(raw, ALLOWED_HOSTS)
    except utm.BadURL as e:
        await msg.reply_text(str(e))
        return

    user = update.effective_user
    fid = str(next(_ids))
    flows[fid] = {"user_id": user.id, "user_name": user.full_name, "username": user.username or "",
                  "url": url, "source": None, "custom": False, "created": time.time(),
                  "cmd_msg_id": msg.message_id}
    await msg.reply_text(f"Link for {html.escape(user.full_name)}\n<code>{html.escape(url)}</code>\n\n"
                         "Where will it be shared?", parse_mode="HTML",
                         reply_markup=keyboard("s", fid, utm.SOURCES, other=True),
                         disable_web_page_preview=True)


# ---------- buttons ----------
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    kind, fid, val = q.data.split("|")
    state = flows.get(fid)
    if state is None:
        await q.answer("This request expired. Send /utm again.", show_alert=True)
        await q.edit_message_reply_markup(None)
        return
    if q.from_user.id != state["user_id"]:
        await q.answer(f"This one belongs to {state['user_name']}. Start your own with /utm.", show_alert=True)
        return
    await q.answer()

    if kind == "x":
        flows.pop(fid, None)
        await q.edit_message_text("Cancelled.")
        return

    if kind == "s":
        if val == "other":
            await q.edit_message_text("Waiting for a custom source…")
            prompt = await ctx.bot.send_message(
                q.message.chat_id, f"{html.escape(state['user_name'])}, reply to this message with the source "
                "(e.g. <i>straits times event</i>).", parse_mode="HTML",
                reply_to_message_id=state["cmd_msg_id"],
                reply_markup=ForceReply(selective=True, input_field_placeholder="source name"))
            other_prompts[prompt.message_id] = fid
            return
        state["source"] = utm.SOURCES[int(val)]
        await q.edit_message_text(medium_prompt(state), parse_mode="HTML",
                                  reply_markup=keyboard("m", fid, utm.MEDIUMS))
        return

    if kind == "m":
        await finish(q, state, fid, utm.MEDIUMS[int(val)])


async def on_other_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not in_group(update) or not msg.reply_to_message:
        return
    fid = other_prompts.get(msg.reply_to_message.message_id)
    state = flows.get(fid) if fid else None
    if state is None or msg.from_user.id != state["user_id"]:
        return
    source = utm.normalise(msg.text or "")
    if not source:
        await msg.reply_text("That came out empty after cleaning. Reply to my earlier message with letters or numbers.")
        return
    other_prompts.pop(msg.reply_to_message.message_id, None)
    state["source"], state["custom"] = source, True
    await msg.reply_text(medium_prompt(state), parse_mode="HTML",
                         reply_markup=keyboard("m", fid, utm.MEDIUMS))


async def finish(q, state: dict, fid: str, medium: str) -> None:
    flows.pop(fid, None)
    now = datetime.now(utm.SGT)
    campaign = utm.campaign_for(state["url"], now)
    tagged = utm.build(state["url"], state["source"], medium, campaign)
    ok = await log_to_sheet([now.strftime("%Y-%m-%d %H:%M:%S"), state["user_name"], state["username"],
                             str(state["user_id"]), state["url"], tagged, state["source"], medium,
                             campaign, "custom" if state["custom"] else "button"])
    text = (f"<code>{html.escape(tagged)}</code>\n\n"
            f"source: <b>{html.escape(state['source'])}</b>{' (custom)' if state['custom'] else ''}\n"
            f"medium: <b>{medium}</b>\n"
            f"campaign: <b>{html.escape(campaign)}</b>\n"
            f"made by: {html.escape(state['user_name'])}")
    if not ok:
        text += "\n\n⚠️ Couldn't log this to the sheet. The link still works."
    await q.edit_message_text(text, parse_mode="HTML", disable_web_page_preview=True)


def main() -> None:
    if GROUP_ID is None:
        log.warning("ALLOWED_GROUP_ID not set: only /chatid will work. Add the bot to the group and run it.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CommandHandler("utm", cmd_utm))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^[smx]\|"))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, on_other_reply))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
