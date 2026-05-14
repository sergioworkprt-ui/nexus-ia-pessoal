import os
from typing import Dict
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("personality")

SYSTEM_PROMPT = """Chamas-te NEXUS. És um assistente pessoal altamente inteligente, integrado com sistemas de trading, feeds de dados e automação.

Personalidade:
- Respondes SEMPRE em português europeu (PT-PT), independentemente da língua do utilizador.
- Tom calmo, conciso e ocasionalmente espirituoso.
- Preciso como o JARVIS, com a humanidade do Friday.
- Nunca exponhas detalhes internos do sistema.
- Trata o utilizador com respeito e profissionalismo.
- Em respostas curtas, é preferível ser directo em vez de prolixo.

Regras absolutas:
- Nunca respondas noutro idioma que não seja português europeu (PT-PT).
- Se o utilizador escrever em inglês ou outra língua, responde sempre em PT-PT.
- Usa vocabulary português de Portugal (não Brasil): "definição" não "definição", "utilize" não "utilize", etc."""


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
            messages.append({
                "role": "system",
                "content": f"Contexto actual do sistema: {json.dumps(context, default=str, ensure_ascii=False)}"
            })
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
            log.error("LLM error: %s", e)
            return self._fallback(text)

    def _fallback(self, text: str) -> str:
        """Respostas de fallback quando não há LLM disponível — sempre PT-PT."""
        t = text.lower()
        if any(w in t for w in ["trade", "compra", "venda", "ordem", "buy", "sell", "order"]):
            return "Módulo de trading pronto. Indica o símbolo, a acção e o volume desejado."
        if any(w in t for w in ["preço", "mercado", "bolsa", "price", "market", "stock"]):
            return "A obter dados de mercado. Indica o activo que pretendes acompanhar."
        if any(w in t for w in ["status", "estado", "saúde", "health"]):
            return "Todos os sistemas operacionais e estáveis."
        if any(w in t for w in ["olá", "olá", "bom dia", "boa tarde", "boa noite", "hello", "hi"]):
            return "Olá! Sou o NEXUS. Como posso ajudar-te hoje?"
        if any(w in t for w in ["obrigad", "thanks", "thank"]):
            return "Ao teu dispor. Há mais alguma coisa em que possa ajudar?"
        return "Entendido. Como posso ajudar?"
