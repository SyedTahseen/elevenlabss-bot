from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import httpx
from logger import log_user_activity
import os
import aiofiles
from db import get_user_config, update_user_config, clear_user_config

# Define the Bot Token directly
BOT_TOKEN = "7548654576:AAGAu8B73cYEpRBlwDE1kAh1WTnyxzZ_KO0"
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
async def start_command(message: Message):
    await message.answer(
        "<b>Welcome to the ElevenLabs Assistant!</b>\n\n"
        "I'm here to help you manage your ElevenLabs account directly from Telegram.\n\n"
        "<b>What can I do for you?</b>\n"
        "* Create new voices\n"
        "* Manage existing voices\n"
        "* Generate text-to-speech\n"
        "* And much more!\n\n"
        "Just send me a command to get started.\n\n"
        "<b>Need help?</b> Type /help for a list of commands.",
        parse_mode="HTML"
    )

@router.message(Command("setapi"))
async def set_api_command(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Please provide your Eleven Labs API key.")
        return

    api_key = args[1].strip()
    await update_user_config(user_id, {"api_key": api_key})
    await message.answer("Your API key has been set.")

@router.message(Command("setvoice"))
async def set_voice_command(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Please provide a valid voice ID.")
        return

    voice_id = args[1].strip()
    await update_user_config(user_id, {"voice_id": voice_id})
    await message.answer(f"Your voice ID has been set to {voice_id}.")

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
        voice_id = voice.get('voice_id', 'Unknown ID')  # Assuming voice_id is available in the API response
        voices_list += f"<b>{voice_name}</b> - <code>{voice_id}</code>\n"  # Use <code> for voice ID

    await message.answer(voices_list, parse_mode="HTML")

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
    if api_key != "Not set":
        try:
            headers = {"xi-api-key": api_key}
            async with httpx.AsyncClient() as client:
                response = await client.get("https://api.elevenlabs.io/v1/user/subscription", headers=headers)
                if response.status_code == 200:
                    subscription_info = response.json()
                else:
                    subscription_info = {"error": f"Failed to fetch subscription info: {response.status_code}"}
        except Exception as e:
            subscription_info = {"error": str(e)}

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

    # Combine configuration and subscription details
    config_details = (
        f"<b>Your Configuration:</b>\n\n"
        f"<b>API Key:</b> <code>{api_key}</code>\n"
        f"<b>Voice ID:</b> <code>{voice_id}</code>\n\n"
        f"<b>Voice Settings:</b>\n"
        f"<b>Stability:</b> <code>{voice_settings['stability']}</code>\n"
        f"<b>Similarity Boost:</b> <code>{voice_settings['similarity_boost']}</code>\n"
        f"<b>Characters Processed:</b> <code>{character_count}</code>\n\n"
        f"<b>Subscription Information:</b>\n{subscription_details}"
    )
    await message.answer(config_details, parse_mode="HTML")

# Set bot commands
async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="setapi", description="Set your Eleven Labs API key"),
        BotCommand(command="setvoice", description="Set your voice ID"),
        BotCommand(command="setsettings", description="Set your voice settings"),
        BotCommand(command="listvoices", description="Set your voice settings"),
        BotCommand(command="generate", description="Generate a voice from text"),
        BotCommand(command="clearconfig", description="Clear your configuration"),
        BotCommand(command="profile", description="Show your current configuration"),
    ]
    await bot.set_my_commands(commands)

# Main function to start the bot
async def main():
    await set_bot_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

    
