#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RESOLVER DE DUPLICIDADE PELA NOTA FISCAL — fecha o T07 da perícia (NÃO REINVENTAR #4: só a NF fecha).

O detector `duplicidade_competencia` aponta a competência DOBRADA (2+ OBs grandes, REs distintos, no mesmo
mês) e para aí: "confirmar pela NF". Medido em 11/11/2026 na `pericia_fornecedor`: dos 300 pares 🟡, 299
tinham T07 = INDICIO — 4.865 competências dobradas, 62.151 OBs, 26.354 processos SEI distintos (32.838 OBs
com processo na coluna do SIAFE), só 696 deles com texto local. Nenhum indício era resolvido; ficavam
parados. Aqui eles andam, determinístico e juízo juntos:

  1. DETERMINÍSTICO — para cada competência dobrada, o processo SEI de cada OB (coluna `processo` do SIAFE,
     só OB Contabilizado; fonte de OB é sempre o SIAFE) é lido do ARQUIVO local (`data/sei_arquivo/<tag>/`,
     ou o cache `data/sei_cache/cdp_SEI_<tag>.json[.zst]`). Das NFs extraídas (número, CNPJ emitente, valor,
     competência do serviço):
       • mesma NF em 2 processos de pagamento do mesmo mês → CONFIRMADO;
       • NFs distintas cobrando meses distintos, ou NF de retroativo/repactuação/complemento/glosa → AFASTADO;
       • OBs do mês no MESMO processo, somando ≤ o bruto das NFs dele → AFASTADO (pagamento fracionado);
       • processo sem texto → PENDENTE_CAPTURA e o processo entra em `sei_fila_captura` (INSERT OR IGNORE —
         pedido à mão não é rebaixado; motivo `duplicidade_nf:` conta como inscrição em massa no drenador).
  2. JUÍZO — onde a regra não decide e há texto: a cascata GRÁTIS da casa (`free_llm.best_free_chat`; OpenRouter
     só `:free`) devolve {veredito, nf_por_ob, motivo, citacao_literal}. A citação TEM de existir no texto
     enviado (substring normalizada) — senão o veredito cai para INDETERMINADO.

O resultado vai para `resolucao_duplicidade` e o T07 da perícia o LÊ (`pericia_sweep.enriquecer` →
`auditoria_contrato._t07_pela_nf`); cada par resolvido é re-periciado na hora.

Uso:
  .venv/bin/python tools/resolver_duplicidade_nf.py --dry-run --limit 10 --sem-llm   # mede, não grava
  .venv/bin/python tools/resolver_duplicidade_nf.py --sem-llm                          # só a regra
  .venv/bin/python tools/resolver_duplicidade_nf.py --limit 50                         # regra + juízo grátis
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent import pericia_sweep as ps  # noqa: E402
from compliance_agent.duplicidade_competencia import _comp_mm_aaaa, detectar  # noqa: E402

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"
ARQUIVO = REPO / "data" / "sei_arquivo"
CACHE = REPO / "data" / "sei_cache"

TOL = 0.05                      # centavos de arredondamento entre OB e NF
MAX_DOC_LLM = 3500              # caracteres por documento enviado ao juízo (corte por documento, citação íntegra)
MAX_TOTAL_LLM = 24000           # teto do prompt do juízo (o groq dá 413 acima de ~8k tokens)

_DDL = """CREATE TABLE IF NOT EXISTS resolucao_duplicidade (
  cnpj TEXT, ug TEXT, competencia TEXT, veredito TEXT, motivo TEXT, nfs_json TEXT, citacao TEXT, camada TEXT,
  obs_json TEXT, atualizado_em TEXT,
  PRIMARY KEY (cnpj, ug, competencia))"""

_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
          "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MES = "(" + "|".join(_MESES) + ")"
_ANO = r"(\d\.?\d{3})"            # "2024" ou "2.024" (NF municipal escreve o ano com ponto)
# DESCRITIVAS — o texto diz o MÊS DO SERVIÇO
_RX_DESC = [
    # "Competência MARÇO/2026", "Competência: Março/2026", "competência de março de 2026"
    (re.compile(r"competencia\s*:?\s*(?:de\s+)?" + _MES + r"\s*(?:/|-|de)?\s*" + _ANO), "nome"),
    # "referente ao mês de fevereiro de 2025", "relativo aos serviços de março/2024", "mês de referência: abril/2024"
    (re.compile(r"(?:referente|referencia|relativ\w*|correspondente)\b[^.\n]{0,40}?\b" + _MES + r"\s*(?:/|-|de)\s*" + _ANO), "nome"),
    # "no período de 01 a 31 de janeiro de 2.024"
    (re.compile(r"periodo\s+de\s+\d{1,2}\s+a\s+\d{1,2}\s+de\s+" + _MES + r"\s+de\s+" + _ANO), "nome"),
    # "período de 01/07/2024 a 31/07/2024" → mês do início
    (re.compile(r"periodo\s+(?:de\s+)?\d{2}/(\d{2})/(\d{4})\s+(?:a|ate)\s+\d{2}/\d{2}/\d{4}"), "num"),
]
# CAMPO numérico "Competência: 02/2024" — na NF municipal costuma ser o mês de EMISSÃO (medido no dry-run de
# 11/11/2026: NF 187 de Meriti, "Competência: 02/2024", serviço de janeiro). Só vale sem descrição, e NUNCA
# para afastar por "meses distintos". "Competência da NFS-e 01/06/2026" (data cheia) não casa.
_RX_CAMPO = re.compile(r"competencia\s*:?\s*(\d{2})/(\d{4})(?!\d)")
_RX_TITULO_MES = re.compile(r"\b" + _MES + r"\s*(?:/|-|de)?\s*" + _ANO)
_RX_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RX_SEI = re.compile(r"(\d{6})/(\d{1,6})/(\d{2,4})(?!\d)")
_RX_VALOR = [re.compile(r"valor\s+(?:bruto\s+|total\s+)?(?:do\s+|dos\s+)?servicos?\s*:?\s*(?:r\$)?\s*([\d.]+,\d{2})"),
             re.compile(r"valor\s+total\s+da\s+nota[^\d]{0,30}([\d.]+,\d{2})"),
             re.compile(r"valor\s+liquido[^\d]{0,30}([\d.]+,\d{2})")]
