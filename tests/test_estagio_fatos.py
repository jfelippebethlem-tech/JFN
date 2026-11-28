# -*- coding: utf-8 -*-
"""E8 `fatos` (O6.3): citação inexistente rejeitada, âncora = substring exata com página/offset, régua da citação do
E8, CPF mascarado ANTES do envio, ordem única (OB paga desc + cota Couto), idempotência e efeito no PostgreSQL
(esquema temporário), assinatura contida não chama, registro do estágio e rotina inativa do config/fluxo.yaml.
LLM sempre FALSO. Partes de PG só rodam com JFN_EVIDENCIAS_DSN (VM-2) — nunca no esquema `public` real."""
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
import yaml

from compliance_agent import evidencias as EV
from compliance_agent import leitura_integral as LI
from compliance_agent.aplicacao.estagios import estagio_de
from compliance_agent.aplicacao.estagios import fatos as F
from tests.fluxo_pg import DSN, precisa_pg

CPF = "123.456.789-00"                    # formato de CPF (DV inválido: a máscara não confere DV — vazar é pior)
PROC = "999001/000001/2026"


def _doc(texto: str, doc_id: str = "sei:1") -> dict:
    return {"doc_id": doc_id, "texto": texto, "sha": F._sha(texto)}


# ── citação: inexistente, âncora, régua ─────────────────────────────────────────────────────────────────────
def test_citacao_inexistente_e_rejeitada_como_falha_de_citacao():
    docs = {"sei:1": _doc("Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA.")}
    f = F.ancorar({"tipo": "valor", "valor": "10.000,00", "citacao": "Autorizo o pagamento de R$ 99.999,00 à ACME",
                   "doc_id": "sei:1"}, docs, {})
    assert f["estado"] == F.FALHA_CITACAO and f["motivo"] == "citação não existe no documento"
    assert f["inicio"] is None and f["doc_sha"] is None
    fora = F.ancorar({"tipo": "ato", "citacao": "Autorizo o pagamento de R$ 10.000,00", "doc_id": "sei:2"}, docs, {})
    assert fora["estado"] == F.FALHA_CITACAO and "não está na fatia" in fora["motivo"]
    assert F.ancorar({"tipo": "ato", "citacao": "  ", "doc_id": "sei:1"}, docs, {})["motivo"] == "sem citação"


def test_valor_fora_da_citacao_e_rejeitado():
    docs = {"sei:1": _doc("Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA, conforme a nota fiscal.")}
    f = F.ancorar({"tipo": "valor", "valor": "20.000,00", "citacao": "Autorizo o pagamento de R$ 10.000,00 à empresa",
                   "doc_id": "sei:1"}, docs, {})
    assert f["estado"] == F.FALHA_CITACAO and "valor" in f["motivo"]


def test_ancora_e_substring_exata_com_pagina_e_offset():
    texto = "Capa do processo\fDESPACHO\nAutorizo   o pagamento\nde R$ 10.000,00 à ACME LTDA.\fFim"
    docs = {"sei:1": _doc(texto)}
    f = F.ancorar({"tipo": "valor", "valor": "R$ 10.000,00", "citacao": "Autorizo o pagamento de R$ 10.000,00",
                   "doc_id": "sei:1"}, docs, {})
    assert f["estado"] == F.VERIFICADO
    assert texto[f["inicio"]:f["fim"]] == f["citacao"] == "Autorizo   o pagamento\nde R$ 10.000,00"
    assert f["pagina"] == 2 and f["doc_sha"] == F._sha(texto)
    assert f["contexto"] is None                             # citação longa não precisa de contexto


def test_regua_do_e8_curta_sem_numero_cai_curta_com_numero_ganha_contexto():
    texto = "Nota de empenho emitida: 2026NE00206, no valor global do contrato. Status\nReconhecido."
    docs = {"sei:1": _doc(texto)}
    curta = F.ancorar({"tipo": "ato", "citacao": "Status Reconhecido", "doc_id": "sei:1"}, docs, {})
    assert curta["estado"] == F.FALHA_CITACAO and "curta" in curta["motivo"]
    num = F.ancorar({"tipo": "ne", "valor": "2026NE00206", "citacao": "2026NE00206", "doc_id": "sei:1"}, docs, {})
    assert num["estado"] == F.VERIFICADO and num["contexto"] and "Nota de empenho" in num["contexto"]
    assert texto[num["inicio"]:num["fim"]] == "2026NE00206"
    assert F.citacao_suficiente("x" * 25) and not F.citacao_suficiente("Assinatura:")


