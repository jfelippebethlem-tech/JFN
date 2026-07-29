# -*- coding: utf-8 -*-
"""Conjunto-ouro de vereditos jurídicos, extraído do acervo oficial do TCU.

POR QUE ESTE MÓDULO EXISTE. A casa mede muita coisa e não media a única que importa para o eixo
não-determinístico: **o veredito jurídico da IA acerta?** `tests/golden/` trava FORMATO de
relatório; `eval_groundtruth.py` mede o motor determinístico contra punições do TCE-RJ;
`tools/bench_modelos.py` mede honestidade do modelo. Nenhum deles diz se o grau verde/amarelo/
vermelho de direcionamento bate com o que um tribunal decidiria. `LEARNING.md` exige o contrário
("só promove o que sobrevive out-of-sample"), e sem corpus rotulado essa exigência é retórica.

A IDEIA. O rótulo não precisa ser opinado: o TCU já publica a tese decidida, em uma frase, na
Jurisprudência Selecionada — 17.510 enunciados já indexados em `data/tcu_juris.db`. A polaridade
da frase É o rótulo:

    "É irregular a exigência de ..."      → a conduta descrita é VÍCIO
    "Não é obrigatório que ..."           → a conduta é LÍCITA
    "A Administração deve ..."            → a OMISSÃO é vício
    "O sobrepreço é desqualificado ..."   → tese EXCULPATÓRIA (lícito), valiosa para o refutador

Rótulo derivado de texto tem de declarar a regra que o produziu e guardar o trecho — é o que
`classificar_enunciado` devolve. Enunciado sem polaridade clara NÃO recebe rótulo e sai do
conjunto: corpus contaminado mede errado com aparência de rigor.

O QUE ESTE MÓDULO NÃO FAZ. Não infere vício por semelhança semântica. O mapa tema→vício é
explícito e fechado (`MAPA_TEMA_VICIO`); tema fora do mapa devolve `None` e o caso não entra.
Chutar o enquadramento produziria um conjunto-ouro que mede a nossa própria imaginação.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator

DB_PADRAO = Path("data/tcu_juris.db")

POLARIDADES = ("veda", "admite", "dever", "indefinida")
ROTULOS: dict[str, str | None] = {
    "veda": "vicio",
    "admite": "licito",
    "dever": "vicio_por_omissao",
    "indefinida": None,
}

# ── polaridade, calibrada sobre as construções REAIS do acervo ────────────────────────────────
# As frequências vieram de contar os inícios de enunciado das áreas Licitação e Contrato
# Administrativo: "é irregular a exigência" (50), "é ilegal a exigência" (38), "é indevida a
# exigência" (17), "a administração deve abster-se" (9), "é vedada a exigência" (8)…

# "deve abster-se de X" / "não deve X" contêm o verbo de dever mas VEDAM — testados primeiro.
_RE_ABSTENCAO = re.compile(
    r"\bdeve[m]?\s+(?:se\s+)?abster|\bn[ãa]o\s+deve[m]?\b|\bdeve[m]?\s+evitar|"
    r"\b[ée]\s+defeso\b", re.I)
_RE_VEDA = re.compile(
    r"\b[ée]\s+(?:irregular|ileg[ai]l|indevid[ao]|vedad[ao]|inadmiss[íi]vel|nul[ao]|"
    r"impr[óo]pri[ao]|incab[íi]vel)\b|"
    r"\bn[ãa]o\s+(?:[ée]|s[ãa]o)\s+(?:admit|permit|l[íi]cit|leg[íi]tim|cab[íi]v)|"
    r"\bconfigura\s+(?:irregularidade|ilegalidade|restri[çc][ãa]o\s+indevida)|"
    r"\baf(?:ronta|asta)\s+(?:o\s+)?(?:princ[íi]pio|car[áa]ter\s+competitivo)|"
    r"\b[ée]\s+irregular\b", re.I)
_RE_ADMITE = re.compile(
    r"\b[ée]\s+(?:l[íi]cit[ao]|leg[íi]tim[ao]|regular|admiss[íi]vel|poss[íi]vel|cab[íi]vel|"
    r"v[áa]lid[ao]|permitid[ao]|facultad[ao])\b|"
    r"\bn[ãa]o\s+(?:[ée]|s[ãa]o)\s+(?:obrigat[óo]ri|irregular|ileg[ai]l|vedad|exig[íi]v)|"
    r"\bn[ãa]o\s+configura\b|\b[ée]\s+desqualificad[ao]\b|\bn[ãa]o\s+caracteriza\b|"
    r"\b[ée]\s+facultado\b|\bpode[m]?\s+ser\s+(?:aceit|admitid|dispensad)", re.I)
_RE_DEVER = re.compile(
    r"\bdeve[m]?\b|\b[ée]\s+(?:obrigat[óo]ri[ao]|essencial|imprescind[íi]vel|necess[áa]ri[ao])\b|"
    r"\b[ée]\s+dever\b|\bdever[áa](?:o)?\b|\bcabe\s+[àa]\s+administra[çc][ãa]o\b", re.I)
_RE_CONDICIONAL = re.compile(
    r"\bdesde\s+que\b|\bsalvo\b|\bexceto\b|\bressalvad[ao]\b|\bquando\s+(?:devidamente\s+)?"
    r"justificad|\bcaso\s+(?:exista|haja)\b|\bem\s+car[áa]ter\s+excepcional\b", re.I)


def classificar_enunciado(enunciado: str | None) -> dict[str, Any]:
    """Polaridade da tese e o rótulo que dela decorre.

    Devolve `{polaridade, rotulo, condicionada, regra}`. `regra` diz QUAL construção decidiu —
    rótulo derivado de texto sem a regra que o produziu é inauditável.
    """
    texto = re.sub(r"\s+", " ", enunciado or "").strip()
    if not texto:
        return {"polaridade": "indefinida", "rotulo": None, "condicionada": False,
                "regra": "enunciado vazio"}

    condicionada = bool(_RE_CONDICIONAL.search(texto))
    # A abstenção vem primeiro: "deve abster-se de exigir X" casaria com _RE_DEVER e inverteria
    # o sinal do rótulo — de vedação para dever.
    if _RE_ABSTENCAO.search(texto):
        pol, regra = "veda", "abstenção ('deve abster-se' / 'não deve')"
    elif _RE_VEDA.search(texto):
        pol, regra = "veda", "vedação explícita ('é irregular/ilegal/vedada')"
    elif _RE_ADMITE.search(texto):
        pol, regra = "admite", "licitude explícita ('é lícito' / 'não é obrigatório')"
    elif _RE_DEVER.search(texto):
        pol, regra = "dever", "dever ('deve' / 'é obrigatório')"
    else:
        pol, regra = "indefinida", "nenhuma construção de polaridade reconhecida"
    return {"polaridade": pol, "rotulo": ROTULOS[pol], "condicionada": condicionada,
            "regra": regra}


# ── tema/subtema do TCU → vício do catálogo canônico ──────────────────────────────────────────
# Mapa EXPLÍCITO e fechado. Cobre os temas mais frequentes das áreas Licitação e Contrato
# Administrativo; o que não está aqui devolve None e sai do conjunto-ouro, com a lacuna medida
# por `cobertura()`. Semelhança semântica ficaria mais "completa" e mediria a nossa imaginação.

MAPA_TEMA_VICIO: dict[str, str] = {
    # habilitação e qualificação
    "qualificacao tecnica": "barreira_habilitacao",
    "qualificacao economico-financeira": "barreira_habilitacao",
    "habilitacao de licitante": "barreira_habilitacao",
    "cadastramento": "barreira_habilitacao",
    "qualificacao juridica": "barreira_habilitacao",
    "regularidade fiscal": "barreira_habilitacao",
    # desenho do edital
    "edital de licitacao": "especificacao_dirigida",
    "projeto basico": "planejamento_fachada",
    "planejamento": "planejamento_fachada",
    "parcelamento do objeto": "lote_pacote",
    "licitacao de tecnica e preco": "pontuacao_dirigida",
    "competitividade": "clausula_restritiva_combinada",
    "direito de preferencia": "clausula_restritiva_combinada",
    "vistoria": "visita_tecnica_filtro",
    "publicidade": "publicidade_prazos_minimizados",
    # contratação direta
    "dispensa de licitacao": "contratacao_direta_indevida",
    "inexigibilidade de licitacao": "contratacao_direta_indevida",
    "contratacao direta": "contratacao_direta_indevida",
    # orçamento e preço
    "orcamento estimativo": "sobrepreco_estimativa",
    "pesquisa de precos": "sobrepreco_estimativa",
    "superfaturamento": "jogo_planilha",
    # julgamento
    "proposta": "propostas_cobertura",
    "julgamento": "inabilitacao_seletiva",
    "sancao administrativa": "sancionada_contratada",
    # execução contratual
    "alteracao do contrato": "aditivo_excessivo",
    "prorrogacao de contrato": "prorrogacao_perpetua",
    "registro de precos": "carona_abusiva",
    "fiscalizacao do contrato": "entrega_fantasma",
    "pagamento": "execucao_financeira_anomala",
    "subcontratacao": "sub_rogacao_ilegal",
}

# Subtema desempata quando o tema é largo demais para um vício só.
MAPA_SUBTEMA_VICIO: dict[str, str] = {
    "especificacao do objeto": "especificacao_dirigida",
    "marca": "especificacao_dirigida",
    "atestado de capacidade tecnica": "barreira_habilitacao",
    "capital social": "barreira_habilitacao",
    "visita tecnica": "visita_tecnica_filtro",
    "prazo": "publicidade_prazos_minimizados",
    "superfaturamento": "jogo_planilha",
    "sobrepreco": "sobrepreco_estimativa",
    "servicos continuos": "prorrogacao_perpetua",
    "adesao a ata": "carona_abusiva",
}


def _norm(s: str | None) -> str:
    """Minúsculo e sem acento — o acervo mistura 'Licitação' e 'Licitacao'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def mapear_vicio(tema: str | None, subtema: str | None = None) -> str | None:
    """Vício do catálogo canônico correspondente. `None` = fora do mapa, e o caso não entra."""
    sub = _norm(subtema)
    if sub in MAPA_SUBTEMA_VICIO:
        return MAPA_SUBTEMA_VICIO[sub]
    return MAPA_TEMA_VICIO.get(_norm(tema))


