import os
import time
import asyncio
import base64
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    BotCommand
)
from pyrogram.errors import (
    UserNotParticipant,
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PasswordHashInvalid,
    FloodWait,
    UserIsBlocked,
    InputUserDeactivated,
    PeerIdInvalid
)

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SHORTENER_URL = os.getenv("SHORTENER_URL", "vplink.in")
SHORTENER_API = os.getenv("SHORTENER_API", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

FSUB_CHANNEL = "Cosmic_Botz"
FSUB_LINK = "https://t.me/Cosmic_Botz"
SUPPORT_BOT_LINK = "https://t.me/UrCosmic_Robot"
TUTORIAL_LINK = "https://t.me/Cosmic_Botz"
START_BANNER = "https://graph.org/file/f6e2ec52e426615b1442c-29b139db080e7dc23c.jpg"

bot = Client("Cosmic_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Async Mongo Client for 1000+ Concurrent Users Performance
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["cosmic_bot_db"]
users_col = db["users"]
tokens_col = db["tokens"]

user_states = {}
active_transfers = {}

async def get_user_data(user_id: int):
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "session": None,
            "token_expiry": None,
            "settings": {
                "fn_find": None,
                "fn_replace": None,
                "cap_find": None,
                "cap_replace": None,
                "cap_remove": None,
                "extra_caption": None,
                "dest_topic": None,
                "thumbnail": None
            }
        }
        await users_col.insert_one(user)
    return user

async def update_user_settings(user_id: int, key: str, value):
    await users_col.update_one({"user_id": user_id}, {"$set": {f"settings.{key}": value}}, upsert=True)

async def clear_user_settings(user_id: int):
    empty_settings = {
        "fn_find": None,
        "fn_replace": None,
        "cap_find": None,
        "cap_replace": None,
        "cap_remove": None,
        "extra_caption": None,
        "dest_topic": None,
        "thumbnail": None
    }
    await users_col.update_one({"user_id": user_id}, {"$set": {"settings": empty_settings}})

async def is_token_valid(user_id: int) -> bool:
    user = await get_user_data(user_id)
    expiry = user.get("token_expiry")
    if expiry and isinstance(expiry, datetime):
        return datetime.utcnow() < expiry
    return False

def parse_telegram_link(link: str):
    link = link.strip()
    topic_id = None
    if "/c/" in link:
        parts = link.split("/c/")[1].split("/")
        chat_id = int("-100" + parts[0])
        if len(parts) == 3:
            topic_id = int(parts[1])
            msg_id = int(parts[2])
        else:
            msg_id = int(parts[1])
    else:
        parts = link.split("/")
        chat_id = parts[-2]
        msg_id = int(parts[-1])
    return chat_id, msg_id, topic_id

async def check_fsub(client: Client, message: Message) -> bool:
    user_id = message.from_user.id
    try:
        member = await client.get_chat_member(FSUB_CHANNEL, user_id)
        if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.RESTRICTED]:
            await message.reply("Aap is channel se banned hain.")
            return False
        return True
    except UserNotParticipant:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=FSUB_LINK)],
            [InlineKeyboardButton("🔄 Try Again", url=f"https://t.me/{client.me.username}?start=fsub")]
        ])
        await message.reply(
            "⚠️ **Access Denied!**\n\nBot ke sabhi features use karne ke liye aapko hamare official channel ko join karna hoga.",
            reply_markup=buttons
        )
        return False
    except Exception:
        return True

async def set_menu_commands(app: Client):
    await app.set_bot_commands([
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("login", "🔑 Login to the bot"),
        BotCommand("token", "🎲 Get free access"),
        BotCommand("batch", "🐣 Extract in bulk"),
        BotCommand("help", "🆘 Get help and support"),
        BotCommand("stop", "🛑 Stop the bot"),
        BotCommand("cancel", "❌ Cancel operation"),
        BotCommand("owner", "👑 Contact owner"),
        BotCommand("broadcast", "📢 Broadcast message (Admin)")
    ])

