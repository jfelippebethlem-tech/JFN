# -*- coding: utf-8 -*-
"""A fonte CANÔNICA de pagamento está truncada, e nada avisava.

A regra nº 2 desta casa é que OB do SIAFE é a verdade sobre pagamento, e o espelho TFE não se usa
para valor. A regra continua certa — mas ela só vale se o SIAFE estiver COMPLETO, e em 2026-08-04
ele não estava: a tela de OB Orçamentária do SIAFE-Rio 2 devolve no máximo **1.000 registros por
consulta**, e uma coleta feita só com `--por-ug` para uma UG grande para exatamente nesse número
sem dizer nada.

Como isso apareceu. Perseguindo um achado C3/C5 do IDESI (CNPJ 28470707000180, INAPTA na Receita,
R$ 92,37 mi pagos), o espelho TFE mostrava R$ 507,75 mi para o mesmo fornecedor — 5,5× o SIAFE.
Todos na UG 294200 (Fundação Saúde). Aí a UG inteira: SIAFE R$ 2,85 bi contra R$ 10,41 bi no
espelho. E na quebra por ano, 2022 e 2023 tinham **exatamente 1.000 OBs** cada.

    23 pares (UG, ano) param em exatamente 1.000 registros, de 642 pares
    outros pares chegam a 6.836 — distribuição natural não empata 23 vezes num número redondo
    nesses 23: SIAFE R$ 8,46 bi · espelho TFE R$ 19,26 bi · 137.654 OBs a menos na fonte canônica

O QUE NÃO É. Não é defeito de código: `siafe_ob_orcamentaria` já tem os três caminhos que furam o
teto (`chkRemoveLimit`, `--por-numero`, `--ug-grande`, com subdivisão por prefixo de Número). É
COLETA INACABADA — as UGs grandes foram varridas com `--por-ug` simples e ninguém as refez.

POR QUE VIRA MÓDULO. Enquanto o truncamento não é medido, ele mente para cima em toda peça que
some valor por UG e para baixo em toda cobertura: a manchete de captura publicada no painel
(universo de R$ 18,06 bi com OB paga) sai de um SIAFE que, nesses 23 pares, conhece menos da
metade do que o espelho registra. INDISPONÍVEL ≠ 0 vale também para a nossa própria coleta.

HONESTIDADE: a comparação com o TFE é indicativa, não aritmética — os dois universos não são
idênticos (há pares com MAIS valor no SIAFE que no espelho, p.ex. 180100/2021). O que prova o
truncamento é o **1.000 exato**, não a diferença; a diferença só dimensiona a ordem de grandeza
do que falta recoletar.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"

TETO_CONSULTA = 1000
"""Teto de registros por consulta da tela de OB Orçamentária (SIAFE-Rio 2). Um par (UG, ano) que
para exatamente nele foi truncado — ver docs/SIAFE-RIO2-GUIA-AUTOMACAO.md §5."""


# Quantos números de OB conferir por par. Amostra, não censo: o objetivo é DETECTAR ausência
# sistemática, e para isso 300 bastam — o censo custaria uma consulta por OB do acervo inteiro.
AMOSTRA_POR_PAR = 300
# Fração da amostra ausente a partir da qual o par é declarado PARCIAL. Medido em 2026-08-09 no
# IDESI/2025: 93% das OBs do espelho não existiam na fonte canônica. Ruído normal entre as duas
# fontes fica muito abaixo disto (há OBs exclusivas dos dois lados).
PISO_AUSENCIA = 0.30


def _parciais_por_numero_de_ob(caminho: Path, ja_truncados: set[tuple[str, str]]) -> list[dict]:
    """Coleta INTERROMPIDA não para num número redondo — e por isso escapa do detector do teto.

    Medido em 2026-08-09: a UG 294200 no exercício de 2025 tem 3.007 linhas (nada de redondo) e,
    ainda assim, **227 das 245 OBs que o espelho conhece para um único credor (93%) não existem na
    fonte canônica**. A causa apareceu no log do dreno no mesmo dia: passadas que terminam em
    `rc=124` (timeout) gravam o que deu tempo e param — deixando uma contagem arbitrária que o
    teste de "parou em 1.000" nunca vê.

    A COMPARAÇÃO POR NÚMERO FOI VERIFICADA antes de virar medida — os dois lados usam o mesmo
    formato (`AAAAOBnnnnn`) e as faixas se sobrepõem. Conferido em 2026-08-09 comparando os
    conjuntos INTEIROS de três pares: 294200/2022 tem **99% de interseção** (coleta completa,
    drenada no mesmo dia), 660100/2025 tem 48% e 266500/2025 tem **1%** — com 235 linhas no SIAFE
    contra 5.021 no espelho. A dúvida inicial veio de amostrar sem `ORDER BY` e cair no topo da
    faixa nos dois lados; o conjunto inteiro desfaz.

    O teste aqui é por IDENTIDADE, não por volume: pega uma amostra de números de OB que o espelho
    registra para o par e pergunta se cada um existe no SIAFE. Comparar totais não serviria — os
    dois universos não são idênticos e há par com mais valor no SIAFE que no espelho, como a nota
    deste módulo já dizia.
    """
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='ordens_bancarias'").fetchone():
            return []
        pares = con.execute(
            "SELECT ug_codigo, substr(data_emissao, 1, 4) ano, COUNT(*) FROM ordens_bancarias "
            "WHERE ug_codigo IS NOT NULL AND numero_ob IS NOT NULL "
            "GROUP BY 1, 2 HAVING COUNT(*) >= 50").fetchall()
        fora = []
        for ug, ano, n_esp in pares:
            chave = (str(ug), str(ano))
            if chave in ja_truncados:
                continue                   # o detector do teto já pegou este
            # DESLOCAMENTO VEM ANTES DO CORTE DE COBERTURA. `numero_ob` é a 1ª coluna e foi gravado
            # certo mesmo na coleta torta, então a amostra de números CASA e o par passa por
            # "coberto" — foi assim que 5 dos 8 pares corrompidos escaparam da primeira versão
            # desta guarda. A pergunta "o dado presta?" é independente de "o dado está lá?".
            # SCHEMA PARCIAL DEGRADA, não derruba: base sem `nome_credor` (fixtures antigas, e
            # qualquer instalação anterior à coluna) não permite julgar deslocamento — e não poder
            # julgar não é o mesmo que julgar limpo. Segue para as outras checagens.
            try:
                n_desloc = con.execute(
                    "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente = ? "
                    "AND substr(data_emissao, 7, 4) = ? "
                    "AND nome_credor GLOB '*[0-9],[0-9][0-9]' "
                    "AND nome_credor NOT GLOB '*[A-Za-z]*'",
                    (str(ug), str(ano))).fetchone()[0]
            except sqlite3.OperationalError:
                n_desloc = 0
            n_no_par = con.execute(
                "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente = ? "
                "AND substr(data_emissao, 7, 4) = ?", (str(ug), str(ano))).fetchone()[0]
            if n_no_par and n_desloc >= n_no_par * 0.9:
                fora.append({
                    "ug": str(ug), "exercicio": str(ano), "estado": "deslocado",
                    "obs_siafe": n_no_par, "obs_deslocadas": n_desloc,
                    "amostra": 0, "ausentes": n_no_par,
                    "pct_ausente": 100.0, "obs_espelho_tfe": n_esp,
                    "recoletar": (f"python -m compliance_agent.siafe_ob_orcamentaria --por-ug {ug} "
                                  f"--exercicio {ano} --ug-grande"),
                })
                continue
            amostra = [r[0] for r in con.execute(
                "SELECT numero_ob FROM ordens_bancarias WHERE ug_codigo = ? "
                "AND substr(data_emissao, 1, 4) = ? AND numero_ob IS NOT NULL LIMIT ?",
                (ug, ano, AMOSTRA_POR_PAR))]
            if not amostra:
                continue
            marcas = ",".join("?" * len(amostra))
            achados = {r[0] for r in con.execute(
                f"SELECT numero_ob FROM ob_orcamentaria_siafe WHERE ug_emitente = ? "
                f"AND numero_ob IN ({marcas})", (str(ug), *amostra))}
            ausentes = len(amostra) - len(achados)
            if ausentes / len(amostra) < PISO_AUSENCIA:
                continue
            # "nunca coletado" e "coletado pela metade" são lacunas diferentes: a primeira é uma
            # UG/ano que a varredura ainda não visitou, a segunda é coleta que MORREU no meio e
            # parece pronta. Rotular tudo de "parcial" esconderia a segunda, que é a perigosa.
            n_siafe = con.execute(
                "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente = ? "
                "AND substr(data_emissao, 7, 4) = ?", (str(ug), str(ano))).fetchone()[0]
            fora.append({
                "ug": str(ug), "exercicio": str(ano),
                "estado": "nunca_coletado" if n_siafe == 0 else "parcial",
                "obs_siafe": n_siafe,
                "amostra": len(amostra), "ausentes": ausentes,
                "pct_ausente": round(100.0 * ausentes / len(amostra), 1),
                "obs_espelho_tfe": n_esp,
                "recoletar": (f"python -m compliance_agent.siafe_ob_orcamentaria --por-ug {ug} "
                              f"--exercicio {ano} --ug-grande"),
            })
        # VARREDURA PRÓPRIA DO DESLOCAMENTO. O laço acima só enxerga pares que o ESPELHO conhece
        # (com 50+ OBs). O espelho não tem 010100 em 2016-2018, então três pares corrompidos ficavam
        # invisíveis — e são justamente os mais antigos, onde ninguém vai olhar. Dado ruim que só o
        # SIAFE tem precisa de uma varredura que parta do SIAFE.
        ja = {(f["ug"], f["exercicio"]) for f in fora}
        try:
            varredura = con.execute(
                "SELECT ug_emitente, substr(data_emissao, 7, 4) ano, "
                "SUM(CASE WHEN nome_credor GLOB '*[0-9],[0-9][0-9]' "
                "         AND nome_credor NOT GLOB '*[A-Za-z]*' THEN 1 ELSE 0 END), COUNT(*) "
                "FROM ob_orcamentaria_siafe GROUP BY 1, 2").fetchall()
        except sqlite3.OperationalError:
            varredura = []            # sem a coluna, não há como medir deslocamento
        for ug, ano, n_desloc, n_par in varredura:
            if not n_par or (n_desloc or 0) < n_par * 0.9 or (str(ug), str(ano)) in ja:
                continue
            fora.append({
                "ug": str(ug), "exercicio": str(ano), "estado": "deslocado",
                "obs_siafe": n_par, "obs_deslocadas": n_desloc,
                "amostra": 0, "ausentes": n_par, "pct_ausente": 100.0,
                "obs_espelho_tfe": 0, "so_no_siafe": True,
                "recoletar": (f"python -m compliance_agent.siafe_ob_orcamentaria --por-ug {ug} "
                              f"--exercicio {ano} --ug-grande"),
            })
        fora.sort(key=lambda d: -d["ausentes"])
        return fora
    except sqlite3.Error:
        return []
    finally:
        con.close()


def estado_do_par(ug: str, ano: str, *, db: str | Path | None = None) -> dict[str, Any]:
    """Cobertura de UM par (UG, exercício) — a versão barata, para usar dentro de rota.

    `medir()` amostra ~800 pares e não cabe num pedido HTTP. Aqui o teste é o mesmo (identidade de
    número de OB contra o espelho), só que num par. Serve para o produto DIZER que o número que
    está mostrando saiu de base incompleta — foi o que faltou quando a concentração da UG 660100
    foi publicada com 57,5% sem avisar que 65% da amostra daquele ano não está na fonte canônica.
    """
    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    if not caminho.exists():
        return {"estado": "indisponivel", "motivo": "compliance.db ausente"}
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        amostra = [r[0] for r in con.execute(
            "SELECT numero_ob FROM ordens_bancarias WHERE ug_codigo = ? "
            "AND substr(data_emissao, 1, 4) = ? AND numero_ob IS NOT NULL LIMIT ?",
            (str(ug), str(ano), AMOSTRA_POR_PAR))]
        n_siafe = con.execute(
            "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente = ? "
            "AND substr(data_emissao, 7, 4) = ?", (str(ug), str(ano))).fetchone()[0]
        if not amostra:
            # sem espelho para comparar não se afirma completude — nem incompletude
            return {"estado": "sem_referencia", "obs_siafe": n_siafe}
        marcas = ",".join("?" * len(amostra))
        achados = con.execute(
            f"SELECT COUNT(DISTINCT numero_ob) FROM ob_orcamentaria_siafe "
            f"WHERE ug_emitente = ? AND numero_ob IN ({marcas})",
            (str(ug), *amostra)).fetchone()[0]
    except sqlite3.Error as exc:
        return {"estado": "indisponivel", "motivo": str(exc)}
    finally:
        con.close()
    ausentes = len(amostra) - achados
    pct = 100.0 * ausentes / len(amostra)
    return {
        "estado": ("nunca_coletado" if n_siafe == 0 else
                   "parcial" if pct >= PISO_AUSENCIA * 100 else "coberto"),
        "obs_siafe": n_siafe, "amostra": len(amostra), "ausentes": ausentes,
        "pct_ausente": round(pct, 1),
    }


def medir(*, db: str | Path | None = None) -> dict[str, Any]:
    """Pares (UG, exercício) cujo total de OBs no SIAFE parou no teto de consulta.

    Devolve a lista dos truncados com o comparativo do espelho TFE (indicativo do que falta), e o
    comando exato que recoleta cada um. Sem a tabela → INDISPONÍVEL declarado, nunca zero.
    """
    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        tem = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('ob_orcamentaria_siafe','ordens_bancarias')")}
        if "ob_orcamentaria_siafe" not in tem:
            return {"ok": True, "indisponivel": True,
                    "motivo": "`ob_orcamentaria_siafe` ausente — sem a fonte canônica não se afere "
                              "o truncamento dela"}
        # data_emissao do SIAFE é TEXTO DD/MM/AAAA: o ano são os 4 últimos, nunca os 4 primeiros.
        try:
            pares = con.execute(
                "SELECT ug_emitente, substr(data_emissao, 7, 4) ano, COUNT(*) n, "
                "       ROUND(COALESCE(SUM(valor), 0), 2) v "
                "FROM ob_orcamentaria_siafe GROUP BY 1, 2").fetchall()
        except sqlite3.OperationalError as exc:
            # esquema diferente do esperado é INDISPONÍVEL declarado, não exceção: quem chama isto
            # (o aviso de piso do vault, o painel) não pode quebrar por causa de uma base parcial.
            return {"ok": True, "indisponivel": True,
                    "motivo": f"`ob_orcamentaria_siafe` com esquema inesperado ({exc})"}
        espelho: dict[tuple[str, str], tuple[int, float]] = {}
        if "ordens_bancarias" in tem:
            for ug, ano, n, v in con.execute(
                    "SELECT ug_codigo, substr(data_emissao, 1, 4) ano, COUNT(*), "
                    "       COALESCE(SUM(valor), 0) FROM ordens_bancarias GROUP BY 1, 2"):
                espelho[(str(ug), str(ano))] = (n, float(v or 0))
    finally:
        con.close()

    truncados = []
    for ug, ano, n, v in pares:
        if n != TETO_CONSULTA:
            continue
        e_n, e_v = espelho.get((str(ug), str(ano)), (0, 0.0))
        truncados.append({
            "ug": str(ug), "exercicio": str(ano),
            "obs_siafe": n, "valor_siafe": v,
            "obs_espelho_tfe": e_n, "valor_espelho_tfe": round(e_v, 2),
            "obs_faltando_ao_menos": max(0, e_n - n),
            "recoletar": (f"python -m compliance_agent.siafe_ob_orcamentaria --por-ug {ug} "
                          f"--exercicio {ano} --ug-grande"),
        })
    truncados.sort(key=lambda t: t["obs_faltando_ao_menos"], reverse=True)
    parciais = _parciais_por_numero_de_ob(caminho, {(str(u), str(a)) for u, a, _, _ in pares
                                                    if _ == TETO_CONSULTA})

    # O NÚMERO DE MANCHETE. Contar pares diz quantas frentes faltam; esta razão diz o TAMANHO do
    # que falta, e é ela que o leitor precisa ver antes de usar qualquer total do SIAFE.
    con2 = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        n_siafe = con2.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0]
        n_esp = con2.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0] if \
            "ordens_bancarias" in tem else 0
    except sqlite3.Error:
        n_siafe = n_esp = 0
    finally:
        con2.close()

    return {
        "ok": True, "indisponivel": False,
        "teto_consulta": TETO_CONSULTA,
        "obs_siafe_total": n_siafe, "obs_espelho_total": n_esp,
        "pct_do_espelho": round(100.0 * n_siafe / n_esp, 1) if n_esp else None,
        "pares_avaliados": len(pares),
        "pares_truncados": len(truncados),
        "obs_faltando_ao_menos": sum(t["obs_faltando_ao_menos"] for t in truncados),
        "valor_siafe_nos_truncados": round(sum(t["valor_siafe"] for t in truncados), 2),
        "valor_espelho_nos_truncados": round(sum(t["valor_espelho_tfe"] for t in truncados), 2),
        "truncados": truncados,
        # SEGUNDO detector: coleta interrompida NÃO para num número redondo. Ver `_parciais…`.
        "pares_parciais": len(parciais),
        "obs_ausentes_por_numero": sum(p["ausentes"] for p in parciais),
        "parciais": parciais,
        "nota": ("O que prova o truncamento é a contagem parar em exatamente "
                 f"{TETO_CONSULTA}, não a diferença para o espelho TFE — os dois universos não são "
                 "idênticos e há pares com mais valor no SIAFE que no espelho. A diferença serve "
                 "só para dimensionar o que falta recoletar. Recoleta pelo caminho que fura o "
                 "teto (`--ug-grande`), que subdivide por prefixo de Número — e só na máquina "
                 "autorizada a falar com o SIAFE (`host_siafe.exigir_autorizacao`), uma sessão "
                 "por IP."),
    }
