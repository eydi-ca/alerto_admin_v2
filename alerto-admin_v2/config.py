import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "alerto.db")

APP_HOST = "0.0.0.0"
APP_PORT = 5000
APP_DEBUG = True