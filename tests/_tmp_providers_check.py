from __future__ import print_function
import os
import asyncio
import httpx
from pathlib import Path

dotenv_path = Path(r'C:/JFN/jfn/compliance_agent/.env')
if dotenv_path.exists():
    for line in dotenv_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip())
else:
    print(f'DOTENV_MISSING: {dotenv_path}')

providers = {
    'qwen': {
        'url': 'https://inference-api.nousresearch.com/v1/chat/completions',
        'model': 'qwen/qwen-2.5-72b-instruct:free',
        'key_env': 'OPENROUTER_API_KEY',
    },
    'openrouter': {
        'url': 'https://openrouter.ai/api/v1/chat/completions',
        'model': 'meta-llama/llama-3.3-70b-instruct:free',
        'key_env': 'OPENROUTER_API_KEY',
    },
    'mistral': {
        'url': 'https://api.mistral.ai/v1/chat/completions',
        'model': 'mistral-small-latest',
        'key_env': 'MISTRAL_API_KEY',
    },
    'huggingface': {
        'url': 'https://router.huggingface.co/v1/chat/completions',
        'model': 'meta-llama/Llama-3.3-70B-Instruct',
        'key_env': 'HUGGINGFACE_API_KEY',
    },
    'gemini': {
        'url': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
        'model': 'gemini-2.5-flash',
        'key_env': 'GEMINI_API_KEY',
    },
}


async def check(name, cfg):
    key = os.getenv(cfg['key_env'], '')
    if not key:
        return 'NO_KEY'
    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': cfg['model'],
        'messages': [{'role': 'user', 'content': 'Diga OK em 1 palavra.'}],
        'max_tokens': 12,
        'temperature': 0,
    }
    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(cfg['url'], json=payload, headers=headers)
    data = r.json()
    try:
        text = data['choices'][0]['message']['content'].strip()
    except Exception as e:
        text = f'ERR_JSON: {e} | raw={str(data)[:220]}'
    return f'status={r.status_code} reply={text}'


async def main():
    for name, cfg in providers.items():
        try:
            out = await check(name, cfg)
            print(f'{name}: {out}')
        except Exception as e:
            print(f'{name}: EXCEPTION {e}')


asyncio.run(main())
