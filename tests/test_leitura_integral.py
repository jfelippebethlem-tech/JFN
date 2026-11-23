# -*- coding: utf-8 -*-
"""Leitura integral comprovada — piloto (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 1). Regras do dono (23/11/2026):
ler 100% do texto, nunca resumo de IA como substituto; fato só vale com citação literal conferida por código."""
import json

import pytest

from compliance_agent import leitura_integral as L


def _pasta(raiz, tag, docs):
    p = raiz / tag
    (p / "texto").mkdir(parents=True)
    man = []
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}_x.txt"
        (p / rel).write_text(texto, encoding="utf-8")
        man.append({"i": i, "titulo": titulo, "tipo": "despacho", "texto": rel, "chars": len(texto)})
    (p / "manifest.json").write_text(json.dumps({"processo": tag.replace("_", "/"), "docs": man}), encoding="utf-8")
    return p


# ── fatiamento: 100% do texto, sem cortar documento quando cabe ─────────────────────────────────────────
def test_fatias_cobrem_todo_o_texto_sem_cortar_documento_que_cabe(tmp_path):
    p = _pasta(tmp_path, "100001_000001_2025", [("Contrato (11111111)", "A" * 300), ("Nota (22222222)", "B" * 300),
                                                 ("Atesto (33333333)", "C" * 300)])
    fatias, cob = L.fatiar(p, alvo=700)
    assert [[d["doc_id"] for d in f["docs"]] for f in fatias] == [["sei:11111111", "sei:22222222"], ["sei:33333333"]]
    assert (cob["chars_existentes"], cob["chars_enviados"], cob["fracao"], cob["leitura"]) == (900, 900, 1.0, "integral")


def test_documento_maior_que_a_fatia_e_dividido_com_sobreposicao_e_nada_se_perde(tmp_path):
    paragrafos = "\n\n".join(f"parágrafo {k} " + "x" * 90 for k in range(30))
    p = _pasta(tmp_path, "100001_000002_2025", [("Planilha de medição (44444444)", paragrafos)])
    fatias, cob = L.fatiar(p, alvo=1000, sobreposicao=100)
    assert len(fatias) > 1 and cob["leitura"] == "integral"
    juntado = "".join(f["docs"][0]["texto"] for f in fatias)
    for k in range(30):
        assert f"parágrafo {k} " in juntado


# ── máscara reversível: CPF e conta nunca saem da VM ───────────────────────────────────────────────────
def test_mascara_cpf_e_conta_e_desfaz_localmente():
    t = "Pague a João, CPF 123.456.789-09, Agência 1234-5 Conta corrente nº 98765-4. CNPJ 12.345.678/0001-90."
    m, mapa = L.mascarar(t)
    assert "123.456.789-09" not in m and "98765-4" not in m and "[CPF_1]" in m and "[CONTA_1]" in m
    assert "12.345.678/0001-90" in m                                        # CNPJ é público: não mascara
    assert L.desmascarar(m, mapa) == t


# ── verificador de citação ─────────────────────────────────────────────────────────────────────────────
TXT = "O valor global do contrato é de R$ 483.333,33 (quatrocentos…),\n  pago   em 12 parcelas."


def test_citacao_literal_aceita_espacos_diferentes_e_recusa_inventada():
    ok = {"tipo": "valor", "valor": "483333.33", "citacao": "valor global do contrato é de R$ 483.333,33", "doc_id": "d"}
    assert L.verificar(ok, {"d": TXT})["estado"] == "VERIFICADO"
    esp = dict(ok, tipo="quantidade", valor="12", citacao="pago em 12 parcelas")   # quebra de linha/espaços
    assert L.verificar(esp, {"d": TXT})["estado"] == "VERIFICADO"
    inventada = dict(ok, citacao="valor global de R$ 500.000,00")
    assert L.verificar(inventada, {"d": TXT})["estado"] == "INDISPONIVEL"
    valor_fora = dict(ok, valor="999.00")                                  # citação existe, valor não está nela
    assert L.verificar(valor_fora, {"d": TXT})["estado"] == "INDISPONIVEL"
    doc_errado = dict(ok, doc_id="outro")
    assert L.verificar(doc_errado, {"d": TXT})["estado"] == "INDISPONIVEL"


def test_resposta_do_modelo_vira_fatos_verificados_e_json_quebrado_nao_vira_fato():
    resp = json.dumps({"fatos": [{"tipo": "valor", "valor": "483333.33", "doc_id": "d",
                                  "citacao": "R$ 483.333,33"},
                                 {"tipo": "cnpj", "valor": "11.111.111/0001-11", "doc_id": "d",
                                  "citacao": "CNPJ 11.111.111/0001-11"}]})
    fatos = L.interpretar(resp, {"d": TXT})
    assert [f["estado"] for f in fatos] == ["VERIFICADO", "INDISPONIVEL"]
    assert L.interpretar("isto não é json", {"d": TXT}) is None             # resposta inválida ≠ "sem fatos"


