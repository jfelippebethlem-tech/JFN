# -*- coding: utf-8 -*-
"""Dados do relatório: resolução de empresa, consultas ao compliance.db e enriquecimento (APIs) — extraído de inteligencia.py (split 2026-07-06).
Comportamento idêntico; rede de segurança: tools/inteligencia_snapshot_check.py + tests/test_inteligencia_snapshot.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Optional

from compliance_agent.reporting.intel_base import _DB, _REGISTRY, moeda, so_digitos

logger = logging.getLogger(__name__)

# timeout (s) para o enriquecimento via APIs públicas (egress da VM é lento).
# O relatório é ASSÍNCRONO/push (não está no caminho do `terminal` 60s do Yoda): pode esperar mais para que
# perfil RFB, sinais corporativos (§5) e CEIS/CNEP/CEPIM (§6) populem em vez de cair em INDISPONÍVEL por egress.
# Antes era 35s e o enriquecimento estourava na VM (2 vCPU, egress lento). Agora ~90s + retry com backoff
# (sinal transitório) + cache por CNPJ (TTL 7 dias) para não repetir o egress a cada relatório.
# Se mesmo assim falhar, o relatório sai com os dados REAIS locais (OBs/contratos) e marca o enriquecimento
# como INDISPONÍVEL — degrada honesto, nunca inventa.
_ENRIQUECE_TIMEOUT = float(os.environ.get("JFN_RELATORIO_ENRIQUECE_TIMEOUT", "90"))
# nº de TENTATIVAS do enriquecimento (1 = sem retry). Backoff entre tentativas em _ENRIQUECE_BACKOFF s.
_ENRIQUECE_TENTATIVAS = int(os.environ.get("JFN_RELATORIO_ENRIQUECE_TENTATIVAS", "2"))
_ENRIQUECE_BACKOFF = float(os.environ.get("JFN_RELATORIO_ENRIQUECE_BACKOFF", "2"))
# TTL do cache do enriquecimento por CNPJ (s). 0 desliga o cache (testes determinísticos).
_ENRIQUECE_CACHE_TTL = float(os.environ.get("JFN_RELATORIO_ENRIQUECE_CACHE_TTL", str(7 * 86400)))


def _carregar_registro() -> list[dict]:
    try:
        return json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _nome_por_cnpj(cnpj: str) -> str:
    """Melhor nome conhecido para um CNPJ (registro > empresas > OBs)."""
    cnpj = so_digitos(cnpj)
    for e in _carregar_registro():
        if so_digitos(e.get("cnpj", "")) == cnpj:
            return e.get("nome", "")
    if _DB.exists():
        con = sqlite3.connect(_DB)
        try:
            r = con.execute("SELECT razao_social FROM empresas WHERE cnpj=?", (cnpj,)).fetchone()
            if r and r[0]:
                return r[0]
            r = con.execute(
                "SELECT favorecido_nome FROM ordens_bancarias WHERE favorecido_cpf=? AND favorecido_nome IS NOT NULL LIMIT 1",
                (cnpj,)).fetchone()
            if r and r[0]:
                return r[0]
        except Exception as exc:
            logger.warning("Consulta de nome p/ CNPJ %s falhou no compliance.db: %s", cnpj, exc)
        finally:
            con.close()
    return ""


def _resolver_db_inteligencia(db_path=None) -> Path:
    """DB efetivo p/ as escritas deste módulo. arg > JFN_DB > _DB (= JFN_DATA_DIR/compliance.db).
    Alinha com _resolver_db de models.py mas honra o _DB local (derivado de JFN_DATA_DIR) como default."""
    return Path(db_path or os.environ.get("JFN_DB") or _DB)


def _favorecido_resumo_disponivel(con: sqlite3.Connection) -> bool:
    """True se a tabela-resumo existe E não está vazia. Guard p/ cair no scan de OB se faltar/stale."""
    try:
        r = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorecido_resumo' LIMIT 1"
        ).fetchone()
        if not r:
            return False
        return (con.execute("SELECT 1 FROM favorecido_resumo LIMIT 1").fetchone()) is not None
    except Exception:  # noqa: BLE001
        return False


def _norm_alnum(s: str) -> str:
    """minúsculas, só [a-z0-9] (tira espaço/pontuação/acento-ascii). 'R. C. Vieira Eng.'→'rcviereng'-ish.
    Casa o fallback com grafias variantes do MESMO CPF ('ENGE PRAT' vs 'engeprat'; 'R C VIEIRA' vs 'R.C.Vieira')."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# `buscar_candidatos` fazia `lower(favorecido_nome) LIKE '%termo%'` + GROUP BY favorecido_cpf em
