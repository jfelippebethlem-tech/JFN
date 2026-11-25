# -*- coding: utf-8 -*-
"""E16 `entregar` (O7.5): manifesto REPRODUZÍVEL (gerar 2× dá o mesmo hash e o mesmo HTML), validador que BLOQUEIA
cada classe de defeito (seção ausente, citação inexistente, número sem fonte, número divergente, CPF exposto,
vocabulário fora do garantir_neutro/penal, manchete não-Tier-1), só OB paga na soma (o resto em "fora da soma"),
conferência do PDF (página numerada, número e seção presentes), entrega honesta (silenciado ⇒ ok=False; só
message_id inteiro vale) e, no PG (VM-2, esquema temporário), RBAC + acesso_log + entrega append-only + efeito.
O PDF real (Chromium + pdftotext) roda com JFN_TESTE_PDF=1 (VM-2/it-campo)."""
import hashlib
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from compliance_agent.aplicacao.estagios import ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import caso as E14
from compliance_agent.aplicacao.estagios import entregar as E16
from compliance_agent.dominio import acesso as AC
from tests.fluxo_pg import DSN, precisa_pg

CPF_TESTE = "529" + "982" + "247" + "25"          # sintético, montado em tempo de execução (scan_pii)
JUST = "pedido do dono: dossiê do órgão para a reunião"
REG = {"r.t3": {"tier": 3, "afirma": "sinal fraco"}, "r.t1": {"tier": 1, "afirma": "pagamento sem liquidação"}}
DOC = ("Despacho. Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA, referente à nota fiscal 3890, emitida em "
       "10/04/2024, conforme o atesto do fiscal do contrato.")
INI = DOC.index("Autorizo")
CIT = DOC[INI:INI + 60]
OBS = [  # numero_ob, ug, data, status, status_envio, tipo_reg, credor, nome, valor, exercicio
    ("2024OB00001", "166100", "10/03/2024", "Contabilizado", "Processado e Pago", "", "11222333000181", "ACME LTDA",
     1500.50, 2024),
    ("2024OB00002", "166100", "11/03/2024", "Contabilizado", "Processado e Pago", "", "11222333000181", "ACME LTDA",
     499.50, 2024),
    ("2025OB00003", "166100", "05/02/2025", "Contabilizado", "Processado e Pago", "", CPF_TESTE, "FULANO DE TAL",
     300.00, 2025),
    ("2025OB00004", "166100", "06/02/2025", "Anulado", "", "", "11222333000181", "ACME LTDA", 999.99, 2025),
    ("2025OB00005", "166100", "07/02/2025", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar",
     "11222333000181", "ACME LTDA", 77.00, 2025),
    ("2025OB00006", "166100", "08/02/2025", "Contabilizado", "Erro no Pagamento", "", "11222333000181", "ACME LTDA",
     55.00, 2025),
    ("2025OB00007", "133100", "08/02/2025", "Contabilizado", "Processado e Pago", "", "11222333000181", "ACME LTDA",
     10_000.00, 2025),
]


def _fonte(tmp_path: Path) -> Path:
    p = tmp_path / "fonte.db"
    if p.exists():
        return p
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, "
                "status_envio TEXT, tipo_regularizacao TEXT, credor TEXT, nome_credor TEXT, valor REAL, exercicio INT, "
                "coletado_em TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,'2026-11-24T10:00:00')", OBS)
    con.commit()
    con.close()
    return p


def _derivado(*, tier_regra="r.t3", status="triagem"):
    a = {"id": 7, "regra_id": tier_regra, "regra_versao": "t", "tier": REG[tier_regra]["tier"], "processo":
         "999001/000001/2024", "entradas_hash": "a" * 64, "origem": "o", "criterio": "ug", "status_regra": "triagem",
         "status_efetivo": status, "estado": "INDICIO", "motivo_estado": "",
         "observacao": f"A OB 2024OB00001 de R$ 1.500,50 foi paga ao credor {CPF_TESTE}",
         "inferencia": "pagamento antes da liquidação", "hipotese": "h", "valores": {}, "decisoes": [],
         "evidencias": [{"ordem": 0, "papel": "contradicao", "fato": {"descricao": "NL anterior", "fonte": "nl_siafe",
                                                                      "referencia": "2024NL1"}}],
         "contestacao_pendente": False}
    return {"caso": {"chave": "ug:166100"}, "achados": [a], "processos": ["999001/000001/2024"],
            "hipoteses_inocentes": [{"achado_id": 7, "regra_id": tier_regra, "hipotese": "reemissão legítima",
                                     "origem": "registro", "excluida_por": None}],
            "lacunas": [], "contraevidencias": [{"achado_id": 7, "origem": "evidencia", "descricao": "NL anterior",
                                                 "fonte": "nl_siafe", "referencia": "2024NL1"}],
            "diligencias": [{"origem": "achado:7", "texto": "conferência humana do achado 7"}],
            "contestacoes": [], "historico": []}


