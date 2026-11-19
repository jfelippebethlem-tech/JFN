# -*- coding: utf-8 -*-
"""Paleta única por órgão/UG (config/cores_orgaos.yaml) — grafo do Obsidian e galáxia do painel."""
import json
import re

from compliance_agent import cores_orgaos as co

NOMES = {"180100": "Secretaria de Estado de Educacao", "133100": "ITERJ — Instituto de Terras e Cartografia do ERJ",
         "999900": "Órgão Qualquer do Estado"}


def test_paleta_e_contrato_principais_distintas_e_resto_estavel():
    cfg = co.carregar()
    assert len(cfg["principais"]) <= len(cfg["paleta"]) and len(set(cfg["paleta"])) == len(cfg["paleta"])
    principais = [co.cor(u) for u in cfg["principais"]]
    assert len(set(principais)) == len(principais)
    assert co.cor("180100") == cfg["paleta"][cfg["principais"].index("180100")]
    assert co.cor("ug:180100") == co.cor("180100")                    # a galáxia chama pelo aglomerado
    assert co.cor("999900") == co.cor("999900") and re.fullmatch(r"#[0-9A-F]{6}", co.cor("999900"))
    assert co.cor("999900") != co.cor("999901")
    for vazio in ("", None, "sem:orgao", "vault:dossies", "indeterminado"):
        assert co.cor(vazio) == cfg["indeterminado"]


def test_slug_usa_sigla_curada_ou_do_nome_canonico_e_nunca_inventa():
    assert co.slug_orgao("180100", NOMES) == "seeduc"
    assert co.slug_orgao("133100", NOMES) == "iterj"
    assert co.slug_orgao("999900", NOMES) == "orgao-qualquer-do-estado"
    assert co.slug_orgao("555555", NOMES) == "indeterminado" and co.slug_orgao("", NOMES) == "indeterminado"


def test_marcar_nota_poe_tags_e_propriedades_sem_tocar_no_resto_e_e_idempotente():
    nota = "---\ntipo: caso\ntags: [caso, tac]\nresumo: x\n---\n# corpo\n#ug/000000 no corpo fica\n"
    m = co.marcar_nota(nota, "180100", NOMES)
    assert "tags: [caso, tac, ug/180100, orgao/seeduc]" in m and 'ug: "180100"' in m
    assert "orgao: Secretaria de Estado de Educacao" in m and m.endswith("# corpo\n#ug/000000 no corpo fica\n")
    assert co.marcar_nota(m, "180100", NOMES) == m
    assert co.marcar_nota(m, "133100", NOMES) == m                    # a UG declarada na nota vence a lida de fora
    troca = co.marcar_nota(m.replace('ug: "180100"', 'ug: "133100"'), None, NOMES)   # corrigiu a UG: a tag antiga sai
    assert "ug/180100" not in troca and "orgao/iterj" in troca
    assert co.marcar_nota("sem frontmatter", "180100", NOMES) is None


def test_marcar_nota_respeita_ug_do_autor_lista_em_bloco_e_desconhecido():
    autor = '---\nug: "133100"\norgao: ITERJ\ntags:\n  - caso\n  - ug/999999\n# jfn:propriedades — x\ncnpj:\n# jfn:propriedades:fim\n---\ncorpo\n'
    m = co.marcar_nota(autor, None, NOMES)                            # None = usar a UG que a nota já declara
    assert "  - caso\n  - ug/133100\n  - orgao/iterj\n" in m and "ug/999999" not in m
    assert m.count("ug:") == 1 and "orgao: ITERJ\n" in m             # chave do autor não é repetida nem trocada
    sem = co.marcar_nota("---\ntipo: caso\nug:\n# jfn:propriedades — x\n# jfn:propriedades:fim\n---\nc\n", None, NOMES)
    assert "tags: [orgao/indeterminado]\n# jfn:propriedades — x" in sem and "ug/" not in sem


def test_grupos_do_grafo_principais_primeiro_e_cor_igual_a_da_paleta():
    g = co.grupos_obsidian({"999900", "180100", "296100"})
    assert [x["query"] for x in g] == ["tag:#ug/296100", "tag:#ug/180100", "tag:#ug/999900", "tag:#orgao/indeterminado"]
    assert g[1]["color"] == {"a": 1, "rgb": int(co.cor("180100")[1:], 16)}


def test_aplicar_vault_marca_casos_e_grava_grafo_preservando_o_resto(tmp_path):
    (tmp_path / "casos").mkdir()
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / "casos" / "a.md").write_text('---\ntipo: caso\nug: "180100"\ntags: [caso]\n---\nx\n', encoding="utf-8")
    (tmp_path / "casos" / "b.md").write_text("---\ntipo: caso\ntags: [caso]\n---\nx\n", encoding="utf-8")
    (tmp_path / ".obsidian" / "graph.json").write_text(json.dumps({"scale": 0.5, "colorGroups": []}), encoding="utf-8")
    r = co.aplicar_vault(tmp_path, NOMES, pastas=("casos",), idade_min_s=0)
    assert r == {"notas": 2, "marcadas": 2, "indeterminadas": 1, "grupos": 2}
    assert "orgao/indeterminado" in (tmp_path / "casos" / "b.md").read_text(encoding="utf-8")
    grafo = json.loads((tmp_path / ".obsidian" / "graph.json").read_text(encoding="utf-8"))
    assert grafo["scale"] == 0.5 and grafo["colorGroups"][0]["query"] == "tag:#ug/180100"
    assert co.aplicar_vault(tmp_path, NOMES, pastas=("casos",), idade_min_s=0)["marcadas"] == 0
