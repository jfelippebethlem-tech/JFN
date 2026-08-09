#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Empresas que dividem contato E receberam do Estado — o elo que ninguém declarou.

A PERGUNTA QUE O GRAFO EXISTE PARA RESPONDER: duas empresas que disputam o mesmo dinheiro público
atendem pelo mesmo telefone ou pelo mesmo e-mail? Se sim, ou são o mesmo grupo (e a disputa entre
elas é aparente), ou há uma mão comum que ninguém declarou.

MEDIDO EM 2026-08-07 sobre 850 credores percorridos e 761 arestas de contato:

    761  arestas de contato no grafo
   -270  ESTRUTURAIS — consórcio divide contato com as consorciadas por desenho da lei; idem SCP
         (aparece o sócio ostensivo), fundo público (não é empresa) e cooperativa (central)
    491  pedem explicação
     51  com os DOIS lados recebendo do Estado  ← a fila

DUAS EXPLICAÇÕES SÃO DECLARADAS, NUNCA ESCONDIDAS:

  · **mesmo grupo aparente** — `OI S.A.` × `OI MÓVEL`, `TAPEVAS SOLUÇÕES` × `TAPEVAS SOLUÇÃO`,
    `PETRA MG` × `PETRA RJ`. Grupo econômico é lícito; o que ele NÃO pode é disputar o mesmo
    certame fingindo concorrência (art. 337-F do CP; Lei 12.529/2011). Fica na fila, marcado.
  · **estrutura jurídica** — sai da fila, com o motivo escrito.

O que sobra sem nenhuma das duas é o que interessa: empresas de nomes distintos, sem forma
jurídica que as una, atendendo pelo mesmo contato, ambas pagas pelo poder público.

    python -m tools.elos_ocultos              # grava JSON + markdown
    python -m tools.elos_ocultos --medir      # só mede
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ESTAB = _REPO / "data" / "receita_estab.db"
_SAIDA = _REPO / "data" / "elos_ocultos.json"
_SAIDA_MD = _REPO / "data" / "elos_ocultos.md"

# Palavras que não distinguem grupo nenhum — sem tirá-las, "COMERCIO" casaria meia base.



import re as _re

from compliance_agent.osint.marca_grupo import mesmo_grupo

_RX_EMAIL = _re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

_SQL_VEREDITO = """
CREATE TABLE IF NOT EXISTS elo_veredito (
  raiz_a      TEXT NOT NULL,
  raiz_b      TEXT NOT NULL,
  veredito    TEXT NOT NULL,      -- 'mesmo_grupo' | 'servico_compartilhado' | 'elo_real'
  motivo      TEXT NOT NULL,      -- por que, em uma frase
  fonte       TEXT NOT NULL,      -- de onde veio a prova (documento, URL, quem decidiu)
  decidido_em TEXT NOT NULL,
  PRIMARY KEY (raiz_a, raiz_b))
"""


def _chave_par(a: str, b: str) -> tuple[str, str]:
    """Par ordenado das RAÍZES — a mesma dupla em qualquer ordem tem uma chave só."""
    ra, rb = _re.sub(r"\D", "", a or "")[:8], _re.sub(r"\D", "", b or "")[:8]
    return (ra, rb) if ra <= rb else (rb, ra)


