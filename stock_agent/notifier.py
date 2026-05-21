"""Sends WhatsApp messages via the Node.js whatsapp-web.js sender."""

import os
import subprocess
from pathlib import Path

# Absolute path to the Node.js sender script
SENDER_JS = Path(__file__).resolve().parent.parent / "whatsapp" / "sender.js"


def send_whatsapp(phone: str, message: str) -> bool:
    """
    Send a WhatsApp message to `phone` (international format, no +).
    Example: "5511999999999"
    Blocks until the Node.js process completes (≤ 60 s).
    """
    if not SENDER_JS.exists():
        print(f"[notifier] sender.js not found at {SENDER_JS}")
        return False

    try:
        result = subprocess.run(
            ["node", str(SENDER_JS), phone, message],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode == 0:
            print(f"[notifier] ✓ Message sent to {phone}")
            return True
        print(f"[notifier] ✗ sender.js exited {result.returncode}: {result.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        print("[notifier] ✗ Timeout waiting for WhatsApp send")
        return False
    except FileNotFoundError:
        print("[notifier] ✗ 'node' not found — install Node.js")
        return False
    except Exception as exc:
        print(f"[notifier] ✗ Unexpected error: {exc}")
        return False
