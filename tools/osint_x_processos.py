#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liga a inteligência OSINT recém-construída aos processos que a casa JÁ LEU.

O PEDIDO DO DONO: *correlacionar a inteligência já adquirida aos processos já vistos*. Havia
inteligência de sobra parada de um lado — 686.964 vínculos societários, 5,86 milhões de razões
sociais, a fila de agente público — e 2.277 fichas de processo com CNPJ do outro, sem que nada as
aproximasse. Um sinal sobre a empresa só vira achado quando aponta para um PROCESSO concreto.

MEDIDO ANTES DE LIGAR (família 18), sobre as 2.277 fichas com CNPJ (902 empresas, 845 raízes):

  · **68,6%** têm algum sinal — inútil como fila. E o que infla é `sem_qsa_capturado` (63,5%), que
    é LACUNA DE CAPTURA, não achado: quer dizer que não observamos o quadro societário, e ler
    silêncio como limpeza é o erro que esta casa mais corrigiu.
  · **7,6%** (174 processos) têm agente público no quadro societário da empresa — taxa que separa.
  · **3,8%** envolvem entidade de terceiro setor.

E O CRUZAMENTO CRU NÃO SERVE, porque o casamento com a folha é por NOME: os primeiros exemplos
eram `JOSE ANTONIO DA SILVA` e `RICARDO CARDOSO DA SILVA`, nomes que gritam homônimo. Por isso a
fonte aqui NÃO é a tabela bruta e sim a **fila de `agente_publico_reverso`**, que já descartou nome
com mais de um CPF mascarado no índice, já vetou o que é desenho de programa (associação de apoio à
escola, fundação de apoio, ente público) e já traz o eixo que separa o comum do grave — a unidade
que pagou ser a unidade onde o agente serve.

O produto é uma fila de PROCESSOS, não de empresas: quem fiscaliza abre autos, não CNPJs.

    python -m tools.osint_x_processos            # grava JSON + markdown
    python -m tools.osint_x_processos --medir    # só mede
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ESTAB = _REPO / "data" / "receita_estab.db"
_SAIDA_JSON = _REPO / "data" / "osint_x_processos.json"
_SAIDA_MD = _REPO / "data" / "osint_x_processos.md"


def _cnpjs_da_ficha(bruto: str) -> list[str]:
    """CNPJs de uma ficha. Aceita JSON ou texto solto — o campo tem as duas formas no acervo."""
    try:
        lista = json.loads(bruto) if str(bruto).strip().startswith("[") else re.findall(
            r"\d{14}", re.sub(r"[.\-/]", "", str(bruto)))
    except (ValueError, TypeError):
        lista = []
    fora = []
    for x in lista:
        d = re.sub(r"\D", "", str(x))
        if len(d) == 14:
            fora.append(d)
    return fora


def processos_com_cnpj(con: sqlite3.Connection) -> tuple[dict[str, list[str]], dict[str, str]]:
    """CNPJs de cada processo, pela ficha e — quando ela nada extraiu — pelo PAGAMENTO.

    Medido em 2026-08-06: das 4.430 fichas, **2.155 têm `cnpjs` vazio** — metade do acervo lido sem
    a parte contratada identificada. Não é defeito de leitura do campo (2.136 são literalmente
    `[]`): é extração que não encontrou o número no texto.

    Mas o processo aparece nas ORDENS BANCÁRIAS, e a OB nomeia o credor. Dessas 2.155, **1.102**
    (51%) se recuperam por aí: 1.091 pelo campo `processo` do SIAFE e 1.052 pelo `numero_sei` do
    espelho TFE. Deixar de usar essa fonte é jogar fora metade da correlação — e ler a ausência de
    CNPJ na ficha como ausência de contratado seria o mesmo erro que esta casa já corrigiu em
    outras camadas.

    A PROCEDÊNCIA VAI JUNTO (`ficha` ou `pagamento`): quem lê precisa saber se o CNPJ veio do texto
    dos autos ou de quem recebeu o dinheiro — são coisas diferentes e sustentam afirmações
    diferentes.
    """
    fora: dict[str, list[str]] = {}
    origem: dict[str, str] = {}
    for numero, cj in con.execute(
            "SELECT numero_sei, cnpjs FROM sei_ficha WHERE cnpjs IS NOT NULL AND cnpjs <> ''"):
        lista = _cnpjs_da_ficha(cj)
        if lista:
            fora[numero] = sorted(set(lista))
            origem[numero] = "ficha"

    faltam = [n for n, in con.execute("SELECT numero_sei FROM sei_ficha") if n not in fora]
    if not faltam:
        return fora, origem
    ph = ",".join("?" * len(faltam))
    achado: dict[str, set[str]] = {}
    for sql in (f"SELECT numero_sei, favorecido_cpf FROM ordens_bancarias "
                f"WHERE numero_sei IN ({ph})",
                f"SELECT processo, credor FROM ob_orcamentaria_siafe WHERE processo IN ({ph})"):
        try:
            linhas = con.execute(sql, tuple(faltam)).fetchall()
        except sqlite3.Error:
            continue
        for numero, doc in linhas:
            d = re.sub(r"\D", "", str(doc or ""))
            if len(d) == 14:
                achado.setdefault(str(numero), set()).add(d)
    for numero, cnpjs in achado.items():
        fora[numero] = sorted(cnpjs)
        origem[numero] = "pagamento"
    return fora, origem


