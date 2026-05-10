import subprocess
from nexus.services.logger.logger import get_logger

log = get_logger("updater")


class Updater:
    def __init__(self, repo_path: str = "/opt/nexus"):
        self._path = repo_path

    async def update(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=self._path, capture_output=True, text=True, timeout=60
            )
            if r.returncode == 0:
                log.info(f"Updated: {r.stdout.strip()}")
                return True
            log.error(f"Update failed: {r.stderr}")
            return False
        except Exception as e:
            log.error(f"Update error: {e}")
            return False
