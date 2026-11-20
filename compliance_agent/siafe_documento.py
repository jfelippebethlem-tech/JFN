"""siafe_documento — coletor dos DOCUMENTOS de execução do SIAFE-Rio 2: Nota de Empenho (NE) e Nota de
Liquidação (NL) (Execução › Execução Orçamentária) e Guia de Devolução (GD) (Execução › Execução Financeira).

POR QUE EXISTE (04/11/2026). O JFN só coletava a OB. A NE traz **Fonte** (a ordem cronológica do Decreto RJ
49.134/2024 art. 9º é "por fonte de recursos"), **Natureza**, **Processo** e o **tipo de reconhecimento de
passivo** (empenho a posteriori, Lei 4.320 art. 60). A NL traz a **Data de Emissão da liquidação** — o próprio
critério da ordem cronológica no art. 9º — a **NE** a que se liga e o **Valor Retido**.

As duas telas usam a MESMA grade (`pt1:tblDocumento:tabViewerDec` — `::db`, `::scroller`, `::ch`,
`chkRemoveLimit`, teto de 1.000), mapeada por `tools/siafe_mapear.py --detalhar`. Não reaproveita o coletor da
OB por herança: ele tem o nome da tabela fixo em ~12 pontos e é o canônico (1,3 mi de linhas); generalizá-lo
arriscava o que funciona. Reaproveita as primitivas (`_typeahead`, `_click_real`, `_login`, `_encerrar`).

A TELA LISTA OS RESTOS A PAGAR. Consultada no exercício 2025, a NE traz as de 2025 E as anteriores com saldo
(medido no ITERJ: NE de 2002 ainda viva). `exercicio` = ano da consulta; `ano_ne`/`ano_nl` = ano do número.

Colunas casadas pelo NOME DO CABEÇALHO, nunca por posição (o SIAFE 1 deslocou R$ 3,41 bi por posição).
Coleta que para perto de 1.000 linhas devolve `capou: true` — não é completa e não finge que é.

Uso:
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_documento --tipo NE --ug 133100 --exercicio 2025
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_documento --tipo NL --ug 133100 --exercicio 2025
    PYTHONPATH=. .venv/bin/python -m compliance_agent.siafe_documento --tipo GD --ug 180100 --exercicio 2026
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
TBL = "pt1:tblDocumento"
_TETO = 1000
_PLATO = 900            # a rolagem virtual perde linhas: 2025NL0 (~5.400) voltou com 974 sob o teto de 1.000 e o
                        # limiar antigo (975, o da OB) aceitou como completo (04/11/2026). Subdividir à toa custa
                        # tempo; não subdividir custa dado.
_COBERTURA_MIN = 0.95   # NL completa = cobre ≥95% das NL que as OBs pagas da UG/ano citam (controle positivo)

_COMUM = {"numero": "numero", "ug emitente": "ug_emitente", "data emissao": "data_emissao", "doc. alt.": "doc_alt",
          "tipo alt.": "tipo_alt", "status": "status", "credor": "credor", "nome do credor": "nome_credor",
          "precatorio": "precatorio", "processo": "processo", "assinatura eletronica": "assinatura_eletronica",
          "valor": "valor"}

TIPOS = {
    "NE": {"tela": "Nota de Empenho", "re": re.compile(r"\b20\d\dNE\d{5}P?\b"), "tabela": "ne_siafe",
           "ano": "ano_ne", "dinheiro": ("valor",),
           "cols": {**_COMUM, "fonte": "fonte", "natureza": "natureza",
                    "tipo de reconhecimento de passivo": "tipo_reconhecimento_passivo"},
           "ddl": """CREATE TABLE IF NOT EXISTS ne_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, ano_ne INTEGER,
    data_emissao TEXT, doc_alt TEXT, tipo_alt TEXT, status TEXT, credor TEXT, nome_credor TEXT,
    fonte TEXT, natureza TEXT, precatorio TEXT, processo TEXT, tipo_reconhecimento_passivo TEXT,
    assinatura_eletronica TEXT, valor REAL, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
           "idx": ("CREATE INDEX IF NOT EXISTS ix_ne_credor ON ne_siafe(credor)",
                   "CREATE INDEX IF NOT EXISTS ix_ne_processo ON ne_siafe(processo)")},
    "NL": {"tela": "Nota de Liquidação", "re": re.compile(r"\b20\d\dNL\d{5}P?\b"), "tabela": "nl_siafe",
           "ano": "ano_nl", "dinheiro": ("valor", "valor_retido"),
           "cols": {**_COMUM, "ne": "ne", "nl rec.": "nl_rec", "status comp.": "status_comp", "gd": "gd",
                    "valor retido": "valor_retido"},
           "ddl": """CREATE TABLE IF NOT EXISTS nl_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, ano_nl INTEGER,
    data_emissao TEXT, doc_alt TEXT, tipo_alt TEXT, status TEXT, ne TEXT, nl_rec TEXT, status_comp TEXT,
    credor TEXT, nome_credor TEXT, gd TEXT, precatorio TEXT, processo TEXT, valor_retido REAL,
    assinatura_eletronica TEXT, valor REAL, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
           "idx": ("CREATE INDEX IF NOT EXISTS ix_nl_ne ON nl_siafe(ne)",
                   "CREATE INDEX IF NOT EXISTS ix_nl_credor ON nl_siafe(credor)")},
}
# GUIA DE DEVOLUÇÃO (13/11/2026). A perícia contábil só sabe quanto voltou de uma OB devolvida quando o status é
# 'Erro no Pagamento' (devolução integral). Com GD e outro status (Parcialmente Pago, Processado e Pago…) o valor
# devolvido só existe nesta tela — Execução › Execução FINANCEIRA › Guia de Devolução, mesma grade da NE/NL
# (`tblGuiaDevolucao`, colunas lidas pela sonda `siafe_mapear` em 04/11/2026). A coluna OB é o vínculo; a chave
# inclui a UG porque o número da guia, como o da OB, se repete entre unidades.
TIPOS["GD"] = {
    "tela": "Guia de Devolução", "menu": "Execução Financeira", "tbl": "pt1:tblGuiaDevolucao",
    "re": re.compile(r"\b20\d\dGD\d{5,6}\b"), "tabela": "gd_siafe", "ano": "ano_gd", "dinheiro": ("valor",),
    "cols": {"numero": "numero", "ug emitente": "ug_emitente", "data emissao": "data_emissao",
             "tipo de baixa": "tipo_baixa", "status": "status", "cod. ug liquidante": "ug_liquidante",
             "ob": "ob", "valor": "valor"},
    "ddl": """CREATE TABLE IF NOT EXISTS gd_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, ano_gd INTEGER,
    data_emissao TEXT, tipo_baixa TEXT, status TEXT, ug_liquidante TEXT, ob TEXT, valor REAL, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
    "idx": ("CREATE INDEX IF NOT EXISTS ix_gd_ob ON gd_siafe(ob, ug_emitente)",)}
