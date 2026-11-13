# -*- coding: utf-8 -*-
"""Aba "Governo Couto" — tudo o que a base do JFN tem sobre a gestão do governador em exercício (Estado › Governo Couto).

Pedido do dono (13/11/2026): "uma aba especialmente pra tudo que foi feito durante a gestão".

INÍCIO DA GESTÃO = 23/03/2026, INTERINA. Fonte primária: DOERJ Parte II de 24/03/2026 (Ofício nº 44/2026 —
renúncia do governador anterior ao cargo, despachada pela Mesa da ALERJ em 23/03/2026) e DOERJ Parte I de 24/03/2026
(primeiros atos assinados "Governador em exercício"). Imprensa do dia 23/03/2026 confirma a assunção interina pelo
presidente do TJRJ (sem vice-governador e com a presidência da ALERJ vaga). 23/03 é dia de TRANSIÇÃO: há decretos
datados de 23/03 assinados pelo governador anterior — por isso os atos são recortados pela ASSINATURA ("Governador em
exercício"), não só pela data.

Regras da casa aplicadas aqui:
  · pagamento = SÓ OB do SIAFE com status "Contabilizado" (`ob_orcamentaria_siafe`); empenho nunca é "pago";
    OB Anulada/Excluída/Não contabilizada fica fora e é contada à parte.
  · valor de contrato = valor CONTRATADO (espelho TCE-RJ), nunca chamado de pago.
  · INDISPONÍVEL ≠ zero: bloco que falha devolve estado "indisponivel" com o erro; o placar mostra "—".
  · CPF de pessoa física sempre mascarado. Indício não é acusação.
"""
from __future__ import annotations

import logging
import json
import os
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
DB_ACHADOS = RAIZ / "data" / "achados.db"
DB_ABERTOS = RAIZ / "data" / "dadosabertos_rj.db"
SUSPEITAS = RAIZ / "data" / "governo_couto_suspeitas.json"
VAULT_CASOS = Path(os.environ.get("JFN_VAULT_CASOS") or Path.home() / "vault" / "casos")

INICIO = "2026-03-23"
GESTAO = {
    "inicio": INICIO, "interina": True,
    "fonte": ("DOERJ Parte II, 24/03/2026 — Ofício nº 44/2026 (renúncia do governador anterior, despachado pela Mesa "
              "da ALERJ em 23/03/2026); DOERJ Parte I, 24/03/2026 — primeiros decretos assinados \"Governador em "
              "exercício\". Assunção interina pelo presidente do TJRJ (sem vice-governador; presidência da ALERJ vaga)."),
    "transicao": ("23/03/2026 é dia de transição: decretos datados de 23/03 ainda saíram assinados pelo governador "
                  "anterior. Atos do governador são recortados pela assinatura \"Governador em exercício\"; contratos "
                  "e OB, pela data (a partir de 23/03/2026)."),
}

_MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
          "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}
# "Governador em exercício" na assinatura — o anterior assinava só "Governador"
_ASSIN = re.compile(r"Governador\s+em\s+exerc[íi]cio", re.I)
_DEC_NUM = re.compile(r"D\s?E\s?C\s?R\s?E\s?T\s?O\s+N[º°o\.]*\s*(\d{2}\.?\d{3})\s*,?\s*DE\s+(\d{1,2})\s+DE\s+"
                      r"([A-ZÇ]+)\s+DE\s+(20\d\d)")
_DEC_SEM = re.compile(r"D\s?E\s?C\s?R\s?E\s?T\s?O\s+DE\s+(\d{1,2})\s+DE\s+([A-ZÇ]+)\s+DE\s+(20\d\d)")
_ATO = re.compile(r"\b(NOMEAR|EXONERAR)\b\s*,?\s*(?:a\s+pedido,?\s*)?(?P<nome>[A-ZÀ-Ü][A-ZÀ-Ü' .\-]{3,80}?)\s*,"
                  r"\s*(?:ID\s+FUNCIONAL[^,]*,\s*)?(?P<resto>.{0,420})", re.S)
_CARGO = re.compile(r"cargo\s+(?:em\s+comissão\s+)?de\s+(?P<cargo>[^,]{3,90}?),\s*símbolo\s+(?P<simb>[A-Z0-9\-]+)"
                    r"\s*,\s*(?:d[aoe]s?\s+)?(?P<org>[^.]{3,200})", re.I | re.S)
_ESCALAO = re.compile(r"^(Secretári[oa]\s+de\s+Estado|Subsecretári[oa]|Presidente|Diretor[a]?[- ]Presidente|"
                      r"Procurador[a]?-Geral|Controlador[a]?-Geral)", re.I)
