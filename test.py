import asyncio
import logging
import html
from typing import List
import aiosqlite

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter 
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

BOT_TOKEN = '8507732883:AAFrm0LfqizW7EhSTfaiOI1RD4rzHb7U94I'

YOUR_MAIN_ADMIN_ID = 7094674617

FORWARD_CHAT_ID = -1003493472015

TARGET_CHANNEL = '@testheieje'

DB_FILE = 'anon_messages.db'

logging.basicConfig(level=logging.INFO)

db_pool = None

bot = Bot(token=BOT_TOKEN, 
          default=DefaultBotProperties(parse_mode=ParseMode.HTML)
         )
dp = Dispatcher()

# --- (Вспомогательные функции и классы без изменений) ---
async def init_db():
    global db_pool
    db_pool = await aiosqlite.connect(DB_FILE)
    
    async with db_pool.cursor() as cursor:
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT
            )
        """)
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS reply_mapping (
                admin_chat_id INTEGER,
                admin_message_id INTEGER,
                original_user_id INTEGER,
                original_message_id INTEGER,
                PRIMARY KEY (admin_chat_id, admin_message_id)
            )
        """)
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS publication_status (
                original_message_id INTEGER PRIMARY KEY,
                published_by_admin INTEGER
            )
        """)
        
        await cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (YOUR_MAIN_ADMIN_ID,))
        if not await cursor.fetchone():
            await cursor.execute("INSERT INTO admins (user_id, role) VALUES (?, ?)", (YOUR_MAIN_ADMIN_ID, "main_admin"))
        
        await db_pool.commit()

async def is_main_admin(user_id: int) -> bool:
    return user_id == YOUR_MAIN_ADMIN_ID

async def get_admin_ids() -> List[int]:
    async with db_pool.cursor() as cursor:
        await cursor.execute("SELECT user_id FROM admins")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def is_admin(user_id: int) -> bool:
    return user_id in await get_admin_ids()

async def save_mapping(admin_chat_id: int, admin_message_id: int, original_user_id: int, original_message_id: int):
    async with db_pool.cursor() as cursor:
        await cursor.execute(
            """INSERT OR REPLACE INTO reply_mapping 
               (admin_chat_id, admin_message_id, original_user_id, original_message_id) 
               VALUES (?, ?, ?, ?)""",
            (admin_chat_id, admin_message_id, original_user_id, original_message_id)
        )
        await db_pool.commit()

async def get_original_user(admin_chat_id: int, admin_message_id: int) -> int | None:
    async with db_pool.cursor() as cursor:
        await cursor.execute(
            "SELECT original_user_id FROM reply_mapping WHERE admin_chat_id = ? AND admin_message_id = ?",
            (admin_chat_id, admin_message_id)
        )
        result = await cursor.fetchone()
        return result[0] if result else None

async def get_original_message_id(admin_chat_id: int, admin_message_id: int) -> int | None:
    async with db_pool.cursor() as cursor:
        await cursor.execute(
            "SELECT original_message_id FROM reply_mapping WHERE admin_chat_id = ? AND admin_message_id = ?",
            (admin_chat_id, admin_message_id)
        )
        result = await cursor.fetchone()
        return result[0] if result else None

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data="publish_post")]
    ])

def get_main_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить администратора", callback_data="manage_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить администратора", callback_data="manage_del_admin")]
    ])

class AnonSend(StatesGroup):
    waiting_for_message = State()

class AdminManage(StatesGroup):
    waiting_for_add_id = State()
    waiting_for_del_id = State()
# --- (Конец вспомогательных функций и классов) ---

@dp.message(Command("start", "anon"))
async def cmd_start_anon(message: types.Message, state: FSMContext):
    await state.set_state(AnonSend.waiting_for_message)
    await message.answer(
        """🚀 Здесь можно отправить анонимное сообщение каналу "фиксики"

✍️ Напишите сюда всё, что хотите ему передать, и через несколько секунд он получит ваше сообщение, но не будет знать от кого.