NE_RE = TIPOS["NE"]["re"]
# BLOQUEIO JUDICIAL e DESPESA DE EXERCÍCIO ANTERIOR (19/11/2026). Mesma família de grade, outro template
# (`pagTemplate:tblEntidadeDec`, sonda `siafe_mapear --detalhar` de 19/11). Chave = "Código".
#  • BJ: lista ÚNICA do Estado (sem coluna de UG; código sequencial — 105 em 19/11). Controle positivo: os códigos
#    colhidos cobrem 1..máximo (sequência sem buraco). Vínculo com OB pelo `codigo_credor` (CNPJ).
#  • DEA: por UG (coluna "UG"), código AA+6 dígitos (26011891). Fatias por "Código começa com" AA0…AA9.
TIPOS["BJ"] = {
    "tela": "Bloqueio Judicial", "menu": "Execução Financeira", "tbl": "pagTemplate:tblEntidadeDec",
    "re": re.compile(r"\b\d{1,7}\b"), "tabela": "bloqueio_judicial_siafe", "ano": None, "ug_fixa": "TODAS",
    "dinheiro": ("valor_bloqueado",),
    "cols": {"codigo": "numero", "codigo credor": "codigo_credor", "nome credor": "nome_credor",
             "valor bloqueado": "valor_bloqueado", "data bloqueio": "data_bloqueio",
             "data desbloqueio": "data_desbloqueio", "autos do bloqueio": "autos", "status": "status"},
    "ddl": """CREATE TABLE IF NOT EXISTS bloqueio_judicial_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, codigo_credor TEXT, nome_credor TEXT,
    valor_bloqueado REAL, data_bloqueio TEXT, data_desbloqueio TEXT, autos TEXT, status TEXT, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
    "idx": ("CREATE INDEX IF NOT EXISTS ix_bj_credor ON bloqueio_judicial_siafe(codigo_credor)",)}
TIPOS["DEA"] = {
    "tela": "Despesa Exercício Anterior", "menu": "Contabilidade", "tbl": "pagTemplate:tblEntidadeDec",
    "re": re.compile(r"\b\d{8}\b"), "tabela": "dea_siafe", "ano": None, "dinheiro": ("valor",),
    "prop_ug": "UG", "prop_numero": "Código", "base": lambda ex: str(int(ex))[2:],
    "cols": {"codigo": "numero", "ug": "ug_emitente", "numero termo": "numero_termo", "codigo credor": "codigo_credor",
             "status": "status", "documento registro": "doc_registro",
             "documento reconhecimento": "doc_reconhecimento", "valor": "valor"},
    "ddl": """CREATE TABLE IF NOT EXISTS dea_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, numero_termo TEXT, codigo_credor TEXT,
    status TEXT, doc_registro TEXT, doc_reconhecimento TEXT, valor REAL, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
    "idx": ("CREATE INDEX IF NOT EXISTS ix_dea_credor ON dea_siafe(codigo_credor)",
            "CREATE INDEX IF NOT EXISTS ix_dea_termo ON dea_siafe(numero_termo)")}