async def generate_anti_bypass_link(bot_username: str, user_id: int) -> str:
    token_code = secrets.token_hex(8)
    await tokens_col.insert_one({
        "code": token_code,
        "user_id": user_id,
        "created_at": datetime.utcnow()
    })
    deep_link = f"https://t.me/{bot_username}?start=token_{token_code}"
    
    short_url = deep_link
    if SHORTENER_API:
        try:
            api_endpoint = f"https://{SHORTENER_URL}/api?api={SHORTENER_API}&url={deep_link}"
            async with aiohttp.ClientSession() as session:
                async with session.get(api_endpoint) as resp:
                    res = await resp.json()
                    if res.get("status") == "success":
                        short_url = res.get("shorturl")
        except Exception as e:
            print("Shortener error:", e)

    encoded_bytes = base64.b64encode(short_url.encode("utf-8"))
    base64_data = encoded_bytes.decode("utf-8")
    netlify_wrapper = f"https://eloquent-sunflower-11e5c6.netlify.app/verify.html?data={base64_data}"
    return netlify_wrapper

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    await get_user_data(user_id)
    
    if len(message.command) > 1:
        param = message.command[1]
        if param.startswith("token_"):
            token_code = param.split("token_")[1]
            token_record = await tokens_col.find_one({"code": token_code, "user_id": user_id})
            if token_record:
                await tokens_col.delete_one({"_id": token_record["_id"]})
                expiry = datetime.utcnow() + timedelta(hours=6)
                await users_col.update_one({"user_id": user_id}, {"$set": {"token_expiry": expiry}}, upsert=True)
                await message.reply("🎉 **Congratulations!**\nAapka **Ultimate Premium Access** next **6 Hours** ke liye verify ho gaya hai!")
                return
            else:
                await message.reply("❌ Invalid ya Expired Token code. Naya token generate karein /token se.")
                return

    if not await check_fsub(client, message):
        return

    welcome_text = (
        f"Hi, 🐣 **{message.from_user.first_name}** ❞\n\n"
        f"> **SAVE ANY FILE OR MEDIA (EVEN IF FORWARDING OFF)**\n\n"
        f"> ⚡ **Fast • Smooth • Reliable.**\n\n"
        f"> 💎 **SEND POST LINK** `/login` • `/help` ...\n\n"
        f"> 🎀 **Cꪮꜱᴍɪᴄ 𝐁ᴏᴛ𝑧** 🎀 ❞"
    )
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("JOIN CHANNEL ↗", url=FSUB_LINK),
            InlineKeyboardButton("❓ HELP", url=SUPPORT_BOT_LINK)
        ],
        [
            InlineKeyboardButton("📺 TUTORIAL ↗", url=TUTORIAL_LINK)
        ]
    ])

    try:
        await message.reply_photo(photo=START_BANNER, caption=welcome_text, reply_markup=buttons)
    except Exception:
        await message.reply(welcome_text, reply_markup=buttons)

@bot.on_message(filters.command("owner") & filters.private)
async def owner_cmd(client: Client, message: Message):
    await get_user_data(message.from_user.id)
    text = (
        "👑 **Cosmic Official Support**\n\n"
        "Aap kisi bhi issue, doubt ya copyright query ke liye niche diye gaye support bot par contact kar sakte hain:\n\n"
        "👉 **Contact:** @UrCosmic_Robot"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Owner / Support", url="https://t.me/UrCosmic_Robot")]
    ])
    await message.reply(text, reply_markup=buttons)

