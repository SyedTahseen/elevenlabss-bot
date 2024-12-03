from datetime import datetime
from aiogram import Bot

LOG_GROUP_ID = -1002054393773 # Replace with your log group chat ID

async def log_user_activity(bot: Bot, user_id: int, username: str, activity: str, details: dict):
    """
    Logs user activity to the specified log group.

    :param bot: The Bot instance from the main file
    :param user_id: Telegram user ID
    :param username: Telegram username
    :param activity: Description of the activity
    :param details: Additional details as a dictionary
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details_formatted = "\n".join(f"<b>{key}:</b> {value}" for key, value in details.items())

    log_message = (
        f"<b>User Activity Log</b>\n"
        f"<b>Timestamp:</b> {timestamp}\n"
        f"<b>User ID:</b> {user_id}\n"
        f"<b>Username:</b> @{username if username else 'N/A'}\n"
        f"<b>Activity:</b> {activity}\n\n"
        f"<b>Details:</b>\n{details_formatted}"
    )

    try:
        await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to log activity: {e}")
