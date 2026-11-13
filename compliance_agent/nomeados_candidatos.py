# -*- coding: utf-8 -*-
"""Servidor/nomeado (folha) × candidato (TSE) — uma linha por PESSOA, com a verificação declarada.

POR QUE ESTE MÓDULO EXISTE (13/11/2026). A rota antiga cruzava a folha com `doacoes_eleitorais` só pelo
NOME, com `LIMIT 1000` sobre linhas ordenadas por nome. Medido na base viva: os 1.000 "cruzamentos" eram o
TETO (a lista parava em nomes começados por "ARI"), eram 442 pessoas repetidas em até 54 cartões (uma linha
por cargo × eleição × órgão), misturavam a Câmara Municipal do Rio com o Estado e não diziam se a pessoa da
folha era a mesma do TSE. Diretriz do dono: "não pode ter margem pra erro em nada" — nome igual NÃO é
vínculo confirmado.

O que muda:
- Candidatos vêm da FONTE PRIMÁRIA — `consulta_cand_{ano}_RJ.csv` do TSE (dados abertos, em
  `data/tse_cache/`), que traz o CPF do candidato (exceto 2024, que o TSE publicou sem CPF). 2018 não tem o
  arquivo no cache: entra pela prestação de contas (`doacoes_eleitorais`), só com nome.
- Segundo atributo: a folha do Estado publica o CPF mascarado com 6 dígitos centrais (`XX123456XXX`). Se os
  6 dígitos batem com o CPF do TSE → VERIFICADO. Se o TSE tem CPF e NENHUM bate → homônimo comprovado, a
  candidatura sai (e é contada em `homonimos_descartados`). Sem CPF de um dos lados → PENDENTE, rotulado
  "possível homônimo — não verificado".
- Uma pessoa = um cartão, com todas as candidaturas e todos os vínculos da folha.
- Esfera pela FONTE da folha: Câmara Municipal do Rio é municipal; Defensoria, TJRJ e o Executivo
  (GESPERJ) são estaduais.
- Totais reais (n por estado de verificação, por esfera); a lista nunca é cortada em silêncio.

CPF nunca sai deste módulo — nem o fragmento. Sai só o veredito da conferência.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
TSE_DIR = RAIZ / "data" / "tse_cache"
ANOS_CSV = (2016, 2020, 2022, 2024, 2026)

# Fonte da folha → esfera e rótulo. Fonte desconhecida NÃO vira estadual por omissão: vira "indefinida".
ESFERA_FONTE = {
    "gesperj_estado": ("estado", "Executivo estadual (GESPERJ)"),
    "dprj_transparencia": ("estado", "Defensoria Pública do Estado do RJ"),
    "tjrj_anexo8": ("estado", "Tribunal de Justiça do Estado do RJ"),
    "camara_csv": ("municipal", "Câmara Municipal do Rio de Janeiro"),
}

VERIFICADO, PENDENTE = "VERIFICADO", "PENDENTE"
_RE_CPF_FOLHA = re.compile(r"^XX(\d{6})XXX$")

# ONDE os 6 dígitos da folha caem no CPF de 11 — varia por FONTE, embora as duas gravem `XX123456XXX`.
# Medido com controle positivo em 13/11/2026 (folha × TSE consulta_cand, pares de mesmo nome com CPF dos
# dois lados): GESPERJ casa no deslocamento 3 (dígitos 4–9, a máscara padrão `***.123.456-**`) em 2.670 de
# 6.818 pares e em 0 no deslocamento 2; a Defensoria casa no deslocamento 2 em 17 de 50 e 1 no 3. Comparar
# GESPERJ no deslocamento 2 dava "17 confirmados e 4.443 homônimos" — número confiante e falso.
# Fonte fora desta tabela NÃO é conferida (fica PENDENTE): deslocamento presumido é chute.
DESLOC_CPF_FONTE = {"gesperj_estado": 3, "dprj_transparencia": 2}


def normalizar(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", s).strip()


def fragmento_folha(cpf: str) -> str | None:
    """Os 6 dígitos centrais que a folha publica (`XX123456XXX`) — None se o formato não for esse."""
    m = _RE_CPF_FOLHA.match((cpf or "").strip())
    return m.group(1) if m else None


def _cpf_tse(c: str) -> str | None:
    c = (c or "").strip()
    return c if c.isdigit() and len(c) == 11 else None


def carregar_candidatos(tse_dir: Path = TSE_DIR, con: sqlite3.Connection | None = None) -> tuple[dict, dict]:
    """{nome_norm: [candidatura]} e a cobertura por ano. Candidatura = ano, cargo, município, partido,
    situação, resultado e `cpf` (só para conferir; nunca exposto). Uma por SQ_CANDIDATO (2º turno não duplica)."""
    cands: dict[str, list] = {}
    cobertura: dict = {}
    for ano in ANOS_CSV:
        p = Path(tse_dir) / f"consulta_cand_{ano}_RJ.csv"
        if not p.exists():
            cobertura[str(ano)] = {"fonte": "TSE consulta_cand", "estado": "INDISPONÍVEL — arquivo ausente"}
            continue
        vistos, n, n_cpf = set(), 0, 0
        with open(p, encoding="latin-1", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                sq = r.get("SQ_CANDIDATO") or f"{r.get('NM_CANDIDATO')}|{r.get('DS_CARGO')}|{r.get('NM_UE')}"
                if sq in vistos:
                    continue
                vistos.add(sq)
                cpf = _cpf_tse(r.get("NR_CPF_CANDIDATO", ""))
                n += 1
                n_cpf += cpf is not None
                cands.setdefault(normalizar(r.get("NM_CANDIDATO", "")), []).append({
                    "ano": ano, "cargo": (r.get("DS_CARGO") or "").title(), "municipio": r.get("NM_UE") or "",
                    "partido": r.get("SG_PARTIDO") or "", "situacao": r.get("DS_SITUACAO_CANDIDATURA") or "",
                    "resultado": "" if (r.get("DS_SIT_TOT_TURNO") or "#NULO") == "#NULO" else r["DS_SIT_TOT_TURNO"],
                    "cpf": cpf, "fonte": "TSE consulta_cand"})
        cobertura[str(ano)] = {"fonte": "TSE consulta_cand (dados abertos)", "candidaturas": n,
                               "com_cpf": n_cpf, "estado": "ok" if n_cpf else "sem CPF publicado — só nome"}
    # anos sem o arquivo do TSE no cache (2018): prestação de contas, só nome — nunca verificável
    if con is not None:
        anos_csv = {int(a) for a, c in cobertura.items() if c.get("estado") != "INDISPONÍVEL — arquivo ausente"}
        try:
            rows = con.execute("SELECT DISTINCT nome_candidato, cargo_candidato, partido, ano_eleicao "
                               "FROM doacoes_eleitorais").fetchall()
        except sqlite3.Error:
            rows = []
        n_doa = Counter()
        for nome, cargo, partido, ano in rows:
            if not ano or int(ano) in anos_csv:
                continue
            n_doa[int(ano)] += 1
            cands.setdefault(normalizar(nome), []).append({
                "ano": int(ano), "cargo": cargo or "", "municipio": "", "partido": partido or "", "situacao": "",
                "resultado": "", "cpf": None, "fonte": "TSE prestação de contas (doações recebidas)"})
        for ano, n in n_doa.items():
            cobertura[str(ano)] = {"fonte": "TSE prestação de contas — só candidatos que receberam doação",
                                   "candidaturas": n, "com_cpf": 0, "estado": "sem CPF — só nome"}
    return cands, cobertura


def _comissionado(cargo: str, vinculo: str) -> bool:
    return "COMISS" in normalizar(f"{cargo} {vinculo}")


def cruzar(con: sqlite3.Connection, tse_dir: Path = TSE_DIR) -> dict:
    """Cruzamento completo. Não corta: devolve TODAS as pessoas e os totais reais."""
    cands, cobertura = carregar_candidatos(tse_dir, con)
    nomes = set(cands)
    pessoas: dict[tuple, dict] = {}
    # Pré-filtro em SQL (a folha tem 1,36 mi de linhas; normalizar todas em Python levava minutos): nome já
    # normalizado casa direto; nome com acento, espaço duplo ou borda (Câmara, TJRJ — centenas) vai para o Python.
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _nc_nomes (n TEXT PRIMARY KEY)")
    con.execute("DELETE FROM _nc_nomes")
    con.executemany("INSERT OR IGNORE INTO _nc_nomes VALUES (?)", [(n,) for n in nomes])
    for nome, cpf, cargo, vinculo, orgao, fonte, comp in con.execute(
            "SELECT nome, cpf, cargo, vinculo, orgao_nome, fonte, MAX(competencia) FROM registros_folha "
            "WHERE nome IN (SELECT n FROM _nc_nomes) OR nome GLOB '*[^ -~]*' OR nome LIKE '%  %' "
            "OR nome <> TRIM(nome) OR nome <> UPPER(nome) "
            "GROUP BY nome, cpf, cargo, vinculo, orgao_nome, fonte"):
        nn = normalizar(nome)
        if nn not in nomes:
            continue
        frag = fragmento_folha(cpf)
        desl = DESLOC_CPF_FONTE.get(fonte)
        chave = (nn, fonte, frag) if frag else (nn, fonte, None)
        esf, rot = ESFERA_FONTE.get(fonte, ("indefinida", fonte or "fonte desconhecida"))
        p = pessoas.setdefault(chave, {"nome": nome.strip(), "_nn": nn, "_frag": frag if desl is not None else None,
                                       "_desl": desl, "_tem_cpf": bool(frag), "vinculos": []})
        p["vinculos"].append({"fonte": rot, "esfera": esf, "orgao": orgao or "", "cargo": cargo or "",
                              "vinculo": vinculo or "", "ultima_competencia": comp or "",
                              "comissionado": _comissionado(cargo, vinculo)})
    descartados = 0
    por_cpf: dict[str, dict] = {}            # pessoa VERIFICADA em duas folhas = o mesmo CPF do TSE → um cartão
    pre = []
    for p in pessoas.values():
        frag, desl, tem_cpf, lista, cpfs = p.pop("_frag"), p.pop("_desl"), p.pop("_tem_cpf"), [], set()
        for c in cands[p.pop("_nn")]:
            if frag and c["cpf"]:
                if c["cpf"][desl:desl + 6] != frag:
                    descartados += 1          # o TSE prova que é OUTRA pessoa com o mesmo nome
                    continue
                conf = VERIFICADO
                cpfs.add(c["cpf"])
            else:
                conf = PENDENTE
            lista.append({k: v for k, v in c.items() if k != "cpf"} | {"verificacao": conf})
        if not lista:
            continue
        if cpfs:
            alvo = next((por_cpf[x] for x in cpfs if x in por_cpf), None)
            if alvo is not None:               # mesma pessoa já vista noutra folha: junta vínculos e candidaturas
                alvo["vinculos"] += p["vinculos"]
                vistas = {(c["ano"], c["cargo"], c["municipio"]) for c in alvo["candidaturas"]}
                alvo["candidaturas"] += [c for c in lista if (c["ano"], c["cargo"], c["municipio"]) not in vistas]
                for x in cpfs:
                    por_cpf[x] = alvo
                continue
        p["candidaturas"] = lista
        p["_tem_cpf"], p["_desl"] = tem_cpf, desl
        for x in cpfs:
            por_cpf[x] = p
        pre.append(p)
    saida = []
    for p in pre:
        lista = p["candidaturas"]
        tem_cpf, desl = p.pop("_tem_cpf"), p.pop("_desl")
        lista.sort(key=lambda c: (c["ano"], c["cargo"]))
        p["vinculos"].sort(key=lambda v: v["ultima_competencia"], reverse=True)
        verif = VERIFICADO if any(c["verificacao"] == VERIFICADO for c in lista) else PENDENTE
        # candidatura sem CPF dentro de um cartão VERIFICADO não herda a verificação: no máximo ganha o
        # município como atributo de apoio — e continua PENDENTE
        muns = {c["municipio"] for c in lista if c["verificacao"] == VERIFICADO and c["municipio"]}
        for c in lista:
            if c["verificacao"] == VERIFICADO:
                c["nota"] = "CPF confere"
            elif c["municipio"] and c["municipio"] in muns:
                c["nota"] = ("não verificado — mesmo nome e mesmo município de candidatura verificada; "
                             "o TSE não publicou CPF desta candidatura")
            else:
                c["nota"] = "possível homônimo — não verificado"
        if verif == VERIFICADO:
            motivo = "CPF parcial da folha (6 dígitos) confere com o CPF da candidatura no TSE"
        elif tem_cpf and desl is None:
            motivo = ("possível homônimo — não verificado: a máscara de CPF desta folha não foi aferida contra o "
                      "TSE; só o nome coincide")
        elif tem_cpf:
            motivo = ("possível homônimo — não verificado: a candidatura é de ano que o TSE publicou sem CPF; "
                      "só o nome coincide")
        else:
            motivo = "possível homônimo — não verificado: a folha desta fonte não publica CPF; só o nome coincide"
        esferas = sorted({v["esfera"] for v in p["vinculos"]})
        saida.append({**p, "verificacao": verif, "motivo_verificacao": motivo,
                      "esfera": esferas[0] if len(esferas) == 1 else "mista", "esferas": esferas,
                      "comissionado": any(v["comissionado"] for v in p["vinculos"])})
    saida.sort(key=lambda x: (x["verificacao"] != VERIFICADO, not x["comissionado"], x["nome"]))
    return {"pessoas": saida, "homonimos_descartados": descartados, "cobertura_tse": cobertura}


def recortar(base: dict, esfera: str = "estado") -> dict:
    """Recorte por esfera com totais REAIS do recorte (e do universo, para o leitor ver o que ficou fora)."""
    todas = base["pessoas"]
    esfera = esfera if esfera in ("estado", "municipal", "todos") else "estado"
    it = todas if esfera == "todos" else [x for x in todas if esfera in x["esferas"]]
    por_esfera = Counter(e for x in todas for e in x["esferas"])
    return {
        "esfera": esfera,
        "total": len(it),
        "n_verificados": sum(x["verificacao"] == VERIFICADO for x in it),
        "n_pendentes": sum(x["verificacao"] == PENDENTE for x in it),
        "n_comissionados": sum(x["comissionado"] for x in it),
        "n_comissionados_verificados": sum(x["comissionado"] and x["verificacao"] == VERIFICADO for x in it),
        "n_candidaturas": sum(len(x["candidaturas"]) for x in it),
        "por_esfera": dict(por_esfera),
        "homonimos_descartados": base["homonimos_descartados"],
        "cobertura_tse": base["cobertura_tse"],
        "itens": it,
    }