def test_resposta_invalida_e_none_nao_lista_vazia():
    assert F.interpretar("não é json", {}, {}) is None
    assert F.interpretar('{"fatos": []}', {}, {}) == []


# ── acervo de brinquedo: máscara antes do envio ─────────────────────────────────────────────────────────────
def _acervo(tmp_path: Path, monkeypatch, docs: list[tuple[str, str]], proc: str = PROC) -> Path:
    monkeypatch.setattr(EV, "ARQUIVO", tmp_path)
    monkeypatch.setattr(LI, "_CONF", set())
    pasta = tmp_path / proc.replace("/", "_")
    (pasta / "texto").mkdir(parents=True)
    man = {"captura_completa": True, "docs_faltantes": [], "docs": []}
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(texto, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": titulo, "texto": rel, "ocr": False})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return pasta


_TEXTO_CPF = (f"Declaro que o servidor de CPF {CPF} atestou a entrega dos bens em 10/04/2026, no valor de "
              "R$ 1.234,56, conforme a Nota Fiscal nº 3890 da empresa ACME LTDA.")


def test_cpf_mascarado_antes_do_envio_e_citacao_volta_ao_original(tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF)])
    p = F.preparar(PROC, set(), set())
    assert p.fora_da_porta is None and len(p.fatias) == 1
    f = p.fatias[0]
    assert CPF not in f.texto and "12345678900" not in f.texto and "[CPF_1]" in f.texto
    assert f.mapa == {"[CPF_1]": CPF}
    # o modelo copia o marcador; a âncora desmascara e acha a substring EXATA no original
    fato = {"tipo": "ato", "citacao": "o servidor de CPF [CPF_1] atestou a entrega dos bens", "doc_id": "sei:123456789"}
    a = F.ancorar(fato, f.docs, f.mapa)
    assert a["estado"] == F.VERIFICADO and CPF in a["citacao"]
    assert f.docs["sei:123456789"]["texto"][a["inicio"]:a["fim"]] == a["citacao"]


def test_preparar_e_deterministico_e_respeita_documento_ja_lido(tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF), ("Despacho (222222222)", "Encaminhe-se " * 20)])
    a, b = F.preparar(PROC, set(), set()), F.preparar(PROC, set(), set())
    assert a.chave == b.chave and [f.chave for f in a.fatias] == [f.chave for f in b.fatias]
    lido = F._sha(_TEXTO_CPF.strip())
    c = F.preparar(PROC, {lido}, set())                       # documento inalterado (mesmo sha) não é relido
    assert all("Declaro que o servidor" not in f.texto for f in c.fatias)
    assert c.chave == a.chave                                 # a chave do processo é do TEXTO, não do que falta ler


def test_fora_da_porta_declara_motivo(tmp_path, monkeypatch):
    pasta = _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF)])
    man = json.loads((pasta / "manifest.json").read_text())
    man["captura_completa"] = False
    (pasta / "manifest.json").write_text(json.dumps(man))
    p = F.preparar(PROC, set(), set())
    assert p.fora_da_porta == "captura não declarada completa" and not p.fatias
    assert F.preparar("888001/000001/2026", set(), set()).fora_da_porta == "sem acervo capturado"