def _casos(**kw):
    return [{"chave": "ug:166100", "caso_id": 1, "versao": 1, "chave_sha": "b" * 64, "derivado": _derivado(**kw)}]


CITS = [{"processo": "999001/000001/2024", "eixo": "execucao", "doc_id": "sei:1000001",
         "documento_sha256": hashlib.sha256(DOC.encode()).hexdigest(), "inicio": INI, "fim": INI + 60, "citacao": CIT}]


def _resolver(proc, doc_id):
    return {"sha": hashlib.sha256(DOC.encode()).hexdigest(), "texto": DOC} if doc_id == "sei:1000001" else None


FILTRO = {"lente": None, "ug": ["166100"], "credor": [], "data_desde": "2024-01-01", "data_ate": None, "casos": []}


def _dossie(tmp_path, **kw):
    con, fid = E16.abrir_fonte(_fonte(tmp_path))
    try:
        return E16.montar(con, fid, FILTRO, casos=kw.pop("casos", _casos()), citacoes=kw.pop("citacoes", CITS),
                          registro=REG)
    finally:
        con.close()


def _classes(d, html=None):
    return {x["classe"] for x in E16.validar(d, html or E16.render(d), resolver_doc=_resolver, registro=REG)}


# ── manifesto e soma ─────────────────────────────────────────────────────────────────────────────────────────────
def test_manifesto_reproduzivel_e_rodape(tmp_path):
    a, b = _dossie(tmp_path), _dossie(tmp_path)
    assert a["manifesto"]["manifesto_sha256"] == b["manifesto"]["manifesto_sha256"]
    assert E16.render(a) == E16.render(b)
    assert E16.sha_manifesto(a["manifesto"]) == a["manifesto"]["manifesto_sha256"]
    assert a["manifesto"]["manifesto_sha256"][:32] in E16.render(a)            # o hash do rodapé É o do manifesto
    c = _dossie(tmp_path, citacoes=[])
    assert c["manifesto"]["manifesto_sha256"] != a["manifesto"]["manifesto_sha256"]


def test_so_ob_paga_soma_e_o_resto_vai_para_fora(tmp_path):
    n = {x["id"]: x["valor"] for x in _dossie(tmp_path)["manifesto"]["numeros"]}
    assert n["total.n"] == 3 and n["total.valor"] == 2300.00                   # anulada, complementar e devolvida fora
    assert n["ano.2024.valor"] == 2000.00 and n["ano.2025.valor"] == 300.00
    fora = {k: v for k, v in n.items() if k.startswith("fora.") and k.endswith(".valor")}
    assert sorted(fora.values()) == [55.00, 77.00, 999.99]
    assert not any(CPF_TESTE in k for k in n)                                   # CPF nunca vira id


def test_dossie_limpo_passa_e_mascara_cpf(tmp_path):
    d = _dossie(tmp_path)
    html = E16.render(d)
    assert E16.validar(d, html, resolver_doc=_resolver, registro=REG) == []
    assert CPF_TESTE not in html and "Pessoa física" in html
    assert E16.SEM_MANCHETE in html                                            # Tier 3 não vira manchete


# ── validador: cada classe de defeito bloqueia ───────────────────────────────────────────────────────────────────
def test_bloqueia_secao_ausente(tmp_path):
    d = _dossie(tmp_path)
    d["ctx"]["secoes"] = [s for s in d["ctx"]["secoes"] if "Diligências" not in s["titulo"]]
    assert "secao_ausente" in _classes(d)


