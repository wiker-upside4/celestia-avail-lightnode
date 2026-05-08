import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(os.environ.get("DABEAT_ENV", "/home/wiker/.dabeat/.env"))
load_dotenv(ENV_PATH)

CELESTIA_RPC = os.environ["CELESTIA_RPC"]
CELESTIA_TOKEN_FILE = os.environ["CELESTIA_TOKEN_FILE"]
CELESTIA_LN_INSTANCE = os.environ["CELESTIA_LN_INSTANCE"]

AVAIL_LC = os.environ["AVAIL_LC"]
AVAIL_LN_INSTANCE = os.environ["AVAIL_LN_INSTANCE"]

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ["DB_PORT"])
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


def get_celestia_token() -> str:
    with open(CELESTIA_TOKEN_FILE, "r") as f:
        return f.read().strip()
