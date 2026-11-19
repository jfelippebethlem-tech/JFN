# -*- coding: utf-8 -*-
"""Ponte automelhoria/perícias → segundo cérebro (docs/ARQUITETURA-SEGUNDO-CEREBRO.md)."""
import json
import sqlite3

import pytest

from compliance_agent import cerebro_compartilhado as cerebro
from compliance_agent import cerebro_ponte as ponte
from compliance_agent.autoaprimoramento import registro

LAUDO = {
    "processo": "SEI-030001/047970/2026", "tag": "030001_047970_2026", "agente": "lote_05",
    "lido": {"docs_total": 55, "docs_lidos": 49}, "objeto": "Avaliação externa da rede estadual",
    "credor": {"nome": "FUNDAÇÃO EXEMPLO", "cnpj": "42.270.181/0001-16"}, "valor_contratado": 65991471.08,
    "pago_ob": {"total": 10615873.23, "fonte": "siafe", "obs": [
        {"numero_ob": "2026OB08890", "ug": "180100", "valor": 8286819.57},
        {"numero_ob": "2026OB08888", "ug": "180100", "valor": 2329053.66}]},
    "achados_principais": [
        {"titulo": "Pagamento de 144 polos quando a contratada operou 137", "grau": "🔴", "valor_envolvido": 195714.12,
         "prova": "doc 37 — \"A estratégia logística utilizou 137 polos de distribuição\"", "porque": "x", "norma": "L4320 art. 63"},
        {"titulo": "Atesto sem data", "grau": "🟡", "prova": "doc 9 — \"trecho que não existe em lugar nenhum do processo\""}],
    "licitantes": [{"nome": "FUNDAÇÃO EXEMPLO", "cnpj": "42.270.181/0001-16", "venceu": True},
                   {"nome": "PERDEDORA LTDA", "cnpj": "11.222.333/0001-81", "venceu": False}],
    "cruzamentos": [{"tipo": "outros_casos", "achado": "ver vault/casos/cesgranrio-dispensa-art24-xiii.md", "fonte": "vault"}],
    "aprendizado": "Reserva técnica de 5% pensada para material não se multiplica sobre pessoas; sócio 123.456.789-09 citado.",
}
CORPUS = "RELATÓRIO\nA estratégia   logística utilizou 137 polos\nde distribuição em todo o estado."


def test_limpar_mascara_cpf_e_email_e_preserva_cnpj():
    t = ponte.limpar("sócio 123.456.789-09 (***.456.789-**), fulano@x.gov.br, CNPJ 42.270.181/0001-16")
    assert "123.456.789-09" not in t and "456.789" not in t and "@" not in t
    assert "42.270.181/0001-16" in t
    assert cerebro.recusar(t) is None


def test_citacao_literal_ignora_quebra_de_linha_e_exige_trecho_longo():
    n = ponte.normalizar(CORPUS)
    assert ponte.citacao_conferida('doc 37 — "A estratégia logística utilizou 137 polos de distribuição"', n) is True
    assert ponte.citacao_conferida('doc 37 — "utilizou 137 polos […] em todo o estado. E mais um trecho inventado aqui"', n) is False
    assert ponte.citacao_conferida('doc 1 — "137 polos"', n) is None        # curta demais: não prova nada
    assert ponte.citacao_conferida("sem aspas", n) is None


def test_conferir_gradua_nivel_pela_citacao_e_confere_ob_no_siafe():
    siafe = {("2026OB08890", "180100"): [8286819.57], ("2026OB08888", "180100"): [1.0]}
    c = ponte.conferir(LAUDO, CORPUS, lambda n, ug: siafe.get((n, ug), []))
    assert c["achados"] == [True, False]
    assert (c["nivel"], c["ob_total"], c["ob_ok"]) == (2, 2, 1)
    sem_fonte = ponte.conferir(LAUDO, None, None)
    assert sem_fonte["nivel"] == 1 and sem_fonte["achados"] == [None, None] and sem_fonte["ob_ok"] is None


def test_fatos_do_laudo_so_afirma_achado_conferido_e_indexa_entidades():
    c = ponte.conferir(LAUDO, CORPUS, None)
    fatos = ponte.fatos_do_laudo(LAUDO, c)
    f = {x["chave"]: x for x in fatos}
    lau = f["pericia-agente:030001_047970_2026"]
    assert "144 polos" in lau["texto"] and "Atesto sem data" not in lau["texto"]
    assert "nível 2" in lau["texto"] and "1 achado(s) sem conferência por código" in lau["texto"]
    assert ("cnpj", "42270181000116", "credor") in lau["entidades"]
    assert ("cnpj", "11222333000181", "licitante perdedor") in lau["entidades"]
    assert ("processo", "030001/047970/2026", "processo") in lau["entidades"]
    assert ("ug", "180100", "ug pagadora") in lau["entidades"]
    lic = f["licao-pericia:030001_047970_2026"]
    assert lic["kind"] == "procedural" and "CANDIDATA" in lic["texto"] and "123.456.789-09" not in lic["texto"]
    assert all(cerebro.recusar(x["texto"]) is None for x in fatos)


def test_laudo_sem_citacao_conferida_nao_leva_achado_ao_cerebro():
    c = ponte.conferir(LAUDO, "outro texto qualquer do processo, sem relação", None)
    lau = ponte.fatos_do_laudo(LAUDO, c)[0]
    assert c["nivel"] == 1 and "144 polos" not in lau["texto"] and "nível 1" in lau["texto"]