# ordens_bancarias (~1,12M linhas) → full-scan ~6-18s por chamada (não indexável: substring+função).
# Mas há só ~73.881 favorecidos DISTINTOS. `favorecido_resumo` é o GROUP BY pré-computado (74k linhas):
# o MESMO LIKE roda ~15× mais rápido.
def atualizar_favorecido_resumo(db_path=None) -> dict:
    """(Re)constrói `favorecido_resumo` — o agregado por credor (CNPJ/CPF) pré-computado.
    Idempotente: DROP+CREATE+INSERT numa ÚNICA transação (a tabela nunca fica vazia/parcial p/ o leitor).
    Respeita JFN_DB/_resolver_db e busy_timeout=30000 (espera o lock do sweep em vez de errar na hora).
    Retorna {ok, linhas, db, ...medidas}.

    VALOR = OB PAGA DO SIAFE (24/11/2026, decisão do dono: "OBs são o principal; TFE pode ter erro"). Até aqui
    `n_obs`/`total_pago` eram o GROUP BY do espelho TFE e alimentavam capital_incompativel, socio_oculto, fênix,
    porta_giratoria, hub_compartilhado e /api/sugestoes. Agora:
      - `n_obs`/`total_pago` = OB paga no SIAFE (régua `_ob_paga`), todos os exercícios que o SIAFE da casa tem;
        credor que o SIAFE não tem → NULL (INDISPONÍVEL, nunca zero) e `fonte_valor='so_tfe'`;
      - `n_obs_tfe`/`total_tfe` = espelho TFE NOS EXERCÍCIOS QUE O SIAFE COBRE — só confronto (divergência),
        nunca somado ao valor;
      - nome (exibição + haystack) = grafias do SIAFE e do espelho: o espelho segue servindo para CASAR NOME.

    PARIDADE com o scan de OB: o mesmo CPF pode ter VÁRIAS grafias de nome. Por isso guardamos:
      - favorecido_nome: o nome de EXIBIÇÃO (MAX do SIAFE; sem SIAFE, MAX do espelho);
      - nome_match: TODAS as grafias distintas (lower) concatenadas → haystack do LIKE primário;
      - nome_ns: nome_match só-alfanumérico → haystack do fallback sem-espaço."""
    alvo = _resolver_db_inteligencia(db_path)
    if not Path(alvo).exists():
        return {"ok": False, "erro": "db_inexistente", "db": str(alvo)}
    from compliance_agent.cruzamentos_intel import _ob_paga
    from compliance_agent.reporting.intel_base import SQL_CREDOR_TERCEIRO_SIAFE
    con = sqlite3.connect(str(alvo))
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")  # espera o lock do sweep (não erra na hora)
        # 1) leitura (fora da transação de escrita — não segura o lock durante as duas varreduras)
        tem_siafe = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='ob_orcamentaria_siafe'").fetchone() is not None
        siafe: dict = {}        # credor -> [n, total, {grafias}, nome_exibicao]
        anos_siafe: set = set()
        if tem_siafe:
            # `+credor`: varredura em ordem física (o índice de credor faz leitura aleatória: 154 s × 22 s medidos)
            for doc, nome, ano, n, tot in con.execute(
                    f"SELECT credor, nome_credor, exercicio, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
                    f"WHERE {_ob_paga(con)} AND {SQL_CREDOR_TERCEIRO_SIAFE} GROUP BY +credor, nome_credor, exercicio"):
                e = siafe.setdefault(doc, [0, 0.0, set(), ""])
                e[0] += n
                e[1] += float(tot or 0.0)
                if nome:
                    e[2].add(nome.lower())
                    e[3] = max(e[3], nome)
                if ano:
                    anos_siafe.add(str(ano))
        tfe: dict = {}          # cpf -> [n_coberto, total_coberto, {grafias}, nome_exibicao]
        # espelho-fora-do-produto: soma do TFE só como CONFRONTO (coluna tfe_* / divergência), nunca como pago
        for doc, nome, ano, n, tot in con.execute(
                "SELECT favorecido_cpf, favorecido_nome, exercicio, COUNT(*), SUM(valor) "
                "FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL GROUP BY 1, 2, 3"):
            e = tfe.setdefault(doc, [0, 0.0, set(), ""])
            if str(ano) in anos_siafe:   # confronto só no período que o SIAFE cobre
                e[0] += n
                e[1] += float(tot or 0.0)
            if nome:
                e[2].add(nome.lower())
                e[3] = max(e[3], nome)
        linhas = []
        for doc in siafe.keys() | tfe.keys():
            s_, t_ = siafe.get(doc), tfe.get(doc)
            grafias = sorted((s_[2] if s_ else set()) | (t_[2] if t_ else set()))
            nm = " | ".join(grafias)   # ' | ' p/ um termo não casar "atravessando" duas grafias
            linhas.append((doc, (s_[3] if s_ and s_[3] else (t_[3] if t_ else "")) or None,
                           s_[0] if s_ else None, round(s_[1], 2) if s_ else None, nm, _norm_alnum(nm),
                           t_[0] if t_ else None, round(t_[1], 2) if t_ else None,
                           "siafe" if s_ else "so_tfe"))
        # 2) escrita numa transação só
        con.execute("BEGIN IMMEDIATE")
        con.execute("DROP TABLE IF EXISTS favorecido_resumo")
        con.execute(
            "CREATE TABLE favorecido_resumo ("
            " favorecido_cpf TEXT PRIMARY KEY,"
            " favorecido_nome TEXT,"   # nome de exibição
            " n_obs INTEGER,"          # OB PAGA do SIAFE (NULL = SIAFE não tem o credor: INDISPONÍVEL)
            " total_pago REAL,"        # idem
            " nome_match TEXT,"        # todas as grafias distintas (lower) — haystack do LIKE primário
            " nome_ns TEXT,"           # nome_match só-alfanumérico — haystack do fallback sem-espaço
            " n_obs_tfe INTEGER,"      # espelho TFE nos exercícios que o SIAFE cobre — só confronto
            " total_tfe REAL,"
            " fonte_valor TEXT)"       # 'siafe' | 'so_tfe'
        )
        con.executemany("INSERT INTO favorecido_resumo VALUES (?,?,?,?,?,?,?,?,?)", linhas)
        con.execute("CREATE INDEX IF NOT EXISTS ix_favres_nome ON favorecido_resumo (favorecido_nome)")
        con.commit()
        so_tfe = [x for x in linhas if x[8] == "so_tfe"]
        return {"ok": True, "linhas": len(linhas), "db": str(alvo), "fonte_valor": "OB paga SIAFE (_ob_paga)",
                "credores_siafe": len(siafe), "credores_so_tfe": len(so_tfe),
                "so_tfe_no_periodo_coberto": sum(1 for x in so_tfe if x[6]),
                "valor_so_tfe_no_periodo_coberto": round(sum(x[7] or 0 for x in so_tfe), 2),
                "exercicios_siafe": sorted(anos_siafe)}
    except Exception as exc:  # noqa: BLE001
        try:
            con.rollback()
        except Exception as exc2:  # noqa: BLE001
            logger.debug("rollback de favorecido_resumo falhou: %s", exc2)
        return {"ok": False, "erro": str(exc)[:200], "db": str(alvo)}
    finally:
        con.close()


