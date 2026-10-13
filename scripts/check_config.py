"""Check configuration without printing secrets or making provider requests."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
model = os.getenv('ADK_MODEL', 'anthropic/claude-sonnet-5-5')
key_name = 'ANTHROPIC_API_KEY' if model.startswith('anthropic/') else 'GOOGLE_API_KEY'
if not os.getenv(key_name):
    raise SystemExit(f'Missing {key_name}: add it to .env before starting.')
print(f'Configured model: {model}; credential present (hidden).')
