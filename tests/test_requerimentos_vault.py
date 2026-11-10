"""Aba Requerimentos: leitura dos requerimentos sugeridos do vault (frontmatter com listas, pasta vazia, nota torta)."""
from compliance_agent import requerimentos_vault as rv

_BOM = """---
id: REQ-1
titulo: Sindicância e TAC
destinatario: Fundação X
caso: "[[casos/caso-a]]"
status: minuta
data_sugestao: 2026-11-09
prioridade: alta
pedidos:
  - primeiro pedido
  - "segundo: com dois-pontos"
fundamento: art. 101 da CE
pendencias:
  - R1 conferir dispositivo
minuta: casos/minuta-a.md
origem: casos/caso-a.md#L10
---
corpo livre
"""


def _req(d, nome, txt):
    (d / f"{nome}.md").write_text(txt, encoding="utf-8")


def _vault(tmp_path, monkeypatch):
    pasta = tmp_path / "requerimentos"
    pasta.mkdir()
    monkeypatch.setattr(rv, "VAULT_REQ", pasta)
    return pasta


def test_lista_campos_e_listas_do_frontmatter(tmp_path, monkeypatch):
    pasta = _vault(tmp_path, monkeypatch)
    _req(pasta, "a", _BOM)
    _req(pasta, "b", "---\nid: REQ-2\ntitulo: Outro\ndestinatario: Órgão Y\nstatus: sugerido\nprioridade: média\n"
                     "pedidos:\n  - um\n---\n")
    r = rv.listar()
    assert r["ok"] and r["total"] == 2 and r["por_status"] == {"minuta": 1, "sugerido": 1}
    a = next(i for i in r["itens"] if i["slug"] == "a")
    assert a["id"] == "REQ-1" and a["destinatario"] == "Fundação X" and a["prioridade"] == "alta"
    assert a["pedidos"] == ["primeiro pedido", "segundo: com dois-pontos"]
    assert a["pendencias"] == ["R1 conferir dispositivo"] and a["fundamento"] == "art. 101 da CE"
    assert a["caso"] == "caso-a"                      # o wikilink vira o slug que a aba Casos abre
    assert a["minuta"] == "casos/minuta-a.md" and a["origem"] == "casos/caso-a.md#L10"
    assert a["problemas"] == []


def test_pasta_vazia_nao_e_erro(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)
    assert rv.listar() == {"ok": True, "total": 0, "por_status": {}, "itens": []}


def test_pasta_inexistente_responde_sem_excecao(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "VAULT_REQ", tmp_path / "nao-existe")
    r = rv.listar()
    assert r["ok"] is False and "indisponível" in r["erro"]


def test_frontmatter_malformado_nao_derruba_e_fica_marcado(tmp_path, monkeypatch):
    pasta = _vault(tmp_path, monkeypatch)
    _req(pasta, "bom", _BOM)
    _req(pasta, "sem-fm", "só texto, sem frontmatter\n")
    _req(pasta, "aberto", "---\ntitulo: nunca fecha\nstatus: sugerido\n")
    _req(pasta, "status-torto", "---\ntitulo: T\ndestinatario: D\nstatus: enviado ontem\npedidos: texto solto\n"
                                "  - item órfão\n: sem chave\n---\n")
    (pasta / "binario.md").write_bytes(b"\xff\xfe\x00---")
    r = rv.listar()
    assert r["ok"] and r["total"] == 5
    por = {i["slug"]: i for i in r["itens"]}
    assert por["bom"]["problemas"] == []
    for s in ("sem-fm", "aberto", "binario"):
        assert por[s]["status"] == "indefinido" and por[s]["problemas"], s
        assert por[s]["pedidos"] == [] and por[s]["pendencias"] == []
    t = por["status-torto"]
    assert t["status"] == "indefinido" and any("status" in p for p in t["problemas"])   # nunca vira "sugerido" por omissão
    assert t["titulo"] == "T" and isinstance(t["pedidos"], list)


def test_minuta_so_abre_markdown_dentro_do_vault(tmp_path, monkeypatch):
    pasta = _vault(tmp_path, monkeypatch)
    (tmp_path / "casos").mkdir()
    (tmp_path / "casos" / "minuta-a.md").write_text("---\ntipo: minuta\n---\n# MINUTA\n\ntexto", encoding="utf-8")
    (tmp_path.parent / "fora.md").write_text("segredo", encoding="utf-8")
    _req(pasta, "a", _BOM)
    _req(pasta, "foge", _BOM.replace("casos/minuta-a.md", "../fora.md"))
    _req(pasta, "pdf", _BOM.replace("casos/minuta-a.md", "~/JFN/reports/x.pdf"))
    _req(pasta, "sem", "---\ntitulo: T\nstatus: sugerido\n---\n")
    r = rv.minuta("a")
    assert r["ok"] and r["markdown"].startswith("# MINUTA")
    for slug in ("foge", "pdf", "sem", "nao-existe", "../../etc/passwd", ""):
        assert rv.minuta(slug)["ok"] is False, slug


def test_rotas_respondem(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from rotas import acervo
    pasta = _vault(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(acervo.router)
    cli = TestClient(app)
    assert cli.get("/api/requerimentos").json()["total"] == 0          # pasta vazia: 200, lista vazia
    _req(pasta, "a", _BOM)
    r = cli.get("/api/requerimentos")
    assert r.status_code == 200 and r.json()["itens"][0]["id"] == "REQ-1"
    assert cli.get("/api/requerimentos/minuta", params={"slug": "a"}).status_code == 404   # minuta citada não existe
    monkeypatch.setattr(rv, "VAULT_REQ", tmp_path / "nao-existe")
    assert cli.get("/api/requerimentos").status_code == 503