def buscar_candidatos(termo: str, limite: int = 8) -> list[dict]:
    """
    Resolve por CNPJ OU por nome (inclusive PARCIAL). Retorna lista de candidatos
    [{cnpj, nome, fonte, total_pago, n_obs}], rankeados por valor pago (empresas com dados de OB
    aparecem primeiro — são as mais relevantes para auditoria). Lista vazia = nada encontrado.
    `total_pago`/`n_obs` = OB PAGA do SIAFE (régua `_ob_paga`); o espelho TFE (e a `favorecido_resumo` que dele
    deriva) serve só para CASAR O NOME — valor dele não vai à pergunta de desambiguação (21/11/2026).
    """
    termo = (termo or "").strip()
    dig = so_digitos(termo)
    if len(dig) == 14:
        return [{"cnpj": dig, "nome": _nome_por_cnpj(dig), "fonte": "cnpj", "total_pago": 0.0, "n_obs": 0}]

    alvo = termo.lower().strip()
    if not alvo:
        return []

    cands: "OrderedDict[str, dict]" = OrderedDict()

    def _add(cnpj, nome, fonte):
        cnpj = so_digitos(cnpj)
        if not cnpj:
            return
        if cnpj not in cands:
            cands[cnpj] = {"cnpj": cnpj, "nome": nome or "", "fonte": fonte, "total_pago": 0.0, "n_obs": 0}
        elif nome and not cands[cnpj]["nome"]:
            cands[cnpj]["nome"] = nome

    # 1) registro curado
    for e in _carregar_registro():
        if alvo in (e.get("nome", "").lower()):
            _add(e.get("cnpj", ""), e.get("nome", ""), "registro")

    if _DB.exists():
        con = sqlite3.connect(_DB)
        con.row_factory = sqlite3.Row
        try:
            # 2) tabela empresas (perfil cadastral)
            for r in con.execute(
                "SELECT cnpj, razao_social FROM empresas WHERE lower(razao_social) LIKE ? LIMIT 50",
                (f"%{alvo}%",)):
                _add(r["cnpj"], r["razao_social"], "empresas_db")
            # 3) nomes nas OBs (fonte mais rica) — agrega valor pago para rankear.
            # ACELERAÇÃO: a tabela-resumo `favorecido_resumo` (74k linhas, GROUP BY pré-computado) substitui
            # o scan de ordens_bancarias (1,12M) — mesmo LIKE, ~15× mais rápido. SÓ se ela existir e não
            # estiver vazia; senão cai no caminho antigo (scan de OB) — se a tabela faltar/stale, nada quebra.
            usa_resumo = _favorecido_resumo_disponivel(con)
            if usa_resumo:
                # match em nome_match (TODAS as grafias do CPF) p/ paridade com o scan linha-a-linha de OB
                for r in con.execute(
                    "SELECT favorecido_cpf cnpj, favorecido_nome nome, n_obs n, total_pago total "
                    "FROM favorecido_resumo WHERE nome_match LIKE ? "
                    "ORDER BY total_pago DESC LIMIT 50",
                    (f"%{alvo}%",)):
                    _add(r["cnpj"], r["nome"], "obs")
            else:
                for r in con.execute(
                    "SELECT favorecido_cpf cnpj, MAX(favorecido_nome) nome, COUNT(*) n FROM ordens_bancarias "
                    "WHERE lower(favorecido_nome) LIKE ? AND favorecido_cpf IS NOT NULL "
                    "GROUP BY favorecido_cpf ORDER BY n DESC LIMIT 50",
                    (f"%{alvo}%",)):
                    _add(r["cnpj"], r["nome"], "obs")
            # fallback SEM-ESPAÇO: "engeprat" (junto) não casa "ENGE PRAT" no LIKE normal. Colapsa os espaços
            # dos DOIS lados e tenta de novo — só quando nada foi achado. Com a tabela-resumo usa a coluna
            # pré-computada `nome_ns` (já sem espaço/minúscula); senão REPLACE no scan de OB (~1-2s, fallback).
            if not cands:
                alvo_ns = alvo.replace(" ", "")
                if len(alvo_ns) >= 3:
                    for r in con.execute(
                        "SELECT cnpj, razao_social FROM empresas "
                        "WHERE REPLACE(lower(razao_social), ' ', '') LIKE ? LIMIT 50", (f"%{alvo_ns}%",)):
                        _add(r["cnpj"], r["razao_social"], "empresas_db")
                    if usa_resumo:
                        # nome_ns é só-alfanumérico (tira espaço E pontuação) → normaliza o termo igual
                        for r in con.execute(
                            "SELECT favorecido_cpf cnpj, favorecido_nome nome, n_obs n, total_pago total "
                            "FROM favorecido_resumo WHERE nome_ns LIKE ? "
                            "ORDER BY total_pago DESC LIMIT 50", (f"%{_norm_alnum(alvo)}%",)):
                            _add(r["cnpj"], r["nome"], "obs")
                    else:
                        for r in con.execute(
                            "SELECT favorecido_cpf cnpj, MAX(favorecido_nome) nome, COUNT(*) n FROM ordens_bancarias "
                            "WHERE REPLACE(lower(favorecido_nome), ' ', '') LIKE ? AND favorecido_cpf IS NOT NULL "
                            "GROUP BY favorecido_cpf ORDER BY n DESC LIMIT 50", (f"%{alvo_ns}%",)):
                            _add(r["cnpj"], r["nome"], "obs")
            # preenche métricas de OB para todos os candidatos — OB PAGA do SIAFE (índice de `credor`, barato).
            from compliance_agent.cruzamentos_intel import _ob_paga
            for cnpj, c in cands.items():
                r = con.execute(
                    "SELECT COUNT(*) n, ROUND(SUM(valor),2) total FROM ob_orcamentaria_siafe "
                    f"WHERE credor=? AND {_ob_paga(con)}", (cnpj,)).fetchone()
                c["n_obs"] = int(r["n"] or 0)
                c["total_pago"] = float(r["total"] or 0.0)
        except Exception as exc:
            logger.warning("falha ao consultar métricas de OB dos candidatos (n_obs/total podem sair zerados): %s", exc)
        finally:
            con.close()

    # colapsa estabelecimentos da MESMA raiz (8 díg.) num candidato único — matriz+filiais = uma só PJ
    # (CC arts. 44/985/1.142; STJ REsp 1.286.122). Evita o Yoda "duplicar" a empresa e consolida o total do grupo.
    grupos: "OrderedDict[str, dict]" = OrderedDict()
    for c in cands.values():
        raiz = so_digitos(c["cnpj"])[:8]
        g = grupos.setdefault(raiz, {"membros": [], "total_pago": 0.0, "n_obs": 0})
        g["membros"].append(c)
        g["total_pago"] += c["total_pago"]
        g["n_obs"] += c["n_obs"]
    colapsados = []
    for raiz, g in grupos.items():
        membros = g["membros"]
        # representante: a matriz (0001) se houver, senão o estabelecimento de maior valor pago
        matriz = next((m for m in membros if so_digitos(m["cnpj"])[8:12] == "0001"), None)
        rep = matriz or max(membros, key=lambda m: (m["total_pago"], m["n_obs"]))
        nome = rep["nome"] or ""
        if len(membros) > 1:
            if matriz:
                n_fil = len(membros) - 1
                nome = f"{nome} (matriz + {n_fil} {'filiais' if n_fil > 1 else 'filial'})"
            else:
                nome = f"{nome} ({len(membros)} estabelecimentos — filiais)"
        colapsados.append({"cnpj": rep["cnpj"], "nome": nome, "fonte": rep["fonte"],
                           "total_pago": round(g["total_pago"], 2), "n_obs": g["n_obs"],
                           "raiz": raiz, "n_estabelecimentos": len(membros)})
    ordenados = sorted(colapsados, key=lambda c: (c["total_pago"], c["n_obs"]), reverse=True)
    return ordenados[:limite]