def vereditos(db: str = "") -> dict[tuple[str, str], dict]:
    """Pares já explicados por PROVA externa — a guarda estrutural contra achado que reaparece.

    POR QUE EXISTE. `AMIL × COI` divide o e-mail jurídico `@uhgbrasil.com.br` e encabeçava a fila
    com R$ 216,5 mi. Nem a marca nem o QSA brasileiro as unem — a COI pertence à Amil, e a Amil é
    controlada pela UnitedHealthCare International IV S.à r.l. via Polar II FIP, o que só está no
    demonstrativo financeiro. Sem um lugar para GRAVAR essa prova, o par voltaria ao topo a cada
    passada, e a alternativa preguiçosa (rebaixar todo domínio corporativo) esconderia elo real.
    Aqui o veredito é dado UMA vez, com fonte, e vale para sempre — como `fachada_veredito` faz
    com a fachada. Nada some da lista: o par continua visível, com o motivo escrito.
    """
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(db or _DB, timeout=30)
    try:
        con.execute(_SQL_VEREDITO)
        con.commit()
        return {(r[0], r[1]): {"veredito": r[2], "motivo": r[3], "fonte": r[4]}
                for r in con.execute(
                    "SELECT raiz_a, raiz_b, veredito, motivo, fonte FROM elo_veredito")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def decidir(cnpj_a: str, cnpj_b: str, veredito: str, motivo: str, fonte: str,
            db: str = "") -> None:
    """Grava o veredito de um par. Idempotente (REPLACE) — reavaliar é corrigir, não duplicar."""
    from compliance_agent.reporting.intel_base import _DB

    ra, rb = _chave_par(cnpj_a, cnpj_b)
    con = sqlite3.connect(db or _DB, timeout=30)
    try:
        con.execute(_SQL_VEREDITO)
        con.execute("INSERT OR REPLACE INTO elo_veredito VALUES (?,?,?,?,?,?)",
                    (ra, rb, veredito, motivo, fonte, time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
    finally:
        con.close()





def grupo_declarado_no_qsa(con: sqlite3.Connection, raiz_a: str, raiz_b: str,
                           razao_a: str = "", razao_b: str = "") -> str:
    """Vínculo PÚBLICO entre as duas raízes no QSA da Receita — sócio em comum (nome+doc) ou uma
    empresa sócia da outra. Elo OCULTO é o vínculo não declarado; sócio em comum é declarado.

    Medido em 2026-08-08: os dois "elos reais" do topo da fila eram grupo declarado — VALID ×
    CONTIPLAN dividem DOIS diretores no QSA (Bressan, Olavo Vaz) e a RIOPAR é SÓCIA da MAIS MOBI.
    O cotejo de marca não os via (nomes nada parecidos); o QSA via. Devolve o rótulo do vínculo
    ('' = nenhum declarado).
    """
    sa = {(r[0] or "", r[1] or "") for r in con.execute(
        "SELECT nome_socio, doc_socio FROM socios_receita WHERE cnpj_basico=?", (raiz_a,))}
    if not sa:
        return ""
    sb = {(r[0] or "", r[1] or "") for r in con.execute(
        "SELECT nome_socio, doc_socio FROM socios_receita WHERE cnpj_basico=?", (raiz_b,))}
    if not sb:
        return ""
    comum = sorted(n for n, _ in sa & sb)
    nomes_a, nomes_b = {n for n, _ in sa}, {n for n, _ in sb}
    cruzado = []
    if razao_b and razao_b.strip().upper() in {n.strip().upper() for n in nomes_a}:
        cruzado.append(f"{razao_b} é sócia")
    if razao_a and razao_a.strip().upper() in {n.strip().upper() for n in nomes_b}:
        cruzado.append(f"{razao_a} é sócia")
    partes = comum + cruzado
    return ("QSA: " + "; ".join(partes))[:120] if partes else ""


def levantar(db: str = "") -> dict:
    from compliance_agent.osint.contato_compartilhado import explicacao_estrutural
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    nat: dict[str, str] = {}
    razao: dict[str, str] = {}
    if _ESTAB.exists():
        est = sqlite3.connect(f"file:{_ESTAB}?mode=ro", uri=True)
        try:
            if est.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                           ).fetchone():
                for r in est.execute("SELECT cnpj_basico, natureza_cod, razao_social FROM empresas"):
                    nat[r[0]] = str(r[1] or "")
                    razao[r[0]] = str(r[2] or "")
        finally:
            est.close()

    pago = {r[0]: r[1] for r in con.execute(
        "SELECT substr(credor,1,8), SUM(valor) FROM ob_orcamentaria_siafe "
        "WHERE status='Contabilizado' AND length(credor)=14 GROUP BY 1")}

    linhas = list(con.execute(
        "SELECT a.nome, a.cpf, b.nome, b.cpf, r.tipo, r.descricao FROM relacionamentos r "
        "JOIN pessoas a ON a.id=r.pessoa_a_id JOIN pessoas b ON b.id=r.pessoa_b_id "
        "WHERE r.tipo IN ('mesmo_telefone','mesmo_email') AND a.tipo='empresa' AND b.tipo='empresa'"))
    con.close()

    total, estrutural, itens = len(linhas), 0, []
    vistos: set[tuple[str, str]] = set()
    from compliance_agent.osint.contato_compartilhado import _de_servico

    servico = 0
    for na, ca, nb, cb, tipo, desc in linhas:
        exp = explicacao_estrutural(nat.get(ca, ""), nat.get(cb, ""))
        if exp:
            estrutural += 1
            continue
        # RECONFERÊNCIA NA LEITURA: o grafo é idempotente e NÃO reclassifica arestas já gravadas.
        # Uma aresta `mesmo_email` persistida ANTES de `_de_servico` passar a olhar a parte local
        # do e-mail (o fix que pegou `contabilidade@dominio` com domínio livre) fica congelada como
        # elo, e um contador compartilhado aparece no topo da fila do fiscal como se fosse vínculo
        # oculto. Medido em 2026-08-08: `contabilidade@loges-es.com.br` unia COSTA CAMARGO × UNIQUE.
        # Reconferir aqui é barato e cobre o passado sem reprocessar o grafo inteiro.
        if tipo == "mesmo_email":
            m = _RX_EMAIL.search(desc or "")
            if m and _de_servico(m.group(0)):
                servico += 1
                continue
        if ca not in pago or cb not in pago:
            continue
        chave = tuple(sorted((ca, cb)))
        if chave in vistos:
            continue
        vistos.add(chave)
        grupo = mesmo_grupo(razao.get(ca, na), razao.get(cb, nb))
        # PISTA, não veredito: o DOMÍNIO do e-mail compartilhado viaja com o item. AMIL × COI
        # dividem @uhgbrasil.com.br (holding UnitedHealth) e ABBOTT × ST JUDE são o mesmo grupo
        # global sem QSA brasileiro em comum — o humano decide; rebaixar às cegas esconderia
        # elo real (handoff 2026-08-08 §5).
        dominio = ""
        if tipo == "mesmo_email":
            m = _RX_EMAIL.search(desc or "")
            if m and "@" in m.group(0):
                dominio = m.group(0).split("@", 1)[1].lower().rstrip(".")
        itens.append({
            "a": razao.get(ca, na), "cnpj_a": ca, "pago_a": pago.get(ca, 0.0),
            "b": razao.get(cb, nb), "cnpj_b": cb, "pago_b": pago.get(cb, 0.0),
            "tipo": tipo, "detalhe": desc or "", "dominio_email": dominio,
            "natureza_a": nat.get(ca, ""), "natureza_b": nat.get(cb, ""),
            "mesmo_grupo_aparente": bool(grupo),
            "marca": grupo,
            "peso": (pago.get(ca, 0.0) + pago.get(cb, 0.0)),
        })
    # GRUPO DECLARADO NO QSA — o vínculo público que o cotejo de MARCA não vê (ver docstring de
    # `grupo_declarado_no_qsa`). Só consulta os pares que sobraram sem explicação (~dezenas).
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    try:
        for x in itens:
            if x["mesmo_grupo_aparente"]:
                continue
            rot = grupo_declarado_no_qsa(con, x["cnpj_a"], x["cnpj_b"], x["a"], x["b"])
            if rot:
                x["mesmo_grupo_aparente"] = True
                x["marca"] = rot
    finally:
        con.close()
    # VEREDITO JÁ DADO, com prova externa — o par sai da fila de trabalho mas CONTINUA na lista,
    # com motivo e fonte à vista (ver `vereditos`). Só 'elo_real' mantém o par em aberto: quando
    # a apuração CONFIRMA o elo, ele não pode sumir junto com os explicados.
    dec = vereditos(db)
    for x in itens:
        v = dec.get(_chave_par(x["cnpj_a"], x["cnpj_b"]))
        if v and v["veredito"] != "elo_real":
            x["mesmo_grupo_aparente"] = True
            x["marca"] = f"{v['veredito']}: {v['motivo']} [fonte: {v['fonte']}]"[:200]
        elif v:
            x["veredito_humano"] = v
    itens.sort(key=lambda x: -x["peso"])
    return {"arestas_de_contato": total, "estruturais": estrutural,
            "contador_compartilhado_reclassificado": servico,
            "pedem_explicacao": total - estrutural,
            "os_dois_lados_pagos": len(itens),
            "mesmo_grupo_aparente": sum(1 for x in itens if x["mesmo_grupo_aparente"]),
            "sem_explicacao": sum(1 for x in itens if not x["mesmo_grupo_aparente"]),
            "itens": itens}


def escrever(r: dict) -> tuple[str, str]:
    _SAIDA.write_text(json.dumps({"gerado_em": time.strftime("%Y-%m-%d %H:%M"), **r},
                                 ensure_ascii=False), encoding="utf-8")
    L = ["# Elos ocultos — empresas que dividem contato e ambas recebem do Estado", "",
         f"Gerado em {time.strftime('%Y-%m-%d %H:%M')} · {r['arestas_de_contato']} arestas de "
         f"contato · {r['estruturais']} estruturais (fora) · **{r['os_dois_lados_pagos']}** com os "
         f"dois lados pagos · {r['sem_explicacao']} sem explicação aparente.", "",
         "> **Indício, nunca prova.** Telefone e e-mail vêm do cadastro da Receita e podem ser de "
         "escritório de contabilidade, central de atendimento ou grupo econômico legítimo. Grupo "
         "econômico é lícito — o que ele não pode é **disputar o mesmo certame fingindo "
         "concorrência** (art. 337-F do Código Penal; Lei 12.529/2011). O que se afirma aqui é que "
         "há o que conferir: quem são os sócios, se disputaram o mesmo item, e com que propostas.",
         "", "| # | Empresa A | Empresa B | Elo | Pago A | Pago B | Grupo aparente |",
         "|---|---|---|---|---|---|---|"]
    from compliance_agent.reporting.intel_base import moeda

    for i, x in enumerate(r["itens"][:120], 1):
        L.append(f"| {i} | {x['a']} | {x['b']} | {x['tipo']} | "
                 f"{moeda(x['pago_a'])} | {moeda(x['pago_b'])} | {x['marca'] or '—'} |")
    _SAIDA_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    return str(_SAIDA), str(_SAIDA_MD)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--medir", action="store_true")
    a = ap.parse_args()
    r = levantar()
    for k, v in r.items():
        if k != "itens":
            print(f"{k:24s} {v}")
    if not a.medir:
        for c in escrever(r):
            print(f"gravado: {c}")
    for x in r["itens"][:8]:
        g = f" ⟨grupo {x['marca']}⟩" if x["mesmo_grupo_aparente"] else ""
        from compliance_agent.reporting.intel_base import moeda as _m
        print(f"  {x['a'][:32]:32s} × {x['b'][:32]:32s} {x['tipo']:15s} "
              f"{_m(x['peso']):>18s}{g}")


if __name__ == "__main__":
    main()