# ── projeção de custo antes de gastar ──────────────────────────────────────────────────────────────────
def test_projecao_de_custo_usa_o_preco_do_lote_e_conta_todas_as_fatias():
    pj = L.projetar([{"texto": "x" * 25_000}, {"texto": "y" * 25_000}], saida_tokens=1000)
    assert pj["fatias"] == 2 and pj["tokens_entrada"] >= 20_000 and pj["usd"] > 0
    assert pj["usd"] == pytest.approx(pj["usd_sem_lote"] / 2, abs=1e-6)


def test_planilha_vai_para_o_leitor_por_codigo_e_continua_na_cobertura(tmp_path):
    planilha = "\n".join(f"{k} | 1.234,{k % 100:02d} | 0,00" for k in range(3000))
    p = _pasta(tmp_path, "100001_000003_2025", [("Despacho (55555555)", "Encaminhe-se o processo. " * 20),
                                                 ("Planilha orçamentária (66666666)", planilha)])
    fatias, cob = L.fatiar(p)
    assert [d["doc_id"] for f in fatias for d in f["docs"]] == ["sei:55555555"]
    assert cob["docs_tabela"] == ["sei:66666666"] and cob["chars_tabela"] == len(planilha)
    assert cob["chars_enviados"] + cob["chars_tabela"] == cob["chars_existentes"]


# ── porta do lote (dono, 23/11/2026: "só entra no lote o que sabemos ser 100% correto e não duplicado") ──
def _man(p, **kw):
    m = json.loads((p / "manifest.json").read_text())
    m.update(kw)
    (p / "manifest.json").write_text(json.dumps(m))


def test_so_processo_com_captura_completa_passa_na_porta(tmp_path):
    p = _pasta(tmp_path, "100001_000004_2025", [("Contrato (11111111)", "texto " * 20)])
    assert L.portao(p) == (False, "captura não declarada completa")          # desconhecido ≠ completo
    _man(p, captura_completa=True, docs_faltantes=[{"i": 9}])
    assert L.portao(p) == (False, "documentos faltando na captura")
    _man(p, captura_completa=True, docs_faltantes=[])
    assert L.portao(p) == (True, "")


def test_texto_de_ocr_espera_confirmacao_e_duplicado_nao_reenvia(tmp_path):
    p = _pasta(tmp_path, "100001_000005_2025", [("Contrato (11111111)", "cláusula " * 20),
                                                 ("NF escaneada (22222222)", "valor 1.000,00 " * 10),
                                                 ("Cópia do contrato (33333333)", "cláusula " * 20)])
    m = json.loads((p / "manifest.json").read_text())
    m["docs"][1]["ocr"] = True
    m["docs"][1]["ocr_motor"] = "tesseract"
    (p / "manifest.json").write_text(json.dumps(m))
    fatias, cob = L.fatiar(p)
    assert [d["doc_id"] for f in fatias for d in f["docs"]] == ["sei:11111111"]      # 3º é cópia idêntica do 1º
    assert cob["docs_ocr_pendente"] == ["sei:22222222"] and cob["docs_duplicados"] == ["sei:33333333"]
    assert cob["chars_enviados"] + cob["chars_ocr_pendente"] + cob["chars_duplicado"] + cob["chars_tabela"] \
        == cob["chars_existentes"]
    sha_1 = fatias[0]["docs"][0]["sha"]
    fatias2, cob2 = L.fatiar(p, ja_lidos={sha_1})                                    # lido em lote anterior
    assert fatias2 == [] and cob2["docs_duplicados"] == ["sei:11111111", "sei:33333333"]


def test_data_por_extenso_confere_com_o_valor_normalizado():
    """Piloto 23/11: 220 fatos de data recusados por rigidez — 'Rio de Janeiro, 12 de junho de 2026' × '12/06/2026'."""
    txt = {"d": "Rio de Janeiro, 12 de junho de 2026. Publicado em 03/07/2026."}
    ok = {"tipo": "data", "valor": "12/06/2026", "doc_id": "d", "citacao": "Rio de Janeiro, 12 de junho de 2026"}
    assert L.verificar(ok, txt)["estado"] == "VERIFICADO"
    assert L.verificar(dict(ok, valor="2026-07-03", citacao="Publicado em 03/07/2026"), txt)["estado"] == "VERIFICADO"
    assert L.verificar(dict(ok, valor="13/06/2026"), txt)["estado"] == "INDISPONIVEL"      # dia errado
    assert L.verificar(dict(ok, valor="12/07/2026"), txt)["estado"] == "INDISPONIVEL"      # mês errado


