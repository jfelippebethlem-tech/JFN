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
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ESTAB = _REPO / "data" / "receita_estab.db"
_SAIDA = _REPO / "data" / "elos_ocultos.json"
_SAIDA_MD = _REPO / "data" / "elos_ocultos.md"

# Palavras que não distinguem grupo nenhum — sem tirá-las, "COMERCIO" casaria meia base.
_GENERICAS = frozenset({
    "COMERCIO", "SERVICOS", "SERVICO", "INDUSTRIA", "DISTRIBUIDORA", "EMPREENDIMENTOS",
    "CONSTRUTORA", "ENGENHARIA", "PARTICIPACOES", "SOLUCOES", "SOLUCAO", "TECNOLOGIA",
    "ASSOCIACAO", "INSTITUTO", "CENTRO", "CLINICA", "MEDICOS", "MEDICA", "LABORATORIO",
    "APOIO", "ESCOLA", "ESCOLAR", "UNIDADES", "UNIDADE", "GESTAO", "ADMINISTRACAO",
    "GERAIS", "GERAL", "INTEGRADA", "INTEGRADAS", "INTEGRADO", "INTEGRADOS",
    "TERCEIRIZADOS", "TERCEIRIZADA", "TECNICOS", "TECNICA", "ESPECIALIZADA",
    "TRANSPORTES", "LTDA", "EIRELI", "SOCIEDADE", "GRUPO", "BRASIL", "RIO", "NACIONAL",
    # BOILERPLATE JURÍDICO — nunca é marca. Medido em 2026-08-08: "OI S.A. - EM RECUPERAÇÃO
    # JUDICIAL" virava marca "RECUPERACAO" (porque "OI", de 2 letras, era pulado), e o par
    # OI S.A. × OI MÓVEL caía no bucket "sem explicação" como se fosse elo oculto. Situação
    # jurídica não distingue empresa: duas falidas quaisquer não são o mesmo grupo.
    "RECUPERACAO", "JUDICIAL", "EXTRAJUDICIAL", "LIQUIDACAO", "FALENCIA", "FALIDA", "MASSA",
    "EPP", "ME", "SA", "CIA", "COMPANHIA", "EMPRESA", "COMERCIAL", "PRODUTOS", "MATERIAIS",
    # preposições/artigos curtos: sem eles, "EM" (de "EM RECUPERAÇÃO") entrava nos tokens e
    # quebrava a comparação por prefixo — "OI EM" ≠ "OI MOVEL EM".
    "EM", "NA", "NO", "DA", "DE", "DO", "AS", "OS", "DAS", "DOS", "COM", "PARA", "POR",
})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z ]", " ", s).upper()


import re as _re
_RX_EMAIL = _re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _marca(razao: str) -> str:
    """Primeira palavra distintiva da razão social — a 'marca' aparente.

    `OI S.A. - EM RECUPERAÇÃO JUDICIAL` e `OI MÓVEL S.A.` compartilham `OI`; `TAPEVAS SOLUÇÕES` e
    `TAPEVAS SOLUÇÃO` compartilham `TAPEVAS`. Palavra genérica não vale: sem essa lista, `COMERCIO`
    uniria meia base num grupo econômico imaginário.
    """
    for p in _norm(razao).split():
        if len(p) >= 3 and p not in _GENERICAS:
            return p
    return ""


def _tokens_marca(razao: str) -> list[str]:
    """Tokens distintivos (sem genéricas nem boilerplate), na ordem — para comparar por prefixo."""
    return [p for p in _norm(razao).split() if len(p) >= 2 and p not in _GENERICAS]


def _mesmo_grupo(razao_a: str, razao_b: str) -> str:
    """Marca comum aparente, ou vazio. Duas vias, ambas conservadoras:

    1. MESMA MARCA: a primeira palavra distintiva (≥3) coincide — o caso comum.
    2. PREFIXO DE TOKENS: os tokens distintivos de uma são prefixo dos da outra e o primeiro token
       coincide — pega matriz/subsidiária cujo nome curto é estendido ("OI" ⊂ "OI MÓVEL",
       "LIGHT" ⊂ "LIGHT SERVIÇOS"). Sem isto, marca de 2 letras (pulada pelo limiar ≥3) some.

    O prefixo exige o PRIMEIRO token igual de propósito: "SERVIÇOS X" e "SERVIÇOS Y" não viram grupo
    porque SERVIÇOS é genérica e cai fora dos tokens; mas "ALFA" e "ALFA BETA" viram, e é o que se
    quer. Conservador porque marcar grupo à toa ESCONDE um elo real da fila do fiscal.
    """
    ma, mb = _marca(razao_a), _marca(razao_b)
    if ma and ma == mb:
        return ma
    ta, tb = _tokens_marca(razao_a), _tokens_marca(razao_b)
    if ta and tb and ta[0] == tb[0]:
        curto, longo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if longo[: len(curto)] == curto:
            return curto[0]
    return ""


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
        grupo = _mesmo_grupo(razao.get(ca, na), razao.get(cb, nb))
        itens.append({
            "a": razao.get(ca, na), "cnpj_a": ca, "pago_a": pago.get(ca, 0.0),
            "b": razao.get(cb, nb), "cnpj_b": cb, "pago_b": pago.get(cb, 0.0),
            "tipo": tipo, "detalhe": desc or "",
            "natureza_a": nat.get(ca, ""), "natureza_b": nat.get(cb, ""),
            "mesmo_grupo_aparente": bool(grupo),
            "marca": grupo,
            "peso": (pago.get(ca, 0.0) + pago.get(cb, 0.0)),
        })
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
