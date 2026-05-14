"""Shared pytest configuration and base test case."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Adicionar nexus/ ao sys.path para que testes de integração possam fazer:
#   from core.xxx import ...      (aponta para nexus/core/xxx)
#   from api.rest.main import ... (aponta para nexus/api/rest/main)
# Isto espelha o ambiente do VPS onde NEXUS_HOME/nexus está em PYTHONPATH.
if str(ROOT / "nexus") not in sys.path:
    sys.path.insert(0, str(ROOT / "nexus"))


class NexusTestCase(unittest.TestCase):
    """Base para todos os testes de integração NEXUS.

    Os testes que herdam desta classe requerem o ambiente completo do VPS
    (nexus/core/, nexus/modules/, etc.). Em CI (GitHub Actions) correm apenas
    test_structure.py e test_deploy_scripts.py — os restantes são ignorados.
    Para correr localmente no VPS: pytest tests/ -v
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="nexus_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def tmp_path(self, name: str) -> str:
        """Caminho para ficheiro temporário (não criado)."""
        return os.path.join(self._tmpdir, name)

    def tmp_subdir(self, name: str) -> str:
        """Caminho para subdiretório temporário (criado)."""
        sub = os.path.join(self._tmpdir, name)
        os.makedirs(sub, exist_ok=True)
        return sub

    def assertNonEmpty(self, obj, msg: str = "") -> None:  # noqa: N802
        """Falha se a colecção ou string for vazia."""
        self.assertTrue(obj, msg or f"Expected non-empty, got: {obj!r}")