_CATEG = (
    ("orçamentário", r"CRÉDITO\s+(SUPLEMENTAR|ESPECIAL|EXTRAORDIN)|REMANEJ|CONTINGENC|PROGRAMAÇÃO\s+(ORÇAMENT|FINANC)"
                     r"|LIMITES?\s+DE\s+(EMPENHO|MOVIMENTAÇÃO|PAGAMENTO)|ORÇAMENT|QUADRO\s+DE\s+DETALHAMENTO"),
    ("auditoria e controle", r"AUDITORIA|CONTROLE\s+INTERNO|INTEGRIDADE|CORREGEDORIA|TRANSPARÊNCIA"),
    ("emergência e calamidade", r"EMERGÊNCIA|CALAMIDADE"),
    ("desapropriação e servidão", r"UTILIDADE\s+PÚBLICA|DESAPROPRIA|SERVIDÃO"),
    ("estrutura e cargos", r"CARGOS?\s+EM\s+COMISSÃO|ESTRUTURA|TRANSFORMA|ORGANIZA|EXTINGUE|CRIA\s+(A|O)\s"),
    ("ponto facultativo e expediente", r"PONTO\s+FACULTATIVO|FACULTATIVO\s+O\s+PONTO|EXPEDIENTE"),
)
_RS = re.compile(r"R\$\s*([\d.]+,\d{2})")

_CACHE: dict = {}
_TTL = 1800


# ── utilidades ──────────────────────────────────────────────────────────────────────────────────────────────────
def _ro(caminho: Path) -> sqlite3.Connection | None:
    if not Path(caminho).exists():
        return None
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _normalizar(t: str) -> str:
    """Junta palavra partida no fim da linha ("sím-\\nbolo") e colapsa espaços."""
    t = re.sub(r"(?<=[a-zà-ü])-\s*\n\s*(?=[a-zà-ü])", "", t or "")
    return re.sub(r"\s+", " ", t)


def _limpar_ementa(t: str) -> str:
    t = re.sub(r"(?<=[A-ZÀ-Ü])- (?=[A-ZÀ-Ü])", "", t)          # "PA- RA" → "PARA" (hifenização do diário)
    return mascarar_texto(t.strip(" .,;:-"))


def mascarar_texto(t: str) -> str:
    from compliance_agent.osint.vinculos import mascarar_cpf
    return mascarar_cpf(t)


