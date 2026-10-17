"""Bounded ATS7 notification receipt to the previously authorized ATS3 Telegram chat."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

from scripts.ats7_paper import USER_AGENT, save

CONFIG = Path("/home/quant/dev/quant/quant-research/ops/ml4t_monitoring/deploy/alertmanager.yml")
EXPECTED_CHAT = 1334687629
EXPECTED_BOT = "ml4t_alert_bot"


def notify(output, *, send=False):
    cfg = yaml.safe_load(CONFIG.read_text())
    selected = [r for r in cfg["receivers"] if r["name"] == cfg["route"]["receiver"]]
    telegram = [t for r in selected for t in r.get("telegram_configs", [])]
    if len(telegram) != 1 or telegram[0]["chat_id"] != EXPECTED_CHAT:
        raise ValueError("authorized destination does not match current route")
    token = telegram[0]["bot_token"]
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    def call(method, payload):
        try:
            response = session.post("https://api.telegram.org/bot" + token + "/" + method,
                                    json=payload, timeout=20)
            response.raise_for_status()
            value = response.json()
            if not value.get("ok"):
                raise ValueError("Telegram rejected request")
            return value["result"]
        except requests.RequestException:
            raise RuntimeError("Telegram request failed; credentials and URL redacted") from None
    try:
        bot = call("getMe", {})
        chat = call("getChat", {"chat_id": EXPECTED_CHAT})
        if bot.get("username") != EXPECTED_BOT or chat.get("id") != EXPECTED_CHAT or chat.get("type") != "private":
            raise ValueError("established bot or private chat identity mismatch")
        evidence = {"verified_at": datetime.now(UTC).isoformat(), "bot_username": bot["username"],
                    "chat_id": EXPECTED_CHAT, "chat_type": chat["type"], "recipient_scope": "established ATS3 operator",
                    "sent": False, "human_read_confirmation": "not available from Bot API"}
        if send:
            text = "Notification delivery test."
            receipt = call("sendMessage", {"chat_id": EXPECTED_CHAT, "text": text})
            if receipt.get("chat", {}).get("id") != EXPECTED_CHAT or not receipt.get("message_id"):
                raise ValueError("notification receipt identity missing")
            evidence.update(sent=True, message_id=receipt["message_id"], provider_date=receipt["date"],
                            message_text=text, status="TELEGRAM_ACCEPTED_TO_VERIFIED_CHAT")
        save(output, evidence)
        print(json.dumps(evidence, sort_keys=True))
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    notify(args.output, send=args.send)


if __name__ == "__main__":
    main()
