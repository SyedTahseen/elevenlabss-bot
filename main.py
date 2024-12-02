from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import httpx
import os
from db import get_user_config, update_user_config, clear_user_config

# Define the Bot Token directly
BOT_TOKEN = "8195569776:AAFLMWcJllRvPUgP3RgrWFWla6p56xS3kHU"
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

# Function to generate audio with Eleven Labs API
async def generate_elevenlabs_audio(text: str, api_key: str, voice_id: str, voice_settings: dict):
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

    audio_path = "elevenlabs_voice.mp3"

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

    return audio_path

# Command Handlers
@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "Welcome! Use /setapi [your_api_key] to set your Eleven Labs API key. "
        "Use /setvoice [voice_id] to set your voice ID. "
        "Use /setsettings [stability] [similarity_boost] to configure your voice settings.\n\n"
        "<b>Important:</b> Remember to configure your API key and voice settings first!",
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
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Please provide the text to convert to speech.")
        return

    text = args[1].strip()
    user_config = await get_user_config(user_id)

    if not user_config:
        await message.answer("Please configure your API key, voice ID, and settings first using /setapi, /setvoice, and /setsettings.")
        return

    api_key = user_config.get("api_key")
    if not api_key:
        await message.answer("Your API key is missing. Use /setapi to set it.")
        return

    voice_id = user_config.get("voice_id", DEFAULT_PARAMS["voice_id"])
    voice_settings = user_config.get("voice_settings", DEFAULT_PARAMS)

    audio_path = None
    try:
        # Update character count
        character_count = await get_or_initialize_character_count(user_id)
        character_count += len(text)
        await update_user_config(user_id, {"character_count": character_count})

        audio_path = await generate_elevenlabs_audio(text, api_key, voice_id, voice_settings)
        audio_file = FSInputFile(audio_path)
        await bot.send_voice(chat_id=message.chat.id, voice=audio_file)
    except Exception as e:
        await message.answer(f"Error: {e}")
    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

@router.message(Command("clearconfig"))
async def clear_config_command(message: Message):
    user_id = message.from_user.id
    await clear_user_config(user_id)
    await message.answer("Your configuration has been cleared.")

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