# ── ordem única ─────────────────────────────────────────────────────────────────────────────────────────────
def test_ordem_por_ob_paga_desc_com_cota_couto():
    valores = {"1/1/2025": (9e6, False), "2/2/2025": (8e6, False), "3/3/2025": (7e6, False),
               "4/4/2026": (1e3, True), "5/5/2026": (5e2, True), "6/6/2025": (0.0, True)}
    fila = F.ordem(valores, {"1/1/2025": "000001/000001/2025"}, fracao_couto=0.5)
    assert [c.chave for c in fila] == ["4/4/2026", "1/1/2025", "5/5/2026", "2/2/2025", "3/3/2025"]   # ⌈n/2⌉ Couto
    assert "6/6/2025" not in {c.chave for c in fila}                          # sem OB paga não entra
    assert fila[1].capturado and fila[1].processo == "000001/000001/2025" and fila[0].processo == "SEI-4/4/2026"
    sem_cota = F.ordem(valores, {}, fracao_couto=0.0)
    assert [c.ob_paga for c in sem_cota] == sorted((c.ob_paga for c in sem_cota), reverse=True)
    assert [c.chave for c in F.ordem(valores, {}, so_couto=True)] == ["4/4/2026", "5/5/2026"]


def test_ob_paga_por_processo_usa_a_regua_canonica(tmp_path):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.executescript("""CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, processo, valor, status, status_envio,
                       tipo_regularizacao, data_emissao);
        INSERT INTO ob_orcamentaria_siafe VALUES ('OB1','1','SEI-020001/000354/2026',100,'Contabilizado','','','10/04/2026');
        INSERT INTO ob_orcamentaria_siafe VALUES ('OB2','1','SEI-020001/000354/2026',50,'Contabilizado','Erro no Pagamento','','11/04/2026');
        INSERT INTO ob_orcamentaria_siafe VALUES ('OB3','1','SEI-020001/000354/2026',70,'Cancelado','','','12/04/2026');
        INSERT INTO ob_orcamentaria_siafe VALUES ('OB4','1','020001/000777/2025',30,'Contabilizado','','','01/02/2026');""")
    c.commit()
    c.close()
    v = F.ob_paga_por_processo(F.abrir_fonte(db))
    assert v["020001/354/2026"] == (100.0, True)               # só a OB paga; emitida ≥ governo_couto.INICIO
    assert v["020001/777/2025"] == (30.0, False)               # paga antes de 23/03/2026: fora da cota Couto


# ── assinatura: ritmo contido não chama ─────────────────────────────────────────────────────────────────────
def test_assinatura_contida_nao_chama_o_gateway(monkeypatch):
    from compliance_agent.adaptadores.llm import gateway as G
    monkeypatch.setattr(F, "motivo_assinatura", lambda con=None: "ritmo semanal da assinatura — contido")

    def proibido(*a, **k):
        raise AssertionError("gateway chamado com o ritmo contido")
    monkeypatch.setattr(G, "chamar", proibido)
    assert F.leitor_assinatura()("sistema", "texto") is None


def test_modelo_e_prompt_sao_os_do_piloto():
    from compliance_agent.llm import claude_api as C
    assert F.MODELO == C.MODELO_BARATO and F.SISTEMA == LI.SISTEMA and F.PROMPT_VERSION == LI.VERSAO_PROMPT
    assert "li-2" in F.versoes_lidas() and F.versao_chave() == "li-2|claude-haiku-5-5"


def test_projecao_usa_preco_oficial_e_faixa_longa():
    pr = F.precos_haiku()
    assert pr["entrada"] == 0.10 and pr["saida"] == 0.50 and pr["desconto_lote"] == 0.5
    curto = F.custo_fatia(10_000, 1_000, 600, lote=True, cache=False, pr=pr)
    assert curto == pytest.approx((10_600 * 0.10 + 1_000 * 0.50) / 1e6 * 0.5)
    longo = F.custo_fatia(120_000, 1_000, 600, lote=True, cache=False, pr=pr)
    assert longo == pytest.approx((120_600 * 0.50 + 1_000 * 2.50) / 1e6 * 0.5)
    assert F.custo_fatia(10_000, 1_000, 600, lote=True, cache=True, pr=pr) < curto