def _auto(tmp_path):
    con = sqlite3.connect(tmp_path / "auto.db")
    registro.preparar(con)
    return con


def test_veredito_do_portao_vira_fato_e_mudanca_de_status_vira_correcao(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_AUTOAPRIMORAMENTO_DIR", str(tmp_path))
    con = _auto(tmp_path)
    ch = registro.registrar(con, {"tipo": "rubrica", "licoes": ["ob_existe_no_siafe"], "filtros": []}, "agentes: teste")
    antes = {x["chave"]: x for x in ponte.fatos_da_automelhoria(con)}[f"autoaprimoramento:{ch}"]
    assert "CANDIDATO" in antes["texto"]
    registro.mover(con, ch, "reprovado", "reprovado no portão — R4 melhora: 46 → 46", "portao")
    depois = {x["chave"]: x for x in ponte.fatos_da_automelhoria(con)}[f"autoaprimoramento:{ch}"]
    assert "REPROVADO" in depois["texto"] and "R4 melhora" in depois["texto"] and "portao" in depois["texto"]
    assert depois["texto"] != antes["texto"]
    reg = sqlite3.connect(tmp_path / "prop.db")
    reg.execute(cerebro.DDL)
    assert cerebro.registrar(antes["chave"], antes["texto"], antes["kind"], con=reg) == "novo"
    assert cerebro.registrar(depois["chave"], depois["texto"], depois["kind"], con=reg) == "corrigido"   # → supersedes


def test_sincronizar_grava_registro_entidades_e_vault_e_e_idempotente(tmp_path, monkeypatch):
    laudos, vault, arq = tmp_path / "pericia_agentes", tmp_path / "vault", tmp_path / "sei_arquivo"
    (arq / LAUDO["tag"] / "texto").mkdir(parents=True)
    (arq / LAUDO["tag"] / "texto" / "037.txt").write_text(CORPUS, encoding="utf-8")
    laudos.mkdir()
    vault.mkdir()
    (laudos / f"{LAUDO['tag']}.json").write_text(json.dumps(LAUDO, ensure_ascii=False), encoding="utf-8")
    outro = {**LAUDO, "tag": "030001_000001_2025", "processo": "SEI-030001/000001/2025", "achados_principais": [],
             "credor": {"nome": "PERDEDORA LTDA", "cnpj": "11.222.333/0001-81"}, "licitantes": [], "aprendizado": ""}
    (laudos / "030001_000001_2025.json").write_text(json.dumps(outro, ensure_ascii=False), encoding="utf-8")
    (laudos / "lote_01.json").write_text("[]", encoding="utf-8")
    (laudos / "quebrado.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(ponte, "DATA", tmp_path)
    monkeypatch.setattr(ponte, "VAULT", vault)
    monkeypatch.setenv("JFN_AUTOAPRIMORAMENTO_DIR", str(tmp_path / "auto"))
    (tmp_path / "auto").mkdir()
    _auto(tmp_path / "auto").close()
    con = sqlite3.connect(tmp_path / "prop.db")
    con.execute(cerebro.DDL)
    r = ponte.sincronizar(con=con, ob_siafe=None)
    assert r["laudos"] == 2 and r["nivel2"] == 1 and r["ilegiveis"] == ["quebrado.json"]
    assert r["registro"]["novo"] == 4                     # 2 laudos + 1 lição + 1 versão (campeão de partida)
    nota = (vault / "jfn" / "pericias-agente" / f"{LAUDO['tag']}.md").read_text(encoding="utf-8")
    assert "tipo: pericia-agente" in nota and "[[casos/cesgranrio-dispensa-art24-xiii]]" in nota
    assert "123.456.789-09" not in nota and "nível 2" in nota
    assert 'ug: "180100"' in nota and "ug/180100" in nota and "orgao/seeduc" in nota     # cor por órgão no grafo
    indice = (vault / "jfn" / "pericias-agente.md").read_text(encoding="utf-8")
    assert "11.222.333/0001-81" in indice and "2 processos" in indice          # perdedora num, credora no outro
    assert "rubrica_v1" in (vault / "jfn" / "automelhoria-licoes.md").read_text(encoding="utf-8")
    achou = ponte.entidade("11.222.333/0001-81", con=con)
    assert {(x["chave"], x["papel"]) for x in achou} == {("pericia-agente:030001_047970_2026", "licitante perdedor"),
                                                         ("pericia-agente:030001_000001_2025", "credor")}
    (laudos / "030001_000002_2025.json").write_text(json.dumps({**outro, "tag": "030001_000002_2025"}), encoding="utf-8")
    assert ponte.sincronizar(con=con, ob_siafe=None, max_novos=0)["adiados"] == 1       # sem conferir, não registra
    (laudos / "030001_000002_2025.json").unlink()
    de_novo = ponte.sincronizar(con=con, ob_siafe=None)
    assert de_novo["registro"] == {"novo": 0, "corrigido": 0, "igual": 4, "recusado": 0} and de_novo["notas_escritas"] == 0


def test_whatsapp_nunca_entra(tmp_path):
    with pytest.raises(ValueError):
        ponte.fatos_do_laudo({**LAUDO, "aprendizado": "visto no WhatsApp do grupo"}, ponte.conferir(LAUDO, CORPUS, None))