def test_bloqueia_citacao_inexistente(tmp_path):
    d = _dossie(tmp_path)
    d["manifesto"]["citacoes"][0]["inicio"] += 1                                # offset que não é a citação
    assert "citacao_inexistente" in _classes(d)
    d = _dossie(tmp_path, citacoes=[{**CITS[0], "doc_id": "sei:9999999"}])     # documento que não abre
    assert "citacao_inexistente" in _classes(d)
    d = _dossie(tmp_path, citacoes=[{**CITS[0], "documento_sha256": "c" * 64}])
    assert "citacao_inexistente" in _classes(d)


def test_bloqueia_numero_sem_fonte(tmp_path):
    d = _dossie(tmp_path)
    d["ctx"]["secoes"][0]["html"] += "<p>Total estimado de R$ 1.000,00 e 12,5% do orçamento.</p>"
    assert "numero_sem_fonte" in _classes(d)
    d = _dossie(tmp_path)
    d["ctx"]["secoes"][0]["html"] += '<span class="n" data-n="inventado">R$ 1,00</span>'
    assert "numero_sem_fonte" in _classes(d)


def test_bloqueia_numero_divergente(tmp_path):
    d = _dossie(tmp_path)
    html = E16.render(d)
    next(x for x in d["manifesto"]["numeros"] if x["id"] == "total.valor")["valor"] = 2300.01
    assert "numero_divergente" in _classes(d, html)


def test_bloqueia_cpf_exposto(tmp_path):
    d = _dossie(tmp_path)
    cpf = f"{CPF_TESTE[:3]}.{CPF_TESTE[3:6]}.{CPF_TESTE[6:9]}-{CPF_TESTE[9:]}"
    d["ctx"]["secoes"][1]["html"] += f"<p>Servidor {cpf}</p>"
    assert "cpf_exposto" in _classes(d)


@pytest.mark.parametrize("termo", ["Relatório do JFN", "houve dolo do gestor", "parecer da Lex"])
def test_bloqueia_vocabulario(tmp_path, termo):
    d = _dossie(tmp_path)
    d["ctx"]["secoes"][1]["html"] += f"<p>{termo}</p>"
    assert "vocabulario" in _classes(d)


def test_bloqueia_manchete_nao_tier1(tmp_path):
    d = _dossie(tmp_path)
    d["manchetes"] = [{"achado_id": 7, "regra_id": "r.t3", "texto": "sinal fraco — achado 7"}]
    d["ctx"]["top_flags"] = ["sinal fraco — achado 7"]
    assert "manchete_nao_tier1" in _classes(d)
    d = _dossie(tmp_path)
    d["ctx"]["top_flags"] = ["Rede de laranjas em 40 órgãos"]                 # destaque solto, sem achado
    assert "manchete_nao_tier1" in _classes(d)
    t1 = _dossie(tmp_path, casos=_casos(tier_regra="r.t1"))
    assert t1["manchetes"] and _classes(t1) == set()                          # Tier 1 vivo vira manchete válida
    ref = _dossie(tmp_path, casos=_casos(tier_regra="r.t1", status="refutado"))
    assert ref["manchetes"] == []                                             # refutado nunca é manchete


# ── filtro ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_filtro_lente_couto_e_vazio():
    from compliance_agent.fluxo.lentes import Lente
    from compliance_agent.governo_couto import INICIO
    assert E16.resolver_filtro({"lente": "couto"})["data_desde"] == INICIO
    lentes = {"bombeiros": Lente(nome="bombeiros", ugs=frozenset({"166100", "160100"}), prioridade=0.2)}
    assert E16.resolver_filtro({"lente": "bombeiros"}, lentes)["ug"] == ["160100", "166100"]
    assert E16.resolver_filtro({"lente": "bombeiros", "filtro": {"ug": ["166100"]}}, lentes)["ug"] == ["166100"]
    with pytest.raises(ErroPermanente):
        E16.resolver_filtro({})
    with pytest.raises(ErroPermanente):
        E16.resolver_filtro({"lente": "inexistente"}, lentes)


