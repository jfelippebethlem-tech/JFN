# -*- coding: utf-8 -*-
"""Rotina SEMANAL do confronto CGE × JFN — o que a Controladoria auditou × o que o JFN tem sobre o MESMO processo.

Origem: confronto feito à mão em 13/11/2026 (`~/vault/notas/cge-irregularidades-x-jfn-2026-11-13.md`): das 64
contratações examinadas pela AGE/CGE (Decreto 50.254/2026), o JFN tinha artefato sobre 0. Esta rotina recalcula a
cobertura toda semana — é a métrica de RECALL do sistema contra um auditor humano.

Entrada: `data/cge_auditorias.json` (fora do git — dado real): a lista de contratações examinadas pela CGE, com o grau
que a própria CGE deu (G1 indício de dano · G2 irregularidade material · G3 falha formal · G0 regular). A lista é
curada a partir dos relatórios lidos; quando um relatório novo da CGE é lido, entra lá.

Para cada processo mede, SÓ LEITURA:
  · autos lidos (íntegra em `data/sei_arquivo/<processo>/texto`), ficha/árvore/lex/veredito por documento;
  · sinal do JFN: achado de detector, alerta, caso;
  · OB Contabilizada do SIAFE pelo campo processo (pago = só OB Contabilizada).
E descobre relatórios novos da CGE no acervo (processos da unidade 320001 com marcador de relatório de auditoria).

Saída: `data/cge_confronto.json` (com histórico semanal). INDISPONÍVEL ≠ zero: tabela que falha sai como indisponível.

Uso:  nice -n 15 timeout 1800 python -m compliance_agent.cge_confronto
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from compliance_agent.rotina_base import DATA, RAIZ, agora_iso, executar, gravar_json, ler_json

NOME = "cge_confronto"
SAIDA = DATA / "cge_confronto.json"
ENTRADA = Path(os.environ.get("JFN_CGE_AUDITORIAS") or DATA / "cge_auditorias.json")
DB = Path(os.environ.get("JFN_DB") or RAIZ / "data" / "compliance.db")
DB_ACHADOS = Path(os.environ.get("JFN_DB_ACHADOS") or RAIZ / "data" / "achados.db")
SEI_ARQUIVO = Path(os.environ.get("JFN_SEI_ARQUIVO") or RAIZ / "data" / "sei_arquivo")
GRAUS = ("G1", "G2", "G3", "G0")
ROTULO_GRAU = {"G1": "indício de dano (comunicação imediata/sindicância)", "G2": "irregularidade material",
               "G3": "falha formal ou de controle", "G0": "sem irregularidade"}
_MARCA_REL = re.compile(r"Relat[óo]rio de Auditoria|Unidade Auditada|siaudi\.rj\.gov\.br", re.I)
HIST_MAX = 60


def chave(processo) -> str | None:
    """'SEI-090002/000036/2025', '090002/000036/25', '090002_000036_2025' → 16 dígitos."""
    s = re.sub(r"[_\s]", "/", str(processo or ""))
    m = re.search(r"(\d{6})/(\d{6})/(\d{4}|\d{2})(?!\d)", s)
    if not m:
        return None
    return m.group(1) + m.group(2) + (m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3))


def _ro(p: Path) -> sqlite3.Connection | None:
    if not p.exists():
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)


def _conjunto(con, sql: str, *a) -> set[str] | None:
    """Chaves de processo de uma tabela. Falha → None (INDISPONÍVEL, não vazio)."""
    if con is None:
        return None
    try:
        return {k for (x,) in con.execute(sql, a) if (k := chave(x))}
    except sqlite3.Error:
        return None


def _autos(arquivo: Path) -> dict[str, int]:
    """{chave: nº de textos lidos} do acervo SEI (só diretórios — não abre arquivo)."""
    out = {}
    if not arquivo.is_dir():
        return out
    for d in os.scandir(arquivo):
        k = chave(d.name)
        if k and d.is_dir():
            t = Path(d.path) / "texto"
            try:
                out[k] = sum(1 for _ in os.scandir(t)) if t.is_dir() else 0
            except OSError:
                out[k] = 0
    return out


def relatorios_cge_no_acervo(arquivo: Path, *, limite_bytes: int = 400_000) -> list[str]:
    """Processos da CGE (unidade 320001) no acervo cujo texto tem marcador de relatório de auditoria."""
    achados = []
    if not arquivo.is_dir():
        return achados
    for d in sorted(os.scandir(arquivo), key=lambda e: e.name):
        if not d.name.startswith("320001") or not d.is_dir():
            continue
        t = Path(d.path) / "texto"
        if not t.is_dir():
            continue
        for f in os.scandir(t):
            try:
                with open(f.path, encoding="utf-8", errors="ignore") as fh:
                    if _MARCA_REL.search(fh.read(limite_bytes)):
                        achados.append(d.name.replace("_", "/"))
                        break
            except OSError:
                continue
    return achados


def coletar(con, con_ach, arquivo: Path, chaves: set[str]) -> dict:
    """Fontes do JFN indexadas por chave de processo. Cada fonte: set (ok) ou None (indisponível)."""
    f: dict = {"autos": _autos(arquivo)}
    f["ficha"] = _conjunto(con, "SELECT numero_sei FROM sei_ficha")
    f["arvore"] = _conjunto(con, "SELECT numero_sei FROM sei_arvore")
    f["lex"] = _conjunto(con, "SELECT numero_sei FROM lex_execucao")
    f["veredito"] = _conjunto(con, "SELECT DISTINCT numero_sei FROM doc_veredito")
    f["fila"] = _conjunto(con, "SELECT numero_sei FROM sei_fila_captura")
    det: dict | None = defaultdict(list)
    try:
        for proc, evid, d, st in con_ach.execute("SELECT processo, evidencia, detector, status FROM achado_detector"):
            for k in {chave(proc), *(chave(m.group(0)) for m in re.finditer(r"\d{6}/\d{6}/\d{2,4}", str(evid or "")))}:
                if k in chaves:
                    det[k].append({"detector": d, "status": st})
    except (sqlite3.Error, AttributeError):
        det = None
    f["detector"] = det
    caso: dict | None = defaultdict(list)
    try:
        for cid, tit, *txt in con.execute("SELECT id, titulo, alvo, resumo, evidencia_ids, nota FROM caso"):
            blob = " ".join(str(x or "") for x in (tit, *txt))
            for m in re.finditer(r"\d{6}/\d{6}/\d{2,4}", blob):
                k = chave(m.group(0))
                if k in chaves:
                    caso[k].append({"id": cid, "titulo": (tit or "")[:120]})
    except sqlite3.Error:
        caso = None
    f["caso"] = caso
    ob: dict | None = defaultdict(lambda: [0, 0.0])
    try:
        for proc, v in con.execute("SELECT processo, valor FROM ob_orcamentaria_siafe WHERE status='Contabilizado' "
                                   "AND processo IS NOT NULL AND processo<>''"):
            k = chave(proc)
            if k in chaves:
                ob[k][0] += 1
                ob[k][1] += v or 0
    except sqlite3.Error:
        ob = None
    f["ob"] = ob
    return f


def _alertas(con, processo: str) -> int | None:
    try:
        return con.execute("SELECT count(*) FROM fts_alertas WHERE fts_alertas MATCH ?", (f'"{processo}"',)).fetchone()[0]
    except sqlite3.Error:
        return None


def confrontar(contratacoes: list[dict], fontes: dict, alertas=lambda p: None) -> dict:
    """Linha a linha + métricas por grau. Função pura sobre `fontes` (testada com dados sintéticos)."""
    linhas = []
    for c in contratacoes:
        k = chave(c.get("processo"))
        tem = lambda nome: (None if fontes.get(nome) is None else (k in fontes[nome]))  # noqa: E731
        n_txt = fontes["autos"].get(k)
        det = None if fontes.get("detector") is None else fontes["detector"].get(k, [])
        cs = None if fontes.get("caso") is None else fontes["caso"].get(k, [])
        ob = None if fontes.get("ob") is None else fontes["ob"].get(k)
        al = alertas(c.get("processo"))
        lidos = bool(n_txt)
        artefato = any([lidos, tem("ficha"), tem("arvore"), tem("lex"), tem("veredito"), bool(det), bool(cs), bool(al)])
        sinal = bool([x for x in (det or []) if x["status"] == "confirmado"]) or bool(cs) or bool(al)
        linhas.append({**{x: c.get(x) for x in ("orgao", "processo", "fornecedor", "objeto", "valor_contratado", "grau",
                                                 "irregularidade")},
                       "autos_lidos": lidos, "n_textos": n_txt or 0, "ficha": tem("ficha"), "arvore": tem("arvore"),
                       "lex": tem("lex"), "veredito": tem("veredito"), "na_fila": tem("fila"),
                       "detectores": det, "casos": cs, "alertas": al,
                       "ob_n": None if fontes.get("ob") is None else (ob[0] if ob else 0),
                       "ob_pago": None if fontes.get("ob") is None else round(ob[1], 2) if ob else 0.0,
                       "jfn_artefato": artefato, "jfn_sinal": sinal})
    met = {}
    for g in (*GRAUS, "G1+G2", "todas"):
        sel = [x for x in linhas if (g == "todas" or x["grau"] == g or (g == "G1+G2" and x["grau"] in ("G1", "G2")))]
        met[g] = {"n": len(sel), "valor_contratado": round(sum(x["valor_contratado"] or 0 for x in sel), 2),
                  "autos_lidos": sum(x["autos_lidos"] for x in sel), "com_artefato": sum(x["jfn_artefato"] for x in sel),
                  "com_sinal": sum(x["jfn_sinal"] for x in sel), "com_ob": sum(bool(x["ob_n"]) for x in sel),
                  "na_fila_sem_leitura": sum(bool(x["na_fila"]) and not x["autos_lidos"] for x in sel)}
    indisp = [n for n in ("ficha", "arvore", "lex", "veredito", "fila", "detector", "caso", "ob") if fontes.get(n) is None]
    return {"linhas": linhas, "metricas": met, "fontes_indisponiveis": indisp}


def _rodar(log, entrada: Path, saida: Path) -> int:
    base = ler_json(entrada)
    anterior = ler_json(saida) or {}
    if not base or not base.get("contratacoes"):
        log.warning("lista de contratações da CGE ausente em %s — confronto INDISPONÍVEL", entrada)
        gravar_json(saida, {**anterior, "estado": "indisponivel", "gerado_em": agora_iso(),
                            "erro": f"lista de contratações auditadas ausente ({entrada.name})"})
        return 0
    contr = base["contratacoes"]
    chaves = {k for c in contr if (k := chave(c.get("processo")))}
    con, con_ach = _ro(DB), _ro(DB_ACHADOS)
    try:
        fontes = coletar(con, con_ach, SEI_ARQUIVO, chaves)
        r = confrontar(contr, fontes, alertas=(lambda p: _alertas(con, p)) if con else (lambda p: None))
    finally:
        for x in (con, con_ach):
            if x is not None:
                x.close()
    rels = relatorios_cge_no_acervo(SEI_ARQUIVO)
    conhecidos = set(base.get("relatorios_lidos") or [])
    novos = sorted(p for p in rels if p not in conhecidos)
    m = r["metricas"]
    agora = agora_iso()
    hist = [h for h in (anterior.get("historico") or []) if h.get("data", "")[:10] != agora[:10]]
    hist.append({"data": agora, "n": m["todas"]["n"], "com_artefato": m["todas"]["com_artefato"],
                 "com_sinal_g12": m["G1+G2"]["com_sinal"], "autos_lidos": m["todas"]["autos_lidos"],
                 "relatorios_no_acervo": len(rels)})
    hist = hist[-HIST_MAX:]
    from compliance_agent.governo_couto import _mascarar_tudo
    doc = _mascarar_tudo({
        "estado": "ok", "gerado_em": agora, "curado_em": base.get("curado_em"),
        "fonte": ("relatórios AGE/CGE (Decreto 50.254/2026) lidos no acervo SEI — lista curada em "
                  f"data/{entrada.name}; JFN: sei_arquivo, sei_ficha, sei_arvore, lex_execucao, doc_veredito, "
                  "sei_fila_captura, achado_detector, caso, fts_alertas, OB Contabilizada do SIAFE por processo"),
        "cobertura": (f"{len(contr)} contratações de {len(base.get('relatorios_lidos') or [])} relatórios lidos; "
                      f"{len(rels)} processo(s) da CGE com relatório no acervo ({len(novos)} ainda não lidos na lista)"),
        "rotulo_grau": ROTULO_GRAU,
        "metricas": m, "linhas": r["linhas"], "fontes_indisponiveis": r["fontes_indisponiveis"],
        "relatorios_no_acervo": rels, "relatorios_novos": novos, "historico": hist,
        "ressalva": ("Avaliação interna de desempenho do JFN (recall contra a CGE). Não é peça acusatória. Valor "
                     "contratado ≠ pago; pago = só OB Contabilizada. INDISPONÍVEL ≠ zero."),
        # AO VIVO: efeito = confronto MEDIDO (contratações casadas com as fontes do JFN), não só "rodou"
        "ultimo_efeito_iso": agora if m["todas"]["n"] and len(r["fontes_indisponiveis"]) < 8
        else anterior.get("ultimo_efeito_iso"),
    })
    gravar_json(saida, doc)
    log.info("CGE × JFN: %d contratações · artefato %d · sinal G1+G2 %d/%d · autos lidos %d · %d relatórios no acervo "
             "(%d novos)", m["todas"]["n"], m["todas"]["com_artefato"], m["G1+G2"]["com_sinal"], m["G1+G2"]["n"],
             m["todas"]["autos_lidos"], len(rels), len(novos))
    if r["fontes_indisponiveis"]:
        log.warning("fontes INDISPONÍVEIS: %s", ", ".join(r["fontes_indisponiveis"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confronto semanal CGE × JFN (recall por processo).")
    ap.add_argument("--entrada", default=str(ENTRADA))
    ap.add_argument("--saida", default=str(SAIDA))
    a = ap.parse_args(argv)
    return executar(NOME, lambda log: _rodar(log, Path(a.entrada), Path(a.saida)))


if __name__ == "__main__":
    raise SystemExit(main())
