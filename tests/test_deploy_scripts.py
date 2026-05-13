"""Tests: scripts de deploy têm sintaxe bash válida e conteúdo correcto."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

BASH_SCRIPTS = [
    "nexus/scripts/rebuild_dashboard.sh",
    "nexus/scripts/rollback.sh",
    "nexus/scripts/health_check.sh",
    "nexus/scripts/deploy_vps.sh",
    "nexus/scripts/install.sh",
]


def test_bash_syntax():
    errors = []
    for rel in BASH_SCRIPTS:
        path = ROOT / rel
        if path.exists():
            r = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            if r.returncode != 0:
                errors.append(f"{rel}: {r.stderr.strip()}")
    assert not errors, "Erros de sintaxe bash:\n" + "\n".join(errors)


def test_rebuild_uses_ws_port_8801():
    content = (ROOT / "nexus/scripts/rebuild_dashboard.sh").read_text()
    assert "8801" in content, "rebuild_dashboard.sh deve usar porta WS 8801"


def test_rebuild_writes_both_env_files():
    content = (ROOT / "nexus/scripts/rebuild_dashboard.sh").read_text()
    assert ".env.local" in content, "rebuild_dashboard.sh deve escrever .env.local"
    assert "> \"$FRONTEND/.env\"" in content, "rebuild_dashboard.sh deve escrever .env"


def test_rollback_script_uses_git():
    content = (ROOT / "nexus/scripts/rollback.sh").read_text()
    assert "git" in content, "rollback.sh deve usar git"


def test_health_check_verifies_ports():
    content = (ROOT / "nexus/scripts/health_check.sh").read_text()
    for port in ["8000", "8801", "9000"]:
        assert port in content, f"health_check.sh deve verificar porta {port}"