def _citacao(numero: Any, ano: Any, colegiado: str | None) -> str:
    """No formato que `tcu_juris_index.verificar_citacao` e `gate_citacoes` reconhecem."""
    n = int(numero)
    formatado = f"{n:,}".replace(",", ".") if n >= 1000 else str(n)
    return f"Acórdão {formatado}/{int(ano)}-{(colegiado or 'Plenário').strip()}"


def montar_caso(linha: dict) -> dict | None:
    """Um caso do conjunto-ouro, ou `None` se não for rotulável.

    Sai `None` quando o enunciado não tem polaridade OU quando o tema não está no mapa: nas duas
    situações o rótulo seria invenção, e um conjunto-ouro com rótulo inventado é pior que nenhum.
    """
    cls = classificar_enunciado(linha.get("enunciado"))
    if not cls["rotulo"]:
        return None
    vicio = mapear_vicio(linha.get("tema"), linha.get("subtema"))
    if not vicio:
        return None
    return {
        "id": linha.get("key") or _citacao(linha["numero"], linha["ano"], linha.get("colegiado")),
        "fonte": "TCU/Jurisprudência Selecionada",
        "citacao": _citacao(linha["numero"], linha["ano"], linha.get("colegiado")),
        "ano": int(linha["ano"]),
        "orgao_julgador": "TCU",
        "area": linha.get("area") or "",
        "tema": linha.get("tema") or "",
        "subtema": linha.get("subtema") or "",
        "vicio": vicio,
        "rotulo": cls["rotulo"],
        "polaridade": cls["polaridade"],
        "condicionada": cls["condicionada"],
        "regra_do_rotulo": cls["regra"],
        "trecho_ancora": re.sub(r"\s+", " ", linha["enunciado"]).strip(),
        "referencia_legal": linha.get("referencia_legal") or "",
    }


