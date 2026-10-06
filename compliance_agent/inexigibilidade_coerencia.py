# -*- coding: utf-8 -*-
"""INEXIGIBILIDADE — os próprios autos sustentam a inviabilidade de competição?

Caso que ensinou (SEEDUC × EUREKA, SEI-030001/103373/2024, lido em 27/09/2026): contratação de R$ 430.998.247,89 por
inexigibilidade (art. 74, I — fornecedor exclusivo) em que o PRÓPRIO estudo técnico preliminar
  • admitia "outras editoras, desde que tenham características físicas similares" (cláusula de EQUIVALÊNCIA), e
  • concluía recomendando "a modalidade licitatória… que o processo licitatório assegure…";
e citava a compra anterior do MESMO material (Contrato SEEDUC 14/2023, SEI-030029/008726/2023) — feita de OUTRA empresa,
a distribuidora PHOTONLUX (R$ 385.799.673,52 pagos em 2023). Se outro CNPJ já vendeu o objeto ao próprio órgão, a
exclusividade que afasta a licitação não se sustenta sem explicação nos autos.

Regras (determinísticas; cada achado cita o trecho e a fonte):
  • etp_admite_equivalente ........ inexigibilidade com cláusula de equivalência no ETP/TR — 🟡 contradição interna
  • etp_recomenda_licitacao ....... inexigibilidade e o ETP conclui por processo licitatório — 🟡
  • objeto_ja_fornecido_por_outro . os autos citam contratação anterior (processo SEI) cujo fornecedor, no TCE-RJ, é
                                    OUTRO CNPJ — 🔴 a exclusividade tem de ser explicada
A carta de exclusividade assinada pela própria contratada é ATRIBUTO, não achado: editora é exclusiva das próprias
obras, e o art. 74 §1º admite a declaração do fabricante — o que ela não prova é que SÓ aquela obra atende.
HONESTIDADE: indício ≠ acusação; a regra aponta incoerência documental, a conclusão exige o parecer (camada subjetiva).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
_RX_INEX = re.compile(r"inexigibilidade", re.I)
# o ATO diz inexigibilidade: contrato, extrato, parecer, ratificação/autorização — "art. 74" citado num pregão não
# basta (PE 24/2023 do INEA contava como inexigibilidade, 27/09/2026)
_RX_ATO = re.compile(r"contrato|extrato|parecer|ratifica|autoriza[çc][ãa]o|termo\s+de\s+inexig|justificativa", re.I)
_RX_PLAN = re.compile(r"estudo\s+t[ée]cnico|termo\s+de\s+refer|\bETP\b|\bTR\b", re.I)
_RX_EQUIV = re.compile(
    # equivalência do OBJETO — "ou similares" solto casava texto de qualificação técnica ("atividades congêneres ou
    # similares ao objeto", 420001/001804/2025)
    r"(?:outr[oa]s\s+(?:editoras|marcas|fabricantes)|ou\s+equivalente|vers[õo]es\s+mais\s+recentes)"
    r"[^.]{0,160}?(?:desde\s+que|caracter[íi]sticas|similar|equivalente)", re.I)
_RX_RECOMENDA_LIC = re.compile(r"(?:observando-se\s+a\s+modalidade\s+licitat[óo]ria|processo\s+licitat[óo]rio\s+assegure|"
                               r"recomenda[- ]se\s+a\s+(?:realiza[çc][ãa]o\s+de\s+)?licita)", re.I)
# a citação só prova "compra anterior do MESMO objeto" com contexto de aquisição ao lado (60 caracteres antes):
# sem isto, inexigibilidade de CURSO citava processos de outros cursos (Instituto Negócios Públicos) — 59 acesos
_RX_COMPRA_ANTERIOR = re.compile(r"(?:foi|foram|j[áa]\s+(?:foi|foram))\s+(?:objeto\s+de\s+aquisi|adquirid)|recompra|"
                                 r"aquisi[çc][ãa]o\s+anterior|contrata[çc][ãa]o\s+anterior|adquirido\s+pela", re.I)
_RX_SEI = re.compile(r"SEI[-\s]?(\d{6})/(\d{6})/(\d{4})")


def _trecho(rx: re.Pattern, texto: str, largura: int = 220) -> str | None:
    m = rx.search(texto or "")
    if not m:
        return None
    a = max(0, m.start() - 60)
    return re.sub(r"\s+", " ", texto[a:m.end() + largura - 60])[:largura]


def _norm(numero: str) -> str:
    return re.sub(r"\D", "", numero or "")


def _fornecedores_tcerj(con, numero: str) -> set[str]:
    """Raiz de CNPJ dos contratos do processo no TCE-RJ — pela `sei_norm` (só dígitos): o TCE-RJ grava os lotes como
    "SEI-030001/103373/A/2024", e o LIKE pelo número exato não os achava."""
    try:
        return {str(r[0])[:8] for r in con.execute("SELECT cnpj FROM contratos_tcerj WHERE sei_norm=? AND cnpj IS NOT NULL",
                                                   (_norm(numero),)) if r[0]}
    except sqlite3.Error:
        return set()


def analisar(docs: list[dict], numero: str, *, db_path: Path | None = None) -> dict:
    """{grau, achados[], ...} — só avalia processo de INEXIGIBILIDADE com ETP/TR nos autos."""
    atos = " ".join(str(d.get("texto") or "")[:4000] for d in docs or [] if _RX_ATO.search(str(d.get("titulo") or "")))
    if not _RX_INEX.search(atos):
        return {"grau": "nao_aplicavel", "achados": [], "resumo": "não é inexigibilidade (ou não se lê nos autos)"}
    plan = [d for d in docs if _RX_PLAN.search(str(d.get("titulo") or ""))]
    achados: list[dict] = []
    for d in plan:
        x = str(d.get("texto") or "")
        if (t := _trecho(_RX_EQUIV, x)) and not any(a["tipo"] == "etp_admite_equivalente" for a in achados):
            achados.append({"tipo": "etp_admite_equivalente", "grau": "amarelo", "fonte": d.get("titulo"), "trecho": t,
                            "diz": "O estudo/TR admite equivalente de outro fornecedor — incompatível com a inviabilidade "
                                   "de competição que sustenta a inexigibilidade (art. 74, I).",
                            "fundamento": "Lei 14.133/2021, art. 74, I e §1º (vedada a preferência por marca)"})
        if (t := _trecho(_RX_RECOMENDA_LIC, x)) and not any(a["tipo"] == "etp_recomenda_licitacao" for a in achados):
            achados.append({"tipo": "etp_recomenda_licitacao", "grau": "amarelo", "fonte": d.get("titulo"), "trecho": t,
                            "diz": "O estudo recomenda processo licitatório, e a contratação saiu por inexigibilidade.",
                            "fundamento": "Lei 14.133/2021, arts. 18 e 72 (a contratação direta decorre do planejamento)"})
    try:
        con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    except sqlite3.Error:
        con = None
    if con is not None:
        try:
            meus = _fornecedores_tcerj(con, numero)
            citados = set()
            for d in plan:
                x = str(d.get("texto") or "")
                for m in _RX_SEI.finditer(x):
                    if _RX_COMPRA_ANTERIOR.search(x[max(0, m.start() - 160):m.start()]):
                        citados.add(f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}")
            citados -= {numero}
            for n in sorted(citados):
                outros = _fornecedores_tcerj(con, n) - meus
                if meus and outros:
                    nome = con.execute("SELECT fornecedor FROM contratos_tcerj WHERE sei_norm=? LIMIT 1", (_norm(n),)).fetchone()
                    achados.append({"tipo": "objeto_ja_fornecido_por_outro", "grau": "vermelho", "fonte": n,
                                    "trecho": None, "processo_citado": n, "fornecedor_citado": (nome[0] if nome else None),
                                    "diz": (f"O planejamento cita a contratação anterior {n}, cujo fornecedor no TCE-RJ é "
                                            f"{(nome[0] if nome else 'outro CNPJ')} — outro CNPJ que não o contratado por "
                                            "exclusividade: se outra empresa já forneceu o objeto, a inviabilidade de "
                                            "competição tem de ser explicada nos autos."),
                                    "fundamento": "Lei 14.133/2021, art. 74, I e §1º"})
        finally:
            con.close()
    grau = "vermelho" if any(a["grau"] == "vermelho" for a in achados) else ("amarelo" if achados else "verde")
    return {"grau": grau, "achados": achados,
            "resumo": "; ".join(a["diz"] for a in achados) or "planejamento coerente com a inexigibilidade (nos autos lidos)",
            "fonte": "inexigibilidade_coerencia (determinístico/offline)"}