def consultar_pagamentos(cnpj: str, anos: Optional[list[int]] = None) -> dict:
    """
    OBs PAGAS ao fornecedor — SIAFE (`ob_orcamentaria_siafe`, régua única `cruzamentos_intel._ob_paga`), nunca o
    espelho TFE. Até 21/11/2026 isto somava `ordens_bancarias.valor` e chamava de "pago" (revisão crítica D4).
    Par UG×ano que o SIAFE da casa não cobre inteiro vai em `cobertura` (INDISPONÍVEL/PARCIAL, com a CONTAGEM de
    OB que o espelho lista ali) — o total é então piso, nunca completado com valor do espelho.
    Retorna estrutura por ano com as linhas individuais.

    {
      "tem_dados": bool,
      "anos": [2023, 2024, 2025, 2026],
      "total_geral": float, "n_geral": int,
      "por_ano": { 2023: {"n": int, "total": float, "linhas": [ {numero_ob,data,orgao,valor}, ... ],
                          "por_orgao": {orgao: total, ...}}, ... },
      "por_orgao_geral": {orgao: total, ...},
      "hhi": {"indice": float, "nivel": str},
    }
    """
    out = {"tem_dados": False, "anos": [], "total_geral": 0.0, "n_geral": 0,
           "por_ano": OrderedDict(), "por_orgao_geral": {}, "hhi": {},
           "raiz": so_digitos(cnpj)[:8], "por_estabelecimento": [], "n_estabelecimentos": 0}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    raiz = cnpj[:8]  # consolidar matriz+filiais = uma só PJ (CC 44/985/1.142; STJ REsp 1.286.122)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        from compliance_agent.cruzamentos_intel import _ob_paga
        from compliance_agent.reporting.cobertura_siafe import (
            ANO_EMISSAO_SIAFE, ISO_EMISSAO_SIAFE, lacunas_do_recorte, resumo_lacunas)
        # GLOB raiz* casa todos os estabelecimentos (matriz 0001 + filiais 0002+) e usa o índice de `credor`
        q = (f"SELECT numero_ob, {ISO_EMISSAO_SIAFE} data_pagamento, ug_emitente ug_codigo, valor, "
             f"CAST({ANO_EMISSAO_SIAFE} AS INTEGER) exercicio, credor favorecido_cpf, nome_credor favorecido_nome "
             f"FROM ob_orcamentaria_siafe WHERE credor GLOB ? AND {_ob_paga(con)}")
        params: list = [f"{raiz}*"]
        if anos:
            q += f" AND CAST({ANO_EMISSAO_SIAFE} AS INTEGER) IN (%s)" % ",".join("?" * len(anos))
            params += list(anos)
        q += " ORDER BY 5, 2, numero_ob"
        try:
            rows = con.execute(q, params).fetchall()
        except sqlite3.OperationalError:     # base sem a tabela do SIAFE: INDISPONÍVEL, não zero
            rows = []
        lac = lacunas_do_recorte(con, credor_raiz=raiz, anos=anos, db=_DB)
        # nome da UG para exibir (o SIAFE não traz): texto do espelho, nunca valor
        nomes_ug: dict = {}
        for u in {r["ug_codigo"] for r in rows}:
            try:
                rn = con.execute("SELECT ug_nome FROM ordens_bancarias WHERE ug_codigo=? AND ug_nome IS NOT NULL "
                                 "LIMIT 1", (u,)).fetchone()
            except sqlite3.OperationalError:
                rn = None
            nomes_ug[u] = (rn[0] if rn else "") or ""
    finally:
        con.close()
    out["fonte_ob"] = "SIAFE (ob_orcamentaria_siafe, régua _ob_paga)"
    out["cobertura"] = {"lacunas": lac, **resumo_lacunas(lac, n_siafe=len(rows))}
    if not rows:
        return out

    from compliance_agent import ugs  # mapa canônico de UG (corrige p.ex. 133100 -> ITERJ)

    por_ano: "OrderedDict[int, dict]" = OrderedDict()
    orgao_geral: dict = defaultdict(float)
    # pivot Órgão × Mês × Ano-exercício: (orgao, ano) -> {mes(1..12): total, 0: sem-data}
    orgao_mes_ano: dict = defaultdict(lambda: defaultdict(float))
    # quebra por estabelecimento (matriz/filial) — transparência da consolidação por raiz
    por_estab: dict = {}
    for r in rows:
        ano = int(r["exercicio"] or 0)
        bloco = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_orgao": defaultdict(float)})
        valor = float(r["valor"] or 0.0)
        est_cnpj = so_digitos(r["favorecido_cpf"])
        est = por_estab.setdefault(est_cnpj, {"cnpj": est_cnpj, "nome": r["favorecido_nome"] or "—",
                                              "n": 0, "total": 0.0,
                                              "tipo": "matriz" if est_cnpj[8:12] == "0001" else f"filial {est_cnpj[8:12]}"})
        est["n"] += 1
        est["total"] += valor
        # rótulo canônico da unidade gestora (corrige o nome do órgão superior nas OBs)
        orgao = ugs.rotulo(r["ug_codigo"], nomes_ug.get(r["ug_codigo"]) or "—")
        data = (r["data_pagamento"] or "—")
        # mês do pagamento (ISO YYYY-MM-DD); 0 quando a data não vem
        mes = 0
        if isinstance(data, str) and len(data) >= 7 and data[4:5] == "-":
            try:
                mes = int(data[5:7])
                mes = mes if 1 <= mes <= 12 else 0
            except ValueError:
                mes = 0
        bloco["n"] += 1
        bloco["total"] += valor
        bloco["por_orgao"][orgao] += valor
        bloco["linhas"].append({"numero_ob": r["numero_ob"] or "—", "data": data, "orgao": orgao, "valor": valor})
        orgao_geral[orgao] += valor
        orgao_mes_ano[(orgao, ano)][mes] += valor

    for ano, b in por_ano.items():
        b["por_orgao"] = dict(sorted(b["por_orgao"].items(), key=lambda kv: kv[1], reverse=True))
    out["por_ano"] = por_ano
    # consolida o pivot mensal: lista ordenada por (órgão, ano)
    matriz_mes: list[dict] = []
    for (orgao, ano), meses in orgao_mes_ano.items():
        matriz_mes.append({"orgao": orgao, "ano": ano,
                           "meses": {m: round(v, 2) for m, v in meses.items()},
                           "total": round(sum(meses.values()), 2)})
    matriz_mes.sort(key=lambda x: (x["orgao"], x["ano"]))
    out["por_orgao_mes_ano"] = matriz_mes
    # estabelecimentos (matriz+filiais) consolidados nesta empresa (raiz)
    estabs = sorted(por_estab.values(), key=lambda e: e["total"], reverse=True)
    for e in estabs:
        e["total"] = round(e["total"], 2)
    out["raiz"] = raiz
    out["por_estabelecimento"] = estabs
    out["n_estabelecimentos"] = len(estabs)
    out["anos"] = sorted(por_ano.keys())
    out["n_geral"] = sum(b["n"] for b in por_ano.values())
    out["total_geral"] = sum(b["total"] for b in por_ano.values())
    out["por_orgao_geral"] = dict(sorted(orgao_geral.items(), key=lambda kv: kv[1], reverse=True))
    out["hhi"] = _hhi(out["por_orgao_geral"])
    out["tem_dados"] = True
    return out


