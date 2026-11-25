# -*- coding: utf-8 -*-
"""Seleção de testes do portão v2 pelo grafo de import (tools/portao_grafo.py, O2.5).

Repositório git de brinquedo em tmp_path: cada caso muda um arquivo num commit e confere QUAIS testes saem — o
transitivo, o relativo, o `from pacote import submódulo`, a string pontilhada do monkeypatch, o caminho de config, a
aresta tardia (import dentro de função) com o teto de 1, a fixture do conftest, o módulo apagado, as catracas e os
transversais. As duas falhas reais de 24/11 viraram os casos `test_falha_*`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import portao_grafo as pg

ARQUIVOS = {
    "pkg/__init__.py": "",
    "pkg/a.py": "import pkg.b\n",
    "pkg/b.py": "X = 1\n",
    "pkg/c.py": "def f():\n    from pkg import d\n    return d\n",
    "pkg/d.py": "def g():\n    import pkg.e\n",
    "pkg/e.py": "Y = 2\n",
    "pkg/f.py": "Z = 3\n",
    "pkg/g.py": "W = 4\n",
    "pkg/leitor.py": "FONTE = 'pkg/a.py'\n",
    "pkg/sub/__init__.py": "",
    "pkg/sub/r.py": "from ..b import X\n",
    "pkg/varredor.py": "import pathlib\nTETO = 0.25\n",
    "config/x.yaml": "rotina: pkg.e\n",
    "tools/pre_push_gate.sh": 'CATRACAS="tests/test_moeda.py tests/test_nao_existe.py"\n',
    "tests/conftest.py": ("import pytest\n\n@pytest.fixture\ndef fix_f():\n    from pkg import f\n    return f\n"),
    "tests/test_a.py": "from pkg import a\n\ndef test_a():\n    assert a\n",
    "tests/test_c.py": "from pkg.c import f\n\ndef test_c():\n    assert f\n",
    "tests/test_r.py": "import pkg.sub.r\n\ndef test_r():\n    pass\n",
    "tests/test_monkey.py": "def test_m(monkeypatch):\n    monkeypatch.setattr('pkg.b.X', 2)\n",
    "tests/test_cfg.py": "from pathlib import Path\nCFG = Path('config/x.yaml')\n",
    "tests/test_usa_fix.py": "def test_u(fix_f):\n    assert fix_f\n",
    "tests/test_g.py": "import pkg.g\n",
    "tests/test_leitor.py": "import pkg.leitor\n",
    "tests/test_varre.py": ("from pathlib import Path\nRAIZ = Path(__file__).parent.parent\n\n"
                            "def test_v():\n    assert list(RAIZ.glob('pkg/**/*.py'))\n"),
    "tests/test_tmp.py": "def test_t(tmp_path):\n    assert not list(tmp_path.glob('*'))\n",
    "tests/test_regra_x.py": "def test_x():\n    pass\n",
    "tests/test_catraca_y.py": "def test_y():\n    pass\n",
    "tests/test_moeda.py": "def test_z():\n    pass\n",
    "tests/test_isolado.py": "def test_i():\n    pass\n",
}
SEMPRE = {"tests/test_regra_x.py", "tests/test_catraca_y.py", "tests/test_moeda.py", "tests/test_varre.py"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CACHE", tmp_path / "cache" / "grafo.json")
    r = tmp_path / "r"
    for caminho, txt in ARQUIVOS.items():
        (r / caminho).parent.mkdir(parents=True, exist_ok=True)
        (r / caminho).write_text(txt, encoding="utf-8")
    _git(r.parent, "init", "-q", str(r))
    _git(r, "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return r


def _mudar(repo: Path, caminho: str, txt: str | None) -> tuple[str, str]:
    base = _git(repo, "rev-parse", "HEAD")
    if txt is None:
        (repo / caminho).unlink()
    else:
        (repo / caminho).write_text(txt, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"muda {caminho}")
    return base, _git(repo, "rev-parse", "HEAD")


def test_import_transitivo_relativo_e_string_pontilhada(repo):
    base, sha = _mudar(repo, "pkg/b.py", "X = 10\n")
    s = pg.selecionar(repo, base, sha)
    assert set(s.testes) == SEMPRE | {"tests/test_a.py", "tests/test_r.py", "tests/test_monkey.py"}
    assert not s.suite_inteira


def test_aresta_tardia_conta_uma_vez_so(repo):
    base, sha = _mudar(repo, "pkg/d.py", "def g():\n    import pkg.e\n    return 1\n")
    assert "tests/test_c.py" in pg.selecionar(repo, base, sha, max_tardias=1).testes
    assert "tests/test_c.py" not in pg.selecionar(repo, base, sha, max_tardias=0).testes
    base, sha = _mudar(repo, "pkg/e.py", "Y = 3\n")            # c →(tardia) d →(tardia) e: duas tardias
    assert "tests/test_c.py" not in pg.selecionar(repo, base, sha, max_tardias=1).testes


def test_config_citada_por_caminho_puxa_quem_le(repo):
    base, sha = _mudar(repo, "config/x.yaml", "rotina: pkg.f\n")
    assert "tests/test_cfg.py" in pg.selecionar(repo, base, sha).testes


def test_import_de_fixture_so_pesa_para_quem_pede_a_fixture(repo):
    base, sha = _mudar(repo, "pkg/f.py", "Z = 4\n")
    s = set(pg.selecionar(repo, base, sha).testes)
    assert "tests/test_usa_fix.py" in s
    assert "tests/test_a.py" not in s and "tests/test_isolado.py" not in s


def test_conftest_mudado_roda_a_suite_inteira(repo):
    base, sha = _mudar(repo, "tests/conftest.py", ARQUIVOS["tests/conftest.py"] + "\n# x\n")
    s = pg.selecionar(repo, base, sha)
    assert s.suite_inteira and "tests/test_isolado.py" in s.testes


def test_modulo_apagado_ainda_importado_e_escolhido(repo):
    base, sha = _mudar(repo, "pkg/g.py", None)
    assert "tests/test_g.py" in pg.selecionar(repo, base, sha).testes


def test_leitura_de_texto_nao_propaga_o_que_o_arquivo_lido_importa(repo):
    base, sha = _mudar(repo, "pkg/b.py", "X = 11\n")          # a importa b; leitor só LÊ o texto de a
    assert "tests/test_leitor.py" not in pg.selecionar(repo, base, sha).testes
    base, sha = _mudar(repo, "pkg/a.py", "import pkg.b\nA = 1\n")
    assert "tests/test_leitor.py" in pg.selecionar(repo, base, sha).testes


def test_catracas_e_transversais_sempre_e_tmp_path_nao_e_varredura(repo):
    base, sha = _mudar(repo, "pkg/e.py", "Y = 9\n")
    s = set(pg.selecionar(repo, base, sha).testes)
    assert SEMPRE <= s
    assert "tests/test_tmp.py" not in s and "tests/test_isolado.py" not in s
    assert "tests/test_nao_existe.py" not in s                 # CATRACAS do portão só entra se existe no commit


def test_falha_de_24_11_teste_que_varre_o_repo_pega_constante_nova(repo):
    """00b63d5b: constante nova num módulo que nenhum teste importa; só o teste que VARRE o repo acusa."""
    base, sha = _mudar(repo, "pkg/varredor.py", "import pathlib\nTETO = 0.25\nTETO_NOVO = 0.5\n")
    assert "tests/test_varre.py" in pg.selecionar(repo, base, sha).testes


def test_falha_de_24_11_importador_alem_do_sexto_do_grep(repo):
    """1008786e: o v1 pegava só os 6 primeiros do `grep -rl`; o grafo pega TODO importador."""
    for i in range(9):
        (repo / f"tests/test_imp_{i}.py").write_text("from pkg import f\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "importadores")
    base, sha = _mudar(repo, "pkg/f.py", "Z = 5\n")
    s = set(pg.selecionar(repo, base, sha).testes)
    assert {f"tests/test_imp_{i}.py" for i in range(9)} <= s


def test_grafo_vem_do_commit_nao_da_arvore_de_trabalho(repo):
    base, sha = _mudar(repo, "pkg/b.py", "X = 12\n")
    (repo / "tests/test_isolado.py").write_text("import pkg.b\n", encoding="utf-8")   # WIP não commitado
    assert "tests/test_isolado.py" not in pg.selecionar(repo, base, sha).testes


def test_cache_por_blob_reaproveita_e_e_podado(repo):
    base, sha = _mudar(repo, "pkg/b.py", "X = 13\n")
    pg.selecionar(repo, base, sha)
    assert pg.CACHE.exists()
    blobs = pg._carregar_cache()
    assert blobs and all("imp" in v for v in blobs.values())
    antes = pg.CACHE.stat().st_mtime_ns
    pg.selecionar(repo, base, sha)                              # nada novo: não regrava
    assert pg.CACHE.stat().st_mtime_ns == antes


def test_string_que_parece_modulo_mas_e_arquivo_nao_liga(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CACHE", tmp_path / "c.json")
    assert pg.extrair_py(b"DB = 'compliance.db'\n")["str"] == ["compliance.db"]
    r = tmp_path / "r"
    (r / "tests").mkdir(parents=True)
    (r / "compliance.py").write_text("", encoding="utf-8")
    (r / "tests/test_db.py").write_text("DB = 'compliance.db'\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", str(r))
    _git(r, "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "b")
    g = pg.montar(r, "HEAD")
    assert "compliance.py" not in g.deps["tests/test_db.py"]


def test_arquivo_que_nao_compila_vira_no_sem_aresta():
    info = pg.extrair_py(b"def (:\n")
    assert info["invalido"] and info["imp"] == []
