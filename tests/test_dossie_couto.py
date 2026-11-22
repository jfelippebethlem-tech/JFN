# -*- coding: utf-8 -*-
"""Dossiê-mestre da gestão Couto: OB paga pela regra da casa, prova primária reconferida, rastreio de todo número a um
fato com id, e o verificador que reprova (controles positivo E negativo)."""
from __future__ import annotations

import re
import sqlite3

import pytest

from compliance_agent.reporting import dossie_couto as dc

_COLS = ("numero_ob", "ug_emitente", "ug_pagadora", "data_emissao", "status", "tipo", "finalidade", "tipo_ob", "nl",
         "credor", "nome_credor", "ug_liquidante", "competencia", "status_envio", "gd", "processo", "re", "pd",
         "tipo_regularizacao", "qtd_impressoes", "assinatura_digital", "vinculacao_pagamento", "valor", "exercicio",
         "coletado_em")


def _ob(con, numero, ug, data, valor, credor="11222333000181", nome="ACME LTDA", status="Contabilizado",
        envio="Processado e Pago", tipo_ob="Orçamentária", reg=""):
    d = dict.fromkeys(_COLS, "")
    d.update(numero_ob=numero, ug_emitente=ug, data_emissao=data, valor=valor, credor=credor, nome_credor=nome,
             status=status, status_envio=envio, tipo_ob=tipo_ob, tipo_regularizacao=reg,
             exercicio=int(data.split("/")[2]), coletado_em="2026-11-20")
    con.execute(f"INSERT INTO ob_orcamentaria_siafe({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
                [d[c] for c in _COLS])


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.execute(f"CREATE TABLE ob_orcamentaria_siafe({', '.join(_COLS)})")
    c.execute("CREATE TABLE ob_reemitida(ob, ug, valor)")
    c.execute("CREATE TABLE sancoes_federais(cadastro, cpf_cnpj, nome, data_inicio, data_fim)")
    c.execute("CREATE TABLE contratos_tcerj(processo, sei_norm)")
    _ob(c, "2026OB00001", "180100", "10/04/2026", 1000.00)
    _ob(c, "2026OB00002", "180100", "11/04/2026", 500.00, envio="Enviado ao Banco")           # paga, sem confirmação
    _ob(c, "2026OB00003", "180100", "12/04/2026", 700.00, envio="Erro no Pagamento")         # devolvida: fora
    _ob(c, "2026OB00004", "180100", "12/04/2026", 300.00, reg="Pagamento Complementar")      # complementar: fora
    _ob(c, "2026OB00005", "180100", "13/04/2026", 900.00, status="Anulado")                  # anulada: fora
    _ob(c, "2026OB00006", "180100", "14/04/2026", 50.00, credor="12345678901", nome="FULANO DE TAL")   # PF
    _ob(c, "2026OB00007", "180100", "15/04/2026", 80.00, tipo_ob="RPP")
    _ob(c, "2026OB00008", "180100", "10/03/2026", 9999.00)                                    # antes da gestão
    _ob(c, "2025OB00001", "180100", "10/04/2025", 400.00)                                     # ano anterior
    c.execute("INSERT INTO sancoes_federais VALUES ('CEIS','11.222.333/0001-81','ACME','2026-01-01','2027-01-01')")
    c.execute("INSERT INTO contratos_tcerj VALUES ('SEI-180001/000001/2026','180001/000001/2026')")
    return c


def test_coletar_ob_so_soma_o_que_e_pagamento(con):
    ob = dc.coletar_ob(con, "2026-03-23", "2026-11-22")
    assert ob["fim"] == "2026-04-15" and ob["fim_ant"] == "2025-04-15"
    ag = dc.agregar_ob(ob, {"ug_orgao": {"180100": "18"}, "nome_orgao": {"18": "Educação"}, "nome_ug": {}})
    t = ag["couto"]["total"]
    assert t["valor"] == 1630.00            # 1000 + 500 + 50 + 80 (devolvida, complementar, anulada e março fora)
    assert t["confirmada"] == 1130.00 and t["sem_confirmacao"] == 500.00
    assert ag["anterior"]["total"]["valor"] == 400.00
    assert ag["couto"]["pf"] == [1, 50.00]
    assert "12345678901" not in str(ob) and "FULANO" not in str(ob), "pessoa física não pode sair da varredura"
    assert set(ag["couto"]["fora"]) == {"devolvida", "complementar", "status:Anulado"}
    assert ag["couto"]["rp"]["RPP"] == [1, 80.00]


def test_amostra_igual_e_divergente(con):
    ob = dc.coletar_ob(con, "2026-03-23", "2026-11-22")
    assert dc.conferir_amostra(con, ob, n=1)["ok"]
    ob["couto"] = [[r[0], r[1], r[2], r[3], r[4], r[5] + 1, r[6], r[7]] for r in ob["couto"]]
    assert not dc.conferir_amostra(con, ob, n=1)["ok"]


