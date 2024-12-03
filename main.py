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

# Define the Bot Token directly
BOT_TOKEN = "7612501799:AAE95Z4VBPAKreCVM0sVa1CnV6xvnKOzaZ8"
if not BOT_TOKEN:
    raise ValueError("Bot token is missing")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()  # Temporary FSM storage
dp = Dispatcher(storage=storage)
router = Router()  # Router for commands
dp.include_router(router)

# Default API Settings
DEFAULT_PARAMS = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Default voice ID
    "stability": 0.5,
    "similarity_boost": 0.7,
}

# Helper function to get or initialize character count
async def get_or_initialize_character_count(user_id):
    user_config = await get_user_config(user_id)
    if not user_config:
        user_config = {"character_count": 0}
        await update_user_config(user_id, user_config)
    return user_config.get("character_count", 0)

async def get_existing_voices(api_key: str):
    headers = {
        "xi-api-key": api_key,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.elevenlabs.io/v1/voices", headers=headers)
        if response.status_code == 200:
            return response.json().get("voices", [])
        else:
            return []
            

# Function to generate audio with Eleven Labs API
async def generate_elevenlabs_audio(text: str, api_key: str, voice_id: str, voice_settings: dict, audio_path: str):
    """
    Generates audio using the ElevenLabs API and saves it to the specified path.
    """
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
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

# Function to upload file to file.io
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
    # Create an inline keyboard with buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="View Documentation", url="https://elevenlabs.io/docs")],
        [InlineKeyboardButton(text="Contact Support", url="https://t.me/xwvux")]
    ])

    # Send the welcome message with the inline buttons
    await message.answer(
        "<b>Welcome to the ElevenLabs Manager!</b>\n\n"
        "I'm here to help you manage your ElevenLabs account directly from Telegram.\n\n"
        "<b>What can I do for you?</b>\n"
        "• Generate text-to-speech\n"
        "• Use multiple accounts\n"
        "• Manage existing voices\n"
        "• And much more!\n\n"
        "Just send me a command to get started.\n\n"
        "<b>Need help?</b> Use the buttons below to read the documentation or contact support.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.message(Command("setapi"))
async def set_api_command(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        # Inline keyboard to guide users to get their API key
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Get your Eleven Labs API Key", url="https://elevenlabs.io")]
        ])
        await message.answer(
            "To set your <b>Eleven Labs API key</b>, use this command like:\n"
            "<code>/setapi &lt;your_api_key&gt;</code>\n\n"
            "Don't have an API key? Click the button below to get one.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    api_key = args[1].strip()

    # Verify the API key
    headers = {"xi-api-key": api_key}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers)

        if response.status_code == 200:
            # Save the API key if it's valid
            await update_user_config(user_id, {"api_key": api_key})
            subscription_info = response.json()
            character_limit = subscription_info.get("character_limit", "Unknown")
            await message.answer(
                f"Your <b>API key</b> has been successfully verified and set. 🎉\n"
                f"<b>Character Limit:</b> {character_limit}",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"<b>Error:</b> The API key is invalid or not authorized. Please check your key and try again.",
                parse_mode="HTML"
            )
    except Exception as e:
        await message.answer(
            f"<b>Error:</b> Unable to verify the API key. Please try again later.\n"
            f"<code>{str(e)}</code>",
            parse_mode="HTML"
        )


@router.message(Command("setvoice"))
async def set_voice_command(message: types.Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        # Create an inline keyboard with a button to fetch voice IDs
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Get Voice IDs", url="https://elevenlabs.io/voice-lab")]
        ])
        
        # Send a usage message with the inline button
        await message.answer(
            "To set a <b>voice ID</b>, use this command like:\n\n"
            "<code>/setvoice &lt;voice_id&gt;</code>\n"
            "Don't know your voice ID? Click the button below to explore available voices.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    voice_id = args[1].strip()
    await update_user_config(user_id, {"voice_id": voice_id})
    await message.answer(f"Your <b>voice ID</b> has been set to <code>{voice_id}</code>.", parse_mode="HTML")

@router.message(Command("setsettings"))
async def set_settings_command(message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Please provide stability and similarity_boost values.")
        return

    try:
        stability, similarity_boost = map(float, args[1:])
        voice_settings = {"stability": stability, "similarity_boost": similarity_boost}
        await update_user_config(user_id, {"voice_settings": voice_settings})
        await message.answer(f"Your voice settings have been set to Stability: {stability}, Similarity Boost: {similarity_boost}.")
    except ValueError:
        await message.answer("Invalid input. Please provide numerical values for stability and similarity_boost.")


@router.message(Command("generate"))
async def generate_voice_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Please provide the text to convert to speech.")
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

    voices_list = "<b>Existing Voices:</b>\n"
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
        BotCommand(command="setsettings", description="Set your voice settings"),
        BotCommand(command="generate", description="Generate a voice from text"),
        BotCommand(command="listvoices", description="Set your voice settings"),
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
