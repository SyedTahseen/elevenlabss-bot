import motor.motor_asyncio

# MongoDB connection
client = motor.motor_asyncio.AsyncIOMotorClient("mongodb+srv://itxcriminal:qureshihashmI1@cluster0.jyqy9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client["voice_bot"]
users_collection = db["users"]

# Function to get user config
async def get_user_config(user_id):
    user = await users_collection.find_one({"user_id": user_id})
    return user if user else None

# Function to update user config
async def update_user_config(user_id, config_data):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": config_data},
        upsert=True
    )

# Function to clear user config
async def clear_user_config(user_id):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"api_key": None, "voice_id": None, "voice_settings": {}, "api_keys": [], "active_api_key": None}},
        upsert=True
    )

# Add a new API key for the user
async def add_api_key(user_id, api_key):
    user = await users_collection.find_one({"user_id": user_id})
    api_keys = user.get("api_keys", []) if user else []
    if api_key not in api_keys:
        api_keys.append(api_key)
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"api_keys": api_keys}},
        upsert=True
    )

# Get all API keys for the user
async def get_api_keys(user_id):
    user = await users_collection.find_one({"user_id": user_id})
    return user.get("api_keys", []) if user else []

# Set the active API key for the user
async def set_active_api_key(user_id, active_key):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"active_api_key": active_key}},
        upsert=True
    )

# Get the active API key for the user
async def get_active_api_key(user_id):
    user = await users_collection.find_one({"user_id": user_id})
    return user.get("active_api_key")