def _mascarar_tudo(x):
    """Último passo antes de sair: todo texto do payload passa pela máscara de CPF (MEI traz o CPF no NOME)."""
    if isinstance(x, str):
        return mascarar_texto(x)
    if isinstance(x, dict):
        return {k: _mascarar_tudo(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_mascarar_tudo(v) for v in x]
    return x


def doc_exibivel(doc: str) -> tuple[str, str]:
    """(tipo, documento exibível). 11 dígitos = pessoa física → CPF mascarado."""
    d = "".join(ch for ch in str(doc or "") if ch.isdigit())
    if len(d) == 11:
        return "CPF", mascarar_texto(d)
    if len(d) == 14:
        return "CNPJ", d
    return "UG/outro", str(doc or "")


def _iso(dia: str, mes: str, ano: str) -> str | None:
    m = _MESES.get(unicodedata.normalize("NFC", mes.upper()))
    return f"{ano}-{m:02d}-{int(dia):02d}" if m else None


def _categoria(ementa: str) -> str:
    for nome, rx in _CATEG:
        if re.search(rx, ementa, re.I):
            return nome
    return "normativo e outros"


def _valor_br(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _sem_acento(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s or "") if unicodedata.category(ch) != "Mn").upper()


# ── parsers do DOERJ ────────────────────────────────────────────────────────────────────────────────────────────
def _blocos(rx: re.Pattern, texto: str):
    ms = list(rx.finditer(texto))
    for i, m in enumerate(ms):
        yield m, texto[m.end():(ms[i + 1].start() if i + 1 < len(ms) else len(texto))]


def extrair_decretos(texto: str) -> list[dict]:
    """Decretos NUMERADOS assinados "Governador em exercício", datados a partir do início da gestão.

    Decreto apenas CITADO ("Decreto nº X, de ... de 2007") não conta: exige ano corrente, data no período e
    a ementa logo após o cabeçalho (cabeçalho seguido de vírgula = citação)."""
    t, out = _normalizar(texto), []
    for m, corpo in _blocos(_DEC_NUM, t):
        data = _iso(m.group(2), m.group(3), m.group(4))
        if not data or data < INICIO or corpo.lstrip()[:1] in (",", ";", ")") or not _ASSIN.search(corpo):
            continue
        ementa = _limpar_ementa(re.split(r"O\s+GOVERNADOR", corpo, maxsplit=1, flags=re.I)[0][:600])
        num = m.group(1).replace(".", "")
        v = _RS.search(ementa)
        out.append({"numero": f"{num[:-3]}.{num[-3:]}", "data": data, "ementa": ementa,
                    "categoria": _categoria(ementa), "valor_ementa": _valor_br(v.group(1)) if v else None})
    return out


def extrair_atos_pessoal(texto: str) -> list[dict]:
    """Nomeações e exonerações do PRIMEIRO ESCALÃO (secretário de Estado, subsecretário, presidente/dirigente,
    procurador-geral, controlador-geral) em decretos sem número assinados "Governador em exercício"."""
    t, out = _normalizar(texto), []
    for m, corpo in _blocos(_DEC_SEM, t):
        data = _iso(*m.groups())
        if not data or data < INICIO or not _ASSIN.search(corpo):
            continue
        for a in _ATO.finditer(corpo):
            cg = _CARGO.search(a.group("resto"))
            if not cg:
                continue
            cargo = cg.group("cargo").strip()
            if cg.group("simb").upper() != "SE" and not _ESCALAO.match(cargo):
                continue
            org = re.split(r"\s*,?\s*(?:Processo|em\s+vaga|sem\s+prejuízo|anteriormente)", cg.group("org"), maxsplit=1)[0]
            out.append({"ato": a.group(1), "nome": a.group("nome").strip(), "cargo": cargo,
                        "simbolo": cg.group("simb"), "orgao": org.strip(" ,;"), "data": data})
    return out


# ── blocos ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _atos(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        "SELECT p.id, p.data_publicacao, p.texto, p.url_fonte FROM fts_doerj f JOIN publicacoes_doerj p "
        "ON p.id=f.rowid WHERE fts_doerj MATCH '\"governador em exercicio\"' AND p.data_publicacao >= ? "
        "ORDER BY p.data_publicacao, p.id", (INICIO,)).fetchall()
    decs: dict[str, dict] = {}
    pessoal: dict[tuple, dict] = {}
    for r in rows:
        for d in extrair_decretos(r["texto"]):
            decs.setdefault(d["numero"], {**d, "publicado": r["data_publicacao"], "url": r["url_fonte"],
                                          "id_doerj": r["id"]})
        for a in extrair_atos_pessoal(r["texto"]):
            k = (a["ato"], a["nome"], a["cargo"].lower(), a["data"])
            pessoal.setdefault(k, {**a, "publicado": r["data_publicacao"], "url": r["url_fonte"]})
    lista = sorted(decs.values(), key=lambda d: int(d["numero"].replace(".", "")))
    nums = [int(d["numero"].replace(".", "")) for d in lista]
    faltam = sorted(set(range(min(nums), max(nums) + 1)) - set(nums)) if nums else []
    cob = con.execute("SELECT MIN(data_publicacao), MAX(data_publicacao), COUNT(DISTINCT data_publicacao) "
                      "FROM publicacoes_doerj WHERE data_publicacao >= ?", (INICIO,)).fetchone()
    orc = [d for d in lista if d["categoria"] == "orçamentário"]
    return {
        "estado": "ok" if lista or pessoal else "parcial",
        "fonte": "DOERJ (base publicacoes_doerj do JFN) — atos assinados \"Governador em exercício\"",
        "cobertura": (f"DOERJ coletado de {cob[0] or '—'} a {cob[1] or '—'} ({cob[2]} dias de edição no período). "
                      f"{len(lista)} decretos numerados localizados no texto"
                      + (f", da numeração {lista[0]['numero']} a {lista[-1]['numero']}: {len(faltam)} números do "
                         f"intervalo NÃO foram localizados (cabeçalho partido entre páginas ou edição não coletada) "
                         f"— não significa que não existam." if lista else ".")
                      + " Pessoal: só 1º escalão (secretário, subsecretário, presidente, procurador-geral, "
                        "controlador-geral) casado pelo extrator; a lista pode estar incompleta."),
        "decretos": lista, "n_faltam_no_intervalo": len(faltam), "faltam_amostra": faltam[:40],
        "por_categoria": dict(Counter(d["categoria"] for d in lista).most_common()),
        "n_orcamentarios": len(orc), "valor_orcamentario_ementas": round(sum(d["valor_ementa"] or 0 for d in orc), 2),
        "pessoal": sorted(pessoal.values(), key=lambda a: (a["data"], a["ato"] != "EXONERAR")),
    }


def _modalidade(direta: tuple | None, objeto: str) -> str:
    if direta:
        afast, enq = (direta[0] or ""), (direta[1] or "")
        if "inexig" in afast.lower():
            return "Inexigibilidade"
        if re.search(r"Art\.?\s*75,?\s*VIII\b", enq):
            return "Dispensa — emergencial (art. 75, VIII)"
        return "Dispensa"
    return "Licitação ou sem registro de contratação direta"