def _hhi(por_orgao: dict) -> dict:
    """Índice Herfindahl-Hirschman da concentração por órgão (0..10000)."""
    total = sum(v for v in por_orgao.values() if v > 0)
    if total <= 0:
        return {"indice": 0.0, "nivel": "—", "top_share": 0.0}
    indice = sum((v / total * 100) ** 2 for v in por_orgao.values() if v > 0)
    if indice < 1500:
        nivel = "BAIXA"
    elif indice < 2500:
        nivel = "MODERADA"
    else:
        nivel = "ALTA"
    top = max(por_orgao.values())
    return {"indice": round(indice, 1), "nivel": nivel, "top_share": round(top / total * 100, 1)}


def _crescimento(pagamentos: dict) -> float:
    """Razão pico/base entre exercícios COMPLETOS com dado (>0). 1.0 se não dá p/ medir.
    Mede salto de faturamento atípico (capacidade operacional / aditivos a verificar)."""
    anos = pagamentos.get("anos") or []
    vals = [pagamentos["por_ano"][a]["total"] for a in anos if pagamentos["por_ano"][a]["total"] > 0]
    if len(vals) < 2:
        return 1.0
    base = min(vals)
    return (max(vals) / base) if base > 0 else 1.0


def _recalibrar_risco(pagamentos: dict, rede: list, contratado_tcerj: float,
                      score_ext: int, risco_ext: str,
                      coendereco: Optional[list] = None, anomalias: Optional[dict] = None,
                      natureza_sem_fins: Optional[dict] = None,
                      sede_status: Optional[str] = None,
                      emendas: Optional[dict] = None) -> dict:
    """Risco JFN = MAIOR entre o score externo e o score interno por sinais REAIS do relatório.
    Corrige o caso em que o enriquecedor externo devolve 0 mas há indícios (conflito, pago≫contratado,
    crescimento atípico, concentração, magnitude, rede mesma-sede §1-B, anomalias PyOD §8-C).
    Indício a verificar — nunca acusação; peso conservador para o NÚMERO refletir a prosa, não inflar."""
    total = float(pagamentos.get("total_geral") or 0)
    top_share = float((pagamentos.get("hhi") or {}).get("top_share") or 0)
    cresc = _crescimento(pagamentos)
    sinais: list[str] = []
    s = 0
    if rede:
        s += 20; sinais.append("conflito doador↔contrato (sócio/empresa doou e é fornecedor)")
        # CONVERGÊNCIA (backlog #16): doador eleitoral CUJA sede é, ela própria, indício de fachada
        # (`verificacao_sede`=INDICIO) é sinal forte — relação política + empresa-fantasma no MESMO
        # fornecedor (art. 337-F CP; art. 11 Lei 8.429/92; Lei 9.504/97). Peso conservador; só soma quando
        # AMBOS os indícios tocam o MESMO CNPJ. Indício a verificar, nunca acusação.
        if (sede_status or "").upper() == "INDICIO":
            s += 15; sinais.append("convergência §1-D×sede: doador eleitoral com sede indício de fachada "
                                   "(art. 337-F CP; art. 11 Lei 8.429/92; Lei 9.504/97)")
    if contratado_tcerj and total > contratado_tcerj * 1.5:
        s += 25; sinais.append(f"pago (R$ {moeda(total)}) ≫ contratado registrado (R$ {moeda(contratado_tcerj)}) — {total/contratado_tcerj:.1f}×")
    elif contratado_tcerj and total > contratado_tcerj * 1.2:
        s += 12; sinais.append(f"pago acima do contratado registrado ({total/contratado_tcerj:.1f}×)")
    if cresc >= 4:
        s += 15; sinais.append(f"crescimento de faturamento atípico (pico/base = {cresc:.1f}×)")
    elif cresc >= 2.5:
        s += 8; sinais.append(f"crescimento de faturamento relevante ({cresc:.1f}×)")
    if top_share >= 60:
        s += 25; sinais.append(f"concentração ≥60% num órgão ({top_share:.0f}%)")
    elif top_share >= 40:
        s += 12; sinais.append(f"concentração relevante no maior órgão ({top_share:.0f}%)")
    if total >= 100e6:
        s += 10; sinais.append(f"exposição muito alta ao erário (R$ {moeda(total)})")
    elif total >= 50e6:
        s += 5; sinais.append(f"exposição alta (R$ {moeda(total)})")

    # Rede MESMA-SEDE (§1-B): N fornecedores no MESMO endereço também recebendo do Estado = indício de
    # fachada/laranja/direcionamento (art. 337-F CP; art. 11 Lei 8.429/92). Peso conservador, escalonado
    # pelo nº de co-endereçados que TAMBÉM recebem OBs (não basta dividir CEP; tem de tocar o erário).
    coend = coendereco or []
    n_coend_pagos = sum(1 for c in coend if (c.get("total_pago") or 0) > 0)
    if n_coend_pagos >= 5:
        s += 20; sinais.append(f"rede mesma-sede §1-B: {n_coend_pagos} fornecedores na MESMA sede também recebendo do Estado")
    elif n_coend_pagos >= 2:
        s += 12; sinais.append(f"rede mesma-sede §1-B: {n_coend_pagos} fornecedores na MESMA sede também recebendo do Estado")
    elif n_coend_pagos == 1:
        s += 6; sinais.append("rede mesma-sede §1-B: 1 fornecedor na MESMA sede também recebendo do Estado")

    # Anomalias PyOD (§8-C): alta FRAÇÃO de OBs com score de anomalia ≥0,70 no ensemble não supervisionado.
    # Usar a FRAÇÃO (não o nº bruto) p/ não punir fornecedor com muitas OBs; peso conservador (indício de
    # pagamento atípico a inspecionar, nunca prova).
    an = anomalias or {}
    if an.get("ok") and (an.get("n_obs") or 0) > 0:
        frac = (an.get("n_anomalas") or 0) / an["n_obs"]
        if frac >= 0.30 and (an.get("n_anomalas") or 0) >= 3:
            s += 18; sinais.append(f"anomalias §8-C: {frac*100:.0f}% das OBs com score alto de anomalia ({an['n_anomalas']}/{an['n_obs']})")
        elif frac >= 0.15 and (an.get("n_anomalas") or 0) >= 2:
            s += 10; sinais.append(f"anomalias §8-C: {frac*100:.0f}% das OBs com score alto de anomalia ({an['n_anomalas']}/{an['n_obs']})")
        elif (an.get("n_anomalas") or 0) >= 1:
            s += 4; sinais.append(f"anomalias §8-C: {an['n_anomalas']} OB(s) com score alto de anomalia")

    # Natureza SEM FINS LUCRATIVOS (§1, dump local): OS/associação/fundação recebendo como fornecedor comum
    # (Lei 9.637/98; Lei 13.019/2014 — MROSC) é indício a confirmar (objeto/credenciamento/prestação de
    # contas). Peso CONSERVADOR e escalonado por valor; SÓ quando NÃO há ressalva de ensino/pesquisa/estágio
    # (nunca punir CIEE/FGV). Indício ≠ acusação.
    nsf = natureza_sem_fins or {}
    if nsf.get("sem_fins") and not nsf.get("ressalva"):
        nat_txt = nsf.get("natureza_txt") or "sem fins lucrativos"
        if total >= 50e6:
            s += 10; sinais.append(f"natureza §1: {nat_txt} ('3xxx') recebendo como fornecedor comum (Lei 9.637/98; Lei 13.019/2014 — MROSC)")
        elif total >= 5e6:
            s += 8; sinais.append(f"natureza §1: {nat_txt} ('3xxx') recebendo como fornecedor comum (Lei 9.637/98; Lei 13.019/2014 — MROSC)")
        else:
            s += 6; sinais.append(f"natureza §1: {nat_txt} ('3xxx') recebendo como fornecedor comum (Lei 9.637/98; Lei 13.019/2014 — MROSC)")

    # Emendas parlamentares (§1-D0): OSC financiada por indicação política. Concentração de MUITOS
    # padrinhos numa mesma entidade = operador de emendas (captura). Peso conservador, escalonado.
    em = emendas or {}
    if em.get("tem_dados"):
        na = int(em.get("n_autores") or 0)
        if na >= 5:
            s += 22; sinais.append(f"operador de emendas §1-D0: {na} padrinhos parlamentares "
                                   f"financiam a entidade (R$ {moeda(em.get('total', 0))})")
        elif na >= 2:
            s += 12; sinais.append(f"recurso por indicação parlamentar §1-D0: {na} autores")
        else:
            s += 6; sinais.append("financiamento por emenda parlamentar §1-D0")

    interno = min(100, s)
    final = max(int(score_ext or 0), interno)
    if final >= 70:
        risco = "ALTO"
    elif final >= 35:
        risco = "MÉDIO"
    elif final >= 15:
        risco = "ATENÇÃO"
    else:
        risco = "BAIXO"
    return {"score": final, "risco": risco, "score_externo": int(score_ext or 0),
            "score_interno": interno, "sinais": sinais}