# ── extração em lote ──────────────────────────────────────────────────────────────────────────

AREAS_PADRAO = ("Licitação", "Contrato Administrativo", "Convênio", "Responsabilidade")


def iterar_casos(db: str | Path | None = None,
                 areas: tuple[str, ...] = AREAS_PADRAO) -> Iterator[dict]:
    """Casos rotuláveis do acervo. Índice ausente ⇒ nenhum caso, sem exceção e sem fingir."""
    caminho = Path(db or DB_PADRAO)
    if not caminho.exists():
        return
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        marcas = ",".join("?" * len(areas))
        for linha in con.execute(
                f"SELECT * FROM tcu_acordao WHERE area IN ({marcas})", areas):
            caso = montar_caso(dict(linha))
            if caso:
                yield caso
    except sqlite3.OperationalError:
        return
    finally:
        con.close()


def cobertura(db: str | Path | None = None,
              areas: tuple[str, ...] = AREAS_PADRAO) -> dict:
    """Quanto do acervo virou caso, e POR QUE o resto ficou de fora.

    Cobertura declarada é regra da casa: "300 casos" sem dizer que 1.200 foram descartados por
    tema fora do mapa faz o conjunto parecer representativo quando é enviesado pelo mapa.
    """
    caminho = Path(db or DB_PADRAO)
    resumo = {"total": 0, "casos": 0, "sem_polaridade": 0, "tema_fora_do_mapa": 0,
              "por_rotulo": {}, "por_vicio": {}, "indice_ausente": not caminho.exists()}
    if resumo["indice_ausente"]:
        return resumo
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        marcas = ",".join("?" * len(areas))
        for linha in con.execute(f"SELECT * FROM tcu_acordao WHERE area IN ({marcas})", areas):
            resumo["total"] += 1
            d = dict(linha)
            if not classificar_enunciado(d.get("enunciado"))["rotulo"]:
                resumo["sem_polaridade"] += 1
                continue
            if not mapear_vicio(d.get("tema"), d.get("subtema")):
                resumo["tema_fora_do_mapa"] += 1
                continue
            caso = montar_caso(d)
            resumo["casos"] += 1
            resumo["por_rotulo"][caso["rotulo"]] = resumo["por_rotulo"].get(caso["rotulo"], 0) + 1
            resumo["por_vicio"][caso["vicio"]] = resumo["por_vicio"].get(caso["vicio"], 0) + 1
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return resumo


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Conjunto-ouro de vereditos (TCU)")
    ap.add_argument("--cobertura", action="store_true")
    ap.add_argument("--exportar", help="caminho .jsonl de saída")
    a = ap.parse_args(argv)

    if a.cobertura:
        print(json.dumps(cobertura(), ensure_ascii=False, indent=2))
        return 0
    if a.exportar:
        n = 0
        with open(a.exportar, "w", encoding="utf-8") as fh:
            for caso in iterar_casos():
                fh.write(json.dumps(caso, ensure_ascii=False) + "\n")
                n += 1
        print(f"{n} casos → {a.exportar}")
        return 0
    print(json.dumps(cobertura(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
