"""Resolvedor de credenciais (24/11/2026): acha nas máquinas/documento sem copiar nada."""
from compliance_agent import credenciais as C


def test_le_env_e_markdown_ultimo_valor_vence():
    txt = "# t\nFOO_KEY=a\nexport FOO_KEY='b'\n- **BAR_TOKEN**: `c`\n| X | y |\nVAZIA=\n"
    assert C.ler_texto("FOO_KEY", txt) == "b"
    assert C.ler_texto("BAR_TOKEN", txt) == "c"
    assert C.ler_texto("VAZIA", txt) is None
    assert C.ler_texto("NAO_EXISTE", txt) is None


def test_ordem_ambiente_depois_local_sem_remoto(tmp_path, monkeypatch):
    (tmp_path / "JFN").mkdir()
    (tmp_path / "JFN" / ".env").write_text("SO_LOCAL=um\n")
    (tmp_path / "CREDENCIAIS.md").write_text("- SO_DOC: dois\n")
    monkeypatch.setattr(C, "HOME", tmp_path)
    monkeypatch.setattr(C, "_cache", {})
    monkeypatch.setattr(C, "_local", lambda nome, home=tmp_path: C.__dict__["_local_orig"](nome, home))
    monkeypatch.setitem(C.__dict__, "_local_orig", lambda n, h: next(
        ((v, p.name) for p in C.arquivos_locais(h)
         if (v := C.ler_texto(n, p.read_text()))), None))
    monkeypatch.setenv("NO_AMBIENTE", "zero")
    assert C.obter("NO_AMBIENTE", remoto=False) == "zero"
    assert C.obter("SO_LOCAL", remoto=False) == "um"
    assert C.obter("SO_DOC", remoto=False) == "dois"
    assert C.obter("NENHUM", remoto=False) is None


def test_remoto_so_quando_local_falha(monkeypatch):
    monkeypatch.setattr(C, "_cache", {})
    monkeypatch.setattr(C, "_local", lambda nome, home=None: None)
    chamadas = []
    monkeypatch.setattr(C, "_remoto", lambda nome: chamadas.append(nome) or ("v", "vm1(x):.env"))
    monkeypatch.delenv("REMOTA_KEY", raising=False)
    assert C.obter("REMOTA_KEY") == "v"
    assert C.obter("REMOTA_KEY") == "v"      # cache: não pergunta de novo
    assert chamadas == ["REMOTA_KEY"]
    assert C.onde("REMOTA_KEY").startswith("vm1(")


def test_cli_onde_nunca_imprime_valor(monkeypatch, capsys):
    monkeypatch.setattr(C, "_cache", {})
    monkeypatch.setattr(C, "_local", lambda nome, home=None: ("segredo-xyz", "local:.env"))
    monkeypatch.delenv("CHAVE_X", raising=False)
    C.main(["onde", "CHAVE_X"])
    saida = capsys.readouterr().out
    assert "segredo-xyz" not in saida and "local:.env" in saida