# ── PDF ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _paginas_de(html: str, n: int = 2, tirar: str = "") -> list[str]:
    vis = E16.visivel(html).replace(tirar, "") if tirar else E16.visivel(html)
    cortes = [0] + [vis.rfind(". ", 0, len(vis) * i // n) + 1 for i in range(1, n)] + [len(vis)]   # fim de frase
    partes = [vis[cortes[i]:cortes[i + 1]] for i in range(n)]
    return [f"{p}\nPágina {i} de {n}" for i, p in enumerate(partes, 1)]


def test_conferir_pdf(tmp_path):
    d = _dossie(tmp_path)
    html = E16.render(d)
    assert E16.conferir_pdf(_paginas_de(html), d, html) == []
    sem_num = _paginas_de(html, tirar="R$ 2.300,00")
    assert any("total.valor" in x["detalhe"] for x in E16.conferir_pdf(sem_num, d, html))
    sem_rodape = [p.replace("Página 2 de 2", "") for p in _paginas_de(html)]
    assert any("página 2" in x["detalhe"] for x in E16.conferir_pdf(sem_rodape, d, html))


@pytest.mark.skipif(os.environ.get("JFN_TESTE_PDF") != "1", reason="PDF real só com JFN_TESTE_PDF=1 (Chromium)")
def test_pdf_real_numerado_leva_tudo(tmp_path):
    import asyncio
    d = _dossie(tmp_path)
    html = E16.render(d)
    pdf = tmp_path / "d.pdf"
    asyncio.run(E16.pdf_numerado(html, str(pdf)))
    pags = E16.texto_pdf(pdf)
    assert pags and E16.conferir_pdf(pags, d, html) == []


# ── entrega honesta ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("resp,ok", [
    ({"ok": True, "silenciado": True}, False), ({"ok": True}, False), ({"ok": True, "result": {}}, False),
    ({"ok": True, "result": {"message_id": True}}, False), ({"ok": False, "description": "chat not found"}, False),
    ({"ok": True, "result": {"message_id": 4242}}, True)])
def test_resultado_telegram(resp, ok):
    r = E16.resultado_telegram(resp)
    assert r["ok"] is ok and (r["message_id"] == 4242) is ok


def test_entregar_telegram_silenciado_e_pedido(tmp_path):
    from compliance_agent.notifications import silencio
    vistos = []

    async def falso(path, caption="", chat_id=""):
        vistos.append(silencio.PEDIDO.get())
        return {"ok": True, "silenciado": True}
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    assert E16.entregar_telegram(pdf, "legenda", enviar=falso)["ok"] is False
    assert vistos == [True] and silencio.PEDIDO.get() is False                 # pedido só dentro do envio


def test_registro_do_estagio():
    assert estagio_de("entregar:dossie_orgao") is E16.ESTAGIO


# ── PG: RBAC, bloqueio, entrega e efeito ─────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def esquema():
    import psycopg
    nome = f"tmp_e16_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        E14.aplicar_schema(con, nome)
        yield nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


@pytest.fixture()
def pg(esquema, monkeypatch):
    monkeypatch.setenv(E14.ENV_ESQUEMA, esquema)
    monkeypatch.setenv("JFN_E11_ESQUEMA", esquema)
    monkeypatch.setattr(E14, "_registro", lambda: REG)
    con = E14.conectar({"dsn": DSN, "esquema": esquema})
    yield con
    con.close()


def _falso_pdf(html, destino):
    async def _f():
        Path(destino).write_bytes(b"%PDF-falso " + html.encode()[:50])
    return _f()


@pytest.fixture()
def paginas(monkeypatch):
    estado = {}
    monkeypatch.setattr(E16, "texto_pdf", lambda p: estado["paginas"])
    return estado