def _marcas_por_cnpj(con: sqlite3.Connection, con_ach: sqlite3.Connection | None, cnpjs: set[str]) -> dict:
    marcas: dict[str, list] = defaultdict(list)
    if not cnpjs:
        return marcas
    lista = sorted(cnpjs)
    for i in range(0, len(lista), 500):
        lote = lista[i:i + 500]
        q = ",".join("?" * len(lote))
        try:
            for r in con.execute(f"SELECT cnpj, MAX(grau) g, SUM(total_pago) t FROM pericia_fornecedor WHERE cnpj IN "
                                 f"({q}) AND grau IN ('🔴','🟡') GROUP BY cnpj", lote):
                marcas[r[0]].append({"fonte": "perícia", "grau": "🔴" if "🔴" in str(r[1]) else r[1],
                                     "rotulo": "Perícia de fornecedor"})
        except sqlite3.OperationalError as exc:
            logger.warning("governo_couto: perícias indisponíveis para as marcas: %s", exc)
        if con_ach is not None:
            try:
                for r in con_ach.execute(f"SELECT processo, detector, motivo FROM achado_detector WHERE status="
                                         f"'confirmado' AND processo IN ({q})", lote):
                    marcas[r[0]].append({"fonte": "detector", "grau": "🟡",
                                         "rotulo": f"Detector {r[1]}: {(r[2] or '')[:120]}"})
            except sqlite3.OperationalError as exc:
                logger.warning("governo_couto: detectores indisponíveis para as marcas: %s", exc)
    return marcas


def _contratacoes(con: sqlite3.Connection, con_ach: sqlite3.Connection | None) -> dict:
    diretas = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT sei_norm, afastamento, enquadramento_legal FROM compras_diretas_tcerj WHERE sei_norm IS NOT NULL")}
    rows = con.execute(
        "SELECT processo, sei_norm, substr(data_contratacao,1,10) d, valor_contrato, status, unidade, objeto, "
        "fornecedor, cnpj FROM contratos_tcerj WHERE substr(data_contratacao,1,10) >= ?", (INICIO,)).fetchall()
    validos = [r for r in rows if (r["status"] or "") != "Cancelado"]
    cnpjs = {"".join(ch for ch in str(r["cnpj"] or "") if ch.isdigit()) for r in validos}
    marcas = _marcas_por_cnpj(con, con_ach, {c for c in cnpjs if len(c) == 14})
    lista, por_org, por_mod = [], defaultdict(lambda: [0, 0.0, 0]), defaultdict(lambda: [0, 0.0])
    for r in validos:
        mod = _modalidade(diretas.get(r["sei_norm"]), r["objeto"] or "")
        doc = "".join(ch for ch in str(r["cnpj"] or "") if ch.isdigit())
        tipo, exib = doc_exibivel(doc)
        v = float(r["valor_contrato"] or 0)
        org = (r["unidade"] or "—").strip()
        por_org[org][0] += 1
        por_org[org][1] += v
        por_org[org][2] += mod != "Licitação ou sem registro de contratação direta"
        por_mod[mod][0] += 1
        por_mod[mod][1] += v
        lista.append({"processo": r["processo"], "data": r["d"], "valor": v, "status": r["status"], "orgao": org,
                      "objeto": mascarar_texto((r["objeto"] or "")[:240]), "fornecedor": r["fornecedor"] or "",
                      "doc_tipo": tipo, "doc": exib, "modalidade": mod,
                      "emergencial_no_objeto": bool(re.search(r"EMERG", _sem_acento(r["objeto"] or ""))),
                      "marcas": marcas.get(doc, []) if tipo == "CNPJ" else []})
    lista.sort(key=lambda x: -x["valor"])
    adit = con.execute("SELECT numero_controle_pncp, numero_termo, objeto, valor_acrescido, data_assinatura, "
                       "tipo_termo, processo FROM contrato_aditivo WHERE substr(data_assinatura,1,10) >= ? "
                       "ORDER BY COALESCE(valor_acrescido,0) DESC", (INICIO,)).fetchall()
    ult_adit = con.execute("SELECT MAX(substr(data_assinatura,1,10)) FROM contrato_aditivo").fetchone()[0]
    ult_ctr = con.execute("SELECT MAX(substr(data_contratacao,1,10)) FROM contratos_tcerj").fetchone()[0]
    destaque = [x for x in lista if x["modalidade"] != "Licitação ou sem registro de contratação direta"
                or x["emergencial_no_objeto"] or x["marcas"]]
    return {
        "estado": "ok",
        "fonte": ("Espelho de contratações do TCE-RJ (contratos_tcerj) + contratações diretas do TCE-RJ "
                  "(compras_diretas_tcerj, por nº SEI) + termos aditivos do PNCP (contrato_aditivo); marcas = perícia "
                  "de fornecedor 🔴/🟡 e achados confirmados dos detectores do JFN."),
        "cobertura": (f"Contratações com data a partir de {INICIO}; última data no espelho: {ult_ctr or '—'}. Valor = "
                      f"CONTRATADO, não pago. Modalidade: o espelho não publica a modalidade — dispensa/inexigibilidade "
                      f"vem do cruzamento com as compras diretas do TCE-RJ pelo nº SEI; sem cruzamento = \"licitação ou "
                      f"sem registro\". Aditivos: só o que o PNCP publicou (último termo coletado: {ult_adit or '—'}) "
                      f"— cobertura parcial, não é o universo de aditivos."),
        "n": len(lista), "valor": round(sum(x["valor"] for x in lista), 2),
        "n_cancelados": len(rows) - len(validos),
        "por_modalidade": sorted(({"modalidade": k, "n": v[0], "valor": round(v[1], 2)} for k, v in por_mod.items()),
                                 key=lambda x: -x["valor"]),
        "por_orgao": sorted(({"orgao": k, "n": v[0], "valor": round(v[1], 2), "n_diretas": v[2]}
                             for k, v in por_org.items()), key=lambda x: -x["valor"]),
        "n_diretas": sum(1 for x in lista if x["modalidade"] != "Licitação ou sem registro de contratação direta"),
        "valor_diretas": round(sum(x["valor"] for x in lista
                                   if x["modalidade"] != "Licitação ou sem registro de contratação direta"), 2),
        "n_marcadas": sum(1 for x in lista if x["marcas"]),
        "lista": destaque[:300], "n_destaques": len(destaque),
        "aditivos": {"n": len(adit), "valor_acrescido": round(sum(float(a[3] or 0) for a in adit), 2),
                     "ultimo_coletado": ult_adit,
                     "lista": [{"pncp": a[0], "termo": a[1], "objeto": mascarar_texto((a[2] or "")[:200]),
                                "valor_acrescido": a[3], "data": (a[4] or "")[:10], "tipo": a[5], "processo": a[6]}
                               for a in adit[:60]]},
    }