def orgao_do_processo(con: sqlite3.Connection) -> dict[str, str]:
    """Unidade gestora de cada processo, pelas OBs que o citam.

    O PROCESSO É A PROVA MELHOR DE QUEM CONTRATA, e isto foi medido: os três Diretores-Gerais da
    Fundação Saúde no quadro da MEDVIVA NÃO acendiam o conflito de órgão, porque a UG que paga no
    SIAFE é o `FUNDO ESTADUAL DA SAÚDE` (294200) e o agente serve na `FUNDAÇÃO SAÚDE DO ESTADO DO
    RIO DE JANEIRO` — os dois nomes compartilham UMA palavra distintiva, e o cotejo exige duas.
    Mas os cinco processos de indenização por serviços médicos que citam a MEDVIVA correm na
    PRÓPRIA Fundação Saúde. O caminho do dinheiro passa pelo fundo; o caminho da DECISÃO passa pelo
    órgão — e é a decisão que o art. 9º, III da Lei 8.429/1992 alcança.
    """
    fora: dict[str, str] = {}
    for numero, ug in con.execute(
            "SELECT numero_sei, ug_nome FROM ordens_bancarias "
            "WHERE numero_sei IS NOT NULL AND ug_nome IS NOT NULL GROUP BY 1, 2"):
        fora.setdefault(str(numero), str(ug))
    return fora


def correlacionar(db: str = "") -> dict:
    from compliance_agent.reporting.intel_base import _DB
    from tools.agente_publico_reverso import _FILA_JSON

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    procs, origem_cnpj = processos_com_cnpj(con)
    raizes = {c[:8] for L in procs.values() for c in L}

    # A FILA CURADA, não a tabela crua: ela já descartou homônimo comprovado e já vetou o que é
    # desenho de programa. Sem esse filtro o cruzamento devolve "JOSE ANTONIO DA SILVA".
    por_raiz: dict[str, list[dict]] = {}
    if _FILA_JSON.exists():
        for x in json.loads(_FILA_JSON.read_text(encoding="utf-8")).get("itens", []):
            if x["cnpj_basico"] in raizes and not x["explicacao_institucional"]:
                por_raiz.setdefault(x["cnpj_basico"], []).append(x)

    # QSA observado — sua AUSÊNCIA é lacuna de captura, jamais achado.
    ph = ",".join("?" * len(raizes)) or "''"
    com_qsa = {r[0] for r in con.execute(
        f"SELECT DISTINCT cnpj_basico FROM socios_receita WHERE cnpj_basico IN ({ph})",
        tuple(raizes))} if raizes else set()

    nat: dict[str, str] = {}
    razao: dict[str, str] = {}
    if _ESTAB.exists() and raizes:
        est = sqlite3.connect(f"file:{_ESTAB}?mode=ro", uri=True)
        try:
            if est.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                           ).fetchone():
                for r in est.execute(
                        f"SELECT cnpj_basico, natureza_cod, razao_social FROM empresas "
                        f"WHERE cnpj_basico IN ({ph})", tuple(raizes)):
                    nat[r[0]] = str(r[1] or "")
                    razao[r[0]] = str(r[2] or "")
        finally:
            est.close()

    from tools.agente_publico_reverso import conflito_de_orgao, explicacao_institucional

    ug_por_proc = orgao_do_processo(con)
    achados = []
    for numero, lista in procs.items():
        agentes, terceiro, sem_qsa = [], [], []
        for c in lista:
            r = c[:8]
            agentes += por_raiz.get(r, [])
            # TERCEIRO SETOR **SEM EXPLICAÇÃO CONHECIDA**. Um processo que paga centenas de
            # Associações de Apoio à Escola citava cada uma delas e subia ao topo com peso 821 —
            # e todas são o DESENHO do programa, não achado. Contar entidade já explicada é
            # transformar a rotina do Estado em fila de suspeita.
            if nat.get(r, "").startswith("3") and not explicacao_institucional(
                    razao.get(r, ""), nat.get(r, "")):
                terceiro.append(c)
            if r not in com_qsa:
                sem_qsa.append(c)
        if not agentes and not terceiro:
            continue
        ug = ug_por_proc.get(numero, "")
        # CONFLITO PELO PROCESSO: o agente serve na unidade que conduz ESTES autos.
        for a in agentes:
            a["_conflito_processo"] = conflito_de_orgao(a["orgao"], {ug}) if ug else ""
        conflito = [a for a in agentes
                    if a["orgao_pagador_e_o_proprio"] or a["_conflito_processo"]]
        achados.append({
            "processo": numero,
            "cnpjs": lista,
            "origem_cnpj": origem_cnpj.get(numero, "ficha"),
            "orgao_do_processo": ug,
            "agentes": [{"nome": a["agente"], "cargo": a["cargo"], "orgao": a["orgao"],
                         "comissionado": a["comissionado"], "entidade": a["entidade"],
                         "conflito_de_orgao": a["orgao_pagador_e_o_proprio"],
                         "conflito_pelo_processo": a.get("_conflito_processo", "")}
                        for a in agentes],
            "terceiro_setor": terceiro,
            "sem_qsa_capturado": sem_qsa,
            "peso": (100 if conflito else 0) + 10 * sum(1 for a in agentes if a["comissionado"])
                    + len(agentes) + len(terceiro),
        })
    con.close()
    achados.sort(key=lambda x: -x["peso"])
    return {"processos_com_cnpj": len(procs),
            "pela_ficha": sum(1 for v in origem_cnpj.values() if v == "ficha"),
            "pelo_pagamento": sum(1 for v in origem_cnpj.values() if v == "pagamento"),
            "empresas": len({c for L in procs.values() for c in L}),
            "com_achado": len(achados), "achados": achados}