def consultar_contratos(cnpj: str) -> dict:
    """Contratos oficiais (compliance.db). Retorna {n, total, linhas[...]}."""
    out = {"n": 0, "total": 0.0, "linhas": []}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    raiz = cnpj[:8]  # contratos de TODOS os estabelecimentos da raiz (matriz+filiais = uma PJ)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        emps = con.execute("SELECT id FROM empresas WHERE cnpj LIKE ?", (f"{raiz}%",)).fetchall()
        if not emps:
            return out
        ids = [e["id"] for e in emps]
        rows = con.execute(
            "SELECT numero, objeto, orgao_contrat, valor_total, data_assinatura, status "
            "FROM contratos WHERE empresa_id IN (%s) ORDER BY valor_total DESC" % ",".join("?" * len(ids)),
            ids,
        ).fetchall()
    finally:
        con.close()
    for r in rows:
        out["linhas"].append({
            "numero": r["numero"] or "—", "objeto": r["objeto"] or "—",
            "orgao": r["orgao_contrat"] or "—", "valor": float(r["valor_total"] or 0.0),
            "assinatura": r["data_assinatura"] or "—", "status": r["status"] or "—",
        })
    out["n"] = len(out["linhas"])
    out["total"] = sum(l["valor"] for l in out["linhas"])
    return out