_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"


def _execucao(con: sqlite3.Connection, con_ab: sqlite3.Connection | None) -> dict:
    """UMA varredura por exercício (a VM tem 2 vCPU): agrupa por UG × credor × status e agrega em Python."""
    from compliance_agent.comissao_orcamento import nomes_orgao, ug_para_orgao
    ano = int(INICIO[:4])
    grupos = con.execute(
        f"SELECT ug_emitente, credor, MAX(nome_credor), status, COUNT(*), SUM(valor), MAX({_OB_ISO}), MAX(coletado_em) "
        f"FROM ob_orcamentaria_siafe WHERE exercicio=? AND {_OB_ISO} >= ? GROUP BY 1, 2, 4",
        (ano, INICIO)).fetchall()
    contab = [g for g in grupos if g[3] == "Contabilizado"]
    fim = max((g[6] for g in contab), default=None)
    if not fim:
        return {"estado": "indisponivel", "erro": "nenhuma OB contabilizada do SIAFE no período",
                "fonte": "SIAFE", "cobertura": "sem OB no período", "pago": None}
    ini_ant, fim_ant = f"{ano - 1}{INICIO[4:]}", f"{ano - 1}{fim[4:]}"
    por_ug_ant = con.execute(
        f"SELECT ug_emitente, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND "
        f"status='Contabilizado' AND {_OB_ISO} BETWEEN ? AND ? GROUP BY 1", (ano - 1, ini_ant, fim_ant)).fetchall()
    tot_ant = (sum(r[1] for r in por_ug_ant), sum(r[2] or 0 for r in por_ug_ant))
    ug_ag: dict = defaultdict(lambda: [0, 0.0])
    cr_ag: dict = defaultdict(lambda: ["", 0, 0.0])
    fora_ag: dict = defaultdict(lambda: [0, 0.0])
    for ug, cred, nome, st, n, v, _d, _c in grupos:
        if st != "Contabilizado":
            fora_ag[st][0] += n
            fora_ag[st][1] += v or 0
            continue
        ug_ag[ug][0] += n
        ug_ag[ug][1] += v or 0
        c = cr_ag[cred]
        c[0] = c[0] or nome or ""
        c[1] += n
        c[2] += v or 0
    por_ug = [(ug, n, v) for ug, (n, v) in ug_ag.items()]
    tot = (sum(x[1] for x in por_ug), sum(x[2] for x in por_ug))
    fora = sorted(((k, n, v) for k, (n, v) in fora_ag.items()), key=lambda x: -x[1])
    cred = [(k, c[0], c[1], c[2]) for k, c in sorted(cr_ag.items(), key=lambda kv: -kv[1][2])[:40]]
    credores_cnpj = {k for k in cr_ag if len(str(k or "")) == 14 and str(k).isdigit()}
    u2o, nomes = ug_para_orgao(con_ab), nomes_orgao(con_ab)

    def _org(ug):
        return u2o.get(str(ug)) or str(ug)[:2]
    ant = defaultdict(float)
    for ug, _n, v in por_ug_ant:
        ant[_org(ug)] += v or 0
    org = defaultdict(lambda: {"n_obs": 0, "pago": 0.0, "ugs": []})
    for ug, n, v in por_ug:
        o = org[_org(ug)]
        o["n_obs"] += n
        o["pago"] += v or 0
        o["ugs"].append({"ug": ug, "n_obs": n, "pago": round(v or 0, 2)})
    por_orgao = []
    for k, o in org.items():
        o["ugs"].sort(key=lambda x: -x["pago"])
        a = ant.get(k)
        por_orgao.append({"orgao": k, "nome": nomes.get(k, f"Órgão {k}"), "n_obs": o["n_obs"],
                          "pago": round(o["pago"], 2), "pago_anterior": round(a, 2) if a else None,
                          "variacao_pct": round((o["pago"] / a - 1) * 100, 1) if a else None, "ugs": o["ugs"][:12]})
    por_orgao.sort(key=lambda x: -x["pago"])
    credores = []
    for c, nome, n, v in cred:
        tipo, exib = doc_exibivel(c)
        credores.append({"tipo": tipo, "doc": exib, "nome": mascarar_texto(nome or ""), "n_obs": n,
                         "pago": round(v or 0, 2)})
    cob = max((str(g[7]) for g in grupos if g[7]), default=None)
    return {
        "estado": "ok",
        "fonte": "SIAFE-Rio 2 — Ordens Bancárias com status \"Contabilizado\" (ob_orcamentaria_siafe). Empenho e "
                 "liquidação não entram; OB anulada/excluída/não contabilizada fica fora.",
        "cobertura": (f"OB emitidas de {INICIO} a {fim} (última OB coletada; coleta mais recente {cob or '—'}). "
                      f"Comparação: mesma janela de {ini_ant} a {fim_ant}, gestão anterior, mesma fonte. O SIAFE "
                      f"inclui repasses e transferências entre UGs — total não é só fornecedor. Órgão = dono "
                      f"orçamentário da UG pelo cadastro do TFE."),
        "inicio": INICIO, "fim": fim, "n_obs": tot[0], "pago": round(tot[1], 2),
        "anterior": {"inicio": ini_ant, "fim": fim_ant, "n_obs": tot_ant[0], "pago": round(tot_ant[1], 2)},
        "variacao_pct": round((tot[1] / tot_ant[1] - 1) * 100, 1) if tot_ant[1] else None,
        "n_nao_contabilizadas": sum(r[1] for r in fora),
        "nao_contabilizadas": [{"status": r[0], "n": r[1], "valor": round(r[2] or 0, 2)} for r in fora],
        "por_orgao": por_orgao, "credores": credores, "_credores_cnpj": credores_cnpj,
    }


