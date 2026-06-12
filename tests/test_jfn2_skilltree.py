# -*- coding: utf-8 -*-
"""Testes da Skilltree (JFN 2.0, Onda 1): registro vivo de capabilities.yaml.

Cobre os criterios de aceite do spec (docs/refs/JFN-SPEC-SKILLTREE-YODA): render por
dominio, detalhe, reload com diff, fail-safe (YAML invalido mantem estado anterior),
validate (reusa o validador unico) e tool_specs (so PRONTO).
"""
from __future__ import annotations

import textwrap

import pytest


def _registry_fresh():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    return st


def test_reload_popula_estado_e_diff():
    """reload() carrega capacidades, calcula sha e retorna o diff add/rm."""
    st = _registry_fresh()
    r = st.reload()
    assert st.capacidades, "deveria carregar capacidades"
    assert len(r["sha"]) == 12
    assert r["total"] == len(st.capacidades)
    # 2o reload identico => sem add/rm
    assert r["add"] == [] and r["rm"] == []


def test_cinco_skills_sistema_presentes():
    """As 5 capacidades de dominio 'sistema' da skilltree existem (aceite §5 do spec)."""
    st = _registry_fresh()
    esperadas = {"skills", "skill_detalhe", "skills_reload", "skills_sync", "skills_validate"}
    assert esperadas <= set(st.capacidades), f"faltam: {esperadas - set(st.capacidades)}"
    for cid in esperadas:
        assert st.capacidades[cid]["dominio"] == "sistema"


def test_render_agrupa_por_dominio_e_filtra():
    """/skills agrupa por dominio; /skills <filtro> reduz (aceite 1)."""
    st = _registry_fresh()
    full = st.render()
    assert "*SISTEMA*" in full and "Skilltree" in full
    so_sistema = st.render("sistema")
    assert "skills_reload" in so_sistema
    # filtro que nao casa nada
    assert "Nenhuma skill" in st.render("zzz_nao_existe_zzz")


def test_detalhe_skill_e_inexistente():
    """/skill <id> mostra rota/args/quando usar; id inexistente => mensagem amigavel (aceite 2)."""
    st = _registry_fresh()
    d = st.detalhe("skills_reload")
    assert "skills_reload" in d and "Quando usar" in d and "PRONTO" in d
    assert "nao existe" in st.detalhe("nao_existe_999")


def test_validate_reusa_validador_unico():
    """validate() delega ao validador unico e o YAML atual e valido (aceite 6)."""
    st = _registry_fresh()
    assert st.validate() == []


def test_tool_specs_ignora_ondas():
    """tool_specs() inclui PRONTO e exclui capacidades em ONDA N."""
    st = _registry_fresh()
    specs = st.tool_specs()
    nomes = {s.get("function", {}).get("name") or s.get("name") for s in specs}
    # 'trace' esta em ONDA 0 -> nao deve aparecer; 'skills' (PRONTO) deve
    assert "skills" in nomes
    assert "trace" not in nomes


def test_fail_safe_yaml_invalido_mantem_estado(tmp_path):
    """INVARIANTE: YAML novo invalido => reload levanta e o estado anterior e preservado.

    E o coracao da skilltree: nunca derrubar o roteador por um YAML quebrado."""
    from compliance_agent.skilltree import SkillTree

    bom = tmp_path / "cap.yaml"
    bom.write_text(textwrap.dedent(
        """
        meta: {versao: "9.9"}
        capacidades:
          - {id: x1, agente: jfn, dominio: teste, tipo: http, status: PRONTO, descricao: ok}
        """
    ), encoding="utf-8")
    st = SkillTree(path=bom)
    st.reload()
    assert set(st.capacidades) == {"x1"}
    sha_bom = st.sha

    # agora corrompe o arquivo e tenta recarregar
    bom.write_text(": : : [[[ invalido", encoding="utf-8")
    with pytest.raises(Exception):
        st.reload()
    # estado anterior intacto
    assert set(st.capacidades) == {"x1"}
    assert st.sha == sha_bom


def test_rotas_http_skilltree():
    """Onda 13 (parte JFN): /api/skills|skill|skills/reload|skills/validate respondem (o /skills do Yoda chama estas)."""
    import warnings
    warnings.filterwarnings("ignore")
    from fastapi.testclient import TestClient
    import server

    c = TestClient(server.app)
    assert c.get("/api/skills").json()["ok"] is True
    assert "SISTEMA" in c.get("/api/skills", params={"filtro": "sistema"}).json()["texto"]
    assert c.get("/api/skill", params={"id": "skills_reload"}).json()["ok"] is True
    assert c.post("/api/skills/reload").json()["ok"] is True
    assert c.get("/api/skills/validate").json()["ok"] is True


def test_id_duplicado_e_rejeitado(tmp_path):
    """_parse rejeita id duplicado (contrato unico, sem ambiguidade no roteador)."""
    from compliance_agent.skilltree import SkillTree

    p = tmp_path / "dup.yaml"
    p.write_text(textwrap.dedent(
        """
        capacidades:
          - {id: a, agente: jfn, dominio: t, tipo: http, status: PRONTO, descricao: a}
          - {id: a, agente: jfn, dominio: t, tipo: http, status: PRONTO, descricao: a2}
        """
    ), encoding="utf-8")
    st = SkillTree(path=p)
    with pytest.raises(ValueError):
        st.reload()


def test_render_menu_curado_e_enxuto():
    """/lista (render_menu) é CURADO e enxuto (não despeja as ~47 capacidades — UX, pedido do dono). O
    catálogo COMPLETO fica no /skills (render). Atualizado 2026-06-09."""
    from compliance_agent.skilltree import SkillTree
    st = SkillTree()
    st.reload()
    m = st.render_menu()
    n_itens = m.count("\n• ")
    assert 6 <= n_itens <= 24                          # curado (grupos + exemplos), não as ~47 prontas; cresceu c/ novas capacidades
    assert "Relatório de um fornecedor" in m           # linguagem humana, não id técnico
    assert "/skills" in m                              # aponta o catálogo completo
    assert "GET /api" not in m                         # sem clutter técnico de rota
    assert st.render().count("`") > 40                 # o /skills (render) segue com o catálogo inteiro
