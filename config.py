import os
from dotenv import load_dotenv

load_dotenv()  # Загружает переменные из .env

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') 
    ADMIN_ID = int(os.getenv('ADMIN_ID'))
    DATABASE_NAME = "bot_database.db"
    DEFAULT_FREE_REQUESTS = 3