# OB DE RETENÇÃO e CONTRATO (19/11/2026, sonda `siafe_mapear --detalhar` de 22h41). A OB Orçamentária é a única OB
# coletada; a de Retenção (IRRF, INSS, ISS… repassados pelo Estado) e o cadastro de Contratos (com nº de aditivos e
# reajustes) ficavam fora. Mesma grade da NE/NL. Sem controle positivo EXTERNO: "completo" = o coletor fechou todas
# as fatias sem teto (como a NE antes da NL) — pô-los em SEM_CONTROLE_POSITIVO faria o sweep reler tudo todo dia.
TIPOS["OBR"] = {
    "tela": "OB de Retenção", "menu": "Execução Financeira", "tbl": "pt1:tblOrdemBancariaRetencao",
    "re": re.compile(r"\b20\d\dOB\d{5,6}\b"), "tabela": "ob_retencao_siafe", "ano": "ano_ob",
    "dinheiro": ("valor",), "base": lambda ex: f"{int(ex)}OB",
    "cols": {"numero": "numero", "ug emitente": "ug_emitente", "ug pagadora": "ug_pagadora",
             "data emissao": "data_emissao", "status": "status", "tipo": "tipo", "finalidade": "finalidade",
             "tipo de retencao": "tipo_retencao", "credor": "credor", "nome do credor": "nome_credor",
             "ug liquidante": "ug_liquidante", "valor": "valor", "competencia": "competencia",
             "status de envio": "status_envio", "gd": "gd", "processo": "processo", "re": "re", "pd": "pd",
             "tipo de regularizacao": "tipo_regularizacao"},
    "ddl": """CREATE TABLE IF NOT EXISTS ob_retencao_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, ano_ob INTEGER, ug_pagadora TEXT,
    data_emissao TEXT, status TEXT, tipo TEXT, finalidade TEXT, tipo_retencao TEXT, credor TEXT, nome_credor TEXT,
    ug_liquidante TEXT, valor REAL, competencia TEXT, status_envio TEXT, gd TEXT, processo TEXT, re TEXT, pd TEXT,
    tipo_regularizacao TEXT, coletado_em TEXT,
    PRIMARY KEY (numero, ug_emitente, exercicio))""",
    "idx": ("CREATE INDEX IF NOT EXISTS ix_obr_pd ON ob_retencao_siafe(pd)",
            "CREATE INDEX IF NOT EXISTS ix_obr_processo ON ob_retencao_siafe(processo)")}
TIPOS["CT"] = {
    "tela": "Contrato", "menu": "Contratos e Convênios", "tbl": "pt1:tblContrato",
    "re": re.compile(r"\b\d{8}\b"), "tabela": "contrato_siafe", "ano": None, "dinheiro": ("valor",),
    "prop_ug": "Cód. Contratante", "prop_numero": "Número Automático", "base": lambda ex: str(int(ex))[2:],
    "cols": {"numero automatico": "numero", "numero da licitacao": "numero_licitacao",
             "numero original": "numero_original", "natureza": "natureza", "objeto": "objeto",
             "cod. contratante": "ug_emitente", "nome contratante": "nome_contratante",
             "cod. contratado": "contratado", "modalidade de licitacao": "modalidade",
             "nome do contratado": "nome_contratado", "situacao": "situacao", "valor do contrato": "valor",
             "qtd. aditivos": "qtd_aditivos", "qtd. reajustes": "qtd_reajustes", "qtd. anexos": "qtd_anexos"},
    "ddl": """CREATE TABLE IF NOT EXISTS contrato_siafe (
    numero TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, numero_licitacao TEXT,
    numero_original TEXT, natureza TEXT, objeto TEXT, nome_contratante TEXT, contratado TEXT, modalidade TEXT,
    nome_contratado TEXT, situacao TEXT, valor REAL, qtd_aditivos TEXT, qtd_reajustes TEXT, qtd_anexos TEXT,
    coletado_em TEXT, PRIMARY KEY (numero, ug_emitente, exercicio))""",
    "idx": ("CREATE INDEX IF NOT EXISTS ix_ct_contratado ON contrato_siafe(contratado)",)}

SEM_CONTROLE_POSITIVO = {"DEA"}


def cobertura_bj_sequencia(exercicio: int, db=None) -> float | None:
    """Controle positivo do Bloqueio Judicial: o código é sequencial no Estado; colhidos ÷ maior código."""
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(TIPOS["BJ"]["ddl"])
        n, mx = con.execute("SELECT COUNT(DISTINCT numero), MAX(CAST(numero AS INTEGER)) FROM bloqueio_judicial_siafe "
                            "WHERE exercicio=?", (int(exercicio),)).fetchone()
    finally:
        con.close()
    return round(n / mx, 4) if mx else None




def _tbl(t: dict) -> str:
    return t.get("tbl", TBL)


_DDL_COB = """CREATE TABLE IF NOT EXISTS siafe_documento_cobertura (
    tipo TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, completo INTEGER NOT NULL,
    colhidas INTEGER, em TEXT, PRIMARY KEY (tipo, ug_emitente, exercicio))"""


_DDL_FATIA = """CREATE TABLE IF NOT EXISTS siafe_documento_fatia (
    tipo TEXT NOT NULL, ug_emitente TEXT NOT NULL, exercicio INTEGER NOT NULL, prefixo TEXT NOT NULL,
    linhas INTEGER NOT NULL, no_teto INTEGER NOT NULL, em TEXT, PRIMARY KEY (tipo, ug_emitente, exercicio, prefixo))"""


def registrar_fatia(tipo: str, ug: str, exercicio: int, prefixo: str, linhas: int, db=None) -> None:
    """PROVA DE COMPLETUDE por fatia (19/11/2026): quantas linhas cada prefixo-folha devolveu e se encostou no
    platô. "Completo" sem esta trilha era afirmação; com ela, qualquer um confere que nenhuma folha bateu no teto."""
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(_DDL_FATIA)
        con.execute("INSERT OR REPLACE INTO siafe_documento_fatia VALUES (?,?,?,?,?,?,?)",
                    (tipo, str(ug), int(exercicio), prefixo, int(linhas), int(linhas >= _PLATO), time.strftime("%F %T")))
        con.commit()
    finally:
        con.close()


