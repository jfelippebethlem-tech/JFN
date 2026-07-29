# -*- coding: utf-8 -*-
"""Perfil de INTERPOSIÇÃO (laranja) — o sócio que não é o dono.

O QUE ESTE MÓDULO RESPONDE. `empresa_fantasma` mede a EMPRESA (endereço, capital, CNAE, idade).
Falta o outro lado da mesma fraude: a PESSOA posta no quadro societário para que o dono real não
apareça. É o vetor que sustenta tanto o direcionamento (o sócio da vencedora é ligado a quem
decidiu) quanto o cartel (a "concorrente" pertence ao mesmo grupo).

OS EIXOS, e o dado que cada um tem nesta casa:

  1. **idade extrema** — `socios_receita.faixa_etaria` (código RFB). Sócio de até 20 anos ou acima
     de 80 num quadro que contrata com o poder público é a assinatura clássica. Medido na base:
     11 sócios na faixa 1 (0–12 anos) e 130 na faixa 2 (13–20).
  2. **multiplicidade** — o mesmo sócio em muitas empresas. Sozinho NÃO é sinal: administrador
     profissional, contador e sócio de holding aparecem em dezenas. Entra por PERCENTIL da própria
     base, não por número absoluto escolhido a dedo.
  3. **entrada recente** — `socios_receita.data_entrada` próxima da data do certame. Trocar o
     quadro às vésperas é o que a linha do tempo (`osint/timeline`) já sabe ler; aqui vira eixo
     de perfil da pessoa.
  4. **servidor público** — o sócio consta na folha. Não é reimplementado: delega a
     `cruzamentos_intel.socio_servidor`, que já casa nome + fragmento de CPF com as janelas
     desalinhadas das duas máscaras (RFB mostra D4–D9, a folha D3–D8) e já descarta homônimo.
  5. **quadro raso** — empresa com um único sócio pessoa física e nenhuma outra ligação.

O QUE FICA DECLARADO FORA. "Sócio com endereço igual ao da empresa" exige endereço de pessoa
FÍSICA, que a base aberta não traz; e "sócio em setores díspares" exige CNAE por empresa, que
`empresas_min` não tem (só natureza jurídica). Preencher esses eixos com proxy seria inventar
sinal — ficam como lacuna nomeada, e o resultado declara que o perfil foi medido em 3 de 5 eixos
quando é o caso.

A ARMADILHA MEDIDA, e ela é grande: **o CPF mascarado não é identidade**. Na base, 977 dos 24.448
documentos mascarados carregam mais de um nome — 4% de colisão pura. Por isso a chave da pessoa
aqui é o par (documento, nome normalizado), nunca o documento sozinho, e mesmo assim o resultado
sai como pista para conferência com CPF completo, jamais como afirmação sobre pessoa determinada.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

# Códigos de faixa etária da RFB. 0 = "não se aplica" (sócio pessoa jurídica) — NÃO é idade zero,
# e tratá-lo como tal produziria um exército de falsos "sócios recém-nascidos".
FAIXA_RFB = {"0": "não se aplica (PJ)", "1": "0 a 12 anos", "2": "13 a 20 anos",
             "3": "21 a 30 anos", "4": "31 a 40 anos", "5": "41 a 50 anos",
             "6": "51 a 60 anos", "7": "61 a 70 anos", "8": "71 a 80 anos", "9": "mais de 80"}
# MEDIDO NA BASE (44.571 sócios), e a medição mudou o desenho: sócio de 0–12 anos é 0,02% e de
# 13–20 é 0,29% — raridade que sustenta indício. Já "mais de 80" é 1,87%: dono idoso de empresa
# familiar é o funcionamento normal, e tratá-lo como o mesmo sinal que um sócio de 10 anos enchia
# o topo do ranking de fundadores. Fica como OBSERVAÇÃO que corrobora, nunca como eixo aceso.
FAIXAS_JOVEM = {"1", "2"}
FAIXAS_IDOSO = {"9"}
PREVALENCIA_MEDIDA = {"0 a 12 anos": 0.0002, "13 a 20 anos": 0.0029, "mais de 80": 0.0187,
                      "quadro de um só sócio": 0.549, "multiplicidade acima do corte": 0.0102}

PERCENTIL_MULTIPLICIDADE = 0.99   # o corte sai da própria base, não de número escolhido a dedo
MULTIPLO_DA_MEDIANA = 3           # e exige CAUDA: percentil sozinho marca todo mundo se a base é achatada
MINIMO_EMPRESAS = 3               # piso: "atípico" com 2 empresas não é atípico em lugar nenhum
DIAS_ENTRADA_RECENTE = 90         # entrada de sócio às vésperas do ato

# `quadro_raso` NÃO está aqui de propósito: 54,9% das empresas da base têm um só sócio. Um "eixo"
# que acende na maioria mede a base, não a anomalia — foi o que produziu 2.187 achados `fraco` em
# 4.000 quadros na primeira calibração, e é a mesma lição que já custou o P1 (71% dos certames).
EIXOS = ("idade_extrema", "multiplicidade", "entrada_recente", "servidor")


def _norm(s: Any) -> str:
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", t)).strip()


def _dia(s: Any) -> str:
    """Data da RFB (`AAAAMMDD` ou `AAAA-MM-DD`) em ISO; '' quando ilegível."""
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) != 8:
        return ""
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def corte_multiplicidade(con: sqlite3.Connection,
                         percentil: float = PERCENTIL_MULTIPLICIDADE) -> dict[str, Any]:
    """Quantas empresas por sócio já é atípico NESTA base.

    Corte absoluto ("sócio em 5+ empresas") transforma contador e administrador profissional em
    suspeito; o percentil acompanha o mercado que a base de fato contém.
    """
    try:
        ns = [r[0] for r in con.execute(
            "SELECT COUNT(DISTINCT cnpj_basico) FROM socios_reverso "
            "WHERE COALESCE(doc_socio,'') <> '' GROUP BY doc_socio, nome_norm")]
    except sqlite3.OperationalError:
        return {"corte": None, "n_socios": 0, "motivo": "tabela socios_reverso ausente"}
    if not ns:
        return {"corte": None, "n_socios": 0, "motivo": "base vazia"}
    ns.sort()
    p99 = ns[min(len(ns) - 1, int(len(ns) * percentil))]
    mediana = ns[len(ns) // 2]
    # As três condições juntas, e não o percentil sozinho: numa base achatada (todo sócio com o
    # mesmo número de empresas) o percentil 99 É esse número, e marcaria TODO MUNDO como atípico.
    # Testado — foi exatamente o defeito que a suíte pegou na primeira versão deste módulo.
    corte = max(p99, mediana * MULTIPLO_DA_MEDIANA, MINIMO_EMPRESAS)
    return {"corte": corte, "n_socios": len(ns), "percentil": percentil,
            "p99": p99, "mediana": mediana, "maximo": ns[-1],
            "regra": (f"atípico = acima do percentil {percentil:.0%} ({p99}), de pelo menos "
                      f"{MULTIPLO_DA_MEDIANA}× a mediana ({mediana}) e nunca abaixo de "
                      f"{MINIMO_EMPRESAS} empresas")}


def _socios_da_empresa(con: sqlite3.Connection, cnpj: str) -> list[dict]:
    basico = re.sub(r"\D", "", cnpj or "")[:8]
    if len(basico) != 8:
        return []
    try:
        return [dict(r) for r in con.execute(
            "SELECT nome_socio, nome_norm, doc_socio, qualificacao_txt, data_entrada, faixa_etaria "
            "FROM socios_receita WHERE cnpj_basico = ?", (basico,))]
    except sqlite3.OperationalError:
        return []


def perfil_socio(con: sqlite3.Connection, socio: dict, *, corte: int | None = None,
                 data_referencia: str | None = None,
                 servidores: set[str] | None = None) -> dict[str, Any]:
    """Eixos de interposição de UMA pessoa. Eixo sem dado sai `None`, nunca `False`.

    A diferença importa: `False` afirma que o sinal foi procurado e não existe; `None` diz que não
    foi possível olhar. Colapsar os dois é a origem do "0 achado" que mente.
    """
    doc, nome = str(socio.get("doc_socio") or ""), _norm(socio.get("nome_socio"))
    faixa = str(socio.get("faixa_etaria") or "")
    eixos: dict[str, Any] = {}
    evid: list[str] = []

    idade_avancada = False
    if faixa and faixa in FAIXA_RFB and faixa != "0":
        eixos["idade_extrema"] = faixa in FAIXAS_JOVEM
        idade_avancada = faixa in FAIXAS_IDOSO
        if eixos["idade_extrema"]:
            evid.append(f"sócio na faixa etária {FAIXA_RFB[faixa]} "
                        f"({PREVALENCIA_MEDIDA.get(FAIXA_RFB[faixa], 0):.2%} da base)")
        elif idade_avancada:
            evid.append(f"sócio com {FAIXA_RFB[faixa]} — observação, não indício: é 1,87% da base")
    else:
        eixos["idade_extrema"] = None

    if corte and doc and nome:
        n = con.execute("SELECT COUNT(DISTINCT cnpj_basico) FROM socios_reverso "
                        "WHERE doc_socio = ? AND nome_norm = ?", (doc, nome)).fetchone()[0]
        eixos["multiplicidade"] = n >= corte
        if n >= corte:
            evid.append(f"consta em {n} empresas (atípico acima de {corte} nesta base)")
    else:
        eixos["multiplicidade"] = None

    entrada = _dia(socio.get("data_entrada"))
    if entrada and data_referencia:
        from datetime import date
        try:
            d1, d2 = date.fromisoformat(entrada), date.fromisoformat(data_referencia[:10])
            dias = (d2 - d1).days
            eixos["entrada_recente"] = 0 <= dias <= DIAS_ENTRADA_RECENTE
            if eixos["entrada_recente"]:
                evid.append(f"entrou no quadro {dias} dias antes da data de referência")
        except ValueError:
            eixos["entrada_recente"] = None
    else:
        eixos["entrada_recente"] = None

    if servidores is None:
        eixos["servidor"] = None
    else:
        eixos["servidor"] = nome in servidores
        if eixos["servidor"]:
            evid.append("nome consta em folha de pagamento pública (conferir CPF completo)")

    return {"nome": socio.get("nome_socio"), "doc": doc, "qualificacao": socio.get("qualificacao_txt"),
            "faixa_etaria": FAIXA_RFB.get(faixa, ""), "data_entrada": entrada,
            "idade_avancada": idade_avancada, "eixos": eixos, "evidencias": evid}


def avaliar(con: sqlite3.Connection, cnpj: str, *, data_referencia: str | None = None,
            servidores: set[str] | None = None, corte: int | None = None) -> dict[str, Any]:
    """Perfil de interposição do quadro societário de uma empresa.

    O grau NÃO soma eixos: conta quantos ACENDERAM sobre quantos foram OLHADOS. Um eixo aceso de
    um olhado não é o mesmo indício que um aceso de cinco, e a razão é o que separa os dois.
    """
    socios = _socios_da_empresa(con, cnpj)
    if not socios:
        return {"cnpj": cnpj, "grau": "nao_aferivel", "socios": [], "n_socios": 0,
                "motivo": "quadro societário não consta na base (RFB ingerida é parcial)",
                "ressalva": _RESSALVA}

    # `corte` é da BASE, não da empresa: num sweep, calcule uma vez e passe adiante.
    if corte is None:
        corte = corte_multiplicidade(con).get("corte")
    perfis = [perfil_socio(con, s, corte=corte, data_referencia=data_referencia,
                           servidores=servidores) for s in socios]

    pf = [p for p in perfis if len(re.sub(r"\D", "", p["doc"])) != 14]
    # Característica declarada, NÃO eixo: 54,9% das empresas têm um só sócio.
    quadro_raso = len(pf) == 1 and len(socios) == 1

    acesos = sum(1 for p in perfis for v in p["eixos"].values() if v is True)
    olhados = sum(1 for p in perfis for v in p["eixos"].values() if v is not None)

    if not olhados:
        grau = "nao_aferivel"
    elif acesos == 0:
        grau = "sem_sinal"
    elif acesos == 1:
        grau = "fraco"
    elif acesos >= 3 or (acesos >= 2 and any(p["eixos"].get("idade_extrema") for p in perfis)):  # noqa: E501
        grau = "forte"
    else:
        grau = "medio"

    return {"cnpj": cnpj, "grau": grau, "socios": perfis, "n_socios": len(socios),
            "quadro_raso": quadro_raso, "eixos_acesos": acesos, "eixos_olhados": olhados,
            "eixos_possiveis": len(EIXOS),
            "lacunas": ["endereço do sócio (base aberta não traz endereço de pessoa física)",
                        "setores díspares (CNAE por empresa ausente em empresas_min)"],
            "corte_multiplicidade": corte,
            "ressalva": _RESSALVA}


_RESSALVA = (
    "O CPF vem MASCARADO nas duas fontes e não é identidade: nesta base, 977 de 24.448 documentos "
    "mascarados carregam mais de um nome (4% de colisão). A chave usada é o par (documento, nome), "
    "e ainda assim o resultado é PISTA para conferência com CPF completo — nunca afirmação sobre "
    "pessoa determinada. Sócio quotista sem gerência pode ser lícito; interposição é indício de "
    "quem NÃO aparece, e a prova exige o beneficiário final."
)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Perfil de interposição (laranja) por CNPJ")
    ap.add_argument("cnpj")
    ap.add_argument("--data", help="data de referência (certame/contrato), AAAA-MM-DD")
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        print(json.dumps(avaliar(con, a.cnpj, data_referencia=a.data),
                         ensure_ascii=False, indent=2))
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
