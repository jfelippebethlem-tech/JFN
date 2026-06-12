# -*- coding: utf-8 -*-
"""Visão agregada e INTELIGENTE dos benefícios sociais dos sócios/administradores (laranja) p/ os relatórios.

Lê `socio_beneficio` (sweep detached) ⋈ `socios_fornecedor` e entrega não só contagens, mas o MATERIAL para
uma leitura raciocinada: quem (nome do QSA — público), papel (sócio/administrador), fonte da resolução de CPF
e qual benefício — distinguindo **indício** / **AFASTADO** / **INDISPONÍVEL** (CPF não resolvido OU benefício
não verificado OU sócio ainda não varrido). `leitura()` devolve a CONCLUSÃO em prosa honesta.

Honestidade (regra-mãe): benefício de subsistência de sócio/admin de fornecedor do Estado é **INDÍCIO** de
interposição de pessoas (laranja — art. 337-F CP; art. 11 Lei 8.429/92), NUNCA acusação. INDISPONÍVEL ≠ "não
recebe". CPF nunca sai (LGPD art. 7º,II/23 — uso interno); o NOME do sócio é dado público do QSA.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_DB = Path("data") / "compliance.db"

# papéis de GESTÃO no QSA (sócio-administrador, diretor, presidente, administrador, conselheiro, titular)
_PAPEL_GESTAO = ("administrador", "diretor", "presidente", "conselheiro", "titular", "liquidante")


def _con(db_path: str | Path | None):
    p = Path(db_path or _DB)
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _vazio() -> dict:
    return {"total_qsa": 0, "n_varridos": 0, "n_resolvidos": 0, "n_verificados": 0,
            "n_com_beneficio": 0, "n_indisponivel": 0, "cobertura": 0.0, "itens": []}


def _papel_gestao(qualif: str) -> bool:
    q = (qualif or "").lower()
    return any(t in q for t in _PAPEL_GESTAO)


def _agg(total_qsa: int, rows: list) -> dict:
    """rows: (cnpj, razao, socio_nome, qualificacao, resolvido, verificado, recebe, fonte, beneficios_json).
    Conta pessoas DISTINTAS (nome+doc) p/ os totais; `itens` (com_benefício) por (cnpj, pessoa) p/ o detalhe."""
    vistos: set = set()
    n_varridos = n_resolvidos = n_verificados = n_com_beneficio = 0
    itens: list[dict] = []
    for cnpj, razao, nome, qualif, nnorm, doc, resolvido, verificado, recebe, fonte, bj in rows:
        chave = (nnorm, doc)
        if chave not in vistos:
            vistos.add(chave)
            n_varridos += 1
            if resolvido:
                n_resolvidos += 1
            if verificado:
                n_verificados += 1
        if recebe == 1:
            n_com_beneficio += 1  # conta o VÍNCULO (cnpj×pessoa) — um laranja em 2 fornecedores conta 2 indícios
            try:
                tipos = json.loads(bj or "[]")
            except Exception:  # noqa: BLE001
                tipos = []
            itens.append({"cnpj": cnpj, "razao": razao, "nome": nome, "doc": doc,
                          "papel": qualif or "(sem qualificação)", "gestao": _papel_gestao(qualif),
                          "fonte": fonte or "", "tipos": tipos})
    # distinto p/ o headline: pessoas com benefício (por nome + doc, coerente com os totais)
    n_pessoas_benef = len({(i["nome"], i["doc"]) for i in itens})
    n_indisponivel = max(0, total_qsa - n_verificados)
    cobertura = round(100.0 * n_verificados / total_qsa, 1) if total_qsa else 0.0
    return {"total_qsa": total_qsa, "n_varridos": n_varridos, "n_resolvidos": n_resolvidos,
            "n_verificados": n_verificados, "n_com_beneficio": n_com_beneficio,
            "n_pessoas_beneficio": n_pessoas_benef, "n_indisponivel": n_indisponivel,
            "cobertura": cobertura, "itens": sorted(itens, key=lambda i: (not i["gestao"], i["razao"]))}


def _total_qsa(con, cnpjs: list[str]) -> int:
    ph = ",".join("?" * len(cnpjs))
    return con.execute(
        f"""SELECT COUNT(*) FROM (SELECT DISTINCT socio_nome_norm, socio_doc FROM socios_fornecedor
             WHERE cnpj IN ({ph}) AND socio_doc LIKE '%*%' AND socio_nome_norm <> '')""", cnpjs).fetchone()[0]


def _join_rows(con, cnpjs: list[str]) -> list:
    ph = ",".join("?" * len(cnpjs))
    return con.execute(
        f"""SELECT s.cnpj, s.razao, s.socio_nome, s.qualificacao, s.socio_nome_norm, s.socio_doc,
                   b.resolvido, b.verificado, b.recebe_beneficio, b.fonte, b.beneficios_json
              FROM socios_fornecedor s
              JOIN socio_beneficio b
                ON b.socio_nome_norm = s.socio_nome_norm AND b.socio_doc = s.socio_doc
             WHERE s.cnpj IN ({ph}) AND s.socio_doc LIKE '%*%' AND s.socio_nome_norm <> ''""",
        cnpjs).fetchall()


def agregar_por_cnpjs(cnpjs, db_path: str | Path | None = None) -> dict:
    """Agrega benefícios dos sócios/admin de um conjunto de fornecedores (ex.: todos de uma UG)."""
    cnpjs = [str(c) for c in cnpjs if c]
    if not cnpjs:
        return _vazio()
    try:
        con = _con(db_path)
        try:
            return _agg(_total_qsa(con, cnpjs), _join_rows(con, cnpjs))
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente / DB indisponível → vazio honesto (INDISPONÍVEL)
        return _vazio()


def por_fornecedor(cnpj: str, db_path: str | Path | None = None) -> dict:
    """Mesma agregação p/ um único fornecedor (usado no relatório de fornecedor)."""
    return agregar_por_cnpjs([cnpj], db_path=db_path)


def leitura(agg: dict, escopo: str = "do órgão") -> str:
    """CONCLUSÃO em prosa honesta sobre o agregado (inteligência, não tabela solta). Indício, nunca acusação."""
    total = agg.get("total_qsa", 0)
    if not total:
        return ("Não há sócios/administradores com CPF mascarado no QSA dos fornecedores "
                f"{escopo} para esta verificação (INDISPONÍVEL — sem base de QSA), ou a varredura ainda não cobriu.")
    verif = agg.get("n_verificados", 0)
    benef = agg.get("n_com_beneficio", 0)
    pessoas = agg.get("n_pessoas_beneficio", 0)
    cob = agg.get("cobertura", 0.0)
    if verif == 0:
        return (f"Dos **{total}** sócios/administradores do QSA dos fornecedores {escopo}, **nenhum** pôde ser "
                "verificado ainda (CPF não resolvido ou varredura pendente) — **INDISPONÍVEL**, o que não equivale "
                "a ausência de benefício.")
    if benef == 0:
        return (f"Dos **{total}** sócios/administradores do QSA, **{verif}** foram verificados ({cob}% de cobertura) "
                f"e **nenhum** recebe benefício social de subsistência — indício de laranja **AFASTADO** para os "
                "verificados. Os demais permanecem **INDISPONÍVEL** (CPF não resolvido/varredura pendente), não 'limpos'.")
    gestao = sum(1 for i in agg.get("itens", []) if i.get("gestao"))
    frase_gestao = (f", dos quais **{gestao}** em papel de gestão (administrador/diretor/sócio-administrador)") if gestao else ""
    return (f"**Indício de interposição de pessoas (laranja):** dos **{total}** sócios/administradores do QSA, "
            f"**{verif}** foram verificados ({cob}%) e **{pessoas}** pessoa(s) — **{benef}** vínculo(s) com fornecedor(es) "
            f"{escopo}{frase_gestao} — recebem benefício social de subsistência (Bolsa Família/BPC/etc.). Receber "
            "benefício de subsistência e simultaneamente ser sócio/gestor de empresa que recebe recursos públicos é "
            "**indício** (não prova) de testa-de-ferro — art. 337-F CP; art. 11 Lei 8.429/92 — a confirmar no SEI e no "
            "contrato social. Os não verificados seguem **INDISPONÍVEL**.")