def prefixos_incrementais(base: str, ultimo: str) -> list[str]:
    """Prefixos DISJUNTOS que cobrem todo número ≥ as 3 primeiras casas do `ultimo` já colhido (a numeração é
    sequencial por UG/ano: documento novo só nasce acima). Ex.: base 2026NL, último 2026NL01234 →
    ['2026NL012', '2026NL013'…'2026NL019', '2026NL02'…'2026NL09', '2026NL1'…'2026NL9']. Relê a fatia do último
    (pode ter ganhado irmãos) e cada fatia acima; fatia vazia custa uma consulta."""
    resto = ultimo[len(base):]
    if not ultimo.startswith(base) or len(resto) < 3 or not resto[:3].isdigit():
        return [f"{base}{d}" for d in range(10)]
    a, b, c = (int(x) for x in resto[:3])
    out = [f"{base}{a}{b}{c}"]
    out += [f"{base}{a}{b}{d}" for d in range(c + 1, 10)]
    out += [f"{base}{a}{d}" for d in range(b + 1, 10)]
    out += [f"{base}{d}" for d in range(a + 1, 10)]
    return out


def registrar_cobertura(tipo: str, ug: str, exercicio: int, completo: bool, colhidas: int, db=None) -> None:
    """Quem lê NE/NL precisa saber se a UG está INTEIRA: 166100 ficou com 1.000 NL de uma coleta capada e o
    detector de ordem cronológica acusou 346 quebras (04/11/2026). Coleta capada ou com erro = completo 0.
    Espera até 5 min pelo lock: em 19/11/2026 uma coleta de 548 s (296100/NE/2026) falhou inteira por "database is
    locked" nesta gravação de 1 linha, com o banco preso por outro escritor por mais de 60 s."""
    con = sqlite3.connect(db or _DB, timeout=300)
    try:
        con.execute(_DDL_COB)
        con.execute("INSERT OR REPLACE INTO siafe_documento_cobertura VALUES (?,?,?,?,?,?)",
                    (tipo, str(ug), int(exercicio), int(bool(completo)), int(colhidas), time.strftime("%F %T")))
        con.commit()
    finally:
        con.close()


def ugs_completas(con, tipos=("NE", "NL")) -> set[tuple[str, int]]:
    """(ug, exercicio) com TODOS os `tipos` coletados por inteiro. Sem a tabela = nenhuma (não é 'todas')."""
    try:
        linhas = con.execute("SELECT ug_emitente, exercicio, tipo FROM siafe_documento_cobertura WHERE completo=1"
                             ).fetchall()
    except sqlite3.OperationalError:
        return set()
    por: dict[tuple, set] = {}
    for ug, ex, tipo in linhas:
        por.setdefault((str(ug), int(ex)), set()).add(tipo)
    return {k for k, v in por.items() if set(tipos) <= v}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def _money(s: str) -> float | None:
    s = re.sub(r"[^\d,.\-]", "", s or "").replace(".", "").replace(",", ".")   # BJ traz "R$ 42.565.673,37"
    try:
        return float(s)
    except ValueError:
        return None


def ingerir(exercicio: int, header: list[str], linhas: list[list[str]], db=None, tipo: str = "NE") -> dict:
    """Grava as linhas colhidas. Coluna pelo nome do cabeçalho; linha sem número do documento é descartada."""
    t = TIPOS[tipo]
    idx = {}
    for i, h in enumerate(header):
        col = t["cols"].get(_norm(h))
        if col and col not in idx:
            idx[col] = i
    if "numero" not in idx or ("ug_emitente" not in idx and not t.get("ug_fixa")):
        return {"ok": False, "erro": "cabecalho_sem_numero_ou_ug", "header": header}
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(t["ddl"])
        for q in t["idx"]:
            con.execute(q)
        agora, n = time.strftime("%F %T"), 0
        for r in linhas:
            rec = {c: (r[i] if i < len(r) else "") for c, i in idx.items()}
            if not t["re"].fullmatch(rec.get("numero", "").strip()):
                continue
            for c in t["dinheiro"]:
                if c in rec:
                    rec[c] = _money(rec[c])
            # `exercicio` é o ano da CONSULTA; a tela lista também os RP com saldo (no ITERJ/2025 havia NE de
            # 2002). O ano da própria NE está no número — guardado à parte para não confundir os dois.
            rec.update({"exercicio": int(exercicio), "coletado_em": agora})
            if t.get("ano"):
                rec[t["ano"]] = int(rec["numero"][:4])
            if t.get("ug_fixa"):
                rec["ug_emitente"] = t["ug_fixa"]
            cols = ",".join(rec)
            con.execute(f"INSERT OR REPLACE INTO {t['tabela']} ({cols}) VALUES ({','.join('?' * len(rec))})",
                        list(rec.values()))
            n += 1
        con.commit()
    finally:
        con.close()
    return {"ok": True, "ingeridas": n, "colunas": sorted(idx)}


# ─────────────────────────────── navegação e colheita (precisa do SIAFE) ───────────────────────────────