_ENRIQUECE_CACHE_PREFIXO = "enriquece_relatorio"


def _enriquece_cache_get(cnpj: str) -> Optional[dict]:
    """Lê o enriquecimento cacheado por CNPJ (TTL _ENRIQUECE_CACHE_TTL). None = miss/desligado."""
    if _ENRIQUECE_CACHE_TTL <= 0:
        return None
    try:
        from relatorio_riscos.collectors import cache as _cache
        res = _cache.get(_ENRIQUECE_CACHE_PREFIXO, so_digitos(cnpj))
        if isinstance(res, dict) and res.get("ok"):
            res["_fonte"] = "CACHE"  # REAL, porém servido do cache (transparência)
            return res
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache de enriquecimento ilegível p/ %s (segue sem cache): %s", cnpj, exc)
    return None


def _enriquece_cache_set(cnpj: str, res: dict) -> None:
    """Persiste APENAS resultado REAL (ok=True). Falha transitória nunca é cacheada por 7 dias."""
    if _ENRIQUECE_CACHE_TTL <= 0 or not (isinstance(res, dict) and res.get("ok")):
        return
    try:
        from relatorio_riscos.collectors import cache as _cache
        _cache.set(_ENRIQUECE_CACHE_PREFIXO, res, so_digitos(cnpj), ttl=_ENRIQUECE_CACHE_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("falha ao gravar cache de enriquecimento de %s (todo relatório re-busca): %s", cnpj, exc)


async def _enriquecer(cnpj: str) -> dict:
    """gerar_relatorio_risco best-effort, com cache por CNPJ + retry/backoff (egress lento da VM).
    Nunca derruba o relatório. fonte: REAL (fresco) | CACHE (REAL servido do cache) | INDISPONIVEL.
    O cache guarda só resultado REAL (TTL 7 dias) para não repetir o egress a cada /relatorio; falhas
    transitórias NÃO são cacheadas (próximo relatório tenta de novo). Degrada honesto: INDISPONÍVEL ≠ inventar."""
    cacheado = _enriquece_cache_get(cnpj)
    if cacheado is not None:
        return cacheado

    from relatorio_riscos import gerar_relatorio_risco
    tentativas = max(1, _ENRIQUECE_TENTATIVAS)
    ultimo_motivo = "falha"
    for tentativa in range(1, tentativas + 1):
        try:
            res = await asyncio.wait_for(
                gerar_relatorio_risco(cnpj, formato="md", salvar=False), timeout=_ENRIQUECE_TIMEOUT
            )
            if res.get("ok"):
                res["_fonte"] = "REAL"
                _enriquece_cache_set(cnpj, res)
                return res
            ultimo_motivo = res.get("erro", "falha")
            # erro determinístico do upstream (ex.: CNPJ inválido) — não adianta repetir
            break
        except asyncio.TimeoutError:
            ultimo_motivo = f"timeout {_ENRIQUECE_TIMEOUT:.0f}s (egress lento)"
        except Exception as exc:  # noqa: BLE001
            ultimo_motivo = str(exc)[:120]
        if tentativa < tentativas:
            await asyncio.sleep(_ENRIQUECE_BACKOFF * tentativa)  # backoff linear (2s, 4s, ...)
    return {"ok": False, "_fonte": "INDISPONIVEL", "_motivo": ultimo_motivo}