Отправить можно фото, видео, 💬 текст, 🔊 голосовые, 📷 видеосообщения (кружки), а также ✨ стикеры""",
        parse_mode=ParseMode.HTML
    )

# ОБРАБОТЧИК 1: Ловит все сообщения, когда пользователь в состоянии AnonSend.waiting_for_message
@dp.message(StateFilter(AnonSend.waiting_for_message))
async def process_anon_message_in_state(message: types.Message, state: FSMContext):
    
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "NoUsername"
    original_msg_id = message.message_id
    
    try:
        await message.reply("✅ Отправлено!")
        await state.clear() 
    except Exception:
        pass

    admin_ids = await get_admin_ids()
    recipient_ids = list(set(admin_ids) | {FORWARD_CHAT_ID})

    # Общие переменные
    header = "✨ <b>У тебя новое анонимное сообщение!</b>"
    standard_footer = "\n\n↩️ <i>Свайпни для ответа.</i>"

    for recipient_id in recipient_ids:
        try:
            sent_message = None
            footer = standard_footer # Начинаем со стандартного футера

            # --- ЛОГИКА ВОССТАНОВЛЕНИЯ ID/USERNAME ---
            if recipient_id == YOUR_MAIN_ADMIN_ID or recipient_id == FORWARD_CHAT_ID:
                 footer += f"\n\n👤 ID: <code>{user_id}</code> | {username}"
            # --- КОНЕЦ ЛОГИКИ ВОССТАНОВЛЕНИЯ ---

            async def send_message_with_mapping(chat_id, text, reply_to_id=None, reply_markup=get_admin_keyboard()):
                msg = await bot.send_message(
                    chat_id, 
                    text, 
                    reply_to_message_id=reply_to_id,
                    reply_markup=reply_markup
                )
                await save_mapping(chat_id, msg.message_id, user_id, original_msg_id)
                return msg

            if message.text:
                safe_text = html.escape(message.text)
                full_text = f"{header}\n\n{safe_text}{footer}"
                
                sent_message = await send_message_with_mapping(recipient_id, full_text)

            elif message.caption:
                caption_text = message.caption
                safe_caption = html.escape(caption_text)
                full_caption = f"{header}\n\n{safe_caption}{footer}"

                if len(full_caption) <= 1024:
                    sent_message = await bot.copy_message(
                        chat_id=recipient_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id,
                        caption=full_caption,
                        reply_markup=get_admin_keyboard()
                    )
                    await save_mapping(recipient_id, sent_message.message_id, user_id, original_msg_id)
                else:
                    sent_media = await bot.copy_message(chat_id=recipient_id, from_chat_id=message.chat.id, message_id=message.message_id)
                    await save_mapping(recipient_id, sent_media.message_id, user_id, original_msg_id)
                    
                    sent_message = await send_message_with_mapping(
                        recipient_id, 
                        f"{header}{footer}", 
                        reply_to_id=sent_media.message_id
                    )

            else:
                sent_media = await bot.copy_message(chat_id=recipient_id, from_chat_id=message.chat.id, message_id=message.message_id)
                await save_mapping(recipient_id, sent_media.message_id, user_id, original_msg_id)
                
                sent_message = await send_message_with_mapping(
                    recipient_id, 
                    f"{header}{footer}", 
                    reply_to_id=sent_media.message_id
                )
                
            if sent_message:
                await save_mapping(recipient_id, sent_message.message_id, user_id, original_msg_id)

        except Exception as e:
            logging.error(f"Ошибка при отправке админу/чату {recipient_id}: {e}")

# ОБРАБОТЧИК 2: Ловит все остальные сообщения, НЕ являющиеся командами.
@dp.message(
    F.content_type.in_({'photo', 'video', 'voice', 'video_note', 'sticker', 'animation', 'document', 'audio'}) | 
    (F.text & F.text.not_startswith('/')) 
)
async def process_anon_message_catch_all(message: types.Message, state: FSMContext):
    
    await state.set_state(AnonSend.waiting_for_message)
    
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "NoUsername"
    original_msg_id = message.message_id
    
    try:
        await message.reply("✅ Отправлено!")
        await state.clear() 
    except Exception:
        pass

    admin_ids = await get_admin_ids()
    recipient_ids = list(set(admin_ids) | {FORWARD_CHAT_ID})

    # Общие переменные
    header = "✨ <b>У тебя новое анонимное сообщение!</b>"
    standard_footer = "\n\n↩️ <i>Свайпни для ответа.</i>"


    for recipient_id in recipient_ids:
        try:
            sent_message = None
            footer = standard_footer # Начинаем со стандартного футера

            # --- ЛОГИКА ВОССТАНОВЛЕНИЯ ID/USERNAME ---
            if recipient_id == YOUR_MAIN_ADMIN_ID or recipient_id == FORWARD_CHAT_ID:
                 footer += f"\n\n👤 ID: <code>{user_id}</code> | {username}"
            # --- КОНЕЦ ЛОГИКИ ВОССТАНОВЛЕНИЯ ---


            async def send_message_with_mapping(chat_id, text, reply_to_id=None, reply_markup=get_admin_keyboard()):
                msg = await bot.send_message(
                    chat_id, 
                    text, 
                    reply_to_message_id=reply_to_id,
                    reply_markup=reply_markup
                )
                await save_mapping(chat_id, msg.message_id, user_id, original_msg_id)
                return msg

            if message.text:
                safe_text = html.escape(message.text)
                full_text = f"{header}\n\n{safe_text}{footer}"
                
                sent_message = await send_message_with_mapping(recipient_id, full_text)

            elif message.caption:
                caption_text = message.caption
                safe_caption = html.escape(caption_text)
                full_caption = f"{header}\n\n{safe_caption}{footer}"

                if len(full_caption) <= 1024:
                    sent_message = await bot.copy_message(
                        chat_id=recipient_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id,
                        caption=full_caption,
                        reply_markup=get_admin_keyboard()
                    )
                    await save_mapping(recipient_id, sent_message.message_id, user_id, original_msg_id)
                else:
                    sent_media = await bot.copy_message(chat_id=recipient_id, from_chat_id=message.chat.id, message_id=message.message_id)
                    await save_mapping(recipient_id, sent_media.message_id, user_id, original_msg_id)
                    
                    sent_message = await send_message_with_mapping(
                        recipient_id, 
                        f"{header}{footer}", 
                        reply_to_id=sent_media.message_id
                    )

            else:
                sent_media = await bot.copy_message(chat_id=recipient_id, from_chat_id=message.chat.id, message_id=message.message_id)
                await save_mapping(recipient_id, sent_media.message_id, user_id, original_msg_id)
                
                sent_message = await send_message_with_mapping(
                    recipient_id, 
                    f"{header}{footer}", 
                    reply_to_id=sent_media.message_id
                )
                
            if sent_message:
                await save_mapping(recipient_id, sent_message.message_id, user_id, original_msg_id)

        except Exception as e:
            logging.error(f"Ошибка при отправке админу/чату {recipient_id}: {e}")

@dp.message(F.reply_to_message, F.chat.type.in_({'private', 'group', 'supergroup'}))
async def process_admin_reply(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == AnonSend.waiting_for_message:
        return 

    if not await is_admin(message.from_user.id):
        return

    replied_id = message.reply_to_message.message_id
    original_user_id = await get_original_user(message.chat.id, replied_id)

    if not original_user_id:
        return await message.reply("Не удалось найти исходного пользователя для этого сообщения.")

    try:
        await bot.copy_message(
            chat_id=original_user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=message.caption
        )
        await message.reply("👌 Ответ отправлен анонимному пользователю.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: Не удалось отправить ответ пользователю. Возможно, он заблокировал бота. Детали: {e}")

@dp.callback_query(F.data == "publish_post")
async def callback_publish(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return await callback.answer("У вас нет прав администратора.", show_alert=True)
    
    if callback.message.reply_to_message:
        mapping_msg_id = callback.message.reply_to_message.message_id
        source_message = callback.message.reply_to_message
    else:
        mapping_msg_id = callback.message.message_id
        source_message = callback.message
        
    original_msg_id = await get_original_message_id(callback.message.chat.id, mapping_msg_id)

    if not original_msg_id:
        return await callback.answer("❌ Не удалось найти исходное сообщение для проверки статуса публикации.", show_alert=True)
    
    async with db_pool.cursor() as cursor:
        await cursor.execute(
            "SELECT published_by_admin FROM publication_status WHERE original_message_id = ?",
            (original_msg_id,)
        )
        already_published = await cursor.fetchone()
        
    if already_published:
        admin_id = already_published[0]
        return await callback.answer(f"❌ Сообщение уже опубликовано администратором с ID {admin_id}.", show_alert=True)

    try:
        
        original_content = source_message.text or source_message.caption or ""
        
        # Очистка текста от служебных футеров (которые теперь унифицированы)
        cleaned_text = original_content.split("✨ <b>У тебя новое анонимное сообщение!</b>")[-1].strip()
        cleaned_text = cleaned_text.split("↩️ <i>Свайпни для ответа.</i>")[0].strip()

        # Дополнительная очистка от ID/Username (на случай, если они присутствуют)
        # Мы удаляем весь текст после последнего символа '👤 ID:' (если он есть)
        if '👤 ID:' in cleaned_text:
            cleaned_text = cleaned_text.split('👤 ID:')[0].strip()
        
        # Удаляем лишние переводы строк, которые могли остаться
        cleaned_text = cleaned_text.strip()


        if source_message.text:
            temp_message = await bot.send_message(
                chat_id=YOUR_MAIN_ADMIN_ID,
                text=cleaned_text
            )
        else:
            temp_message = await bot.copy_message(
                chat_id=YOUR_MAIN_ADMIN_ID,
                from_chat_id=source_message.chat.id,
                message_id=source_message.message_id,
                caption=cleaned_text if cleaned_text else None
            )

        await bot.forward_message(
            chat_id=TARGET_CHANNEL,
            from_chat_id=YOUR_MAIN_ADMIN_ID,
            message_id=temp_message.message_id
        )

        await bot.delete_message(YOUR_MAIN_ADMIN_ID, temp_message.message_id)

        async with db_pool.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO publication_status (original_message_id, published_by_admin) VALUES (?, ?)",
                (original_msg_id, callback.from_user.id)
            )
            await db_pool.commit()
            
        await callback.answer("✅ Опубликовано в канале как пересланное от бота!", show_alert=True)

    except Exception as e:
        await callback.answer(f"❌ Ошибка публикации: {e}", show_alert=True)
        logging.error(f"Publish error: {e}")

@dp.message(Command("admin"))
async def cmd_admin_menu(message: types.Message):
    if not await is_main_admin(message.from_user.id):
        return await message.reply("У вас нет доступа к меню управления администраторами.")
    
    await message.reply("⚙️ **Меню управления администраторами**", reply_markup=get_main_admin_menu())

@dp.callback_query(F.data == "manage_add_admin")
async def callback_add_admin(callback: CallbackQuery, state: FSMContext):
    if not await is_main_admin(callback.from_user.id):
        return await callback.answer("У вас нет прав.", show_alert=True)
    
    await callback.message.edit_text("➕ Введите ID пользователя, которого вы хотите **ДОБАВИТЬ** в администраторы.")
    await state.set_state(AdminManage.waiting_for_add_id)
    await callback.answer()

@dp.callback_query(F.data == "manage_del_admin")
async def callback_del_admin(callback: CallbackQuery, state: FSMContext):
    if not await is_main_admin(callback.from_user.id):
        return await callback.answer("У вас нет прав.", show_alert=True)

    admin_list_ids = [str(id) for id in await get_admin_ids() if id != YOUR_MAIN_ADMIN_ID]
    admin_list = "\n".join(admin_list_ids)
    
    if not admin_list_ids:
        await callback.message.edit_text("➖ **Нет других администраторов для удаления.**")
        await state.clear()
        return await callback.answer()
        
    await callback.message.edit_text(
        f"➖ Введите ID администратора, которого вы хотите **УДАЛИТЬ**. Список текущих админов (кроме вас):\n\n{admin_list}"
    )
    await state.set_state(AdminManage.waiting_for_del_id)
    await callback.answer()

@dp.message(AdminManage.waiting_for_add_id)
async def process_new_admin_id(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        return await message.reply("Пожалуйста, введите корректный числовой ID.")
    
    new_admin_id = int(message.text)
    
    if await is_admin(new_admin_id):
        await state.clear()
        await message.reply(f"Пользователь с ID <code>{new_admin_id}</code> уже является администратором.")
        return await cmd_admin_menu(message)

    try:
        async with db_pool.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO admins (user_id, role) VALUES (?, ?)", 
                (new_admin_id, "admin")
            )
            await db_pool.commit()
        await state.clear()
        await message.reply(f"✅ Пользователь с ID <code>{new_admin_id}</code> добавлен в администраторы.")
    except Exception as e:
        await state.clear()
        await message.reply(f"❌ Ошибка при добавлении администратора: {e}")

@dp.message(AdminManage.waiting_for_del_id)
async def process_del_admin_id(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        return await message.reply("Пожалуйста, введите корректный числовой ID.")
    
    del_admin_id = int(message.text)

    if del_admin_id == YOUR_MAIN_ADMIN_ID:
        await state.clear()
        await message.reply("Вы не можете удалить главного администратора.")
        return await cmd_admin_menu(message)
    
    async with db_pool.cursor() as cursor:
        await cursor.execute("DELETE FROM admins WHERE user_id = ? AND role = ?", (del_admin_id, "admin"))
        deleted_count = cursor.rowcount
        await db_pool.commit()
            
    await state.clear()

    if deleted_count > 0:
        await message.reply(f"✅ Администратор с ID <code>{del_admin_id}</code> удален.")
    else:
        await message.reply(f"❌ Пользователь с ID <code>{del_admin_id}</code> не найден в списке администраторов (или является Главным админом).")

async def main():
    try:
        await init_db()
        await bot.delete_webhook(drop_pending_updates=True)
        print("Бот запущен...")
        await dp.start_polling(bot)
    finally:
        if db_pool:
            await db_pool.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Стоп.")
