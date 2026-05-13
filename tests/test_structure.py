"""Tests: ficheiros essenciais existem e sintaxe Python é válida."""
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).parent.parent

ESSENTIAL_FILES = [
    "nexus/main.py",
    "nexus/__init__.py",
    "nexus/requirements.txt",
    "nexus/ws_server.py",
    "nexus/api/rest/main.py",
    "nexus/dashboard/server.py",
    "nexus/dashboard/frontend/package.json",
    "nexus/dashboard/frontend/src/App.tsx",
    "nexus/dashboard/frontend/src/api.ts",
    "nexus/scripts/install.sh",
    "nexus/scripts/rebuild_dashboard.sh",
    "nexus/scripts/rollback.sh",
    "nexus/scripts/health_check.sh",
    ".github/workflows/deploy.yml",
    ".github/workflows/rollback-manual.yml",
]

PYTHON_FILES = [
    "nexus/main.py",
    "nexus/api/rest/main.py",
    "nexus/ws_server.py",
    "nexus/dashboard/server.py",
]

REQUIRED_DEPS = [
    "fastapi",
    "uvicorn",
    "websockets",
    "pydantic",
    "httpx",
    "psutil",
]


def test_essential_files_exist():
    missing = [f for f in ESSENTIAL_FILES if not (ROOT / f).exists()]
    assert not missing, f"Ficheiros em falta: {missing}"


def test_python_syntax():
    errors = []
    for rel in PYTHON_FILES:
        path = ROOT / rel
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{rel}: {e}")
    assert not errors, "Erros de sintaxe Python:\n" + "\n".join(errors)


def test_requirements_has_key_deps():
    content = (ROOT / "nexus/requirements.txt").read_text().lower()
    missing = [d for d in REQUIRED_DEPS if d not in content]
    assert not missing, f"Falta em requirements.txt: {missing}"


def test_frontend_package_json():
    data = json.loads((ROOT / "nexus/dashboard/frontend/package.json").read_text())
    assert "scripts" in data, "package.json sem 'scripts'"
    assert "build" in data["scripts"], "package.json sem script 'build'"
    assert "dev" in data["scripts"], "package.json sem script 'dev'"


def test_vite_env_vars_in_api_ts():
    content = (ROOT / "nexus/dashboard/frontend/src/api.ts").read_text()
    assert "VITE_API_URL" in content, "api.ts deve referenciar VITE_API_URL"
    assert "VITE_WS_URL" in content, "api.ts deve referenciar VITE_WS_URL"


def test_cors_configured_correctly():
    content = (ROOT / "nexus/api/rest/main.py").read_text()
    assert "CORSMiddleware" in content, "CORS middleware em falta em rest/main.py"
    assert 'allow_origins=["*"]' in content, "allow_origins deve ser wildcard"
    assert "allow_credentials=False" in content, "allow_credentials deve ser False com wildcard"


def test_chat_endpoint_has_no_auth():
    lines = (ROOT / "nexus/api/rest/main.py").read_text().splitlines()
    for i, line in enumerate(lines):
        if '@app.post("/chat")' in line:
            context = "\n".join(lines[i : i + 4])
            assert "_auth" not in context, (
                f"/chat não deve requerer auth:\n{context}"
            )
            return
    # Endpoint não encontrado — falha
    assert False, "Endpoint POST /chat não encontrado em rest/main.py"
