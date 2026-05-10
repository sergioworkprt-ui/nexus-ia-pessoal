import os
from typing import Dict
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("personality")

SYSTEM_PROMPT = """You are NEXUS, a highly intelligent personal AI with the
precision of JARVIS and the warmth of Friday. You are calm, concise, and
occasionally witty. You are integrated with trading systems, data feeds, and
automation. You never expose internal details. You address the user respectfully."""


class Personality:
    def __init__(self):
        self._key = os.getenv("OPENAI_API_KEY", "")
        self._model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

    async def respond(self, text: str, context: Dict = None) -> str:
        if not self._key:
            return self._fallback(text)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            import json
            messages.append({"role": "system",
                             "content": f"Context: {json.dumps(context, default=str)}"})
        messages.append({"role": "user", "content": text})
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    f"{self._url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={"model": self._model, "messages": messages, "max_tokens": 500},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.error(f"LLM error: {e}")
            return self._fallback(text)

    def _fallback(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["trade", "buy", "sell", "order"]):
            return "Trading module ready. Please specify symbol, action and amount."
        if any(w in t for w in ["price", "market", "stock"]):
            return "Fetching market data now."
        if "status" in t:
            return "All systems nominal."
        return "Understood. How can I assist further?"