@bot.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if OWNER_ID and user_id != OWNER_ID:
        await message.reply("❌ Yeh command sirf Bot Owner ke liye hai.")
        return

    if not message.reply_to_message:
        await message.reply("⚠️ **Kaise broadcast karein?**\n\nPehle kisi message/photo/video ko send karein, phir us par reply karke `/broadcast` likhein.")
        return

    reply_msg = message.reply_to_message
    status_msg = await message.reply("⏳ **Broadcasting started...**")

    all_users = await users_col.find({}, {"user_id": 1}).to_list(length=None)
    total_users = len(all_users)
    successful = 0
    blocked = 0
    deleted = 0
    unsuccessful = 0

    for user in all_users:
        u_id = user["user_id"]
        try:
            await reply_msg.copy(chat_id=u_id)
            successful += 1
            await asyncio.sleep(0.04)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await reply_msg.copy(chat_id=u_id)
                successful += 1
            except Exception:
                unsuccessful += 1
        except UserIsBlocked:
            blocked += 1
        except InputUserDeactivated:
            deleted += 1
        except PeerIdInvalid:
            blocked += 1
        except Exception:
            unsuccessful += 1

    summary_text = (
        "<u>Broadcast completed</u>\n\n"
        f"◇ Total Users: {total_users}\n"
        f"◇ Successful: {successful}\n"
        f"◇ Blocked Users: {blocked}\n"
        f"◇ Deleted Accounts: {deleted}\n"
        f"◇ Unsuccessful: {unsuccessful}"
    )

    await status_msg.edit_text(summary_text, parse_mode=enums.ParseMode.HTML)

@bot.on_message(filters.command("token") & filters.private)
async def token_cmd(client: Client, message: Message):
    if not await check_fsub(client, message):
        return

    user_id = message.from_user.id
    verify_url = await generate_anti_bypass_link(client.me.username, user_id)

    msg_text = (
        "♻️ ***Click the button below to verify your free access token:***\n\n"
        "**`What will you get ? ❞`**\n\n"
        "1. NO TIME BOUND LIMIT UPTO Next 6 HOURS.\n"
        "2. NO LIMIT TO DOWNLOAD LARGER BATCH SIZES UPTO 50000+ FILES.\n"
        "3. ALL PREMIUM FUNCTIONS UNLOCKED."
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("♦️ Verify the token now.. ♦️ ↗", url=verify_url)],
        [InlineKeyboardButton("⁉️ How To Verify Token ⁉️ ↗", url=TUTORIAL_LINK)],
        [InlineKeyboardButton("🚀 SKIP VERIFY | 👉 FOR PREMIUM✨ ↗", url=SUPPORT_BOT_LINK)]
    ])
    await message.reply(msg_text, reply_markup=buttons)

@bot.on_message(filters.command("login") & filters.private)
async def login_cmd(client: Client, message: Message):
    if not await check_fsub(client, message):
        return
    user_id = message.from_user.id
    user_states[user_id] = {"step": "LOGIN_PHONE"}
    await message.reply(
        "**Login — Step 1/3**\n\n"
        "Apna phone number international format mein bhejo.\n\n"
        "Example: `+91XXXXXXXXXX`"
    )

@bot.on_message(filters.command("resend_otp") & filters.private)
async def resend_otp_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state or state.get("step") != "LOGIN_OTP":
        await message.reply("Koi active OTP login session nahi hai.")
        return
    
    temp_client = state["temp_client"]
    try:
        code_info = await temp_client.send_code(state["phone"])
        state["phone_code_hash"] = code_info.phone_code_hash
        await message.reply("🔄 Naya OTP bhej diya gaya hai. Enter karein:")
    except Exception as e:
        await message.reply(f"Failed to resend OTP: {e}")

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_states:
        state = user_states[user_id]
        if "temp_client" in state:
            try:
                await state["temp_client"].disconnect()
            except Exception:
                pass
        del user_states[user_id]
        await message.reply("Cancelled.\n\nUse /batch to start again.")
    else:
        await message.reply("Cancelled.")

