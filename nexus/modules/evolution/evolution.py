"""Code Evolution — propose improvements and apply with approval."""
from __future__ import annotations
import asyncio, json, os, re, uuid
from datetime import datetime
from pathlib import Path
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("evolution")

_SAFE_BASE = Path("/opt/nexus/nexus")
_FORBIDDEN = ["/etc", "/bin", "/usr", "/boot", "/sys", "/proc", "/root"]


class Evolution:
    def __init__(self):
        self._path = Path("/data/nexus/evolution.json")
        self._proposals: dict[str, dict] = self._load()
        self._llm_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self._llm_key = os.getenv("OPENAI_API_KEY", "")
        self._llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text()) if self._path.exists() else {}
        except Exception:
            return {}

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._proposals, indent=2, default=str))
        except Exception as e:
            log.warning(f"evolution save: {e}")

    async def propose(self, description: str, target_file: str | None = None) -> dict:
        pid = str(uuid.uuid4())[:8]
        context = ""
        if target_file:
            fp = _SAFE_BASE / target_file.lstrip("/")
            if fp.exists() and not any(str(fp).startswith(f) for f in _FORBIDDEN):
                context = f"\n\nFile ({target_file}):\n```python\n{fp.read_text()[:2000]}\n```"
        prompt = (
            f"You are a senior Python engineer reviewing an improvement request for the NEXUS AI system.{context}\n\n"
            f"Request: {description}\n\n"
            'Respond with JSON: {"summary": str, "risks": str, "approach": str, "files_affected": [str]}'
        )
        analysis = {"summary": description, "risks": "Analysis unavailable", "approach": "", "files_affected": []}
        if self._llm_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(
                        f"{self._llm_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._llm_key}"},
                        json={"model": self._llm_model, "max_tokens": 1024,
                              "messages": [{"role": "user", "content": prompt}]},
                    )
                    content = r.json()["choices"][0]["message"]["content"]
                    m = re.search(r"\{.*\}", content, re.DOTALL)
                    if m:
                        analysis = json.loads(m.group())
            except Exception as e:
                log.warning(f"LLM analysis: {e}")
        proposal = {
            "id": pid, "description": description, "target_file": target_file,
            "status": "waiting_approval", "analysis": analysis,
            "created_at": datetime.utcnow().isoformat(), "applied_at": None,
        }
        self._proposals[pid] = proposal
        self._save()
        log.info(f"evolution proposal: {pid}")
        return proposal

    def list_proposals(self, status: str | None = None) -> list[dict]:
        items = list(self._proposals.values())
        if status:
            items = [p for p in items if p["status"] == status]
        return sorted(items, key=lambda p: p["created_at"], reverse=True)

    def approve(self, pid: str) -> bool:
        if p := self._proposals.get(pid):
            p["status"] = "approved"
            self._save()
            log.info(f"evolution approved: {pid}")
            return True
        return False

    def reject(self, pid: str) -> bool:
        if p := self._proposals.get(pid):
            p["status"] = "rejected"
            self._save()
            return True
        return False

    async def apply(self, pid: str) -> dict:
        p = self._proposals.get(pid)
        if not p:
            return {"error": "proposal not found"}
        if p["status"] != "approved":
            return {"error": f"proposal status is '{p['status']}', must be 'approved'"}
        p.update({"status": "applied", "applied_at": datetime.utcnow().isoformat()})
        self._save()
        log.info(f"evolution applied (logged): {pid}")
        return {"status": "applied", "id": pid,
                "note": "Evolution logged. Code changes must be applied manually via git."}

    async def start(self):
        log.info("Evolution started")

    def stop(self):
        pass
