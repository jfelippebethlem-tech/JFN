# -*- coding: utf-8 -*-
"""Reorganização automática do índice de memória (tools/memoria_indice.py). Defeito medido em 20/11/2026: MEMORY.md
com 213 linhas para um limite de 200 — o carregamento corta o fim, justamente as entradas mais NOVAS.
Controles: nada some do índice, nenhum arquivo de memória é tocado, gancho que só existe no índice não é rebaixado,
índice dentro do limite não é mexido, e a aplicação recusa resultado que perca referência."""
from pathlib import Path

import pytest

from tools import memoria_indice as M


def _pasta(tmp_path: Path, n_gancho: int) -> Path:
    p = tmp_path / "memory"
    p.mkdir()
    linhas = ["# Memory Index", "", "> Índice: cada `slug` = `slug.md` nesta pasta.", "",
              "## Regras e diretrizes permanentes", "- `regra-um` · `regra-dois`", "",
              "## SEI", "- `sei-busca` · [Auditoria X](../../../vault/aprendizados/auditoria-x.md)", "",
              "## Infra, IA e ecossistema", "- `vm-compartilhada`", ""]
    for slug in ("regra-um", "regra-dois", "sei-busca", "vm-compartilhada"):
        (p / f"{slug}.md").write_text(f"---\nname: {slug}\ndescription: descrição de {slug}\n---\ncorpo\n", encoding="utf-8")
    for i in range(n_gancho):
        tema = ("sei-captura", "yoda-voz", "siafe-cota", "decisao")[i % 4]
        slug = f"{tema}-{i:03d}"
        linhas.append(f"- `{slug}` — gancho {i} escrito no índice, com data e detalhe que também está no arquivo")
        (p / f"{slug}.md").write_text(f"---\nname: {slug}\ndescription: descrição {i}\n---\ncorpo {i}\n", encoding="utf-8")
    (p / "MEMORY.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return p


def test_indice_acima_do_limite_volta_para_o_alvo_sem_perder_referencia(tmp_path):
    p = _pasta(tmp_path, 215)
    antes = (p / "MEMORY.md").read_text(encoding="utf-8")
    assert M.estado(p)["linhas"] > M.LIMITE
    r = M.reorganizar(p)
    novo = r["texto"]
    assert len(novo.splitlines()) <= M.ALVO
    assert M.referencias(antes) <= M.referencias(novo), "nenhum slug nem link pode sumir do índice"
    assert M.conferir(antes, novo) == []
    # os mais NOVOS (fim do arquivo) mantêm o gancho; os mais antigos viram slug no TEMA deles
    assert "- `decisao-211` — gancho 211" in novo and "gancho 0 " not in novo
    sei = novo.split("## SEI")[1].split("\n## ")[0]
    assert "`sei-captura-000`" in sei and "`yoda-voz-001`" not in sei
    assert "`yoda-voz-001`" in novo.split("## Infra, IA e ecossistema")[1].split("\n## ")[0]
    assert all(len(l) <= M.LARGURA for l in novo.splitlines() if l not in antes.splitlines())
    # o gancho rebaixado não se perde: vai para o arquivo-razão, com o slug
    assert "gancho 0 escrito no índice" in r["ganchos_arquivados"] and "sei-captura-000" in r["ganchos_arquivados"]


def test_controle_negativo_indice_dentro_do_limite_nao_e_mexido(tmp_path):
    p = _pasta(tmp_path, 30)
    antes = (p / "MEMORY.md").read_text(encoding="utf-8")
    r = M.reorganizar(p)
    assert r["texto"] == antes and r["rebaixados"] == []


def test_gancho_sem_arquivo_ou_sem_description_nao_e_rebaixado(tmp_path):
    p = _pasta(tmp_path, 215)
    (p / "sei-captura-000.md").unlink()                                              # o gancho é o único registro
    (p / "yoda-voz-001.md").write_text("sem cabeçalho\n", encoding="utf-8")
    novo = M.reorganizar(p)["texto"]
    assert "- `sei-captura-000` — gancho 0 " in novo and "- `yoda-voz-001` — gancho 1 " in novo
    assert len(novo.splitlines()) <= M.ALVO


def test_arquivo_de_memoria_fora_do_indice_entra_no_tema(tmp_path):
    p = _pasta(tmp_path, 215)
    (p / "sei-orfao.md").write_text("---\nname: sei-orfao\ndescription: nunca indexado\n---\nx\n", encoding="utf-8")
    assert "sei-orfao" in M.estado(p)["fora_do_indice"]
    novo = M.reorganizar(p)["texto"]
    assert "`sei-orfao`" in novo.split("## SEI")[1].split("\n## ")[0]


def test_aplicar_so_escreve_o_indice_guarda_copia_e_recusa_perda(tmp_path, monkeypatch):
    p = _pasta(tmp_path, 215)
    antes = (p / "MEMORY.md").read_text(encoding="utf-8")
    outros = {a.name: a.read_bytes() for a in p.glob("*.md") if a.name != "MEMORY.md"}
    r = M.aplicar(p)
    assert r["aplicado"] and len((p / "MEMORY.md").read_text(encoding="utf-8").splitlines()) <= M.ALVO
    assert Path(r["copia"]).read_text(encoding="utf-8") == antes
    assert {a.name: a.read_bytes() for a in p.glob("*.md") if a.name not in ("MEMORY.md", M.RAZAO)} == outros
    assert "gancho 0 escrito" in (p / M.RAZAO).read_text(encoding="utf-8")
    assert M.aplicar(p)["aplicado"] is False                                         # idempotente: já está no alvo
    # controle: resultado que perde referência é recusado e nada é escrito
    p2 = _pasta(tmp_path / "b", 215) if (tmp_path / "b").mkdir() is None else None
    antes2 = (p2 / "MEMORY.md").read_text(encoding="utf-8")
    monkeypatch.setattr(M, "_montar", lambda *a, **k: "# Memory Index\n")
    with pytest.raises(RuntimeError, match="perderia"):
        M.aplicar(p2)
    assert (p2 / "MEMORY.md").read_text(encoding="utf-8") == antes2 and not list(p2.glob("MEMORY.md.antes-*"))
