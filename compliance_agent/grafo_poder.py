# -*- coding: utf-8 -*-
"""Grafo de Poder — JFN 2.0, Onda 4. Une sócios+OB+doações+folha+co-endereço num grafo único.

Constrói a vizinhança de um alvo por EXPANSÃO LOCAL (BFS limitado em saltos e fanout) —
não carrega o grafo inteiro (1,1M OBs) em memória. Arestas vêm das tabelas reais:
  cnpj —[socio]→ pessoa (QSA, socios_fornecedor)
  cnpj —[pago_por]→ ug (ordens_bancarias)
  pessoa —[doou]→ candidato (doacoes_eleitorais)
  cnpj —[co_endereco]→ cnpj (endereco_fornecedor)
  pessoa —[servidor]→ ug (registros_folha)

Honestidade: vínculo é INDÍCIO de relação (presunção de legitimidade); CPF mascarado (LGPD).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
_FANOUT = 12  # teto de vizinhos por nó (evita explosão em UG/sócio de alto grau)


def _con() -> sqlite3.Connection:
    return sqlite3.connect(str(_DB))


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm_nome(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").upper()).strip()


def _resolver_alvo(con, alvo: str) -> str | None:
    """Resolve o alvo num node-id: 'cnpj:<14>' | 'socio:<nome>' | 'cand:<nome>' | 'ug:<cod>'."""
    d = _digits(alvo)
    if len(d) == 14:
        # só é nó se o CNPJ aparece em alguma fonte (senão = fora do universo de dados)
        existe = con.execute(
            "SELECT 1 FROM socios_fornecedor WHERE cnpj=? LIMIT 1", (d,)).fetchone() or \
            con.execute(
                "SELECT 1 FROM ordens_bancarias WHERE "
                "REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')=? LIMIT 1",
                (d,)).fetchone()
        return f"cnpj:{d}" if existe else None
    if d and len(d) in (6, 7) and con.execute(
            "SELECT 1 FROM ordens_bancarias WHERE ug_codigo=? LIMIT 1", (d,)).fetchone():
        return f"ug:{d}"
    nome = _norm_nome(alvo)
    # empresa por nome?
    row = con.execute(
        "SELECT favorecido_cpf FROM ordens_bancarias WHERE UPPER(favorecido_nome) LIKE ? "
        "AND LENGTH(REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-',''))=14 LIMIT 1",
        (f"%{nome}%",)).fetchone()
    if row:
        return f"cnpj:{_digits(row[0])}"
    # candidato?
    if con.execute("SELECT 1 FROM doacoes_eleitorais WHERE UPPER(nome_candidato) LIKE ? LIMIT 1",
                   (f"%{nome}%",)).fetchone():
        return f"cand:{nome}"
    # sócio/doador por nome
    if con.execute("SELECT 1 FROM socios_fornecedor WHERE socio_nome_norm LIKE ? LIMIT 1",
                   (f"%{nome}%",)).fetchone():
        return f"socio:{nome}"
    return None


def _expandir(con, node: str, so_contrato: bool) -> list[tuple]:
    """Vizinhos de um nó: [(vizinho_id, tipo_aresta, attrs_no)]. Limitado a _FANOUT por classe."""
    tipo, _, val = node.partition(":")
    out: list[tuple] = []

    if tipo == "cnpj":
        cnpj = val
        # UGs que pagaram (pago_por)
        for ug, ugn, tot in con.execute(
                "SELECT ug_codigo, MAX(ug_nome), SUM(valor) FROM ordens_bancarias "
                "WHERE REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')=? "
                "GROUP BY ug_codigo ORDER BY SUM(valor) DESC LIMIT ?", (cnpj, _FANOUT)):
            # nome CANÔNICO da UG (ITERJ p/ 133100), consistente com /relatorio e /orgao — não o
            # ug_nome cru da OB (que às vezes traz o órgão superior). Fallback ao nome cru.
            from compliance_agent import ugs as _ugs
            _lbl = _ugs.nome_canonico(str(ug), fallback="") or ugn or str(ug)
            out.append((f"ug:{ug}", "pago_por", {"label": _lbl, "total_ob": round(tot or 0, 2)}))
        if so_contrato:
            return out
        # sócios (QSA)
        for nome, doc in con.execute(
                "SELECT socio_nome_norm, socio_doc FROM socios_fornecedor WHERE cnpj=? LIMIT ?",
                (cnpj, _FANOUT)):
            if nome:
                out.append((f"socio:{nome}", "socio", {"label": nome, "doc": doc}))
        # co-endereço
        for c2, in con.execute(
                "SELECT b.cnpj FROM endereco_fornecedor a JOIN endereco_fornecedor b "
                "ON a.endereco_norm=b.endereco_norm AND a.cnpj<>b.cnpj WHERE a.cnpj=? LIMIT ?",
                (cnpj, _FANOUT)):
            out.append((f"cnpj:{_digits(c2)}", "co_endereco", {"label": c2}))

    elif tipo == "socio":
        nome = val
        # outras empresas do mesmo sócio
        for c2, in con.execute(
                "SELECT DISTINCT cnpj FROM socios_fornecedor WHERE socio_nome_norm=? LIMIT ?",
                (nome, _FANOUT)):
            out.append((f"cnpj:{_digits(c2)}", "socio", {"label": c2}))
        if so_contrato:
            return out
        # doações que esse nome fez
        for cand, partido, val_d in con.execute(
                "SELECT nome_candidato, MAX(partido), SUM(valor) FROM doacoes_eleitorais "
                "WHERE UPPER(nome_doador)=? GROUP BY nome_candidato ORDER BY SUM(valor) DESC LIMIT ?",
                (nome, _FANOUT)):
            out.append((f"cand:{_norm_nome(cand)}", "doou",
                        {"label": cand, "partido": partido, "valor": round(val_d or 0, 2)}))

    elif tipo == "ug":
        ug = val
        # top empresas pagas
        for cpf, nm, tot in con.execute(
                "SELECT favorecido_cpf, MAX(favorecido_nome), SUM(valor) FROM ordens_bancarias "
                "WHERE ug_codigo=? GROUP BY favorecido_cpf ORDER BY SUM(valor) DESC LIMIT ?",
                (ug, _FANOUT)):
            if len(_digits(cpf)) == 14:
                out.append((f"cnpj:{_digits(cpf)}", "pago_por",
                            {"label": nm, "total_ob": round(tot or 0, 2)}))

    elif tipo == "cand":
        nome = val
        # doadores do candidato
        for doador, doc, val_d in con.execute(
                "SELECT nome_doador, MAX(cpf_cnpj_doador), SUM(valor) FROM doacoes_eleitorais "
                "WHERE UPPER(nome_candidato) LIKE ? GROUP BY nome_doador ORDER BY SUM(valor) DESC LIMIT ?",
                (f"%{nome}%", _FANOUT)):
            d = _digits(doc)
            vid = f"cnpj:{d}" if len(d) == 14 else f"socio:{_norm_nome(doador)}"
            out.append((vid, "doou", {"label": doador, "valor": round(val_d or 0, 2)}))

    return out


def vizinhanca(alvo: str, saltos: int = 2, so_contrato: bool = False) -> dict:
    """Subgrafo ao redor do alvo até `saltos` (BFS limitado). Retorna {ok, alvo, nos, arestas, n_nos}."""
    if not _DB.exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    saltos = max(1, min(int(saltos), 3))
    con = _con()
    try:
        raiz = _resolver_alvo(con, alvo)
        if not raiz:
            return {"ok": True, "alvo": alvo, "nos": [], "arestas": [],
                    "_nota": f"INDISPONÍVEL: alvo '{alvo}' não encontrado (CNPJ/UG/nome)."}
        nos: dict[str, dict] = {raiz: {"id": raiz, "tipo": raiz.split(":")[0], "salto": 0}}
        arestas: list[dict] = []
        vistas: set[tuple] = set()
        fronteira = [raiz]
        for nivel in range(1, saltos + 1):
            nova = []
            for node in fronteira:
                for viz, rel, attrs in _expandir(con, node, so_contrato):
                    if viz not in nos:
                        nos[viz] = {"id": viz, "tipo": viz.split(":")[0], "salto": nivel,
                                    "label": attrs.get("label")}
                        nova.append(viz)
                    chave = tuple(sorted([node, viz])) + (rel,)
                    if chave not in vistas:
                        vistas.add(chave)
                        arestas.append({"de": node, "para": viz, "rel": rel, **{
                            k: v for k, v in attrs.items() if k != "label"}})
            fronteira = nova
            if not fronteira:
                break
        return {"ok": True, "alvo": alvo, "raiz": raiz, "n_nos": len(nos),
                "nos": list(nos.values()), "arestas": arestas,
                "_fonte": "QSA + OB + TSE + folha + co-endereço (compliance.db)",
                "_nota": "Vínculo = indício de relação (presunção de legitimidade); CPF mascarado (LGPD)."}
    finally:
        con.close()


def comunidades(ug: str | None = None, limite: int = 20) -> dict:
    """Detecta comunidades (sócios/co-endereço comuns) entre fornecedores — reusa grafo_cartel/rede."""
    try:
        from compliance_agent import grafo_cartel
        base = grafo_cartel.captura_orgaos(limite=limite) if not ug else \
            grafo_cartel.vizinhanca_cartel(ug, limite=limite)
        return {"ok": True, "comunidades": base,
                "_nota": "Indício de cluster (sócio/endereço/órgão comum), não prova de cartel."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e)}