@precisa_pg
def test_exportar_rbac_bloqueio_entrega_e_efeito(pg, tmp_path, paginas):
    fonte = _fonte(tmp_path)
    payload = {"produto": "dossie_orgao", "fonte": str(fonte), "saida": str(tmp_path / "out"), "justificativa": JUST,
               "filtro": {"ug": ["166100"], "data_desde": "2024-01-01"}}
    leitura = AC.Principal("leitura:t", AC.Papel.LEITURA)
    with pytest.raises(AC.AcessoNegado):                                      # leitura não monta nem exporta
        E16.gerar(payload, leitura, pg=pg)
    servico = AC.Principal("servico:t", AC.Papel.SERVICO)
    with pytest.raises(AC.AcessoNegado):                                      # sem justificativa
        E16.gerar({**payload, "justificativa": ""}, servico, pg=pg, gerar_pdf=_falso_pdf)
    neg = pg.execute("SELECT count(*) FROM acesso_log WHERE NOT permitido").fetchone()[0]
    assert neg >= 2                                                           # as negadas ficaram na trilha

    con, fid = E16.abrir_fonte(fonte)
    d = E16.montar(con, fid, E16.resolver_filtro(payload), casos=[], citacoes=[], registro=REG)
    casos = E16.casos_do_pg(pg, E16.resolver_filtro(payload), servico)
    dd = E16.montar(con, fid, E16.resolver_filtro(payload), casos=casos, citacoes=[], registro=REG)
    con.close()
    paginas["paginas"] = _paginas_de(E16.render(dd))          # o "PDF" é o texto do dossiê que o gerar vai montar
    ruim = {**d, "ctx": {**d["ctx"], "secoes": d["ctx"]["secoes"] + [{"titulo": "X", "html": "<p>R$ 5,00</p>"}]}}
    with pytest.raises(E16.ExportacaoBloqueada) as e:
        E16.exportar(pg, ruim, servico, JUST, chave="c:ruim", saida=tmp_path / "bloq", gerar_pdf=_falso_pdf,
                     registro=REG)
    assert {x["classe"] for x in e.value.defeitos} == {"numero_sem_fonte"}
    assert not (tmp_path / "bloq").exists()                                   # nada foi gravado como entregue
    assert pg.execute("SELECT ok FROM entrega WHERE chave = 'c:ruim'").fetchone() == (False,)

    async def silenciado(path, caption="", chat_id=""):
        return {"ok": True, "silenciado": True}
    r = E16.gerar({**payload, "enviar": True}, servico, pg=pg, gerar_pdf=_falso_pdf, enviar_fn=silenciado,
                  resolver_doc=_resolver)
    assert r["telegram"]["ok"] is False
    tele = pg.execute("SELECT ok, message_id FROM entrega WHERE id = %s", (r["entregas"][1],)).fetchone()
    assert tele == (False, None)
    assert E16.efeito_ok(E16.conferir(pg, r, {**payload, "enviar": True}, resolver_doc=_resolver,
                                      registro=REG)) is False                 # pediu Telegram e não houve message_id

    async def entregue(path, caption="", chat_id=""):
        return {"ok": True, "result": {"message_id": 9001}}
    r2 = E16.gerar({**payload, "enviar": True}, servico, pg=pg, gerar_pdf=_falso_pdf, enviar_fn=entregue,
                   resolver_doc=_resolver)
    assert r2["telegram"] == {"ok": True, "message_id": 9001, "motivo": "entregue"}
    assert r2["manifesto_sha256"] == r["manifesto_sha256"]                    # mesma fonte, mesmo estado ⇒ mesmo hash
    c = E16.conferir(pg, r2, {**payload, "enviar": True}, resolver_doc=_resolver, registro=REG)
    assert E16.efeito_ok(c), c
    man = Path(r2["manifesto"])
    man.write_text(man.read_text(encoding="utf-8").replace('"valor": 2300.0', '"valor": 2300.5'), encoding="utf-8")
    assert E16.conferir(pg, r2, payload, resolver_doc=_resolver, registro=REG)["manifesto_ok"] is False


def test_cobertura_por_ug_e_ano(tmp_path):
    p = _fonte(tmp_path)
    con, fid = E16.abrir_fonte(p)
    d = E16.montar(con, fid, FILTRO, casos=_casos(), citacoes=[], registro=REG)
    con.close()
    assert "INDISPONÍVEL" in E16.render(d)                                   # sem espelho: nunca "coberto"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ordens_bancarias (ug_codigo TEXT, numero_ob TEXT, data_emissao TEXT)")
    c.executemany("INSERT INTO ordens_bancarias VALUES ('166100', ?, ?)",
                  [("2024OB00001", "2024-03-10"), ("2024OB00002", "2024-03-11"), ("2025OB00003", "2025-02-05"),
                   ("2025OB09998", "2025-02-06"), ("2025OB09999", "2025-02-07")])
    c.commit()
    c.close()
    con, fid = E16.abrir_fonte(p)
    col = E16.Coleta()
    cob = {(x["ug"], x["ano"]): x["estado"] for x in E16.cobertura(con, col, FILTRO)}
    con.close()
    assert cob == {("166100", "2024"): "coberto", ("166100", "2025"): "parcial"}   # 2 de 3 do espelho faltam
    assert {q["id"] for q in col.consultas} == {"q.cobertura_espelho", "q.cobertura_siafe"}
    assert "não medida" in E16.cobertura(None, E16.Coleta(), {**FILTRO, "ug": []})
