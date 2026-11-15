import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
FHIR_BASE = 'https://r4.smarthealthit.org'
SAMPLE_PATIENT = '98671a34-1c6e-4569-a1bc-6ee40c8d03a5'


def required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'{name} is not configured. Follow the local setup instructions.')
    return value