async def _ir_para(pg, tela: str, tentativas: int = 4, menu: str = "Execução Orçamentária",
                  tbl: str = TBL) -> bool:
    """Navega com novas tentativas: logo após o login o menu às vezes ainda não montou (04/11/2026, 166100:
    `etapa: navegacao` em 53 s com login incluso) — o mesmo prólogo intermitente que o coletor da OB trata."""
    for i in range(tentativas):
        kw = {} if (menu, tbl) == ("Execução Orçamentária", TBL) else {"menu": menu, "tbl": tbl}
        if await _ir_para_uma_vez(pg, tela, **kw):
            return True
        await pg.wait_for_timeout(6000 * (i + 1))
    return False


async def _ir_para_uma_vez(pg, tela: str, menu: str = "Execução Orçamentária", tbl: str = TBL) -> bool:
    """Execução (pt_np4) › Execução Orçamentária (pt_np3) › <tela> — pelo TEXTO (índice de menu não é
    identidade; ver siafe1-navegacao-e-cabecalho-vivo)."""
    from tools.siafe_mapear import _JS_CLICAR, _JS_IDS, _clicar_id, _ev
    for padrao, alvo in ((r"pt_np4:\d+:pt_cni6::disclosureAnchor$", "Execução"),
                         (r"pt_np3:\d+:pt_cni4::disclosureAnchor$", menu)):
        el = [x for x in await _ev(pg, _JS_IDS, padrao) if x["t"] == alvo]
        if not el:
            return False
        await _clicar_id(pg, el[0]["id"])
    if not await _ev(pg, _JS_CLICAR, tela):
        return False
    for _ in range(60):
        await pg.wait_for_timeout(2000)
        if await _ev(pg, "()=>!!document.getElementById('" + tbl + ":tabViewerDec::db')"):
            return True
    return False


def _acao_limite(rotulo: str, marcado: bool) -> str:
    """O mesmo id `chkRemoveLimit` tem semânticas opostas conforme a tela: na NE/NL o rótulo é "Limite de 1000
    registros" e MARCADO = limite ATIVO (04/11/2026: UG 166100 parou em 1.000 com o código achando que o limite
    já estava removido). Decide pelo rótulo, não pelo id."""
    r = _norm(rotulo)
    if "remov" in r:                       # "Remover limite": marcado = sem limite
        return "nada" if marcado else "clicar"
    if "limite" in r:                      # "Limite de 1000 registros": marcado = com limite
        return "clicar" if marcado else "nada"
    return "desconhecido"


async def _remover_limite(pg, tbl: str = TBL) -> str:
    from tools.siafe_mapear import _ev
    cid = tbl + ":chkRemoveLimit::content"
    info = await _ev(pg, r"""(i)=>{const cb=document.getElementById(i); if(!cb)return null;
        const lb=document.querySelector('label[for="'+i+'"]'); const pai=cb.closest('span,div,td');
        return {marcado:cb.checked, rotulo:((lb&&lb.innerText)||(pai&&pai.innerText)||'').trim()};}""", cid)
    if not info:
        return "ausente"
    acao = _acao_limite(info["rotulo"], info["marcado"])
    if acao == "clicar":
        await _ev(pg, r"""(i)=>{const cb=document.getElementById(i);cb.click();
            cb.dispatchEvent(new Event('change',{bubbles:true}));}""", cid)
        await pg.wait_for_timeout(8000)
        return "limite_removido"
    return {"nada": "sem_limite", "desconhecido": f"rotulo_desconhecido:{info['rotulo'][:40]}"}[acao]


async def _filtrar_ug(pg, ug: str, tbl: str = TBL, rotulo: str = "UG Emi") -> dict:
    """Receita do coletor da OB (validada 2026-06-07), com o id desta tabela: Propriedade/Operador por
    typeahead, valor commitado com Tab."""
    from compliance_agent import siafe_ob_orcamentaria as S
    from compliance_agent.siafe_adf import AdfSync
    adf = AdfSync(pg)
    prop = f"{tbl}:table_rtfFilter:0:cbx_col_sel_rtfFilter::content"
    op = f"{tbl}:table_rtfFilter:0:cbx_op_sel_rtfFilter::content"
    if await pg.locator(f'[id="{prop}"]').count() == 0:
        await S._click_real(pg, f"{tbl}:sdtFilter::disAcr"); await adf.wait()
    if await pg.locator(f'[id="{prop}"]').count() == 0:
        return {"ok": False, "erro": "painel de filtro não abriu"}
    await S._typeahead(pg, prop, rotulo); await adf.wait()
    await S._typeahead(pg, op, "começa com"); await adf.wait()
    val = pg.locator('[id*="in_value_rtfFilter"]:visible').last
    if await val.count() == 0:
        return {"ok": False, "erro": "campo de valor não renderizou"}
    await val.click(); await val.press("Control+a"); await val.press("Delete")
    await pg.keyboard.type(str(ug), delay=100)
    await pg.keyboard.press("Tab")
    await adf.wait(); await pg.wait_for_timeout(4000)
    return {"ok": True, "ug": ug}