@bot.on_message(filters.command("batch") & filters.private)
async def batch_cmd(client: Client, message: Message):
    if not await check_fsub(client, message):
        return

    user_id = message.from_user.id
    if not await is_token_valid(user_id):
        await message.reply(" 𝗨𝘀𝗲 /token 𝗧𝗼 𝗚𝗲𝘁 𝗨𝗹𝘁𝗶𝗺𝗮𝘁𝗲 𝗣𝗿𝗲𝗺𝗶𝘂𝗺 𝗔𝗰𝗰𝗲𝘀𝘀 𝗼𝗳 𝗕𝗼𝘁 𝗳𝗼𝗿 𝗻𝗲𝘅𝘁 6 𝗛𝗼𝘂𝗿𝘀😘")
        return

    user_states[user_id] = {"step": "BATCH_FIRST_LINK"}
    await message.reply(
        "Step 1/3 — First Link\n\n"
        "Send the link of the FIRST message from the public or private channel / group / topic.\n\n"
        "/cancel — Cancel this task"
    )

@bot.on_callback_query()
async def callback_handler(client: Client, cb: CallbackQuery):
    user_id = cb.from_user.id
    data = cb.data
    user_data = await get_user_data(user_id)

    if data == "setting_fn_replace":
        user_states[user_id] = {"step": "EDIT_FN_FIND"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_fn"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("📝 **Filename: Find & Replace**\n\nPehle wo text bhejo jo filename mein replace karna chahte hain (Search Text):", reply_markup=buttons)

    elif data == "setting_cap_replace":
        user_states[user_id] = {"step": "EDIT_CAP_FIND"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_cap"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("💬 **Caption: Find & Replace**\n\nPehle wo text bhejo jo caption se replace karna hai (Search Text):", reply_markup=buttons)

    elif data == "setting_cap_remove":
        user_states[user_id] = {"step": "EDIT_CAP_REMOVE"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_remove"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("✂️ **Caption: Remove Text**\n\nWo text/link/username bhejo jo caption se bilkul hatana hai:", reply_markup=buttons)

    elif data == "setting_extra_cap":
        user_states[user_id] = {"step": "EDIT_EXTRA_CAP"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_extra"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("➕ **Add Extra Caption**\n\nWo text/line bhejo jo sabhi messages ke bottom/top par add karna chahte hain:", reply_markup=buttons)

    elif data == "setting_dest_topic":
        user_states[user_id] = {"step": "EDIT_DEST_TOPIC"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_topic"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("🧵 **Set Destination Topic**\n\nDestination Topic / Thread ID bhejo (e.g. `19`):", reply_markup=buttons)

    elif data == "setting_thumb":
        user_states[user_id] = {"step": "EDIT_THUMB"}
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_thumb"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await cb.message.edit_text("🖼️ **Set Transfer Thumbnail**\n\nPhoto bhejo jo aap transfer media ki thumbnail set karna chahte hain:", reply_markup=buttons)

    elif data in ["skip_fn", "skip_cap", "skip_remove", "skip_extra", "skip_topic", "skip_thumb", "cancel_setting"]:
        user_states.pop(user_id, None)
        await show_setup_complete(cb.message, user_id)

    elif data == "clear_all_settings":
        await clear_user_settings(user_id)
        await cb.answer("Cleared all customization settings!", show_alert=True)
        await show_review_screen(cb.message, user_id)

    elif data == "back_to_settings":
        await show_setup_complete(cb.message, user_id)

    elif data == "setup_done":
        await show_review_screen(cb.message, user_id)

    elif data == "confirm_start_transfer":
        await start_actual_transfer(client, cb, user_id)

    elif data == "stop_transfer":
        if user_id in active_transfers:
            active_transfers[user_id] = False
            await cb.answer("🛑 Stopping transfer...", show_alert=True)
        else:
            await cb.answer("No active transfer found.", show_alert=True)

async def show_setup_complete(message, user_id: int):
    state = user_states.get(user_id, {})
    range_count = state.get("msg_count", 0)
    start_id = state.get("start_id", 0)
    end_id = state.get("end_id", 0)

    text = (
        f"**Setup Complete!**\n\n"
        f"**Range:** `{start_id}` to `{end_id}` (~{range_count} messages)\n\n"
        f"Aap transferable content ki customization neeche diye gaye buttons se adjust kar sakte hain:"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Filename: Find & Replace", callback_data="setting_fn_replace")],
        [InlineKeyboardButton("💬 Caption: Find & Replace", callback_data="setting_cap_replace")],
        [InlineKeyboardButton("✂️ Caption: Remove Text", callback_data="setting_cap_remove")],
        [InlineKeyboardButton("➕ Add Extra Caption", callback_data="setting_extra_cap")],
        [InlineKeyboardButton("🧵 Set Destination Topic", callback_data="setting_dest_topic")],
        [InlineKeyboardButton("🖼️ Set Transfer Thumbnail", callback_data="setting_thumb")],
        [InlineKeyboardButton("✅ Done - Start Transfer", callback_data="setup_done"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]
    ])
    if hasattr(message, "edit_text"):
        await message.edit_text(text, reply_markup=buttons)
    else:
        await message.reply(text, reply_markup=buttons)

async def show_review_screen(message, user_id: int):
    user_data = await get_user_data(user_id)
    s = user_data.get("settings", {})
    
    mods = []
    if s.get("fn_find"): mods.append(f"• Filename Find: `{s['fn_find']}` -> `{s['fn_replace']}`")
    if s.get("cap_find"): mods.append(f"• Caption Find: `{s['cap_find']}` -> `{s['cap_replace']}`")
    if s.get("cap_remove"): mods.append(f"• Caption Remove: `{s['cap_remove']}`")
    if s.get("extra_caption"): mods.append(f"• Extra Caption: `{s['extra_caption']}`")
    if s.get("dest_topic"): mods.append(f"• Destination Topic: `{s['dest_topic']}`")
    if s.get("thumbnail"): mods.append("• Custom Thumbnail: Enabled 🖼️")

    mod_str = "\n".join(mods) if mods else "⚠️ No modifications set (Default Copy Mode)"

    text = (
        f"**Review Settings & Confirm**\n\n"
        f"**Applied Customizations:**\n{mod_str}\n\n"
        f"Kya aap transfer start karne ke liye ready hain?"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Settings", callback_data="back_to_settings")],
        [InlineKeyboardButton("🗑️ Clear All Settings", callback_data="clear_all_settings")],
        [InlineKeyboardButton("✅ Confirm & Start", callback_data="confirm_start_transfer")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]
    ])
    if hasattr(message, "edit_text"):
        await message.edit_text(text, reply_markup=buttons)
    else:
        await message.reply(text, reply_markup=buttons)

@bot.on_message(filters.private & ~filters.command(["start", "login", "token", "batch", "resend_otp", "cancel", "help", "stop", "owner", "broadcast"]))
async def message_input_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await get_user_data(user_id)
    state = user_states.get(user_id)
    if not state:
        return

    step = state.get("step")

    if step == "LOGIN_PHONE":
        phone = message.text.strip().replace(" ", "")
        msg = await message.reply("Sending OTP...")
        temp_client = Client(f"session_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await temp_client.connect()
        try:
            code_info = await temp_client.send_code(phone)
            state["step"] = "LOGIN_OTP"
            state["phone"] = phone
            state["temp_client"] = temp_client
            state["phone_code_hash"] = code_info.phone_code_hash
            await msg.edit_text(
                "**Login — Step 2/3**\n\n"
                f"Phone: `{phone}` par aaya OTP bhejo.\n\n"
                "Format: `1 2 3 4 5` ya `12345`.\n\n"
                "Commands:\n/resend_otp — Request new code\n/cancel — Cancel login"
            )
        except Exception as e:
            await temp_client.disconnect()
            await msg.edit_text(f"❌ Failed to send code: {e}")

    elif step == "LOGIN_OTP":
        otp = message.text.strip().replace(" ", "")
        temp_client = state["temp_client"]
        try:
            await temp_client.sign_in(state["phone"], state["phone_code_hash"], otp)
            session_str = await temp_client.export_session_string()
            await users_col.update_one({"user_id": user_id}, {"$set": {"session": session_str}}, upsert=True)
            await temp_client.disconnect()
            del user_states[user_id]
            await message.reply("🎉 **Login Successful!**\nAapka user session safely save ho gaya hai.")
        except SessionPasswordNeeded:
            state["step"] = "LOGIN_2FA"
            await message.reply(
                "**Login — Step 3/3**\n\n"
                "2-Step Verification Password enabled hai. Apna 2FA password bhejo:\n\n"
                "/cancel — Cancel login"
            )
        except PhoneCodeInvalid:
            await message.reply("❌ Galat OTP. Phir se try karein ya /resend_otp bhejein.")
        except Exception as e:
            await message.reply(f"❌ Login error: {e}")

    elif step == "LOGIN_2FA":
        password = message.text.strip()
        temp_client = state["temp_client"]
        try:
            await temp_client.check_password(password)
            session_str = await temp_client.export_session_string()
            await users_col.update_one({"user_id": user_id}, {"$set": {"session": session_str}}, upsert=True)
            await temp_client.disconnect()
            del user_states[user_id]
            await message.reply("🎉 **Login Successful with 2FA!**\nAapka session save ho gaya hai.")
        except PasswordHashInvalid:
            await message.reply("❌ Incorrect 2FA Password. Phir se try karein.")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")

    elif step == "BATCH_FIRST_LINK":
        try:
            src_chat, start_id, topic_id = parse_telegram_link(message.text)
            state["src_chat"] = src_chat
            state["start_id"] = start_id
            state["topic_id"] = topic_id
            state["step"] = "BATCH_LAST_LINK"
            await message.reply(
                "Step 2/3 — Last Link\n\n"
                "Send the link of the LAST message from the channel / group / topic.\n\n"
                "/cancel — Cancel this task"
            )
        except Exception:
            await message.reply("❌ Invalid Link Format! Direct message link bhejein.")

    elif step == "BATCH_LAST_LINK":
        try:
            src_chat, end_id, _ = parse_telegram_link(message.text)
            start_id = state.get("start_id")
            if end_id < start_id:
                await message.reply("❌ Last message link first link se purana nahi ho sakta!")
                return
            state["end_id"] = end_id
            state["msg_count"] = (end_id - start_id) + 1
            state["step"] = "BATCH_DEST"
            await message.reply(
                f"Range set — ~{state['msg_count']} messages\n"
                f"{start_id} to {end_id}\n\n"
                "──────────────────────────────\n"
                "Step 3/3 — Destination\n\n"
                "Destination channel/group ka ID bhejo. Bot wahan FULL ADMIN hona chahiye.\n\n"
                "Example: `-100XXXXXXXXXX`\n\n"
                "Destination group mein `/id` type karo ID pane ke liye.\n"
                "Ya destination se koi bhi message yahan forward karo.\n\n"
                "/cancel — Cancel"
            )
        except Exception:
            await message.reply("❌ Invalid Last Link format!")

    elif step == "BATCH_DEST":
        dest_chat = None
        if message.forward_from_chat:
            dest_chat = message.forward_from_chat.id
        else:
            try:
                dest_chat = int(message.text.strip())
            except ValueError:
                await message.reply("❌ Invalid Chat ID!")
                return
        state["dest_chat"] = dest_chat
        state["step"] = "BATCH_CUSTOMIZE"
        await show_setup_complete(message, user_id)

    elif step == "EDIT_FN_FIND":
        state["fn_find"] = message.text
        state["step"] = "EDIT_FN_REPLACE"
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_fn"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await message.reply("Filename: Filename mein replace karne ke liye Naya Text (Replacement Text) bhejo:", reply_markup=buttons)

    elif step == "EDIT_FN_REPLACE":
        await update_user_settings(user_id, "fn_find", state.get("fn_find"))
        await update_user_settings(user_id, "fn_replace", message.text)
        await message.reply("✅ Filename Find & Replace Rule Added!")
        await show_setup_complete(message, user_id)

    elif step == "EDIT_CAP_FIND":
        state["cap_find"] = message.text
        state["step"] = "EDIT_CAP_REPLACE"
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("⏩ Skip", callback_data="skip_cap"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_setting")]])
        await message.reply("Caption: Caption mein replace karne ke liye Naya Text (Replacement Text) bhejo:", reply_markup=buttons)

    elif step == "EDIT_CAP_REPLACE":
        await update_user_settings(user_id, "cap_find", state.get("cap_find"))
        await update_user_settings(user_id, "cap_replace", message.text)
        await message.reply("✅ Caption Find & Replace Rule Added!")
        await show_setup_complete(message, user_id)

    elif step == "EDIT_CAP_REMOVE":
        await update_user_settings(user_id, "cap_remove", message.text)
        await message.reply("✅ Caption Removal Rule Added!")
        await show_setup_complete(message, user_id)

    elif step == "EDIT_EXTRA_CAP":
        await update_user_settings(user_id, "extra_caption", message.text)
        await message.reply("✅ Extra Caption Set!")
        await show_setup_complete(message, user_id)

    elif step == "EDIT_DEST_TOPIC":
        try:
            t_id = int(message.text.strip())
            await update_user_settings(user_id, "dest_topic", t_id)
            await message.reply("✅ Destination Topic Set!")
            await show_setup_complete(message, user_id)
        except ValueError:
            await message.reply("❌ Invalid Topic ID. Number bhejein.")

    elif step == "EDIT_THUMB":
        if message.photo:
            thumb_path = await message.download()
            await update_user_settings(user_id, "thumbnail", thumb_path)
            await message.reply("✅ Custom Thumbnail Set!")
            await show_setup_complete(message, user_id)
        else:
            await message.reply("❌ Kripya photo bhejein thumbnail ke liye.")

async def start_actual_transfer(client: Client, cb: CallbackQuery, user_id: int):
    user_data = await get_user_data(user_id)
    session_str = user_data.get("session")
    if not session_str:
        await cb.answer("❌ Kripya pehle /login se Login karein!", show_alert=True)
        return

    state = user_states.get(user_id, {})
    src_chat = state.get("src_chat")
    start_id = state.get("start_id")
    end_id = state.get("end_id")
    dest_chat = state.get("dest_chat")
    source_topic = state.get("topic_id")
    settings = user_data.get("settings", {})

    status_msg = await cb.message.edit_text(
        "Download Start!\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "run . 8784 | 1 GB RAM\n"
        f"~{(end_id - start_id)+1} messages queued\n\n"
        "🔍 **Scanning messages...**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Transfer", callback_data="stop_transfer")]])
    )

    await asyncio.sleep(2)

    active_transfers[user_id] = True
    start_time = time.time()

    success = 0
    not_found = 0
    skipped = 0
    total_bytes = 0

    user_app = Client(f"user_session_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_str, in_memory=True)
    await user_app.start()

    last_update_time = 0

    try:
        for msg_id in range(start_id, end_id + 1):
            if not active_transfers.get(user_id, True):
                break

            try:
                msg = await user_app.get_messages(src_chat, msg_id)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                msg = await user_app.get_messages(src_chat, msg_id)
            except Exception:
                not_found += 1
                continue

            if not msg or msg.empty:
                not_found += 1
                continue

            if source_topic and msg.message_thread_id != source_topic:
                skipped += 1
                continue

            caption = msg.caption or ""
            if settings.get("cap_remove"):
                caption = caption.replace(settings["cap_remove"], "")
            if settings.get("cap_find") and settings.get("cap_replace"):
                caption = caption.replace(settings["cap_find"], settings["cap_replace"])
            if settings.get("extra_caption"):
                caption += f"\n\n{settings['extra_caption']}"

            dest_thread_id = settings.get("dest_topic")

            try:
                if msg.media:
                    media_file = await user_app.download_media(
                        msg,
                        progress=progress_callback,
                        progress_args=(status_msg, "📥 Downloading", time.time(), user_id)
                    )
                    if media_file and os.path.exists(media_file):
                        file_size = os.path.getsize(media_file)
                        total_bytes += file_size
                        
                        thumb = settings.get("thumbnail") if settings.get("thumbnail") and os.path.exists(settings.get("thumbnail")) else None

                        if msg.photo:
                            await client.send_photo(dest_chat, media_file, caption=caption, message_thread_id=dest_thread_id)
                        elif msg.video:
                            await client.send_video(dest_chat, media_file, caption=caption, thumb=thumb, message_thread_id=dest_thread_id)
                        elif msg.document:
                            await client.send_document(dest_chat, media_file, caption=caption, thumb=thumb, message_thread_id=dest_thread_id)
                        elif msg.audio:
                            await client.send_audio(dest_chat, media_file, caption=caption, message_thread_id=dest_thread_id)
                        else:
                            await client.send_document(dest_chat, media_file, caption=caption, message_thread_id=dest_thread_id)

                        try:
                            os.remove(media_file)
                        except Exception:
                            pass
                        success += 1
                    else:
                        not_found += 1
                elif msg.text:
                    text = msg.text
                    if settings.get("cap_remove"):
                        text = text.replace(settings["cap_remove"], "")
                    if settings.get("cap_find") and settings.get("cap_replace"):
                        text = text.replace(settings["cap_find"], settings["cap_replace"])
                    if settings.get("extra_caption"):
                        text += f"\n\n{settings['extra_caption']}"
                    await client.send_message(dest_chat, text, message_thread_id=dest_thread_id)
                    success += 1

            except Exception as e:
                print(f"Error copying msg {msg_id}: {e}")
                not_found += 1

            now = time.time()
            if now - last_update_time > 3:
                last_update_time = now
                elapsed = int(now - start_time)
                mb_size = total_bytes / (1024 * 1024)
                speed = (mb_size / elapsed) if elapsed > 0 else 0
                await status_msg.edit_text(
                    f"🚀 **Transfer Progressing...**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Processed: {success + not_found + skipped}/{(end_id - start_id)+1}\n"
                    f"📦 Total Size: {mb_size:.2f} MB\n"
                    f"⚡ Speed: {speed:.1f} MB/s\n\n"
                    f"⏳ Elapsed: {elapsed}s",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Transfer", callback_data="stop_transfer")]])
                )

    finally:
        await user_app.stop()
        active_transfers.pop(user_id, None)

    total_time = int(time.time() - start_time)
    minutes, seconds = divmod(total_time, 60)
    time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
    mb_total = total_bytes / (1024 * 1024)
    avg_speed = (mb_total / total_time) if total_time > 0 else 0

    completion_card = (
        "🏁 **Task Completed!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Success:**         `{success}`\n"
        f"🗑️ **Not Found:**       `{not_found}` _(deleted/restricted)_\n"
        f"⏭️ **Skipped:**         `{skipped}`\n"
        f"📦 **Total Size:**      `{mb_total:.2f}MB`\n"
        f"⚡ **Avg Speed:**       `{avg_speed:.1f} MB/s`\n"
        f"⏱️ **Time:**            `{time_str}`"
    )

    await status_msg.edit_text(completion_card)

async def progress_callback(current, total, message, action_title, start_t, user_id):
    if not active_transfers.get(user_id, True):
        raise Exception("Transfer Stopped by User")

if __name__ == "__main__":
    print("Starting Cosmic Botz...")
    bot.start()
    bot.loop.run_until_complete(set_menu_commands(bot))
    bot.stop()
    bot.run()