def _casos_vault(seis: set[str]) -> dict:
    if not VAULT_CASOS.is_dir():
        return {"estado": "indisponivel", "erro": "pasta de casos indisponível", "itens": []}
    from compliance_agent.casos_vault import _frontmatter, _nivel, _titulo
    itens = []
    for p in sorted(VAULT_CASOS.glob("*.md")):
        try:
            texto = p.read_text(encoding="utf-8")
        except OSError:
            continue
        cita = set(re.findall(r"SEI-\d{6}/\d{6}/\d{4}", texto))
        motivo = []
        if cita & seis:
            motivo.append("cita processo de contratação da gestão")
        if re.search(r"50\.254", texto):
            motivo.append("cita o Decreto 50.254/2026")
        if not motivo:
            continue
        meta, corpo = _frontmatter(texto)
        _o, rot, grau = _nivel(meta)
        itens.append({"slug": p.stem, "titulo": mascarar_texto(_titulo(corpo, p.stem)), "grau": grau,
                      "nivel": rot, "motivo": "; ".join(motivo)})
    return {"estado": "ok", "itens": itens}


def _controle(con: sqlite3.Connection, con_ach: sqlite3.Connection | None, seis_gestao: set[str],
             credores: set[str]) -> dict:
    aud = []
    for r in con.execute("SELECT p.id, p.data_publicacao, p.orgao, p.titulo, p.texto, p.url_fonte FROM fts_doerj f "
                         "JOIN publicacoes_doerj p ON p.id=f.rowid WHERE fts_doerj MATCH '\"50.254\"' AND "
                         "p.data_publicacao >= ? ORDER BY p.data_publicacao", (INICIO,)):
        t = _normalizar(r["texto"])
        i = t.find("50.254")
        trecho = t[max(0, i - 220): i + 200] if i >= 0 else t[:400]
        aud.append({"data": r["data_publicacao"], "orgao": _normalizar(r["orgao"] or "")[:120],
                    "titulo": mascarar_texto(_normalizar(r["titulo"] or "")[:200]),
                    "trecho": mascarar_texto(trecho), "url": r["url_fonte"],
                    "instaura": bool(re.search(r"(INSTAURA|INSTITUI)\w*\s+(A\s+)?(AUDITORIA|COMISSAO)", _sem_acento(t)))})
    pen = con.execute("SELECT processo, tipo, valor, orgao, substr(data_sessao,1,10) FROM penalidades_tcerj WHERE "
                      "substr(data_sessao,1,10) >= ? ORDER BY COALESCE(valor,0) DESC", (INICIO,)).fetchall()
    ult_pen = con.execute("SELECT MAX(substr(data_sessao,1,10)) FROM penalidades_tcerj").fetchone()[0]
    por_org = Counter()
    for p in pen:
        por_org[p[3] or "—"] += 1
    try:
        n_dec = con.execute("SELECT COUNT(*) FROM decisoes_tce").fetchone()[0]
    except sqlite3.OperationalError:
        n_dec = 0
    per = []
    lista = sorted(credores)
    for i in range(0, len(lista), 500):
        lote = lista[i:i + 500]
        per += con.execute(f"SELECT cnpj, MAX(favorecido), MAX(grau), SUM(total_pago), COUNT(*) FROM "
                           f"pericia_fornecedor WHERE grau IN ('🔴','🟡') AND cnpj IN ({','.join('?' * len(lote))}) "
                           f"GROUP BY cnpj", lote).fetchall()
    per.sort(key=lambda r: (r[2] != "🔴", -(r[3] or 0)))
    det = []
    if con_ach is not None:
        try:
            for r in con_ach.execute("SELECT ug, detector, processo, score, motivo FROM achado_detector "
                                     "WHERE status='confirmado'"):
                if r[2] in credores:
                    det.append({"ug": r[0], "detector": r[1], "cnpj": r[2], "score": r[3],
                                "motivo": mascarar_texto((r[4] or "")[:200])})
        except sqlite3.OperationalError as exc:
            logger.warning("governo_couto: detectores indisponíveis no bloco de controle: %s", exc)
    return {
        "estado": "ok",
        "fonte": ("DOERJ (atos que citam o Decreto 50.254/2026 — auditorias AGE/CGE nas secretarias); penalidades do "
                  "TCE-RJ (penalidades_tcerj, por data de sessão); perícia de fornecedor e detectores do JFN sobre "
                  "credores pagos no período; casos do vault."),
        "cobertura": (f"DOERJ a partir de {INICIO}. Penalidades TCE-RJ: última sessão coletada {ult_pen or '—'}. "
                      f"Os autos SEI das auditorias (respostas, termos de ciência) não estão nesta base — só a "
                      f"publicação no DOERJ."),
        "auditorias_50254": {"n": len(aud), "n_instauracoes": sum(a["instaura"] for a in aud), "itens": aud},
        "tce": {"n": len(pen), "valor": round(sum(p[2] or 0 for p in pen), 2), "ultima_sessao": ult_pen,
                "por_orgao": [{"orgao": k, "n": v} for k, v in por_org.most_common(30)],
                "itens": [{"processo": p[0], "tipo": p[1], "valor": p[2], "orgao": p[3], "data": p[4]}
                          for p in pen[:80]]},
        "tce_decisoes": ({"estado": "indisponivel", "motivo": "tabela decisoes_tce vazia na base — acórdãos do "
                          "TCE-RJ não coletados; INDISPONÍVEL, não zero."} if not n_dec else
                         {"estado": "ok", "n_base": n_dec}),
        "pericias": {"n": len(per), "n_vermelho": sum(1 for r in per if r[2] == "🔴"),
                     "itens": [{"cnpj": r[0], "favorecido": mascarar_texto(r[1] or ""), "grau": r[2],
                                "total_pago_pericia": round(r[3] or 0, 2), "n_ugs": r[4]} for r in per[:80]]},
        "detectores": {"n": len(det), "itens": det[:80]},
        "casos": _casos_vault(seis_gestao),
    }