async def _colher(pg, regex, maxn: int = 20000, tbl: str = TBL) -> tuple[list[str], list[list[str]]]:
    """Rola o `::scroller` virtual e colhe o `::db` a cada passo (a tabela só tem ~50 linhas no DOM)."""
    from tools.siafe_mapear import _ev
    header = await _ev(pg, r"""()=>{const h=document.getElementById('""" + tbl + r""":tabViewerDec::ch');
        return h?[...h.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x):[];}""")
    js_rows = (r"""()=>{const db=document.getElementById('""" + tbl + r""":tabViewerDec::db');const o=[];
        if(db)db.querySelectorAll('tr').forEach(tr=>{const t=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'')
        .replace(/\s+/g,' ').trim());if(t.some(x=>x))o.push(t);});return o;}""")
    sc = tbl + ":tabViewerDec::scroller"
    vistos, linhas, y, seco = set(), [], 0, 0
    while len(linhas) < maxn and seco < 10:
        novos = 0
        for r in await _ev(pg, js_rows):
            m = regex.search(" ".join(r[:2]))
            if m and m.group(0) not in vistos:
                vistos.add(m.group(0)); linhas.append(r); novos += 1
        seco = 0 if novos else seco + 1
        geo = await _ev(pg, "()=>{const s=document.getElementById('" + sc + "');"
                            "return s?{sh:s.scrollHeight,ch:s.clientHeight}:null;}") or {"sh": 0, "ch": 700}
        y += int(max(geo["ch"], 300) * 0.7)
        await _ev(pg, "()=>{const s=document.getElementById('" + sc + "');if(s){s.scrollTop=" + str(y)
                  + ";s.dispatchEvent(new Event('scroll',{bubbles:true}));}}")
        await pg.wait_for_timeout(1100)
        if y >= geo["sh"] - geo["ch"] and not novos:
            break
    return header, linhas


def _fatia_casa(linhas: list[list[str]], prefixo: str, regex) -> bool:
    """As linhas de uma fatia têm de começar com o prefixo filtrado — senão o filtro de Número não aplicou e a
    página veio sem filtro. Vazio é aceitável (fim da série de números)."""
    nums = [m.group(0) for r in linhas if (m := regex.search(" ".join(r[:2])))]
    return not nums or sum(n.startswith(prefixo) for n in nums) >= 0.95 * len(nums)


def cobertura_pela_ob(ug: str, exercicio: int, db=None) -> float | None:
    """Fração das NL citadas pelas OBs pagas (UG, exercício) que estão em `nl_siafe` — o controle positivo da
    completude da NL. None se não há OB para comparar."""
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        tot, ach = con.execute(
            "SELECT COUNT(DISTINCT o.nl), COUNT(DISTINCT l.numero) FROM ob_orcamentaria_siafe o LEFT JOIN nl_siafe l "
            "ON l.numero=o.nl AND l.ug_emitente=o.ug_emitente WHERE o.ug_emitente=? AND o.exercicio=? "
            "AND o.status='Contabilizado' AND o.nl LIKE ?", (str(ug), int(exercicio), f"{exercicio}NL%")).fetchone()
    finally:
        con.close()
    return round(ach / tot, 4) if tot else None


def cobertura_gd_pela_ob(ug: str, exercicio: int, db=None) -> float | None:
    """Fração das GD que as OBs da (UG, exercício) citam na coluna `gd` e que estão em `gd_siafe` com a MESMA OB —
    o controle positivo da GD, como o da NL. None se nenhuma OB cita GD (nada a conferir)."""
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(TIPOS["GD"]["ddl"])
        tot, ach = con.execute(
            # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
            "SELECT COUNT(DISTINCT o.gd), COUNT(DISTINCT g.numero) FROM ob_orcamentaria_siafe o LEFT JOIN gd_siafe g "
            "ON g.numero=o.gd AND g.ug_emitente=o.ug_emitente AND g.ob=o.numero_ob WHERE o.ug_emitente=? "
            "AND o.exercicio=? AND o.gd LIKE ?", (str(ug), int(exercicio), f"{exercicio}GD%")).fetchone()
    finally:
        con.close()
    return round(ach / tot, 4) if tot else None


def cobertura_ne_pela_nl(ug: str, exercicio: int, db=None) -> float | None:
    """Fração das NE (do próprio exercício) citadas pelas NL da (UG, exercício) que estão em `ne_siafe` — o
    controle positivo da NE (a NE não tem OB que a cite; a NL tem). None se não há NL para comparar."""
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        for tipo in ("NE", "NL"):
            con.execute(TIPOS[tipo]["ddl"])
        tot, ach = con.execute(
            "SELECT COUNT(DISTINCT l.ne), COUNT(DISTINCT e.numero) FROM nl_siafe l LEFT JOIN ne_siafe e "
            "ON e.numero=l.ne AND e.ug_emitente=l.ug_emitente WHERE l.ug_emitente=? AND l.exercicio=? "
            "AND l.ne LIKE ?", (str(ug), int(exercicio), f"{exercicio}NE%")).fetchone()
    finally:
        con.close()
    return round(ach / tot, 4) if tot else None


def _ne_registrada_completa(ug: str, exercicio: int, db=None) -> bool:
    con = sqlite3.connect(db or _DB, timeout=60)
    try:
        con.execute(_DDL_COB)
        r = con.execute("SELECT completo FROM siafe_documento_cobertura WHERE tipo='NE' AND ug_emitente=? "
                        "AND exercicio=?", (str(ug), int(exercicio))).fetchone()
    finally:
        con.close()
    return bool(r and r[0])