_RX_NUM_TEXTO = [re.compile(r"numero\s+da\s+nfs-?e\s*:?\s*(\d+)"),
                 re.compile(r"numero\s+da\s+nota(?:\s+fiscal)?\s*:?\s*(?:n[o.]\s*)?(\d+)")]
_RX_NUM_TITULO = [re.compile(r"^(?:nota\s+fiscal\b[^0-9]{0,15}?|nfs?-?e?\s*(?:n[o.]?\s*)?)(\d+)"),
                  re.compile(r"^(?:nota\s+fiscal|nfs?-?e?|danfs?e?)\b.*?\bnf\s*(?:n[o.]?\s*)?(\d+)")]
# documento que É a nota (não o despacho que a cita): título começa por NF, ou o corpo traz a marca do DANFE/DANFSe
_TITULO_NF = re.compile(r"^(?:nota\s+fiscal|nfs?-?e\b|nf\b|danf)")
_MARCA_NF = ("documento auxiliar da nfs", "danfse", "danfe", "numero da nfs-e", "chave de acesso da nfs-e")
# NF distinta que diz cobrar outra coisa que não o mês corrente
_RX_BENIGNO = re.compile(r"retroativ\w*|repactua\w*|complement\w*|glosa\w*|diferenca\s+de\s+reajuste|reajuste")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return s.replace("º", "o").replace("°", "o")