def test_porta_por_processo_inteiro_ocr_ou_documento_sem_texto_barram_o_processo(tmp_path):
    """Dono 23/11: 'nos processos que temos certeza que o ocr, a extração, estão todos certos em tudo pra não ter que
    gastar duas vezes' — processo com qualquer pendência espera inteiro; o que entra é lido uma vez, por completo."""
    p = _pasta(tmp_path, "100001_000006_2025", [("Contrato (11111111)", "texto " * 20), ("NF (22222222)", "x " * 30)])
    _man(p, captura_completa=True, docs_faltantes=[])
    assert L.portao(p) == (True, "")
    m = json.loads((p / "manifest.json").read_text())
    m["docs"][1]["ocr_motor"] = "surya"
    (p / "manifest.json").write_text(json.dumps(m))
    assert L.portao(p) == (False, "documento de OCR ainda não confirmado")
    m["docs"][1].pop("ocr_motor")
    m["docs"].append({"i": 2, "titulo": "Anexo (33333333)", "tipo": "anexo"})       # sem texto capturado
    (p / "manifest.json").write_text(json.dumps(m))
    assert L.portao(p) == (False, "documento sem texto")


# ── leitor de tabela por código (Fase 5): 100% das linhas, citação = a própria linha ──────────────────────
def test_tabela_lida_por_codigo_extrai_toda_linha_com_numero_e_le_uma_vez_so(tmp_path, monkeypatch):
    monkeypatch.setattr(L.E, "RAIZ", tmp_path)
    con = L.E.conectar(tmp_path / "ev.db")
    con.executescript(L._DDL)
    def brl(k):
        return f"{k // 1000}.{k % 1000:03d}" if k >= 1000 else str(k)
    planilha = "\n".join(f"{k} | Item {k} | R$ {brl(k)},50 | 0,00" for k in range(1, 3001))
    p = _pasta(tmp_path, "100001_000007_2025", [("Despacho (55555555)", "Encaminhe-se. " * 20),
                                                 ("Planilha (66666666)", planilha)])
    r = L.ler_tabelas(con, p)
    assert r == {"tabelas": 1, "novas": 1, "linhas_com_numero": 3000}
    assert L.ler_tabelas(con, p)["novas"] == 0                                   # mesma tabela (sha): uma vez só
    lidas = L.tabelas_lidas(con)
    fatias, cob = L.fatiar(p, tabelas_lidas=lidas)
    assert cob["chars_tabela"] == 0 and cob["chars_tabela_lida"] == len(planilha) and cob["leitura"] == "integral"
    linhas = L.linhas_da_tabela(lidas_sha := next(iter(lidas)))
    assert len(linhas) == 3000 and linhas[-1]["citacao"] == "3000 | Item 3000 | R$ 3.000,50 | 0,00"
    assert ("valor", "3000.50") in {(n["tipo"], n["norma"]) for n in linhas[-1]["numeros"]}
    assert lidas_sha


# ── braço da ASSINATURA (dono: "mistura API com teto + assinatura"; balde da API fechou em 23/11) ──────
def test_assinatura_le_processo_inteiro_e_so_marca_lido_se_todas_as_fatias_voltaram(tmp_path, monkeypatch):
    import types
    monkeypatch.setattr(L.E, "RAIZ", tmp_path)
    monkeypatch.setattr(L.E, "ARQUIVO", tmp_path)
    con = L.E.conectar(tmp_path / "ev.db")
    con.executescript(L._DDL)
    p = _pasta(tmp_path, "100001_000008_2025", [("Contrato (11111111)", "Valor global R$ 483.333,33 do contrato. " * 3)])
    _man(p, captura_completa=True, docs_faltantes=[])
    resp = '{"fatos": [{"tipo": "valor", "valor": "483333.33", "doc_id": "sei:11111111", "citacao": "R$ 483.333,33"}]}'
    r = L.ler_pela_assinatura(con, ["100001/000008/2025"], pensar=lambda *a, **k: types.SimpleNamespace(texto=resp))
    assert r == {"processos_lidos": 1, "fatias": 1, "parou_sem_cota": False}
    assert con.execute("SELECT estado FROM fatos WHERE processo='100001/000008/2025'").fetchall() == [("VERIFICADO",)]
    assert con.execute("SELECT lote FROM leituras WHERE processo='100001/000008/2025'").fetchone() == ("assinatura",)
    # de novo: já lido, nada a fazer
    assert L.ler_pela_assinatura(con, ["100001/000008/2025"], pensar=lambda *a, **k: None)["processos_lidos"] == 0


def test_assinatura_sem_cota_para_sem_marcar_lido(tmp_path, monkeypatch):
    monkeypatch.setattr(L.E, "RAIZ", tmp_path)
    monkeypatch.setattr(L.E, "ARQUIVO", tmp_path)
    con = L.E.conectar(tmp_path / "ev.db")
    con.executescript(L._DDL)
    p = _pasta(tmp_path, "100001_000009_2025", [("Contrato (11111111)", "texto do contrato " * 10)])
    _man(p, captura_completa=True, docs_faltantes=[])
    r = L.ler_pela_assinatura(con, ["100001/000009/2025"], pensar=lambda *a, **k: None)
    assert r == {"processos_lidos": 0, "fatias": 0, "parou_sem_cota": True}
    assert con.execute("SELECT COUNT(*) FROM leituras").fetchone()[0] == 0