def fechar_cobertura(tipo: str, ug: str, exercicio: int, r: dict, db=None) -> bool:
    """Registra se a (UG, exercício) ficou INTEIRA. O coletor dizer "completo" não basta: NL e GD conferem contra
    o que as OBs citam (≥95%). Devolve o `completo` registrado e põe a cobertura medida em `r`."""
    n = r.get("colhidas", r.get("ingeridas", 0))
    completo = bool(r.get("ok")) and not r.get("capou")
    medir = {"NL": cobertura_pela_ob, "GD": cobertura_gd_pela_ob,
             "BJ": lambda _ug, ex, db=None: cobertura_bj_sequencia(ex, db=db)}.get(tipo)
    if completo and medir:
        cob = medir(ug, exercicio, db=db)
        r["cobertura_pela_ob"] = cob
        completo = cob is None or cob >= _COBERTURA_MIN
    # DEA: o código é sequência do ESTADO (UG 045200 tem 26001388…26011891 com buracos de outras UGs) e nada
    # cita a DEA de fora — sem controle positivo, a coleta fica PENDENTE (lida, não provada inteira).
    if tipo in SEM_CONTROLE_POSITIVO and completo:
        r["sem_controle_positivo"] = True
        completo = False
    if tipo == "NE" and completo:
        cob = cobertura_ne_pela_nl(ug, exercicio, db=db)
        r["cobertura_pela_nl"] = cob
        completo = cob is None or cob >= _COBERTURA_MIN
    registrar_cobertura(tipo, ug, exercicio, completo, n or 0, db=db)
    # a NL completa CONFERE a NE já registrada completa: NE que não cobre as NE citadas pelas NL era parcial
    if tipo == "NL" and completo and _ne_registrada_completa(ug, exercicio, db=db):
        cob_ne = cobertura_ne_pela_nl(ug, exercicio, db=db)
        r["cobertura_ne_pela_nl"] = cob_ne
        if cob_ne is not None and cob_ne < _COBERTURA_MIN:
            con = sqlite3.connect(db or _DB, timeout=60)
            try:
                con.execute("UPDATE siafe_documento_cobertura SET completo=0, em=? WHERE tipo='NE' AND "
                            "ug_emitente=? AND exercicio=?", (time.strftime("%F %T"), str(ug), int(exercicio)))
                con.commit()
            finally:
                con.close()
            r["ne_rebaixada"] = True
    return completo


def _subdividir(prefixo: str, n: int, base_len: int) -> list[str]:
    """Fatia que encosta no teto vira 10 fatias filhas, até 3 dígitos após o tipo (mesma regra da OB)."""
    if n >= _PLATO and len(prefixo) < base_len + 3:
        return [f"{prefixo}{d}" for d in range(10)]
    return []


def prazo_absoluto(ate: str, inicio: datetime) -> datetime:
    """`HH:MM` → data/hora absoluta. Prazo anterior (ou igual) à hora de início é o da madrugada SEGUINTE: o cron
    das 23:20 com `--ate 02:55` parava na hora, porque "23:20" >= "02:55" como texto (laudo 13/11/2026)."""
    h, m = (int(x) for x in ate.split(":"))
    alvo = inicio.replace(hour=h, minute=m, second=0, microsecond=0)
    return alvo + timedelta(days=1) if alvo <= inicio else alvo


def _normalizar_prazo(ate: str | None, inicio: datetime) -> str | None:
    """`HH:MM` vira `AAAA-MM-DDTHH:MM` relativo ao início; o que já é absoluto passa como veio."""
    if not ate or "T" in ate:
        return ate
    return prazo_absoluto(ate, inicio).strftime("%Y-%m-%dT%H:%M")


def _passou(ate: str | None) -> bool:
    if not ate:
        return False
    if "T" in ate:                       # prazo absoluto (vindo da varredura ou normalizado no main)
        return time.strftime("%Y-%m-%dT%H:%M") >= ate
    return time.strftime("%H:%M") >= ate


