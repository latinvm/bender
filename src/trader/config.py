import os
from typing import NamedTuple
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class BitvavoConfig(NamedTuple):
    api_key: str = os.getenv('BITVAVO_API_KEY', '')
    api_secret: str = os.getenv('BITVAVO_API_SECRET', '')

def get_config() -> BitvavoConfig:
    return BitvavoConfig()