# ── registro e rotina ───────────────────────────────────────────────────────────────────────────────────────
def test_estagio_registrado_e_rotina_inativa():
    assert estagio_de("fatos") is F.ESTAGIO and estagio_de("fatos:020001/000354/2025") is F.ESTAGIO
    cfg = yaml.safe_load((F.RAIZ / "config" / "fluxo.yaml").read_text(encoding="utf-8"))
    r = cfg["rotinas"]["fatos_e8"]
    assert r["estagio"] == "E8" and r["ativa"] is False and r.get("bloqueio")
    assert "compliance_agent.aplicacao.estagios.fatos" in " ".join(map(str, r["comando"]))


# ── PostgreSQL (esquema temporário): idempotência e efeito ──────────────────────────────────────────────────
@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_fatos_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        F.aplicar_schema(con, nome)
        yield con, nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


class _Falso:
    """LLM falso: devolve fatos copiando literalmente do texto que recebeu (e uma citação inventada)."""

    def __init__(self, sem_cota_depois: int | None = None):
        self.chamadas: list[str] = []
        self.sem_cota_depois = sem_cota_depois

    def __call__(self, sistema: str, texto: str):
        if self.sem_cota_depois is not None and len(self.chamadas) >= self.sem_cota_depois:
            return None
        self.chamadas.append(texto)
        doc = texto.split("=== DOC ", 1)[1].split(" |", 1)[0]
        fatos = [{"tipo": "ato", "valor": "", "citacao": "o servidor de CPF [CPF_1] atestou a entrega dos bens",
                  "doc_id": doc},
                 {"tipo": "valor", "valor": "1.234,56", "citacao": "no valor de R$ 1.234,56", "doc_id": doc},
                 {"tipo": "valor", "valor": "9.999,99", "citacao": "valor inventado de R$ 9.999,99", "doc_id": doc}]
        return F.Leitura(texto=json.dumps({"fatos": fatos}, ensure_ascii=False), motor="claude-haiku-5-5@falso")


@precisa_pg
def test_idempotencia_e_efeito_no_pg(pg, tmp_path, monkeypatch):
    con, _ = pg
    _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF)])
    falso = _Falso()
    r1 = F.ler_processo(con, PROC, falso)
    assert len(falso.chamadas) == 1 and CPF not in falso.chamadas[0]          # mascarado ANTES do envio
    assert r1["fatos_gravados"] == 3 and r1["fatos_verificados"] == 2 and r1["fatos_falha"] == 1
    c = F.conferir(con, r1)
    assert F._efeito_ok(r1, c) and c["amostra"] == 2 and not c["divergentes"]
    est = dict(con.execute("SELECT estado, count(*) FROM fatos GROUP BY 1").fetchall())
    assert est == {F.VERIFICADO: 2, F.FALHA_CITACAO: 1}
    lin = con.execute("SELECT texto_sha, chave, pecas_nao_lidas, fracao FROM leituras WHERE processo = %s",
                      (PROC,)).fetchone()
    assert lin[1] == r1["chave"] and lin[2] == [] and lin[3] == 1.0
    # 2ª vez: mesma chave (processo, sha do texto, prompt, modelo) ⇒ nada é lido nem regravado
    ids = [x[0] for x in con.execute("SELECT id FROM fatos ORDER BY id")]
    r2 = F.ler_processo(con, PROC, falso)
    assert r2["ja_lido"] and len(falso.chamadas) == 1
    assert [x[0] for x in con.execute("SELECT id FROM fatos ORDER BY id")] == ids
    assert F._efeito_ok(r2, F.conferir(con, r2))
    # efeito independente: adulterar a citação gravada derruba a conferência
    con.execute("UPDATE fatos SET citacao = citacao || ' X' WHERE estado = %s", (F.VERIFICADO,))
    assert F.conferir(con, r1)["divergentes"]