async def _colher_fatiado(pg, t: dict, exercicio: int, tipo: str, ate: str | None = None,
                          ug_ckpt: str = "", a_partir: str | None = None) -> dict:
    """Linha 1 do filtro = Número começa com <prefixo>; fatia capada subdivide. Ingesta fatia a fatia."""
    from compliance_agent import siafe_ob_orcamentaria as S
    from compliance_agent.siafe_adf import AdfSync
    adf = AdfSync(pg)
    if not await S._esperar_linha_filtro(pg, 1, adf):
        return {"ok": False, "etapa": "filtro_linha1"}
    tbl = _tbl(t)
    await S._typeahead(pg, f"{tbl}:table_rtfFilter:1:cbx_col_sel_rtfFilter::content", t.get("prop_numero", "Número"))
    await adf.wait()
    await S._typeahead(pg, f"{tbl}:table_rtfFilter:1:cbx_op_sel_rtfFilter::content", "começa com"); await adf.wait()
    base = t["base"](exercicio) if t.get("base") else f"{exercicio}{tipo}"
    ckp = _REPO / "data" / "sei_cache" / f"siafe_doc_{tipo}_{ug_ckpt}_{exercicio}.json"
    feitas = set(json.loads(ckp.read_text())) if ckp.exists() else set()
    inicio = prefixos_incrementais(base, a_partir) if a_partir else [f"{base}{d}" for d in range(10)]
    work, fatias, total, capadas = inicio, {}, 0, []
    while work:
        if _passou(ate):               # para ENTRE fatias e sai pelo `finally` com logout: nunca no meio
            return {"ok": False, "etapa": "prazo", "ate": ate, "fatias": fatias, "ingeridas": total,
                    "faltam": len(work)}
        pref = work.pop(0)
        if pref in feitas:             # retomada: fatia folha já colhida numa passada anterior (UG gigante)
            continue
        await S._set_valor(pg, '[id*="table_rtfFilter:1"] input[type="text"]:visible', pref)
        await adf.wait(); await pg.wait_for_timeout(4000)
        header, linhas = await _colher(pg, t["re"], tbl=tbl)
        if not _fatia_casa(linhas, pref, t["re"]):
            return {"ok": False, "etapa": "filtro_numero_nao_aplicou", "fatia": pref, "fatias": fatias,
                    "ingeridas": total}
        filhas = _subdividir(pref, len(linhas), len(base))
        if filhas:
            work[:0] = filhas
            continue
        if len(linhas) >= _PLATO:
            capadas.append(pref)               # profundidade máxima e ainda no teto: declarar, não esconder
        fatias[pref] = len(linhas)
        total += ingerir(exercicio, header, linhas, tipo=tipo).get("ingeridas", 0)
        if ug_ckpt:
            registrar_fatia(tipo, ug_ckpt, exercicio, pref, len(linhas))
        if linhas:                     # ZERO NÃO ENTRA NO CHECKPOINT (lição da OB, ae72a7bf): re-consultar é barato
            feitas.add(pref)
            ckp.parent.mkdir(parents=True, exist_ok=True)
            ckp.write_text(json.dumps(sorted(feitas)))
    ckp.unlink(missing_ok=True)        # UG fechou: a próxima passada começa limpa
    return {"ok": True, "fatias": fatias, "ingeridas": total, "capadas": capadas, "retomadas": len(feitas)}


async def coletar_ug(ug: str, exercicio: int, tipo: str = "NE", ate: str | None = None,
                     a_partir: str | None = None) -> dict:
    """Uma UG inteira; com `a_partir` (último número já colhido de uma UG completa) só os números acima —
    a passada INCREMENTAL do exercício corrente, que não relê o que não muda."""
    t = TIPOS[tipo]
    from playwright.async_api import async_playwright
    from compliance_agent import siafe_ob_orcamentaria as S
    from compliance_agent.recursos import browser_lock_async
    # o MESMO lock de navegador do coletor da OB e do dreno: o lock do siafe_runner sozinho não os segura,
    # e duas sessões na mesma conta derrubam uma à outra (sessão única por IP).
    async with browser_lock_async(nome="siafe", espera_max=900), async_playwright() as pw:
        ctx, pg = await S._novo_browser(pw, headless=True)
        try:
            lg = await S._login(pg, exercicio)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", "erro": lg.get("erro")}
            if not await _ir_para(pg, t["tela"], menu=t.get("menu", "Execução Orçamentária"), tbl=_tbl(t)):
                return {"ok": False, "etapa": "navegacao"}
            lim = await _remover_limite(pg, tbl=_tbl(t))
            if not t.get("ug_fixa"):            # lista única do Estado (BJ) não tem coluna de UG
                f = await _filtrar_ug(pg, ug, tbl=_tbl(t), rotulo=t.get("prop_ug", "UG Emi"))
                if not f.get("ok"):
                    return {"ok": False, "etapa": "filtro", **f}
            header, linhas = ([], []) if a_partir else await _colher(pg, t["re"], tbl=_tbl(t))
            if not a_partir and len(linhas) < _PLATO:
                r = ingerir(exercicio, header, linhas, tipo=tipo)
                return {**r, "tipo": tipo, "ug": ug, "exercicio": exercicio, "colhidas": len(linhas),
                        "limite": lim, "capou": False}
            # TETO DO SERVIDOR: desmarcar o limite não basta (166100/2025 parou em 1.000 de novo). Fatiar.
            fat = await _colher_fatiado(pg, t, exercicio, tipo, ate, ug_ckpt=ug, a_partir=a_partir)
        finally:
            await S._encerrar(pg, ctx)
    return {**fat, "tipo": tipo, "ug": ug, "exercicio": exercicio, "limite": lim, "fatiado": True,
            "incremental_a_partir": a_partir,
            "capou": bool(fat.get("capadas")),
            "aviso": ("fatias no teto mesmo na profundidade máxima: " + ", ".join(fat["capadas"])
                      if fat.get("capadas") else "")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", choices=sorted(TIPOS), default="NE")
    ap.add_argument("--ug", required=True)
    ap.add_argument("--exercicio", type=int, required=True)
    ap.add_argument("--ate", default=None, help="HH:MM — para entre fatias (com logout) a partir deste horário")
    ap.add_argument("--a-partir", default=None, help="último número colhido: só os acima (incremental)")
    a = ap.parse_args()
    a.ate = _normalizar_prazo(a.ate, datetime.now())
    from compliance_agent import host_siafe
    from compliance_agent import siafe_runner as R
    host_siafe.exigir_autorizacao()
    if not R._acquire("siafe_documento"):
        raise SystemExit(f"SIAFE ocupado: {R.lock_status()}")
    try:
        r = asyncio.run(coletar_ug(a.ug, a.exercicio, a.tipo, a.ate, a_partir=a.a_partir))
        fechar_cobertura(a.tipo, a.ug, a.exercicio, r)
        print(json.dumps(r, ensure_ascii=False))
    finally:
        R._release()


if __name__ == "__main__":
    main()