def test_prova_primaria_reconferida(con):
    from compliance_agent.cruzamentos_intel import _ob_paga
    paga = _ob_paga(con)
    it = {"cnpj": "11222333000181"}
    ok = dc.conferir_prova(con, paga, it, "OB 2026OB00001 · UG 180100 · 2026-04-10 · R$ 1.000,00")
    assert ok["resultado"] == "confere" and ok["confirmada"]
    devolvida = dc.conferir_prova(con, paga, it, "OB 2026OB00003 · UG 180100 · 2026-04-12 · R$ 700,00")
    assert devolvida["resultado"] == "diverge"
    valor_errado = dc.conferir_prova(con, paga, it, "OB 2026OB00001 · UG 180100 · 2026-04-10 · R$ 1.001,00")
    assert valor_errado["resultado"] == "diverge"
    assert dc.conferir_prova(con, paga, it, "OB 2026OB09999 · UG 180100 · 2026-04-10 · R$ 1,00")["resultado"] == "ausente"
    assert dc.conferir_prova(con, paga, it, "CEIS — Impedimento de contratar")["resultado"] == "confere"
    assert dc.conferir_prova(con, paga, {"cnpj": "99999999000199"}, "CEIS — x")["resultado"] == "ausente"
    assert dc.conferir_prova(con, paga, it, "contrato no espelho do TCE-RJ, processo SEI-180001/000001/2026")[
        "resultado"] == "confere"
    assert dc.conferir_prova(con, paga, it, "fantasma_score = 90 (alto)")["resultado"] == "nao_reconferivel"


def _dados(con, achados):
    ob = dc.coletar_ob(con, "2026-03-23", "2026-11-22")
    ind = {"estado": "indisponivel", "erro": "fixture"}
    return {"gerado_em": "2026-11-22T01:00:00", "inicio": "2026-03-23", "gestao": dc.gc.GESTAO, "ob": ob,
            "cadastro": {"ug_orgao": {"180100": "18"}, "nome_orgao": {"18": "Educação"}, "nome_ug": {"180100": "SEEDUC"}},
            "contratacoes": ind, "aditivos": ind, "tac": ind, "atos": ind, "controle": {}, "sei": {},
            "achados": {"estado": "ok", "itens": achados, "camada_subjetiva": {}}}


def _achado(passou=True, n_ok=1, id_="D14-11222333000181-2026-01-01", grau="🟡"):
    return {"id": id_, "grau": grau, "regra_ou_hipotese": "D14 · ACME paga na vigência (R$ 1.000,00; 34,4% do pago)",
            "orgao": "Sec. Educação (UG 180100)", "valor_ob": 1000.0, "fonte": "SIAFE-Rio; CEIS",
            "explicacao_inocente": "serviço anterior à sanção", "proximo_passo": "requerer NL e atesto",
            "verificacao": "VERIFICADO", "camada": "deterministica", "passou": passou, "n_provas_ok": n_ok,
            "n_provas_divergentes": 0, "motivo_portao": None if passou else "x", "processos_sei": ["SEI-180001/000001/2026"],
            "provas": [{"texto": "OB 2026OB00001 · UG 180100 · 2026-04-10 · R$ 1.000,00", "tipo": "OB", "ob": "2026OB00001",
                        "ug": "180100", "valor": 1000.0, "resultado": "confere", "confirmada": True,
                        "detalhe": "OB paga no SIAFE"}]}


def _render(dados):
    from compliance_agent.reporting.render_html import render_html
    ctx = dc.Montador(dados).montar()
    return render_html(ctx), ctx["_dados"]


def test_documento_aprovado_e_todo_numero_rastreia(con):
    html, fatos = _render(_dados(con, [_achado()]))
    assert "<!--fato:dossie_couto:exec.total.couto:valor-->" in html
    v = dc.verificar(html, fatos, [_achado()], pdf_texto=None)
    assert v["aprovado"], v["falhas"]
    assert v["n_numeros_citados"] > 20
    ids = {f["fato_id"] for lst in ("brl", "contagem", "percentual", "indice") for f in fatos[lst]}
    assert all(re.match(r"^[a-z][a-z0-9_]*(:[A-Za-z0-9_.\-]+)+$", i) for i in ids), "id fora do padrão do registro"
    assert "R$ 1.630,00" in html


def test_verificador_reprova_numero_sem_fato(con):
    html, fatos = _render(_dados(con, [_achado()]))
    v = dc.verificar(html.replace("</body>", "<p>Pago a mais: R$ 9.999,99</p></body>"), fatos, [_achado()], None)
    assert not v["aprovado"] and any("número sem fato" in f for f in v["falhas"])


