"""Multi-AI Learning — query OpenAI, Claude, Gemini in parallel and synthesize."""
from __future__ import annotations
import asyncio, os
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("learning")


class LearningModule:
    def __init__(self):
        self._providers = self._init_providers()

    def _init_providers(self) -> dict:
        p: dict = {}
        if os.getenv("OPENAI_API_KEY"):
            p["openai"] = {
                "url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
                "key": os.getenv("OPENAI_API_KEY"),
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "type": "openai",
            }
        if os.getenv("ANTHROPIC_API_KEY"):
            p["claude"] = {
                "url": "https://api.anthropic.com",
                "key": os.getenv("ANTHROPIC_API_KEY"),
                "model": "claude-3-5-haiku-20241022",
                "type": "anthropic",
            }
        if os.getenv("GEMINI_API_KEY"):
            p["gemini"] = {
                "url": "https://generativelanguage.googleapis.com",
                "key": os.getenv("GEMINI_API_KEY"),
                "model": "gemini-1.5-flash",
                "type": "gemini",
            }
        return p

    async def _ask(self, cfg: dict, question: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if cfg["type"] == "anthropic":
                    r = await client.post(
                        f"{cfg['url']}/v1/messages",
                        headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"},
                        json={"model": cfg["model"], "max_tokens": 1024,
                              "messages": [{"role": "user", "content": question}]},
                    )
                    return r.json()["content"][0]["text"]
                elif cfg["type"] == "gemini":
                    r = await client.post(
                        f"{cfg['url']}/v1beta/models/{cfg['model']}:generateContent?key={cfg['key']}",
                        json={"contents": [{"parts": [{"text": question}]}]},
                    )
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    r = await client.post(
                        f"{cfg['url']}/chat/completions",
                        headers={"Authorization": f"Bearer {cfg['key']}"},
                        json={"model": cfg["model"], "max_tokens": 1024,
                              "messages": [{"role": "user", "content": question}]},
                    )
                    return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[error: {e}]"

    async def multi_query(self, question: str) -> dict[str, str]:
        if not self._providers:
            return {"info": "No AI providers configured. Add OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY to .env"}
        results = await asyncio.gather(*[self._ask(cfg, question) for cfg in self._providers.values()])
        return dict(zip(self._providers.keys(), results))

    async def synthesize(self, question: str) -> dict:
        answers = await self.multi_query(question)
        if len(answers) <= 1:
            return {"answers": answers, "synthesis": list(answers.values())[0] if answers else ""}
        synth_prompt = (
            f'Multiple AI answers to: "{question}"\n\n'
            + "\n\n".join(f"[{k}]: {v}" for k, v in answers.items())
            + "\n\nSynthesize the most accurate, complete answer. Note any disagreements."
        )
        first = list(self._providers.values())[0]
        synthesis = await self._ask(first, synth_prompt)
        return {"answers": answers, "synthesis": synthesis}

    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    async def start(self):
        log.info(f"LearningModule started — providers: {list(self._providers.keys()) or ['none']}")

    def stop(self):
        pass
