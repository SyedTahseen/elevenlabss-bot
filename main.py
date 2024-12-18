from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import httpx
from logger import log_user_activity
import os
import aiofiles
from datetime import datetime
from db import get_user_config, update_user_config, clear_user_config
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import types
import uvloop
from aiogram.utils.keyboard import InlineKeyboardBuilder

uvloop.install()
BOT_TOKEN = "7612501799:AAE95Z4VBPAKreCVM0sVa1CnV6xvnKOzaZ8"
if not BOT_TOKEN:
    raise ValueError("Bot token is missing")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()  # Temporary FSM storage
dp = Dispatcher(storage=storage)
router = Router()  # Router for commands
dp.include_router(router)

DEFAULT_PARAMS = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Default voice ID
    "stability": 0.5,
    "similarity_boost": 0.7,
}

async def get_or_initialize_character_count(user_id):
    user_config = await get_user_config(user_id)
    if not user_config:
        user_config = {"character_count": 0}
        await update_user_config(user_id, user_config)
    return user_config.get("character_count", 0)

async def get_existing_voices(api_key: str):
    headers = {
        "xi-api-key": api_key,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.elevenlabs.io/v1/voices", headers=headers)
        if response.status_code == 200:
            return response.json().get("voices", [])
        else:
            return []

# Add API
@router.callback_query(F.callback_data == "add_api")
async def add_api_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To add an API key, use the /setapi command with your key.\nExample:\n<code>/setapi [API_KEY]</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

# List Voices
@router.callback_query(F.callback_data == "list_voices")
async def list_voices_callback(callback_query: types.CallbackQuery):
    await list_voices_command(callback_query.message)
    await callback_query.answer()

# Profile
@router.callback_query(F.callback_data == "profile")
async def profile_callback(callback_query: types.CallbackQuery):
    await show_config_command(callback_query.message)
    await callback_query.answer()

# Voice Settings
@router.callback_query(F.callback_data == "voice_settings")
async def voice_settings_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To update voice settings, use:\n<code>/voicesettings [Stability] [Similarity Boost]</code>\nExample:\n<code>/voicesettings 0.7 0.5</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

# Generate Speech
@router.callback_query(F.callback_data == "speech")
async def speech_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To generate speech, use the /speech command followed by the text.\nExample:\n<code>/speech Hello, how are you?</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

# Clear Config
@router.callback_query(F.callback_data == "clear_config")
async def clear_config_callback(callback_query: types.CallbackQuery):
    await clear_config_command(callback_query.message)
    await callback_query.answer("Configuration cleared.")
    

async def generate_elevenlabs_audio(text: str, api_key: str, voice_id: str, voice_settings: dict, audio_path: str):
    """
    Generates audio using the ElevenLabs API and saves it to the specified path.
    """
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    }
    voice_settings = {
        "stability": voice_settings.get("stability", 0.5),
        "similarity_boost": voice_settings.get("similarity_boost", 0.7),
    }
    data = {
        "text": text,
        "voice_settings": voice_settings,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers=headers,
            json=data,
        )

        if response.status_code == 200:
            with open(audio_path, "wb") as f:
                f.write(response.content)
        else:
            raise ValueError(f"Error from ElevenLabs API (status {response.status_code}): {response.text}")

