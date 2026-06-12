# -*- coding: utf-8 -*-
"""Cruzamento INTELIGENTE: sócio/administrador de fornecedor que também está na FOLHA do Estado (conflito de
pessoal / incompatibilidade). Servidor/terceirizado que é sócio de empresa contratada pelo mesmo aparelho
estatal é indício de **conflito de interesse / incompatibilidade** (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133 art. 9º).

PONTE (sem precisar resolver o CPF completo): tanto o QSA público quanto a folha trazem o CPF MASCARADO, mas em
posições diferentes — QSA expõe as posições **4-9** (`***.XXX.XXX-**`), a folha expõe **3-8** (`XX######XXX`).
A sobreposição são as **posições 4-8 (5 dígitos)**. Cruzando (nome normalizado + esses 5 dígitos) entre os dois,
um match é forte indício de ser a MESMA pessoa — cobre TODOS os sócios mascarados (não só os ~5% com CPF resolvido).

Honestidade: indício, NUNCA acusação (5 díg + nome ainda admite homonímia rara; vínculo pode ser lícito —
acumulação permitida). CPF nunca sai (LGPD); o nome do QSA e da folha são dados públicos.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from compliance_agent.resolucao_cpf import _digitos, _norm, middle6

_DB = Path("data") / "compliance.db"


def _con(db_path):
    return sqlite3.connect(f"file:{Path(db_path or _DB)}?mode=ro", uri=True)


def _vazio() -> dict:
    return {"n_socios": 0, "n_na_folha": 0, "itens": []}


def _chave_socio(doc: str) -> str:
    """Posições 4-8 (5 díg) do CPF a partir do doc mascarado do QSA (middle6 = posições 4-9)."""
    m6 = middle6(doc)
    return m6[:5] if len(m6) == 6 else ""


def _chave_folha(cpf: str) -> str:
    """Posições 4-8 (5 díg) do CPF mascarado da folha (mostra posições 3-8 = 6 díg)."""
    d = _digitos(cpf)
    return d[1:6] if len(d) == 6 else ""


_FOLHA_IDX_CACHE: dict = {}  # {db_path: {(nome_norm, pos4-8): {orgao,cargo,vinculo,competencia}}}


def _folha_index(db_path: str | Path | None) -> dict:
    """Índice {(nome_norm, posições 4-8): vínculo} da folha — construído 1× por processo (cacheado).
    A folha muda só no sweep diário; cache no processo (jfn.service) evita varrer 257k linhas por relatório."""
    key = str(Path(db_path or _DB))
    cached = _FOLHA_IDX_CACHE.get(key)
    if cached is not None:
        return cached
    idx: dict = {}
    try:
        con = _con(db_path)
        try:
            for cpf, nome, orgao, cargo, vinculo, comp in con.execute(
                    "SELECT cpf, nome, orgao_nome, cargo, vinculo, competencia FROM registros_folha "
                    "WHERE nome IS NOT NULL AND cpf IS NOT NULL"):
                k = (_norm(nome), _chave_folha(cpf))
                if k[1] and k not in idx:  # 1 vínculo representativo por chave (basta p/ o relatório)
                    idx[k] = {"orgao": orgao or "", "cargo": cargo or "", "vinculo": vinculo or "",
                              "competencia": comp or ""}
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente / DB indisponível → índice vazio (não cacheia)
        return {}
    _FOLHA_IDX_CACHE[key] = idx
    return idx


def por_cnpjs(cnpjs, db_path: str | Path | None = None) -> dict:
    """Sócios/admin (mascarados) dos fornecedores que cruzam com a folha do Estado por (nome + posições 4-8)."""
    cnpjs = [str(c) for c in cnpjs if c]
    if not cnpjs:
        return _vazio()
    folha = _folha_index(db_path)
    ph = ",".join("?" * len(cnpjs))
    try:
        con = _con(db_path)
        try:
            socios = con.execute(
                f"""SELECT DISTINCT s.cnpj, s.razao, s.socio_nome, s.qualificacao, s.socio_nome_norm, s.socio_doc
                      FROM socios_fornecedor s
                     WHERE s.cnpj IN ({ph}) AND s.socio_doc LIKE '%*%' AND s.socio_nome_norm <> ''""",
                cnpjs).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return _vazio()
    alvo: set = set()
    achados: list = []
    for cnpj, razao, nome, qualif, nnorm, doc in socios:
        ks = _chave_socio(doc)
        if not ks:
            continue
        alvo.add((nnorm, ks))
        vinc = folha.get((nnorm, ks))
        if vinc:
            achados.append({"cnpj": cnpj, "razao": razao, "nome": nome,
                            "papel": qualif or "(sem qualificação)", **vinc})
    return {"n_socios": len(alvo), "n_na_folha": len({(i["cnpj"], i["nome"]) for i in achados}),
            "itens": achados}


def por_fornecedor(cnpj: str, db_path: str | Path | None = None) -> dict:
    return por_cnpjs([cnpj], db_path=db_path)


def leitura(agg: dict, escopo: str = "deste fornecedor") -> str:
    """Conclusão honesta sobre o conflito de pessoal (indício, nunca acusação)."""
    ns = agg.get("n_socios", 0)
    nf = agg.get("n_na_folha", 0)
    if ns == 0:
        return ("Não há sócios/administradores com CPF mascarado no QSA para cruzar com a folha "
                f"{escopo} — **INDISPONÍVEL** (não equivale a ausência de conflito).")
    if nf == 0:
        return (f"Cruzados **{ns}** sócios/administradores {escopo} com a folha do Estado (por nome + 5 dígitos do "
                "CPF): **nenhum** consta na folha — indício de conflito de pessoal **AFASTADO**.")
    return (f"**Indício de conflito de pessoal:** **{nf}** de {ns} sócios/administradores {escopo} constam na "
            "**folha do Estado** (servidor/terceirizado/bolsista), cruzados por nome + 5 dígitos do CPF. Ser sócio/"
            "gestor de empresa contratada pelo poder público e integrar sua folha é **indício** de conflito de "
            "interesse/incompatibilidade (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133 art. 9º) — confirmar a "
            "identidade (homonímia rara) e a natureza do vínculo. **Indício, não prova.**")