def test_verificador_reprova_valor_que_nao_bate_com_o_registro(con):
    html, fatos = _render(_dados(con, [_achado()]))
    adulterado = html.replace('data-fato="dossie_couto:exec.total.couto:valor">R$ 1.630,00',
                              'data-fato="dossie_couto:exec.total.couto:valor">R$ 1.631,00', 1)
    assert adulterado != html
    assert not dc.verificar(adulterado, fatos, [_achado()], None)["aprovado"]


def test_verificador_reprova_achado_sem_prova(con):
    a = _achado(n_ok=0)
    html, fatos = _render(_dados(con, [a]))
    v = dc.verificar(html, fatos, [a], None)
    assert not v["aprovado"] and any("sem prova" in f for f in v["falhas"])


def test_verificador_reprova_pdf_que_perdeu_conteudo(con):
    html, fatos = _render(_dados(con, [_achado()]))
    texto = dc._visivel(html)
    assert dc.verificar(html, fatos, [_achado()], texto)["aprovado"]
    cortado = texto[: len(texto) // 2]
    v = dc.verificar(html, fatos, [_achado()], cortado)
    assert not v["aprovado"] and any("PDF" in f for f in v["falhas"])


def test_item_que_nao_passou_nao_vira_ficha(con):
    a = _achado(passou=False, id_="D10-99")
    html, fatos = _render(_dados(con, [a]))
    assert 'data-achado="D10-99"' not in html and "D10-99" in html
    assert dc.verificar(html, fatos, [a], None)["aprovado"]


def test_indisponivel_nao_e_zero(con):
    dados = _dados(con, [])
    dados["ob"] = {"estado": "indisponivel", "erro": "sem OB"}
    html, fatos = _render(dados)
    assert "INDISPONÍVEL" in html and "R$ 0,00" not in html
    assert dc.verificar(html, fatos, [], None)["aprovado"]


def test_documento_neutro_e_sem_cpf(con):
    from compliance_agent.reporting.neutralidade import termos_proibidos
    html, _ = _render(_dados(con, [_achado()]))
    assert not termos_proibidos(dc._visivel(html))
    assert "12345678901" not in html and "FULANO" not in html


def test_aproximacao_da_regua_vira_fato_conferido():
    r = dc.Registro("2026-11-22")
    h = dc.texto_com_fatos(r, "cerca de R$ 111 a 120 mi/mês e R$ 2.000,00", "t", "régua")
    assert h.count("data-fato=") == 2 and 'data-aprox="1">R$ 111 a 120 mi<' in h
    assert dc.valor_aproximado("R$ 111 a 120 mi") == 111_000_000.0
    fatos = r.publicar()
    assert dc.verificar(f"<p>{h}</p>", fatos, [], None)["aprovado"]
    falso = h.replace("R$ 111 a 120 mi", "R$ 211 a 220 mi")
    assert not dc.verificar(f"<p>{falso}</p>", fatos, [], None)["aprovado"]


def test_registro_recusa_dois_valores_para_o_mesmo_fato():
    r = dc.Registro("2026-11-22")
    r.put("x", 1, "contagem", "a", "f", "c")
    with pytest.raises(ValueError):
        r.put("x", 2, "contagem", "a", "f", "c")


def test_pago_sem_confirmacao_nao_sai_verificado():
    r = dc.Registro("2026-11-22")
    fid = r.put("p", 10.0, "BRL", "a", "f", "c", natureza="pago", base="ob_contabilizada_sem_confirmacao")
    assert r.f[fid]["estado"] == "A CONFERIR"
    fid = r.put("q", 10.0, "BRL", "a", "f", "c", natureza="pago", base=dc.BASE_PAGO_CONFIRMADO)
    assert r.f[fid]["estado"] == "VERIFICADO"


def test_tipo_de_decreto_orcamentario():
    """Regressão 22/11/2026: o padrão passava por _sem_acento, que punha `\\s` em maiúscula (`\\S`) — os 70 decretos
    de crédito caíam todos em "programação orçamentária"."""
    assert dc.tipo_orcamentario("ABRE CRÉDITO SUPLEMENTAR A DIVERSOS ÓRGÃOS, NO VALOR DE R$ 1,00") == "crédito suplementar"
    assert dc.tipo_orcamentario("ABRE CRÉDITO ESPECIAL À SECRETARIA") == "crédito especial"
    assert dc.tipo_orcamentario("ESTABELECE LIMITES DE EMPENHO") == "contingenciamento e limites"
    assert dc.tipo_orcamentario("ALTERA O QUADRO DE DETALHAMENTO DA DESPESA") == "programação orçamentária/financeira"
