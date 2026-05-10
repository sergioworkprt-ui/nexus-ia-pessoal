"""Truth Checker — verify claims via web search + LLM."""
from __future__ import annotations
import os
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("truth_checker")


class TruthChecker:
    def __init__(self):
        self._llm_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self._llm_key = os.getenv("OPENAI_API_KEY", "")
        self._llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._serp_key = os.getenv("SERP_API_KEY", "")

    async def _search(self, query: str) -> str:
        if not self._serp_key:
            return "[Web search not configured — add SERP_API_KEY to .env]"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "api_key": self._serp_key, "num": 5},
                )
                results = r.json().get("organic_results", [])
                return "\n".join(f"- {x.get('title')}: {x.get('snippet')}" for x in results[:5])
        except Exception as e:
            return f"[search error: {e}]"

    async def check(self, claim: str) -> dict:
        search_results = await self._search(claim)
        if not self._llm_key:
            return {"claim": claim, "verdict": "unknown",
                    "reason": "LLM not configured — add OPENAI_API_KEY"}
        prompt = (
            f"Verifica esta afirmação com base nos resultados de pesquisa.\n\n"
            f"Afirmação: {claim}\n\n"
            f"Resultados:\n{search_results}\n\n"
            "Responde com: VEREDICTO (verdadeiro/falso/incerto/precisa_verificação) e RAZÃO (2-3 frases)."
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self._llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm_key}"},
                    json={"model": self._llm_model, "max_tokens": 512,
                          "messages": [{"role": "user", "content": prompt}]},
                )
                analysis = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return {"claim": claim, "verdict": "error", "reason": str(e)}
        verdict = "incerto"
        for v in ("verdadeiro", "falso", "incerto", "precisa_verificação",
                  "true", "false", "uncertain"):
            if v.lower() in analysis.lower():
                verdict = v
                break
        return {"claim": claim, "verdict": verdict, "analysis": analysis, "sources": search_results}

    async def start(self):
        log.info("TruthChecker started")

    def stop(self):
        pass