_CAMADAS = ("deterministica", "subjetiva")
_ORDEM_GRAU = {"🔴": 0, "🟡": 1, "⚪": 2}


def _pontos_atencao() -> dict:
    base = {"fonte": f"data/{SUSPEITAS.name} — análise em duas camadas (determinística e subjetiva)",
            "cobertura": "o que a análise gravou; cada ponto traz a explicação inocente ao lado do indício"}
    if not SUSPEITAS.exists():
        return {**base, "estado": "em_andamento", "itens": [], "por_camada": {}, "por_grau": {},
                "mensagem": "Análise em andamento — o arquivo de pontos de atenção ainda não foi gravado."}
    try:
        bruto = json.loads(SUSPEITAS.read_text(encoding="utf-8"))
        if isinstance(bruto, dict):
            bruto = bruto.get("itens") or bruto.get("achados") or bruto.get("suspeitas") or []
        if not isinstance(bruto, list):
            raise ValueError("esperava uma lista de pontos")
    except (OSError, ValueError) as exc:
        return {**base, "estado": "erro", "erro": f"{type(exc).__name__}: {exc}", "itens": [], "por_camada": {},
                "por_grau": {}}
    itens = []
    for i, x in enumerate(bruto):
        if not isinstance(x, dict):
            continue
        it = {k: (mascarar_texto(v) if isinstance(v, str) else v) for k, v in x.items()}
        it["id"] = str(it.get("id") or f"p{i + 1}")
        it["camada"] = it.get("camada") if it.get("camada") in _CAMADAS else "subjetiva"
        it["grau"] = it.get("grau") if it.get("grau") in _ORDEM_GRAU else "⚪"
        if not str(it.get("explicacao_inocente") or "").strip():
            it["explicacao_inocente"] = "(a análise não registrou explicação inocente — apurar antes de concluir)"
        itens.append(it)
    itens.sort(key=lambda x: (_ORDEM_GRAU[x["grau"]], -(float(x.get("valor_ob") or 0))))
    mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(SUSPEITAS.stat().st_mtime))
    return {**base, "estado": "ok", "atualizado_em": mtime, "itens": itens,
            "por_camada": dict(Counter(x["camada"] for x in itens)), "por_grau": dict(Counter(x["grau"] for x in itens))}