async def upload_to_file_io(file_path: str) -> str:
    """
    Uploads a file to file.io and returns the download link.
    """
    try:
        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as file:
                response = await client.post(
                    "https://file.io/", files={"file": file}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("link", "No link provided")
                else:
                    raise ValueError(f"File.io API error: {response.text}")
    except Exception as e:
        raise ValueError(f"Failed to upload file to file.io: {e}")
        

# Command Handlers
@router.message(Command("start"))
async def start_command(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Add API", callback_data="add_api"),
        InlineKeyboardButton(text="List Voices", callback_data="list_voices")
    )
    builder.row(
        InlineKeyboardButton(text="Profile", callback_data="profile"),
        InlineKeyboardButton(text="Voice Settings", callback_data="voice_settings")
    )
    builder.row(
        InlineKeyboardButton(text="Generate Speech", callback_data="speech"),
        InlineKeyboardButton(text="Clear Config", callback_data="clear_config")
    )
    await message.answer(
        "<b>Welcome to the ElevenLabs Manager Bot!</b>\n\n"
        "Choose an option from the menu below to manage your ElevenLabs account:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )



@router.message(Command("setapi"))
async def set_api_command(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        # If no argument is provided, show stored API keys and active key
        stored_api_keys = await get_api_keys(user_id)
        active_key = await get_active_api_key(user_id)
        if not stored_api_keys:
            await message.answer(
                "You don't have any API keys saved. Use:\n<code>/setapi [API_KEY]</code> to add one.",
                parse_mode="HTML"
            )
            return
        
        api_list = "\n".join(
            [f"{index + 1}. <code>{key}</code>{' (Active)' if key == active_key else ''}" 
             for index, key in enumerate(stored_api_keys)]
        )
        await message.answer(
            f"<b>Your Stored API Keys:</b>\n{api_list}\n\n"
            "To set an active key, use:\n<code>/setapi select [Index]</code>",
            parse_mode="HTML"
        )
        return

    command_args = args[1].strip()

    # If the command is to select an active API key
    if command_args.startswith("select"):
        try:
            index = int(command_args.split()[1]) - 1
            stored_api_keys = await get_api_keys(user_id)
            if index < 0 or index >= len(stored_api_keys):
                await message.answer("Invalid index. Please check your stored API keys and try again.")
                return
            
            active_key = stored_api_keys[index]
            await set_active_api_key(user_id, active_key)
            await message.answer(
                f"Your active API key has been set to:\n<code>{active_key}</code>",
                parse_mode="HTML"
            )
        except (IndexError, ValueError):
            await message.answer("Invalid format. Use:\n<code>/setapi select [Index]</code>", parse_mode="HTML")
        return

    # Otherwise, add a new API key
    api_key = command_args

    # Verify the API key
    headers = {"xi-api-key": api_key}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers)

        if response.status_code == 200:
            # Add the API key and set it as active
            await add_api_key(user_id, api_key)
            await set_active_api_key(user_id, api_key)
            subscription_info = response.json()
            character_limit = subscription_info.get("character_limit", "Unknown")
            await message.answer(
                f"Your <b>API key</b> has been successfully added and set as active. 🎉\n"
                f"<b>Character Limit:</b> {character_limit}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "Invalid API key. Please check your key and try again.",
                parse_mode="HTML"
            )
    except Exception as e:
        await message.answer(
            f"Error verifying the API key. Please try again later.\n<code>{str(e)}</code>",
            parse_mode="HTML"
        )




# Command to show main menu
@router.message(Command("menu"))
async def show_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Add API", callback_data="add_api"),
        InlineKeyboardButton(text="List Voices", callback_data="list_voices")
    )
    builder.row(
        InlineKeyboardButton(text="Profile", callback_data="profile"),
        InlineKeyboardButton(text="Voice Settings", callback_data="voice_settings")
    )
    builder.row(
        InlineKeyboardButton(text="Generate Speech", callback_data="speech"),
        InlineKeyboardButton(text="Clear Config", callback_data="clear_config")
    )
    await message.answer("Choose an option:", reply_markup=builder.as_markup())

# Callback handlers for navigation
@router.callback_query(F.callback_data == "add_api")
async def add_api_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To add an API key, use the /setapi command with your key.\nExample:\n<code>/setapi [API_KEY]</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

@router.callback_query(F.callback_data == "list_voices")
async def list_voices_callback(callback_query: types.CallbackQuery):
    await list_voices_command(callback_query.message)
    await callback_query.answer()

@router.callback_query(F.callback_data == "profile")
async def profile_callback(callback_query: types.CallbackQuery):
    await show_config_command(callback_query.message)
    await callback_query.answer()

@router.callback_query(F.callback_data == "voice_settings")
async def voice_settings_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To update voice settings, use:\n<code>/voicesettings [Stability] [Similarity Boost]</code>\nExample:\n<code>/voicesettings 0.7 0.5</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

@router.callback_query(F.callback_data == "speech")
async def speech_callback(callback_query: types.CallbackQuery):
    await callback_query.message.answer(
        "To generate speech, use the /speech command followed by the text.\nExample:\n<code>/speech Hello, how are you?</code>",
        parse_mode="HTML"
    )
    await callback_query.answer()

@router.callback_query(F.callback_data == "clear_config")
async def clear_config_callback(callback_query: types.CallbackQuery):
    await clear_config_command(callback_query.message)
    await callback_query.answer()



@router.message(Command("setvoice"))
async def set_voice_command(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Get Voice IDs", url="https://elevenlabs.io/voice-lab")]
        ])
        
        await message.answer(
            "To set a <b>Voice ID</b>, use this command like:\n\n"
            "<code>/setvoice [VOICE_ID]</code>\n\n"
            "Don't know your voice ID? Click the button below to explore available voices.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    voice_id = args[1].strip()
    await update_user_config(user_id, {"voice_id": voice_id})
    await message.answer(f"Your <b>voice ID</b> has been set to <code>{voice_id}</code>.", parse_mode="HTML")

@router.message(Command("voicesettings"))
async def set_settings_command(message: Message):
    user_id = message.from_user.id
    args = message.text.split()

    # Check if the user provided sufficient arguments
    if len(args) != 3:
        await message.answer(
            (
                "To set voice settings, use the command like this:\n\n"
                "<code>/voicesettings [Stability] [Similarity Boost]</code>\n\n"
                "<b>Ranges:</b>\n"
                "Stability: <b>0.1 to 1</b>\n"
                "Similarity Boost: <code>0.1 to 1</code>\n\n"
                "<b>Example:</b>\n"
                "<code>/voicesettings 0.7 0.5</code>"
            ),
            parse_mode="HTML"
        )
        return

    try:
        # Parse and validate the input values
        stability, similarity_boost = map(float, args[1:])
        if not (0.1 <= stability <= 1) or not (0.1 <= similarity_boost <= 1):
            await message.answer(
                (
                    "❗ <b>Invalid values</b>. Both Stability and Similarity Boost must be between "
                    "<b>0.1 and 1</b>.\n\n"
                    "Please try again using valid values.\n"
                    "<b>Example:</b> <code>/voicesettings 0.7 0.5</code>"
                ),
                parse_mode="HTML"
            )
            return

        # Update the user settings in the database
        voice_settings = {"stability": stability, "similarity_boost": similarity_boost}
        await update_user_config(user_id, {"voice_settings": voice_settings})

        # Confirm success
        await message.answer(
            (
                "✅ <b>Your voice settings have been updated:</b>\n"
                f"<b>Stability:</b> {stability}\n"
                f"<b>Similarity Boost:</b> {similarity_boost}"
            ),
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer(
            (
                "❗ <b>Invalid input</b>. Please provide numerical values for Stability and Similarity Boost.\n\n"
                "<b>Correct Usage:</b>\n"
                "<code>/voicesettings 0.7 0.5</code>"
            ),
            parse_mode="HTML"
        )
        
@router.message(Command("speech"))
async def generate_voice_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "To generate Text-to-Speech, use this command like this:\n\n"
            "<code>/speech [Text]</code>\n\n"
            "Example: <code>/speech Hello, how are you?</code>",
            parse_mode="HTML"
        )
        return

    text = args[1].strip()
    user_config = await get_user_config(user_id)

    if not user_config:
        await message.answer(
            "Please configure your API key, voice ID, and settings first using /setapi, /setvoice, and /setsettings."
        )
        return

    api_key = user_config.get("api_key")
    if not api_key:
        await message.answer("Your API key is missing. Use /setapi to set it.")
        return

    voice_id = user_config.get("voice_id", DEFAULT_PARAMS["voice_id"])
    voice_settings = user_config.get("voice_settings", DEFAULT_PARAMS)

    progress_message = await message.answer("<b>Processing your request...</b>", parse_mode="HTML")
    audio_path = f"elevenlabs_voice_{user_id}.mp3"

    try:
        # Update character count
        character_count = await get_or_initialize_character_count(user_id)
        character_count += len(text)
        await update_user_config(user_id, {"character_count": character_count})

        # Generate the audio file
        await generate_elevenlabs_audio(text, api_key, voice_id, voice_settings, audio_path)

        # Confirm the file exists
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found at {audio_path}")

        # Upload the file to file.io and get the link
        file_io_link = await upload_to_file_io(audio_path)

        # Log the activity
        await log_user_activity(
            bot=bot,  # Pass the bot instance
            user_id=user_id,
            username=username,
            activity="Generated Voice",
            details={
                "Text": text,
                "Voice ID": voice_id,
                "Stability": voice_settings.get("stability"),
                "Similarity Boost": voice_settings.get("similarity_boost"),
                "File.io Link": file_io_link,
            },
        )

        # Edit the progress message and send the audio
        await progress_message.edit_text(
            f"<b>Voice generated successfully!</b>\n\n"
            f"<b>File.io Link:</b> <a href='{file_io_link}'>{file_io_link}</a>",
            parse_mode="HTML",
        )
        audio_file = FSInputFile(audio_path)
        await bot.send_voice(chat_id=message.chat.id, voice=audio_file)

    except Exception as e:
        await progress_message.edit_text(f"<b>Error:</b> {e}", parse_mode="HTML")
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
            

@router.message(Command("clearconfig"))
async def clear_config_command(message: Message):
    user_id = message.from_user.id
    await clear_user_config(user_id)
    await message.answer("Your configuration has been cleared.")

@router.message(Command("listvoices"))
async def list_voices_command(message: Message):
    user_id = message.from_user.id
    user_config = await get_user_config(user_id)
    
    if not user_config:
        await message.answer("You need to configure your ElevenLabs API key first using /setapi.")
        return

    api_key = user_config.get("api_key")
    if not api_key:
        await message.answer("Your API key is missing. Use /setapi to set it.")
        return

    # Fetch the existing voices
    existing_voices = await get_existing_voices(api_key)
    
    if not existing_voices:
        await message.answer("<b>No existing voices found.</b>", parse_mode="HTML")
        return

    voices_list = "<b>Available Voices:</b>\n"
    for voice in existing_voices:
        voice_name = voice.get('name', 'Unknown Voice')
        voice_id = voice.get('voice_id', 'Unknown ID')
        voices_list += f"<b>{voice_name}</b> - <code>{voice_id}</code>\n"

    await message.answer(voices_list, parse_mode="HTML")

@router.message(Command("history"))
async def history_command(message: Message):
    user_id = message.from_user.id
    user_config = await get_user_config(user_id)

    if not user_config:
        await message.answer("Please configure your API key first using /setapi.")
        return

    api_key = user_config.get("api_key")
    if not api_key:
        await message.answer("Your API key is missing. Use /setapi to set it.")
        return

    # Fetch history from ElevenLabs API
    try:
        headers = {"xi-api-key": api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.elevenlabs.io/v1/history", headers=headers)

            if response.status_code == 200:
                history_data = response.json()
                history_items = history_data.get("history", [])

                if not history_items:
                    await message.answer("<b>No history found.</b>", parse_mode="HTML")
                    return

                # Prepare the history data
                history_texts = []
                current_text = "<b>Your ElevenLabs Usage History:</b>\n\n"
                
                for item in history_items:
                    text = item.get("text", "No text available")
                    date_unix = item.get("date_unix", 0)
                    date = datetime.utcfromtimestamp(date_unix).strftime('%Y-%m-%d %H:%M:%S') if date_unix else "Unknown date"
                    voice_name = item.get("voice_name", "Unknown voice")

                    entry = (
                        f"📅 <b>Date:</b> {date}\n"
                        f"🎤 <b>Voice:</b> {voice_name}\n"
                        f"📝 <b>Text:</b> <code>{text}</code>\n\n"
                    )

                    # Split into chunks if the message exceeds the Telegram limit
                    if len(current_text) + len(entry) > 4000:
                        history_texts.append(current_text)
                        current_text = entry
                    else:
                        current_text += entry

                # Append the last chunk
                if current_text:
                    history_texts.append(current_text)

                # Send the chunks sequentially
                for chunk in history_texts:
                    await message.answer(chunk, parse_mode="HTML")
            else:
                await message.answer(
                    f"<b>Error:</b> Unable to fetch history. (Status: {response.status_code})",
                    parse_mode="HTML"
                )
    except Exception as e:
        await message.answer(f"<b>Error:</b> {e}", parse_mode="HTML")

@router.message(Command("profile"))
async def show_config_command(message: Message):
    user_id = message.from_user.id
    user_config = await get_user_config(user_id)

    if not user_config:
        await message.answer("No configuration found. Please set your API key, voice ID, and settings first.")
        return

    api_key = user_config.get("api_key", "Not set")
    voice_id = user_config.get("voice_id", DEFAULT_PARAMS["voice_id"])
    voice_settings = user_config.get("voice_settings", DEFAULT_PARAMS)
    character_count = user_config.get("character_count", 0)

    # Fetch subscription details
    subscription_info = None
    try:
        if api_key != "Not set":
            headers = {"xi-api-key": api_key}
            async with httpx.AsyncClient() as client:
                response = await client.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers)
                if response.status_code == 200:
                    subscription_info = response.json()
                else:
                    subscription_info = {"error": f"Failed to fetch subscription info: {response.status_code}"}
    except Exception as e:
        subscription_info = {"error": str(e)}

    # Format subscription details
    if subscription_info and "error" not in subscription_info:
        subscription_details = (
            f"<b>Plan:</b> {subscription_info.get('tier', 'Unknown')}\n"
            f"<b>Character Count:</b> {subscription_info.get('character_count', 'Unknown')}\n"
            f"<b>Character Limit:</b> {subscription_info.get('character_limit', 'Unknown')}\n"
            f"<b>Remaining:</b> {subscription_info.get('character_limit', 0) - subscription_info.get('character_count', 0)}\n"
            f"<b>Voice Limit:</b> {subscription_info.get('voice_limit', 'Unknown')}\n"
            f"<b>Professional Voice Limit:</b> {subscription_info.get('professional_voice_limit', 'Unknown')}\n"
            f"<b>Can Extend Character Limit:</b> {subscription_info.get('can_extend_character_limit', False)}\n"
            f"<b>Instant Voice Cloning:</b> {subscription_info.get('can_use_instant_voice_cloning', False)}\n"
            f"<b>Next Reset:</b> {subscription_info.get('next_character_count_reset_unix', 'Unknown')}\n"
        )
    else:
        subscription_details = subscription_info.get("error", "Unable to fetch subscription details.")

    # Ensure all details are displayed, even if missing
    config_details = (
        f"<b>Your Configuration:</b>\n\n"
        f"<b>API Key:</b> <code>{api_key}</code>\n"
        f"<b>Voice ID:</b> <code>{voice_id}</code>\n\n"
        f"<b>Voice Settings:</b>\n"
        f"<b>Stability:</b> <code>{voice_settings.get('stability', 'Not set')}</code>\n"
        f"<b>Similarity Boost:</b> <code>{voice_settings.get('similarity_boost', 'Not set')}</code>\n"
        f"<b>Characters Processed:</b> <code>{character_count}</code>\n\n"
        f"<b>ElevenLabs Subscription Information:</b>\n{subscription_details}"
    )

    await message.answer(config_details, parse_mode="HTML")
    
# Set bot commands
async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="setapi", description="Set your Eleven Labs API key"),
        BotCommand(command="setvoice", description="Set your voice ID"),
        BotCommand(command="voicesettings", description="Set your voice settings"),
        BotCommand(command="speech", description="Generate text to speech"),
        BotCommand(command="listvoices", description="List available voices"),
        BotCommand(command="clearconfig", description="Clear your configuration"),
        BotCommand(command="profile", description="Show your current configuration"),
        BotCommand(command="history", description="Get elevenlabs usage"),
    ]
    await bot.set_my_commands(commands)

# Main function to start the bot

async def main():
    # Fetch bot details
    bot_details = await bot.get_me()

    # Display bot details in the terminal
    print("=" * 40)
    print("🚀 Starting Telegram Bot")
    print(f"🤖 Bot Name: {bot_details.first_name}")
    print(f"🆔 Bot Username: @{bot_details.username}")
    print(f"🔑 Bot ID: {bot_details.id}")
    print("=" * 40)

    # Set bot commands
    await set_bot_commands()

    # Start polling
    print("📡 Bot is now polling for updates...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