def escrever(r: dict) -> tuple[str, str]:
    _SAIDA_JSON.parent.mkdir(parents=True, exist_ok=True)
    _SAIDA_JSON.write_text(json.dumps(
        {"gerado_em": time.strftime("%Y-%m-%d %H:%M"), **r}, ensure_ascii=False), encoding="utf-8")

    L = ["# OSINT × processos lidos", "",
         f"Gerado em {time.strftime('%Y-%m-%d %H:%M')} · {r['processos_com_cnpj']} processos com "
         f"CNPJ na ficha · **{r['com_achado']}** com sinal OSINT na empresa.", "",
         "> **Indício, nunca prova.** A ponte processo→empresa vem do CNPJ citado na ficha; a ponte "
         "empresa→pessoa vem do casamento por NOME com as folhas (o TSE mascara o CPF e a folha não "
         "o traz). Nomes com mais de um CPF no índice já foram descartados, e o que é desenho de "
         "programa — associação de apoio à escola, fundação de apoio, ente público — já foi vetado. "
         "**Ausência de QSA capturado é LACUNA, não limpeza.**", "",
         "| # | Processo | Sinal | Pessoa | Cargo · Órgão | Entidade |",
         "|---|---|---|---|---|---|"]
    for i, a in enumerate(r["achados"][:120], 1):
        if a["agentes"]:
            g = a["agentes"][0]
            sinal = ("⚠ AUTOS no próprio órgão do agente" if g["conflito_pelo_processo"]
                     else ("⚠ pago pelo próprio órgão" if g["conflito_de_orgao"]
                           else ("★ comissionado" if g["comissionado"]
                                 else "agente público no QSA")))
            L.append(f"| {i} | {a['processo']} | {sinal} | {g['nome']} | "
                     f"{g['cargo']} · {g['orgao']} | {g['entidade']} |")
        else:
            L.append(f"| {i} | {a['processo']} | terceiro setor | — | — | "
                     f"{', '.join(a['terceiro_setor'])} |")
    _SAIDA_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    return str(_SAIDA_JSON), str(_SAIDA_MD)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--medir", action="store_true", help="não grava, só mede")
    a = ap.parse_args()
    r = correlacionar()
    print(f"processos com CNPJ na ficha : {r['processos_com_cnpj']:,}")
    print(f"empresas citadas            : {r['empresas']:,}")
    print(f"processos COM sinal OSINT   : {r['com_achado']:,}")
    if not a.medir:
        for c in escrever(r):
            print(f"gravado: {c}")
    for x in r["achados"][:8]:
        g = (x["agentes"] or [{}])[0]
        print(f"  {x['peso']:4d} {x['processo']}  {str(g.get('nome',''))[:28]:28s} "
              f"{str(g.get('cargo',''))[:20]:20s} {str(g.get('entidade',''))[:26]}")


if __name__ == "__main__":
    main()