def _seguro(fn, *a) -> dict:
    try:
        return fn(*a)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        return {"estado": "indisponivel", "erro": f"{type(exc).__name__}: {exc}", "fonte": "—",
                "cobertura": "bloco INDISPONÍVEL (erro ao ler a base) — não é zero"}


def _ok(b: dict) -> bool:
    return b.get("estado") in ("ok", "parcial")


def _pesado() -> dict:
    if (c := _CACHE.get("x")) and time.time() - c[0] < _TTL:
        return c[1]
    con, con_ach, con_ab = _ro(DB), _ro(DB_ACHADOS), _ro(DB_ABERTOS)
    if con is None:
        return {}
    try:
        atos = _seguro(_atos, con)
        ctr = _seguro(_contratacoes, con, con_ach)
        exe = _seguro(_execucao, con, con_ab)
        seis = {x["processo"] for x in ctr.get("lista", []) if x.get("processo")}
        ctl = _seguro(_controle, con, con_ach, seis, exe.pop("_credores_cnpj", set()))
    finally:
        for x in (con, con_ach, con_ab):
            if x is not None:
                x.close()
    r = _mascarar_tudo({"atos": atos, "contratacoes": ctr, "execucao": exe, "controle": ctl,
                        "gerado_em": time.strftime("%Y-%m-%d %H:%M")})
    _CACHE["x"] = (time.time(), r)
    return r


def montar(pesado: dict | None = None) -> dict:
    """Payload inteiro da aba. Blocos de base em cache de 30 min; os pontos de atenção são relidos a cada chamada
    (o arquivo é gravado por outra análise e pode aparecer a qualquer momento)."""
    p = pesado if pesado else _pesado()
    if not p:
        return {"ok": False, "erro": f"base indisponível: {DB.name}"}
    atos, ctr, exe, ctl = p["atos"], p["contratacoes"], p["execucao"], p["controle"]
    pts = _pontos_atencao()
    pessoal = atos.get("pessoal", []) if _ok(atos) else []
    placar = {
        "decretos": len(atos["decretos"]) if _ok(atos) else None,
        "decretos_orcamentarios": atos.get("n_orcamentarios") if _ok(atos) else None,
        "nomeacoes": sum(a["ato"] == "NOMEAR" for a in pessoal) if _ok(atos) else None,
        "exoneracoes": sum(a["ato"] == "EXONERAR" for a in pessoal) if _ok(atos) else None,
        "contratacoes": ctr.get("n") if _ok(ctr) else None,
        "valor_contratado": ctr.get("valor") if _ok(ctr) else None,
        "diretas": ctr.get("n_diretas") if _ok(ctr) else None,
        "valor_diretas": ctr.get("valor_diretas") if _ok(ctr) else None,
        "pago": exe.get("pago") if _ok(exe) else None,
        "n_obs": exe.get("n_obs") if _ok(exe) else None,
        "pago_anterior": exe.get("anterior", {}).get("pago") if _ok(exe) else None,
        "variacao_pct": exe.get("variacao_pct") if _ok(exe) else None,
        "auditorias_50254": ctl.get("auditorias_50254", {}).get("n") if _ok(ctl) else None,
        "penalidades_tce": ctl.get("tce", {}).get("n") if _ok(ctl) else None,
        "pontos_atencao": len(pts["itens"]) if pts["estado"] == "ok" else None,
    }
    return {"ok": True, "gestao": {**GESTAO, "ate": exe.get("fim") or time.strftime("%Y-%m-%d")},
            "placar": placar, **p, "pontos_atencao": pts,
            "ressalva": ("Indício não é acusação — presunção de legitimidade dos atos. Pagamento = só OB Contabilizada "
                         "do SIAFE; empenho nunca é pago; valor de contrato é contratado. INDISPONÍVEL ≠ zero.")}