def _norm_cit(s: str) -> str:
    """Normalização da conferência de citação: sem acento, minúsculo, espaço colapsado, aspas/travessões iguais."""
    s = _norm(s)
    s = re.sub(r"[‘’“”\"'`]", "", s)
    s = re.sub(r"[–—-]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def _money(s) -> float:
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _br(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tag_processo(bruto) -> str | None:
    """'SEI-040002/001422/2026' / 'SEI 330020/0878/2025' / '330020/000211/21' → '040002_001422_2026'.
    Empenho/NL na coluna (SIAFE com colunas deslocadas) e processo E-20 (pré-SEI) → None."""
    m = _RX_SEI.search(str(bruto or ""))
    if not m:
        return None
    ano = m[3] if len(m[3]) == 4 else "20" + m[3][-2:]
    return f"{m[1]}_{int(m[2]):06d}_{ano}"


def numero_sei(tag: str) -> str:
    return "SEI-" + tag.replace("_", "/")


def _comp(mm, ano) -> str | None:
    mm = _MESES[mm] if mm in _MESES else int(mm)
    return f"{mm:02d}/{ano.replace('.', '')}" if 1 <= mm <= 12 else None


def competencia_descritiva(texto: str) -> str | None:
    """Mês de SERVIÇO que o texto descreve (MM/AAAA), ou None."""
    t = _norm(texto)
    achados = []
    for rx, _forma in _RX_DESC:
        m = rx.search(t)
        if m:
            achados.append((m.start(), _comp(m[1], m[2])))
    achados = [a for a in achados if a[1]]
    return min(achados)[1] if achados else None


def competencia_do_texto(texto: str) -> str | None:
    """A descritiva; sem ela, o campo numérico "Competência: MM/AAAA"."""
    c = competencia_descritiva(texto)
    if c:
        return c
    m = _RX_CAMPO.search(_norm(texto))
    return _comp(m[1], m[2]) if m else None


def mesmo_grupo(cnpj_a: str, cnpj_b: str) -> bool:
    """Mesma raiz de CNPJ (matriz × filial): o consórcio credor /0001 fatura pela filial /0002."""
    a, b = re.sub(r"\D", "", cnpj_a or ""), re.sub(r"\D", "", cnpj_b or "")
    return len(a) == 14 and len(b) == 14 and a[:8] == b[:8]


# ───────────────────────── histórico da OB (texto do espelho TFE, NUNCA valor) ─────────────────────────
# A coluna `processo` da `ob_orcamentaria_siafe` vem VAZIA em parte das OBs (medido 11/11/2026: 1.926
# competências sem processo em nenhuma OB), e a tabela do SIAFE não guarda o HISTÓRICO que o gestor digita na
# OB. O espelho TFE (`ordens_bancarias.observacao`) guarda. REGRA DE OURO mantida: quais OBs, valor e status
# vêm SÓ do SIAFE; do TFE sai apenas o TEXTO do histórico da MESMA OB (mesmo número, UG e credor), que diz o
# processo SEI, o contrato, a unidade e o mês do serviço:
# "PG DO DOCUMENTO 2594 CONFORME PROCESSO HOTELARIA - CONTRATO 424/2022 - COMPETENCIA 03/2023 - UNIDADE HMHS".
_RX_H_CONTRATO = re.compile(r"\bcontrato\s+(?:de\s+gestao\s+)?(?:n\s*[o.]?\s*)?(\d{1,4})\s*/\s*(\d{2,4})\b")
_RX_H_UNIDADE = re.compile(r"\b(?:unidade|opm)\s*:?\s+([a-z0-9][a-z0-9 .]{1,40}?)\s*(?=$|[-,;()]|\bretenc|\bcomp)")
_RX_H_COMP = [re.compile(r"\bcomp(?:etencia)?\s*\.?\s*:?\s*(?:de\s+)?(\d{1,2})\s*/\s*(\d{4})\b"),
              re.compile(r"\bno\s+mes\s+(?:de\s+)?(\d{1,2})\s*/\s*(\d{4})\b"),
              re.compile(r"\bcomp(?:etencia)?\s*\.?\s*:?\s*(?:de\s+)?" + _MES + r"\s*(?:/|-|de)\s*" + _ANO)]


def ler_historico(texto: str) -> dict:
    """{processo, contrato, unidade, comp} do histórico da OB — cada um None quando o texto não diz (ou diz 2)."""
    t = _norm(texto)
    procs = {x for x in (tag_processo(m.group(0)) for m in _RX_SEI.finditer(t)) if x}
    ctrs = {f"{int(m[1])}/{m[2] if len(m[2]) == 4 else '20' + m[2]}" for m in _RX_H_CONTRATO.finditer(t)}
    unids = {re.sub(r"[\s.]+", " ", m[1]).strip() for m in _RX_H_UNIDADE.finditer(t)}
    comps = set()
    for rx in _RX_H_COMP:
        for m in rx.finditer(t):
            c = _comp(m[1], m[2])
            if c:
                comps.add(c)
    um = lambda s: next(iter(s)) if len(s) == 1 else None  # noqa: E731 — ambíguo (2 valores) = não diz
    return {"processo": um(procs), "contrato": um(ctrs), "unidade": um(unids), "comp": um(comps)}


def historicos(c, ug: str, cnpj: str, numeros: list[str]) -> dict[str, str]:
    """numero_ob → histórico (`ordens_bancarias.observacao`, espelho TFE — só o texto) da MESMA OB/UG/credor.
    Sem a tabela → {}."""
    out: dict[str, list[str]] = {}
    nums = sorted(set(numeros))
    try:
        for i in range(0, len(nums), 400):
            lote = nums[i:i + 400]
            for ob, obs_txt, fav in c.execute(
                    f"SELECT numero_ob, observacao, favorecido_cpf FROM ordens_bancarias WHERE ug_codigo=? "
                    f"AND numero_ob IN ({','.join('?' * len(lote))})", [str(ug), *lote]):
                fav_d = re.sub(r"\D", "", str(fav or ""))
                if fav_d and fav_d != cnpj:          # OB de outro credor com o mesmo número: não é esta
                    continue
                if obs_txt:
                    out.setdefault(ob, []).append(str(obs_txt))
    except sqlite3.OperationalError:
        return {}
    return {k: " | ".join(dict.fromkeys(v)) for k, v in out.items()}


def completar_pelo_historico(obs: list[dict], hist: dict[str, str]) -> list[dict]:
    """Anexa o histórico a cada OB; processo VAZIO na coluna do SIAFE é completado pelo do histórico."""
    for o in obs:
        h = hist.get(o.get("numero_ob"), "")
        o["historico"] = h
        if h and tag_processo(o.get("processo")) is None:
            p = ler_historico(h)["processo"]
            if p:
                o["processo"] = numero_sei(p)
                o["processo_fonte"] = "historico"
    return obs


# ───────────── processo do CONTRATO (TCE-RJ) para OB sem processo — camada 2021–2023 ─────────────
# Medido 12/11/2026: 1.204 das 1.241 competências INDETERMINADAS eram "sem processo SEI na coluna do SIAFE"
# (1.124 delas de 2021–2023, SIAFE 1, coluna vazia). O contrato do par no TCE-RJ (contratos_tcerj, API pública,
# 2023+) traz o processo SEI; renovação mantém o nº do processo original, então processo aberto até o ano da
# competência cobre o par. Só UM candidato vira processo (fonte "contrato_tcerj"); 2+ = ambíguo, fica como está.
# A UG do SIAFE ↔ "Unidade" do TCE é APRENDIDA do próprio dado: OBs cujo processo casa o processo de um contrato.
_RX_PROC4 = re.compile(r"(\d{6})/(\d{3,6})/(\d{4})")


def mapa_contratos(c) -> tuple[dict, dict]:
    """(ug → unidade TCE, (cnpj, unidade) → [(numero_sei, ano_do_processo)]). Sem a tabela → ({}, {})."""
    try:
        contratos = c.execute("SELECT processo, cnpj, unidade FROM contratos_tcerj WHERE processo LIKE 'SEI%'").fetchall()
        obs = c.execute("SELECT ug_emitente, processo FROM ob_orcamentaria_siafe WHERE processo LIKE '%/%/%'").fetchall()
    except sqlite3.OperationalError:
        return {}, {}
    un_por_tag, por_par = {}, {}
    for proc, cnpj, un in contratos:
        m = _RX_PROC4.search(proc or "")
        if not m:
            continue
        tag = f"{m[1]}_{int(m[2]):06d}_{m[3]}"
        un_por_tag[tag] = un
        por_par.setdefault((re.sub(r"\D", "", cnpj or ""), un), set()).add((numero_sei(tag), int(m[3])))
    votos: dict[str, Counter] = {}
    for ug, proc in obs:
        t = tag_processo(proc)
        if t and t in un_por_tag:
            votos.setdefault(str(ug), Counter())[un_por_tag[t]] += 1
    return ({ug: v.most_common(1)[0][0] for ug, v in votos.items()},
            {k: sorted(v) for k, v in por_par.items()})


def completar_pelo_contrato(obs: list[dict], cnpj: str, ug: str, mapas: tuple[dict, dict]) -> list[dict]:
    """OB ainda sem processo recebe o processo do contrato do par quando há UM só candidato aberto até o ano."""
    ug2un, por_par = mapas
    un = ug2un.get(str(ug))
    if not un:
        return obs
    cands = por_par.get((cnpj, un), [])
    for o in obs:
        if tag_processo(o.get("processo")) is not None:
            continue
        mm = _comp_mm_aaaa(o.get("competencia")) or ""
        ano = int(mm[-4:]) if mm[-4:].isdigit() else None
        if ano is None:
            continue
        unicos = {p for p, a in cands if a <= ano}
        if len(unicos) == 1:
            o["processo"] = next(iter(unicos))
            o["processo_fonte"] = "contrato_tcerj"
    return obs


def mapa_empenhos(c) -> dict:
    """(credor, ug, exercício) → {numero_sei} das NEs do SIAFE (`ne_siafe`). Processo truncado sem ano (o SIAFE
    corta: 'SEI-330005/0002') não reconhece e fica fora. Sem a tabela → {}."""
    out: dict = {}
    try:
        for cred, ug, ex, proc in c.execute("SELECT credor, ug_emitente, exercicio, processo FROM ne_siafe "
                                            "WHERE processo LIKE '%/%/%'"):
            t = tag_processo(proc)
            if t:
                out.setdefault((re.sub(r"\D", "", cred or ""), str(ug), int(ex)), set()).add(numero_sei(t))
    except sqlite3.OperationalError:
        return {}
    return out


def completar_pelo_empenho(obs: list[dict], cnpj: str, ug: str, mapa: dict) -> list[dict]:
    """OB sem processo recebe o processo das NEs do MESMO credor/UG/exercício quando ele é ÚNICO (fonte
    "empenho_siafe"). Mais específico que o contrato do TCE: vem antes dele."""
    for o in obs:
        if tag_processo(o.get("processo")) is not None:
            continue
        mm = _comp_mm_aaaa(o.get("competencia")) or ""
        if not mm[-4:].isdigit():
            continue
        cands = mapa.get((cnpj, str(ug), int(mm[-4:])), set())
        if len(cands) == 1:
            o["processo"] = next(iter(cands))
            o["processo_fonte"] = "empenho_siafe"
    return obs


def _unidades_distintas(a: str, b: str) -> bool:
    """Nome de unidade escrito de 2 jeitos ("UPA CAMPO GRANDE I" / "UPA C GRANDE I") NÃO é unidade distinta:
    só conta como distinta quando os nomes não compartilham a maioria das palavras."""
    ta, tb = set(a.split()), set(b.split())
    if a == b or a.startswith(b) or b.startswith(a):
        return False
    return len(ta & tb) / max(1, len(ta | tb)) < 0.5


def afastado_pelo_historico(comp: str, obs: list[dict]) -> tuple[str, str] | None:
    """(motivo, citação) quando o histórico das OBs mostra que NÃO é o mesmo mês pago 2×; senão None.
      • histórico diz outro mês de serviço → a OB não repete esta competência;
      • as OBs que sobram são, duas a duas, de CONTRATOS distintos ou de UNIDADES distintas."""
    info = {o["numero_ob"]: ler_historico(o.get("historico") or "") for o in obs}
    fora = [ob for ob, i in info.items() if i["comp"] and i["comp"] != comp]
    resto = [ob for ob in info if ob not in fora]
    cita = lambda ob: next(o.get("historico", "") for o in obs if o["numero_ob"] == ob)[:300]  # noqa: E731
    notas = [f"OB {ob}: histórico diz competência {info[ob]['comp']}" for ob in fora]
    if fora and len(resto) <= 1:
        return ("o histórico das OBs diz outro mês de serviço — " + "; ".join(notas)
                + f"; o campo competência do SIAFE repete {comp}", cita(fora[0]))
    if len(resto) < 2:
        return None

    def distintas(a, b):
        ia, ib = info[a], info[b]
        return bool((ia["contrato"] and ib["contrato"] and ia["contrato"] != ib["contrato"])
                    or (ia["unidade"] and ib["unidade"] and _unidades_distintas(ia["unidade"], ib["unidade"])))
    if all(distintas(a, b) for i, a in enumerate(resto) for b in resto[i + 1:]):
        rot = "; ".join(f"OB {ob}: " + ", ".join(f"{k} {info[ob][k]}" for k in ("contrato", "unidade") if info[ob][k])
                        for ob in resto)
        return ("OBs de contratos/unidades distintos no mesmo mês, não o mesmo serviço pago 2× — " + rot
                + (f"; {'; '.join(notas)}" if notas else ""), cita(resto[0]))
    return None


def _eh_nf(doc: dict) -> bool:
    if _TITULO_NF.match(_norm(doc.get("titulo")).strip()):
        return True
    corpo = _norm(doc.get("texto"))[:3000]
    return any(m in corpo for m in _MARCA_NF)


def extrair_nfs(docs: list[dict]) -> list[dict]:
    """NFs dos documentos que SÃO nota fiscal: {numero, cnpj, competencia, valor, titulo, benigno}."""
    out, vistos = [], set()
    for doc in docs:
        if not _eh_nf(doc):
            continue
        t, tit = _norm(doc.get("texto")), _norm(doc.get("titulo")).strip()
        numero = None
        for rx in _RX_NUM_TEXTO:
            m = rx.search(t)
            if m:
                numero = m[1]
                break
        if numero is None:
            for rx in _RX_NUM_TITULO:
                m = rx.search(tit)
                if m:
                    numero = m[1]
                    break
        if numero is None:
            continue
        numero = numero.lstrip("0") or "0"
        i = min([p for p in (t.find("emitente"), t.find("prestador")) if p >= 0] or [0])
        mc = _RX_CNPJ.search(t, i) or _RX_CNPJ.search(t)
        cnpj = re.sub(r"\D", "", mc[0]) if mc else ""
        valor = 0.0
        for rx in _RX_VALOR[:2]:
            m = rx.search(t)
            if m:
                valor = _money(m[1])
                break
        m = _RX_VALOR[2].search(t)
        liquido = _money(m[1]) if m else 0.0
        chave = (cnpj, numero)
        if chave in vistos:
            continue
        vistos.add(chave)
        bm = _RX_BENIGNO.search(t)
        mt = _RX_TITULO_MES.search(tit)       # "Nota Fiscal n° 187-1 janeiro 2024" — o servidor escreve o mês
        desc = (_comp(mt[1], mt[2]) if mt else None) or competencia_descritiva(doc.get("texto") or "")
        out.append({"numero": numero, "cnpj": cnpj, "competencia": desc or competencia_do_texto(doc.get("texto") or ""),
                    "comp_desc": bool(desc), "valor": valor or liquido, "liquido": liquido,
                    "titulo": (doc.get("titulo") or "")[:90], "benigno": bm[0] if bm else ""})
    return out


def _ler_cache(tag: str):
    try:
        from compliance_agent.sei.cache_arquivo import ler_json
        return ler_json(CACHE / f"cdp_SEI_{tag}.json")
    except (OSError, ValueError, ImportError):  # cache ilegível = sem texto (vira PENDENTE_CAPTURA, nunca "sem NF"); ler_json já devolve None p/ JSON torto
        return None


def textos_do_processo(tag: str) -> list[dict]:
    """Documentos com teor do processo: arquivo compacto primeiro (canônico, PLAYBOOK-SEI §0), cache CDP depois."""
    d = ARQUIVO / tag
    docs: list[dict] = []
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    for x in man.get("docs") or []:
        cam = str(x.get("texto") or "").strip()
        if not cam:
            continue
        try:
            txt = (d / cam).read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        if txt.strip():
            docs.append({"titulo": x.get("titulo") or "", "tipo": x.get("tipo") or "", "texto": txt})
    if docs:
        return docs
    cache = _ler_cache(tag) or {}
    for x in (cache.get("conteudo_documentos") or []) if isinstance(cache, dict) else []:
        txt = str(x.get("conteudo") or "")
        if txt.strip():
            docs.append({"titulo": str(x.get("doc") or ""), "tipo": "", "texto": txt})
    # cache com CORTE FIXO de ~400 caracteres por documento (o sei_arquivar já os recusa): é título, não teor.
    # Medido no dry-run de 11/11/2026 — SEI-080002/017893/2024 tinha 3 docs de exatamente 400 caracteres.
    if docs and sum(len(d["texto"]) <= 400 for d in docs) >= 0.8 * len(docs):
        return []
    return docs


def _competencias_do_processo(docs: list[dict], nfs: list[dict]) -> set:
    """Mês de serviço que o processo cobra (só DESCRITIVO): o das NFs e o do atesto/medição/fiscalização."""
    comps = {n["competencia"] for n in nfs if n["competencia"] and n["comp_desc"]}
    for doc in docs:
        tit = _norm(doc.get("titulo"))
        if any(k in tit for k in ("atest", "medic", "relatorio de fiscaliz", "nota de liquida")):
            c = competencia_descritiva(doc.get("texto") or "")
            if c:
                comps.add(c)
    return comps


def _rotulo_nfs(nfs: list[dict]) -> str:
    return ", ".join(f"NF {n['numero']}" + (f" ({n['competencia']})" if n["competencia"] else "") for n in nfs) or "sem NF"


# ───────────────────────── juízo (LLM grátis) ─────────────────────────
_SYS = ("Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ). Decide se um mês de serviço contínuo foi PAGO EM DOBRO, lendo as "
        "notas fiscais e os documentos dos processos de pagamento. Regras ABSOLUTAS: indício ≠ acusação (presunção de "
        "legitimidade); mesma NF em duas OBs = confirmado; NFs distintas para meses, postos, retroativo, repactuação, "
        "glosa ou complemento distintos = afastado; se os documentos não permitem concluir, indeterminado. A "
        "citacao_literal é um trecho COPIADO LETRA POR LETRA dos documentos — sem trecho literal, responda "
        "indeterminado. Responda SÓ o JSON.")
_SCHEMA = ('{"veredito":"confirmado|afastado|indeterminado","nf_por_ob":{"<numero_ob>":"<numero da NF>"},'
           '"motivo":"1-2 frases","citacao_literal":"trecho copiado dos documentos"}')


def _docs_para_juizo(procs: dict) -> str:
    partes, total = [], 0
    for tag, p in procs.items():
        partes.append(f"\n=== PROCESSO {numero_sei(tag)} — OBs: {', '.join(p['obs'])} ===")
        relevantes = [x for x in p["docs"] if _eh_nf(x) or any(
            k in _norm(x["titulo"]) for k in ("atest", "medic", "fiscaliz", "liquida", "despacho", "ordem banc", "desembolso"))]
        for x in relevantes or p["docs"]:
            bloco = f"\n--- {x['titulo']} ---\n{x['texto'][:MAX_DOC_LLM]}"
            if total + len(bloco) > MAX_TOTAL_LLM:
                break
            partes.append(bloco)
            total += len(bloco)
    return "".join(partes)


def _juizo(comp: str, obs: list[dict], procs: dict, nfs_por_ob: dict, gerar) -> dict:
    from compliance_agent.llm.json_resposta import parse_json_llm
    docs = _docs_para_juizo(procs)
    linhas = "\n".join(f"- OB {o['numero_ob']}: R$ {_br(float(o['valor'] or 0))}, emitida {o.get('data_emissao')}, "
                       f"RE {o.get('re')}, NL {o.get('nl')}, processo {o.get('processo')}" for o in obs)
    prompt = (f"Competência {comp} aparece paga por {len(obs)} OBs do SIAFE (Contabilizado):\n{linhas}\n\n"
              f"NFs extraídas por OB: {json.dumps(nfs_por_ob, ensure_ascii=False)}\n\nDOCUMENTOS:{docs}\n\n"
              f"Responda no formato: {_SCHEMA}")
    try:
        bruto = gerar(prompt, _SYS)
    except Exception as e:  # noqa: BLE001 — juízo fora do ar não derruba o lote; o mês fica indeterminado
        return {"veredito": "INDETERMINADO", "motivo": f"juízo não rodou ({type(e).__name__}) — reprocessar",
                "citacao": "", "camada": "juizo"}
    j = parse_json_llm(bruto) if isinstance(bruto, str) else None
    if not isinstance(j, dict):
        return {"veredito": "INDETERMINADO", "motivo": "juízo devolveu resposta sem JSON válido — reprocessar",
                "citacao": "", "camada": "juizo"}
    v = str(j.get("veredito") or "").strip().lower()
    cit = str(j.get("citacao_literal") or "").strip()
    motivo = str(j.get("motivo") or "").strip()
    if v not in ("confirmado", "afastado"):
        return {"veredito": "INDETERMINADO", "motivo": f"juízo: {motivo or 'os documentos não permitem concluir'}",
                "citacao": cit, "camada": "juizo", "nf_por_ob": j.get("nf_por_ob")}
    if not cit or _norm_cit(cit) not in _norm_cit(docs):
        return {"veredito": "INDETERMINADO", "camada": "juizo", "citacao": "", "nf_por_ob": j.get("nf_por_ob"),
                "motivo": f"juízo disse '{v}' mas a citação literal não existe no texto — descartado ({motivo})"}
    valores = {o["numero_ob"]: float(o.get("valor") or 0) for o in obs}
    if v == "confirmado" and not _confirmacao_sustentada(j.get("nf_por_ob"), cit, valores):
        # medido 11/11/2026: o juízo "confirmou" citando o histórico de OUTRA OB e chamando de NF o nº de um
        # documento SEI. Citação que existe não basta: tem de ser a NF REPETIDA, atribuída a 2 OBs.
        return {"veredito": "INDETERMINADO", "camada": "juizo", "citacao": cit[:400], "nf_por_ob": j.get("nf_por_ob"),
                "motivo": f"juízo disse 'confirmado' sem citar a NF repetida em 2 OBs — não confirmado ({motivo})"}
    return {"veredito": v.upper(), "motivo": f"juízo: {motivo}", "citacao": cit[:400], "camada": "juizo",
            "nf_por_ob": j.get("nf_por_ob")}


def _confirmacao_sustentada(nf_por_ob, citacao: str, valores: dict | None = None) -> bool:
    """CONFIRMADO do juízo só vale se a MESMA NF foi atribuída a 2+ OBs, o número dela está na citação literal e
    (com `valores`) 2 dessas OBs pagam a MESMA quantia (±1%). Mesma NF em OBs de valores diferentes = a NF
    liquidada em parcelas (medido 11/11/2026: NF 58044 do SAMU em 2 NLs que somam exatamente o valor da NF)."""
    if not isinstance(nf_por_ob, dict):
        return False
    por_nf: dict[str, list] = {}
    for ob, v in nf_por_ob.items():
        for x in (v if isinstance(v, list) else [v]):
            d = re.sub(r"\D", "", str(x or "")).lstrip("0")
            if d:
                por_nf.setdefault(d, []).append(ob)
    nums_cit = {x.lstrip("0") for x in re.findall(r"\d+", _norm(citacao))}
    for n, obs_nf in por_nf.items():
        if len(obs_nf) < 2 or n not in nums_cit:
            continue
        if valores is None:
            return True
        vs = sorted(valores.get(o, 0.0) for o in obs_nf)
        if any(b and abs(a - b) <= 0.01 * b for a, b in zip(vs, vs[1:])):
            return True
    return False


# ───────────────────────── camada determinística ─────────────────────────
def resolver_competencia(cnpj: str, comp: str, obs: list[dict], gerar=None) -> dict:
    """Veredito de UMA competência dobrada a partir das NFs dos processos das suas OBs."""
    procs: dict[str, dict] = {}
    sem_proc = []
    for o in obs:
        t = tag_processo(o.get("processo"))
        if t is None:
            sem_proc.append(o["numero_ob"])
            continue
        procs.setdefault(t, {"obs": [], "valor": 0.0})
        procs[t]["obs"].append(o["numero_ob"])
        procs[t]["valor"] += float(o.get("valor") or 0)
    for t, p in procs.items():
        p["docs"] = textos_do_processo(t)
        p["nfs"] = [n for n in extrair_nfs(p["docs"]) if not n["cnpj"] or n["cnpj"] == cnpj or mesmo_grupo(n["cnpj"], cnpj)]
        p["comps"] = _competencias_do_processo(p["docs"], p["nfs"])
    # NF DA OB: a única NF do processo que bate em valor (bruto ou líquido, ± centavos); senão as NFs do processo
    # que dizem cobrar ESTA competência; senão, se nenhuma NF do processo diz o mês, todas as dele.
    nf_da_ob: dict[str, dict] = {}
    for o in obs:
        t = tag_processo(o.get("processo"))
        if t is None or not procs[t]["docs"]:
            continue
        nfs, v = procs[t]["nfs"], float(o.get("valor") or 0)
        casam = [n for n in nfs if abs(n["valor"] - v) <= TOL or (n["liquido"] and abs(n["liquido"] - v) <= TOL)]
        if len(casam) == 1:
            nf_da_ob[o["numero_ob"]] = {"por": "valor", "nfs": casam}
        elif any(n["competencia"] == comp for n in nfs):
            nf_da_ob[o["numero_ob"]] = {"por": "competencia", "nfs": [n for n in nfs if n["competencia"] == comp]}
        elif nfs and not any(n["competencia"] for n in nfs):
            nf_da_ob[o["numero_ob"]] = {"por": "processo", "nfs": nfs}
    nfs_por_ob = {}
    for o in obs:
        t = tag_processo(o.get("processo"))
        lst = [dict(n, processo=numero_sei(t)) for n in (procs[t]["nfs"] if t else [])]
        da = {x["numero"] for x in nf_da_ob.get(o["numero_ob"], {}).get("nfs", [])}
        for n in lst:
            n["da_ob"] = n["numero"] in da
        nfs_por_ob[o["numero_ob"]] = lst
    res = {"nfs_json": json.dumps(nfs_por_ob, ensure_ascii=False), "obs": [o["numero_ob"] for o in obs],
           "capturar": [], "camada": "deterministica", "citacao": ""}
    com_texto = {t: p for t, p in procs.items() if p["docs"]}
    sem_texto = sorted(t for t, p in procs.items() if not p["docs"])

    # (1) CONFIRMADO — a mesma NF é a NF de 2 OBs: casada por valor nas duas, ou cobrando esta competência em 2
    # processos de pagamento distintos. Vale mesmo com outro processo ainda sem texto. NF de retroativo/glosa não.
    ob_proc = {o["numero_ob"]: tag_processo(o.get("processo")) for o in obs}
    ids = sorted(nf_da_ob)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            na, nb = nf_da_ob[a], nf_da_ob[b]
            if ob_proc[a] == ob_proc[b] and not (na["por"] == nb["por"] == "valor"):
                continue
            comum = ({(n["cnpj"][:8], n["numero"]) for n in na["nfs"] if not n["benigno"]}
                     & {(n["cnpj"][:8], n["numero"]) for n in nb["nfs"] if not n["benigno"]})
            if comum:
                num = sorted(comum)[0][1]
                tit = next(n["titulo"] for n in na["nfs"] if n["numero"] == num)
                onde = (f"no mesmo processo {numero_sei(ob_proc[a])}, casada por valor nas duas" if ob_proc[a] == ob_proc[b]
                        else f"em {numero_sei(ob_proc[a])} e {numero_sei(ob_proc[b])}")
                return {**res, "veredito": "CONFIRMADO", "citacao": tit,
                        "motivo": f"NF nº {num} é a nota cobrada pela OB {a} e pela OB {b} ({onde}) — mesma NF paga "
                                  f"em 2 OBs na competência {comp}"}
    # (1b) HISTÓRICO DA OB (texto do espelho TFE; valores seguem do SIAFE): outro mês de serviço, ou contratos/unidades distintos → AFASTADO,
    # sem precisar do processo. Só AFASTA — duplicidade só se CONFIRMA pela NF (acima).
    h = afastado_pelo_historico(comp, obs)
    if h:
        return {**res, "veredito": "AFASTADO", "motivo": h[0], "citacao": h[1], "camada": "historico_ob"}
    # (2) processo sem texto → captura (sem a NF dele não há como fechar)
    if sem_texto:
        cap = [numero_sei(t) for t in sem_texto]
        return {**res, "veredito": "PENDENTE_CAPTURA", "capturar": cap,
                "motivo": f"capturar {', '.join(cap)} — processo(s) da(s) OB(s) "
                          f"{', '.join(o for t in sem_texto for o in procs[t]['obs'])} sem texto no arquivo local"}
    if sem_proc:
        return {**res, "veredito": "INDETERMINADO",
                "motivo": f"OB(s) {', '.join(sem_proc)} sem processo SEI na coluna do SIAFE — NF não localizável"}
    # (3) processo que cobra OUTRO mês (NF/atesto DESCRITIVOS sem esta competência) ou só NF de retroativo,
    # repactuação, glosa ou complemento: as OBs dele não repetem esta competência.
    fora, notas = set(), []
    for t, p in com_texto.items():
        if p["comps"] and comp not in p["comps"]:
            fora.add(t)
            notas.append(f"{numero_sei(t)} cobra {', '.join(sorted(p['comps']))} ({_rotulo_nfs(p['nfs'])})")
        elif p["nfs"] and all(n["benigno"] for n in p["nfs"]):
            fora.add(t)
            notas.append(f"{numero_sei(t)} só tem NF de {p['nfs'][0]['benigno']} ({_rotulo_nfs(p['nfs'])})")
    resto = {t: p for t, p in com_texto.items() if t not in fora}
    n_obs_resto = sum(len(p["obs"]) for p in resto.values())
    if fora and n_obs_resto <= 1:
        cit = next((n["titulo"] for t in sorted(fora) for n in com_texto[t]["nfs"]), "")
        return {**res, "veredito": "AFASTADO", "citacao": cit,
                "motivo": "NFs distintas, não o mesmo mês pago de novo — " + "; ".join(notas)
                          + f"; o campo competência do SIAFE repete {comp}"}
    # (4) as OBs que sobram estão num processo só e cabem no bruto das NFs DESTA competência → pagamento fracionado
    if len(resto) == 1:
        (t, p), = resto.items()
        base = [n for n in p["nfs"] if n["competencia"] == comp] or (
            p["nfs"] if not any(n["competencia"] for n in p["nfs"]) else [])
        soma_nf = sum(n["valor"] for n in base)
        if base and soma_nf and p["valor"] <= soma_nf + TOL:
            return {**res, "veredito": "AFASTADO", "citacao": base[0]["titulo"],
                    "motivo": f"pagamento fracionado: {len(p['obs'])} OBs no mesmo processo {numero_sei(t)} somam "
                              f"R$ {_br(p['valor'])} ≤ R$ {_br(soma_nf)} das NFs da competência ({_rotulo_nfs(base)})"
                              + (f"; {'; '.join(notas)}" if notas else "")}
    # (5) a regra não decide
    if gerar is None:
        return {**res, "veredito": "INDETERMINADO",
                "motivo": "NFs não fecham pela regra (" + "; ".join(
                    f"{numero_sei(t)}: {_rotulo_nfs(p['nfs'])}" for t, p in sorted(com_texto.items()))
                          + ") — falta o juízo sobre o texto"}
    j = _juizo(comp, obs, com_texto, {k: [n["numero"] for n in v] for k, v in nfs_por_ob.items()}, gerar)
    if j.get("nf_por_ob"):
        res["nfs_json"] = json.dumps({"extraidas": nfs_por_ob, "juizo": j["nf_por_ob"]}, ensure_ascii=False)
    return {**res, "veredito": j["veredito"], "motivo": j["motivo"], "citacao": j["citacao"], "camada": j["camada"]}


def resolver_par(cnpj: str, ug: str, obs: list[dict], favorecido: str = "", gerar=None) -> list[dict]:
    """Uma linha por competência dobrada do par (só OB Contabilizado — REGRA DE OURO)."""
    contab = [o for o in obs if str(o.get("status") or "").strip().lower().startswith("contabiliz")]
    out = []
    for f in detectar(contab, favorecido=favorecido, orgao=ug):
        if f["tipo_indicio"] != "competencia_dobrada":
            continue
        alvo_ids = set(f.get("obs") or [])
        alvo = [o for o in contab if o.get("numero_ob") in alvo_ids
                and _comp_mm_aaaa(o.get("competencia")) == f["competencia"]]
        r = resolver_competencia(cnpj, f["competencia"], alvo, gerar=gerar)
        r.update({"cnpj": cnpj, "ug": str(ug), "competencia": f["competencia"],
                  "total": round(sum(float(o.get("valor") or 0) for o in alvo), 2)})
        out.append(r)
    return out


# ───────────────────────── banco ─────────────────────────
def garantir_tabela(c) -> None:
    c.execute(_DDL)


def gravar(c, linhas: list[dict]) -> None:
    agora = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    c.executemany("""INSERT OR REPLACE INTO resolucao_duplicidade
        (cnpj,ug,competencia,veredito,motivo,nfs_json,citacao,camada,obs_json,atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  [(r["cnpj"], r["ug"], r["competencia"], r["veredito"], r["motivo"], r.get("nfs_json") or "{}",
                    r.get("citacao") or "", r.get("camada") or "", json.dumps(r.get("obs") or []), agora)
                   for r in linhas])


def enfileirar(c, linhas: list[dict], vagas: int) -> int:
    """Processo sem texto → `sei_fila_captura` (INSERT OR IGNORE: pedido existente, à mão ou não, fica como está)."""
    n = 0
    agora = time.strftime("%Y-%m-%dT%H:%M:%S")
    for r in linhas:
        for proc in r.get("capturar") or []:
            if n >= vagas:
                return n
            n += c.execute("INSERT OR IGNORE INTO sei_fila_captura VALUES (?,?,?,?,?,?)",
                           (proc, re.sub(r"\D", "", proc),
                            f"duplicidade_nf: {r['cnpj']} UG {r['ug']} competência {r['competencia']} (NF fecha o T07)",
                            r.get("total") or 0.0, 0, agora)).rowcount
    return n


def _manter_juizo(c, cnpj: str, ug: str, linhas: list[dict]) -> list[dict]:
    """Rodada SÓ COM A REGRA (cron) não apaga o juízo já feito: competência que a regra deixaria em
    "falta o juízo" mantém o veredito do juízo gravado para as MESMAS OBs (OB nova = juízo velho não vale)."""
    try:
        velhos = {r[0]: r for r in c.execute(
            "SELECT competencia, veredito, motivo, nfs_json, citacao, camada, obs_json FROM resolucao_duplicidade "
            "WHERE cnpj=? AND ug=? AND camada='juizo'", (cnpj, str(ug)))}
    except sqlite3.OperationalError:
        return linhas
    out = []
    for r in linhas:
        v = velhos.get(r["competencia"])
        if (v and r["veredito"] == "INDETERMINADO" and r.get("camada") == "deterministica"
                and "falta o juízo" in (r.get("motivo") or "")
                and sorted(json.loads(v[6] or "[]")) == sorted(r.get("obs") or [])):
            r = {**r, "veredito": v[1], "motivo": v[2], "nfs_json": v[3], "citacao": v[4], "camada": v[5]}
        out.append(r)
    return out


def pares_amarelos(c, limit: int | None = None) -> list[tuple]:
    """Pares 🟡 cujo T07 é INDICIO, maior pago primeiro (a fila de captura herda essa prioridade)."""
    out = []
    for cnpj, ug, fav, aj in c.execute("SELECT cnpj, ug, favorecido, achados_json FROM pericia_fornecedor "
                                       "WHERE grau='🟡' ORDER BY total_pago DESC"):
        try:
            ach = json.loads(aj or "[]")
        except ValueError:
            continue
        if any(a.get("codigo") == "T07-DUPLICIDADE-COMP" and a.get("status") == "INDICIO" for a in ach):
            out.append((cnpj, ug, fav or ""))
            if limit and len(out) >= limit:
                break
    return out


def rodar(db=DB, limit: int | None = None, gerar=None, dry_run: bool = False, lote: int = 20,
          teto_fila: int = 500, log=None) -> dict:
    """Resolve os pares 🟡 com T07 INDICIO. `gerar=None` = só a regra. `dry_run` abre o banco read-only."""
    if dry_run:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=120)
    else:
        c = sqlite3.connect(db, timeout=120)
    c.row_factory = sqlite3.Row
    vereditos, enfileirados, n_comp = Counter(), 0, 0
    try:
        pares = pares_amarelos(c, limit)
        if not dry_run:
            garantir_tabela(c)
        mapas = mapa_contratos(c)
        empenhos = mapa_empenhos(c)
        for i, (cnpj, ug, fav) in enumerate(pares, 1):
            obs = ps._obs_de(c, cnpj, ug)
            completar_pelo_historico(obs, historicos(c, ug, cnpj, [o["numero_ob"] for o in obs]))
            completar_pelo_empenho(obs, cnpj, ug, empenhos)
            completar_pelo_contrato(obs, cnpj, ug, mapas)
            linhas = resolver_par(cnpj, ug, obs, favorecido=fav, gerar=gerar)
            n_comp += len(linhas)
            vereditos.update(r["veredito"] for r in linhas)
            if log:
                log(f"[{i}/{len(pares)}] {cnpj} UG {ug}: " + ", ".join(f"{k}={v}" for k, v in
                                                                         Counter(r['veredito'] for r in linhas).items()))
            if dry_run:
                continue
            if gerar is None:
                linhas = _manter_juizo(c, cnpj, ug, linhas)
            c.execute("DELETE FROM resolucao_duplicidade WHERE cnpj=? AND ug=?", (cnpj, str(ug)))
            gravar(c, linhas)
            enfileirados += enfileirar(c, linhas, max(0, teto_fila - enfileirados))
            ps._gravar(c, ps.periciar(cnpj, ug, c))          # o T07 relê a tabela na hora
            if i % lote == 0:
                c.commit()
        if not dry_run:
            c.commit()
    finally:
        c.close()
    return {"pares": len(pares), "competencias": n_comp, "vereditos": dict(vereditos), "enfileirados": enfileirados,
            "dry_run": dry_run}


def _gerar_free(prompt: str, sistema: str) -> str:
    """Cascata GRÁTIS da casa (pool free_llm; OpenRouter forçado a `:free`; desligados/pagos fora)."""
    from compliance_agent.llm.free_llm import best_free_chat
    return best_free_chat(prompt, system=sistema)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="não grava nada (banco read-only)")
    ap.add_argument("--limit", type=int, default=None, help="máximo de pares")
    ap.add_argument("--sem-llm", action="store_true", help="só a camada determinística")
    ap.add_argument("--lote", type=int, default=20, help="commit a cada N pares")
    ap.add_argument("--teto-fila", type=int, default=500, help="máximo de processos enfileirados por rodada")
    a = ap.parse_args()
    try:
        os.nice(10)
    except OSError:
        pass
    out = rodar(limit=a.limit, gerar=None if a.sem_llm else _gerar_free, dry_run=a.dry_run, lote=a.lote,
                teto_fila=a.teto_fila, log=lambda m: print(m, flush=True))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