@precisa_pg
def test_sem_cota_no_meio_nao_marca_lido_e_retoma_sem_duplicar(pg, tmp_path, monkeypatch):
    con, _ = pg
    grande = "\n\n".join(f"Parágrafo {i}: " + _TEXTO_CPF for i in range(260))       # > ALVO_CHARS ⇒ várias fatias
    _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", grande)])
    n = len(F.preparar(PROC, set(), set()).fatias)
    assert n >= 2
    with pytest.raises(F.SemCota):
        F.ler_processo(con, PROC, _Falso(sem_cota_depois=1))
    assert con.execute("SELECT count(*) FROM leituras").fetchone()[0] == 0
    feitos = con.execute("SELECT count(*) FROM fatos").fetchone()[0]
    falso = _Falso()
    r = F.ler_processo(con, PROC, falso)
    assert len(falso.chamadas) == n - 1                                 # a fatia gravada não é relida
    assert r["fatos_gravados"] == feitos * n and F._efeito_ok(r, F.conferir(con, r))
    assert con.execute("SELECT count(DISTINCT chave) FROM fatos").fetchone()[0] == n


@precisa_pg
def test_fora_da_porta_nao_e_feito_e_declara_o_motivo(pg, tmp_path, monkeypatch):
    """Achado 1.13: `fora_da_porta` fazia `_efeito_ok` True ⇒ o job virava "feito" sem leitura nenhuma. Agora o
    efeito reprova (falhou_efeito) com o motivo na conferência; a propagação reabre o job quando a porta abrir."""
    con, _ = pg
    pasta = _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF)])
    man = json.loads((pasta / "manifest.json").read_text())
    man["captura_completa"] = False
    (pasta / "manifest.json").write_text(json.dumps(man))
    falso = _Falso()
    r = F.ler_processo(con, PROC, falso)
    c = F.conferir(con, r)
    assert r["fora_da_porta"] and not falso.chamadas and c["leitura_no_pg"]
    assert not F._efeito_ok(r, c) and "captura não declarada completa" in c["motivo"]


class _FalsoInvalido(_Falso):
    """LLM falso que devolve JSON inválido nas primeiras `n` chamadas."""

    def __init__(self, n: int):
        super().__init__()
        self.n = n

    def __call__(self, sistema: str, texto: str):
        if len(self.chamadas) < self.n:
            self.chamadas.append(texto)
            return F.Leitura(texto="isto não é JSON", motor="claude-haiku-5-5@falso")
        return super().__call__(sistema, texto)


@precisa_pg
def test_fatia_com_json_invalido_e_relida_na_reexecucao(pg, tmp_path, monkeypatch):
    """Achado 1.13: a fatia com JSON inválido deixava a leitura "parcial", mas `leitura_concluida` só excluía
    FORA_DA_PORTA ⇒ a reexecução devolvia `ja_lido` e a fatia nunca era relida."""
    con, _ = pg
    _acervo(tmp_path, monkeypatch, [("Atesto (123456789)", _TEXTO_CPF)])
    r1 = F.ler_processo(con, PROC, _FalsoInvalido(1))
    assert r1["fatias_invalidas"] and r1["fatos_gravados"] == 0
    falso = _Falso()
    r2 = F.ler_processo(con, PROC, falso)
    assert not r2["ja_lido"] and len(falso.chamadas) == 1 and r2["fatos_gravados"] == 3
    assert con.execute("SELECT leitura FROM leituras WHERE processo = %s", (PROC,)).fetchone()[0] != "parcial"
    r3 = F.ler_processo(con, PROC, falso)                                # agora sim: lida, 0 LLM
    assert r3["ja_lido"] and len(falso.chamadas) == 1


@precisa_pg
def test_schema_evolui_tabela_antiga_sem_renomear(pg):
    con, nome = pg
    assert F.verificar_schema(con) == []
    F.aplicar_schema(con, nome)                                         # idempotente
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='fatos' "
                                      "AND table_schema=%s", (nome,))}
    assert {"payload_sha", "citacao", "estado", "doc_sha", "pagina", "inicio", "fim", "chave"} <= cols


def test_normalizar_tira_byte_nul_que_o_postgresql_recusa():
    """27/11/2026: 2 jobs do E8 quebravam com «PostgreSQL text fields cannot contain NUL (0x00) bytes»."""
    t, cabeca, corte = F.normalizar_texto("[Despacho (1)]\nDe\x00spacho do fiscal\x00", "Despacho (1)")
    assert "\x00" not in t and "\x00" not in cabeca and t == "Despacho do fiscal"
