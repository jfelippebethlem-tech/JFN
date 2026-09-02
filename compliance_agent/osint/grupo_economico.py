# -*- coding: utf-8 -*-
"""Concentração por GRUPO econômico de fato, não por CNPJ (G.6).

A PERGUNTA QUE ISTO RESPONDE, e que nenhum indicador da casa fazia: um órgão pode contratar dez
empresas diferentes e, ainda assim, estar pagando quase tudo a **um só dono**. Todo índice de
concentração do JFN — e da literatura — mede por CNPJ; a competição aparente sobrevive à medição
justamente porque a medição para no CNPJ.

COMO O GRUPO É FORMADO. Pela pessoa que liga empresas: `rede_socios_fornecedores` já materializa
quem consta no QSA de dois ou mais fornecedores nossos. Empresas ligadas pela MESMA pessoa entram
no mesmo grupo, por fecho transitivo — se A e B compartilham a pessoa X, e B e C compartilham a
pessoa Y, as três são um grupo. É a definição de grupo **de fato**, que é o que importa para
concentração: não exige controle formal declarado.

O NÚMERO QUE IMPORTA É O DELTA. HHI por CNPJ diz o que já se sabia; HHI por grupo diz o que se
ignorava. A diferença entre os dois é exatamente a concentração que a estrutura societária
escondia — e é ela que vai ao relatório, não o valor absoluto.

TRÊS HONESTIDADES OBRIGATÓRIAS:

  · **Cobertura de QSA.** Fornecedor sem quadro societário na base não pode ser agrupado; ele
    conta como grupo de si mesmo, e a fração de valor nessa situação sai declarada. Um delta
    calculado sobre 30% de cobertura não significa a mesma coisa que sobre 90%.
  · **Grupo não é ilícito.** Holding, franquia e sócio investidor são lícitos. O achado é a
    CONCENTRAÇÃO que não aparecia, e o que ela pede é diligência — nunca imputação.
  · **Pagamento é OB.** A concentração se mede sobre Ordem Bancária, jamais sobre empenho:
    empenho é valor bruto que pode ser cancelado, e concentrar empenho não é concentrar dinheiro.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

# Uma pessoa em muitíssimas empresas não forma "grupo": é administrador profissional ou o efeito
# da máscara de CPF (medido: 977 de 24.448 documentos carregam mais de um nome). Acima deste
# limite a pessoa não é usada para unir empresas — uniria o mercado inteiro num grupo só.
MAX_EMPRESAS_POR_PESSOA = 20
HHI_CONCENTRADO = 0.25          # o mesmo piso já usado em `editais/screens_participacao`
DELTA_RELEVANTE = 0.05          # abaixo disto o agrupamento não mudou a leitura
# Fração mínima de pontes com poder de mando para o grupo ser LIDO como comandado. Calibrado no
# acervo (2026-08-09): Cidades tem 2 administradores em 5 pontes (40%) e é comando; FSERJ tem 1 em
# 28 (3,6%) e é teia de cotistas com uma exceção. Não há caso do acervo entre 0,036 e 0,40 — o piso
# fica no meio, longe dos dois. Não altera agrupamento nem HHI: só a leitura.
PONTE_DE_COMANDO_MIN = 0.20


def _doc(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


class _Uniao:
    """Union-find — o fecho transitivo de "compartilham sócio" é o que define o grupo de fato."""

    def __init__(self) -> None:
        self._pai: dict[str, str] = {}

    def achar(self, x: str) -> str:
        self._pai.setdefault(x, x)
        while self._pai[x] != x:
            self._pai[x] = self._pai[self._pai[x]]
            x = self._pai[x]
        return x

    def unir(self, a: str, b: str) -> None:
        ra, rb = self.achar(a), self.achar(b)
        if ra != rb:
            self._pai[ra] = rb


def montar_grupos(con: sqlite3.Connection, *,
                  max_empresas_por_pessoa: int = MAX_EMPRESAS_POR_PESSOA) -> dict[str, Any]:
    """`{raiz_cnpj -> id_do_grupo}` e as pessoas que uniram cada grupo."""
    try:
        linhas = con.execute(
            "SELECT nome_socio, doc_socio, cnpjs_basicos FROM rede_socios_fornecedores").fetchall()
    except sqlite3.OperationalError:
        return {"grupo_de": {}, "unido_por": {}, "pessoas_usadas": 0,
                "motivo": "rede_socios_fornecedores ausente"}

    u = _Uniao()
    unido_por: dict[str, set[str]] = {}
    usadas = descartadas = 0
    for nome, doc, csv in linhas:
        basicos = [b for b in re.split(r"[,;\s]+", str(csv or "")) if b.strip()]
        basicos = sorted({b[:8] for b in basicos if len(b) >= 8})
        if len(basicos) < 2:
            continue
        if len(basicos) > max_empresas_por_pessoa:
            descartadas += 1          # administrador profissional / colisão de máscara
            continue
        usadas += 1
        for b in basicos[1:]:
            u.unir(basicos[0], b)
        for b in basicos:
            unido_por.setdefault(u.achar(b), set()).add(f"{nome}".strip())

    grupo_de = {b: u.achar(b) for b in u._pai}
    # reancora as pessoas na raiz final (a união pode ter mudado depois de registrá-las)
    final: dict[str, set[str]] = {}
    for raiz, pessoas in unido_por.items():
        final.setdefault(u.achar(raiz), set()).update(pessoas)
    return {"grupo_de": grupo_de, "unido_por": {k: sorted(v) for k, v in final.items()},
            "pessoas_usadas": usadas, "pessoas_descartadas": descartadas,
            "max_empresas_por_pessoa": max_empresas_por_pessoa}


def cimento_do_grupo(con: sqlite3.Connection, cnpjs: list[str]) -> dict[str, Any]:
    """O grupo é cimentado por CONTROLE ou por mera coparticipação? A leitura muda inteira.

    Medido em 2026-08-09, comparando os dois maiores grupos do acervo:

      · UG 660100 (Cidades) — 5 pessoas ligam 7 CNPJs e **duas administram** duas empresas cada
        (uma delas é Administrador em uma e Presidente em outra). Isso é comando comum.
      · UG 294200 (FSERJ) — 11 pessoas ligam 8 CNPJs e **só uma administra** duas; as outras dez
        são sócias de sociedades médicas com 17 a 110 cotistas. Um médico ser cotista de duas
        clínicas é o exercício normal da profissão, não estrutura de grupo.

    O fecho transitivo trata os dois casos igual — e deve mesmo, porque grupo **de fato** não exige
    controle formal (é o que o cabeçalho deste módulo declara). Mas entregar os dois números com a
    mesma cara faz o fiscal ler coparticipação profissional como comando comum. Este qualificador
    não altera o agrupamento nem o HHI: só diz o que sustenta o grupo, para quem for ler.

    Devolve `estado='indisponivel'` se o QSA não estiver na base — ausência de dado nunca vira
    "sem controle".
    """
    raizes = sorted({_doc(c)[:8] for c in cnpjs if len(_doc(c)) >= 8})
    if len(raizes) < 2:
        return {"estado": "grupo_de_um", "pontes": 0, "pontes_que_administram": 0}
    onde: dict[str, set[str]] = {}
    manda: dict[str, set[str]] = {}
    try:
        for rz in raizes:
            for nome, qual in con.execute(
                    "SELECT nome_socio, qualificacao_txt FROM socios_receita WHERE cnpj_basico = ?",
                    (rz,)):
                pessoa = str(nome or "").strip()
                if not pessoa:
                    continue
                onde.setdefault(pessoa, set()).add(rz)
                if "dministrador" in str(qual or "") or "residente" in str(qual or ""):
                    manda.setdefault(pessoa, set()).add(rz)
    except sqlite3.OperationalError:
        return {"estado": "indisponivel", "motivo": "socios_receita ausente"}

    pontes = {p: v for p, v in onde.items() if len(v) > 1}
    if not pontes:
        return {"estado": "indisponivel", "motivo": "QSA sem ponte entre os CNPJs do grupo",
                "pontes": 0, "pontes_que_administram": 0}
    controle = sorted(p for p in pontes if len(manda.get(p, set())) > 1)
    fracao = len(controle) / len(pontes)
    # A PROPORÇÃO decide, não a existência. Medido: Cidades tem 2 administradores em 5 pontes (40%)
    # e FSERJ tem 1 em 28 (3,6%) — um teste de existência acendia "comando comum" nos dois. Uma
    # única ponte de mando dentro de uma teia grande de cotistas é o ruído esperado, não a estrutura.
    if not controle:
        tipo, leitura = "coparticipacao", (
            "coparticipação: nenhuma ponte administra duas empresas do grupo — pode ser "
            "sobreposição profissional (sociedade de cotistas), não estrutura de comando")
    elif fracao >= PONTE_DE_COMANDO_MIN:
        tipo, leitura = "comando_comum", (
            f"comando comum: {len(controle)} de {len(pontes)} pontes ADMINISTRAM duas ou mais "
            "empresas do grupo")
    else:
        tipo, leitura = "coparticipacao_com_excecao", (
            f"predominantemente coparticipação: só {len(controle)} de {len(pontes)} pontes "
            "administram duas empresas — o grupo se sustenta em sócios sem poder de mando, e a "
            "exceção merece olhar isolado, não a leitura de grupo comandado")
    return {
        "estado": "medido",
        "tipo": tipo,
        "pontes": len(pontes),
        "pontes_que_administram": len(controle),
        "fracao_de_comando": round(fracao, 4),
        "administradores_em_comum": controle[:5],
        "leitura": leitura,
    }


def _hhi(valores: dict[str, float]) -> float:
    total = sum(v for v in valores.values() if v > 0)
    if total <= 0:
        return 0.0
    return sum((v / total) ** 2 for v in valores.values() if v > 0)


def concentracao_da_ug(con: sqlite3.Connection, ug: str, *,
                       grupos: dict | None = None, ano: str | None = None) -> dict[str, Any]:
    """HHI por CNPJ × HHI por GRUPO na mesma UG. O DELTA é o achado.

    Mede sobre **Ordem Bancária** — pagamento. Empenho é valor bruto que pode ser cancelado, e
    concentrar empenho não é concentrar dinheiro.
    """
    g = grupos or montar_grupos(con)
    mapa = g.get("grupo_de") or {}

    sql = ("SELECT credor, nome_credor, SUM(valor) FROM ob_orcamentaria_siafe "
           "WHERE ug_emitente = ? AND valor > 0")
    par: list[Any] = [str(ug)]
    if ano:
        sql += " AND substr(data_emissao, 7, 4) = ?"   # data_emissao é TEXTO DD/MM/AAAA
        par.append(str(ano))
    sql += " GROUP BY credor, nome_credor"
    try:
        linhas = con.execute(sql, par).fetchall()
    except sqlite3.OperationalError:
        return {"ug": ug, "estado": "sem_dado", "motivo": "ob_orcamentaria_siafe ausente"}

    por_cnpj: dict[str, float] = {}
    nomes: dict[str, str] = {}
    for credor, nome, valor in linhas:
        d = _doc(credor)
        if len(d) != 14:
            continue                      # pessoa física / credor não-CNPJ não entra na medida
        por_cnpj[d] = por_cnpj.get(d, 0.0) + float(valor or 0)
        nomes.setdefault(d, str(nome or ""))
    if not por_cnpj:
        return {"ug": ug, "estado": "sem_pagamento_a_pj", "n_cnpj": 0}

    por_grupo: dict[str, float] = {}
    membros: dict[str, set[str]] = {}
    sem_qsa_valor = 0.0
    for cnpj, valor in por_cnpj.items():
        raiz = mapa.get(cnpj[:8])
        if raiz is None:
            sem_qsa_valor += valor        # sem QSA, a empresa é grupo de si mesma
            raiz = f"solo:{cnpj[:8]}"
        por_grupo[raiz] = por_grupo.get(raiz, 0.0) + valor
        membros.setdefault(raiz, set()).add(cnpj)

    total = sum(por_cnpj.values())
    hhi_cnpj, hhi_grupo = _hhi(por_cnpj), _hhi(por_grupo)
    delta = hhi_grupo - hhi_cnpj

    topo = sorted(por_grupo.items(), key=lambda kv: -kv[1])[:5]
    maiores = [{
        "grupo": raiz,
        "valor": round(v, 2),
        "fracao": round(v / total, 4) if total else 0.0,
        "n_cnpj": len(membros[raiz]),
        "cnpjs": sorted(membros[raiz])[:8],
        "unido_por": (g.get("unido_por") or {}).get(raiz, [])[:5],
        # o que SUSTENTA o grupo — comando comum ou coparticipação (ver `cimento_do_grupo`)
        "cimento": cimento_do_grupo(con, sorted(membros[raiz])),
    } for raiz, v in topo]

    return {
        "ug": ug, "ano": ano, "estado": "medido",
        "total_pago": round(total, 2), "n_cnpj": len(por_cnpj), "n_grupo": len(por_grupo),
        "hhi_por_cnpj": round(hhi_cnpj, 4), "hhi_por_grupo": round(hhi_grupo, 4),
        "delta_hhi": round(delta, 4),
        "concentrado_por_grupo": hhi_grupo >= HHI_CONCENTRADO,
        "agrupamento_mudou_a_leitura": delta >= DELTA_RELEVANTE,
        "cobertura_qsa": {
            "valor_sem_qsa": round(sem_qsa_valor, 2),
            "fracao_sem_qsa": round(sem_qsa_valor / total, 4) if total else 0.0,
            "nota": ("fornecedor sem QSA na base conta como grupo de si mesmo — o delta é PISO, "
                     "nunca teto: mais cobertura só pode revelar mais concentração"),
        },
        "maiores_grupos": maiores,
        "ressalva": _RESSALVA,
    }


def ranking(con: sqlite3.Connection, *, ano: str | None = None, minimo_cnpj: int = 5,
            limite: int = 20) -> list[dict]:
    """UGs ordenadas pelo quanto o agrupamento MUDA a leitura — não pelo HHI absoluto."""
    g = montar_grupos(con)
    try:
        ugs = [r[0] for r in con.execute(
            "SELECT ug_emitente FROM ob_orcamentaria_siafe WHERE valor > 0 "
            "GROUP BY ug_emitente HAVING COUNT(DISTINCT credor) >= ?", (minimo_cnpj,))]
    except sqlite3.OperationalError:
        return []
    fora = []
    for ug in ugs:
        r = concentracao_da_ug(con, ug, grupos=g, ano=ano)
        if r.get("estado") == "medido" and r["n_cnpj"] >= minimo_cnpj:
            fora.append(r)
    fora.sort(key=lambda d: (-d["delta_hhi"], -d["hhi_por_grupo"]))
    return fora[:limite]


_RESSALVA = (
    "Grupo econômico de fato NÃO é ilícito: holding, franquia e sócio investidor são lícitos. O "
    "achado é a CONCENTRAÇÃO que não aparecia na medição por CNPJ, e o que ela pede é diligência, "
    "nunca imputação. O agrupamento vem do QSA (pessoa que consta em dois ou mais fornecedores) e "
    "carrega as limitações dele — inclusive a máscara de CPF, que não é identidade. Valores são de "
    "Ordem Bancária: empenho não é pagamento."
)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Concentração por grupo econômico de fato")
    ap.add_argument("--ug")
    ap.add_argument("--ano")
    ap.add_argument("--ranking", action="store_true")
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    try:
        if a.ug:
            print(json.dumps(concentracao_da_ug(con, a.ug, ano=a.ano),
                             ensure_ascii=False, indent=2))
        else:
            for r in ranking(con, ano=a.ano):
                print(f"UG {r['ug']}: HHI cnpj {r['hhi_por_cnpj']:.3f} → grupo "
                      f"{r['hhi_por_grupo']:.3f} (delta {r['delta_hhi']:+.3f}) · "
                      f"{r['n_cnpj']} CNPJ em {r['n_grupo']} grupos · "
                      f"sem QSA {r['cobertura_qsa']['fracao_sem_qsa']:.0%}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
