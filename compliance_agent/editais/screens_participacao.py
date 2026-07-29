# -*- coding: utf-8 -*-
"""Screens de PARTICIPAÇÃO — quem concorre com quem, e quem só faz número.

POR QUE ISTO SÓ FOI POSSÍVEL AGORA. `cruzamentos_intel.perdedoras_contumazes` já responde a
pergunta, mas sobre as atas extraídas do SEI — que são poucas. Com `tcerj_licitante` (dados
abertos do TCE-RJ), a mesma leitura passa a ter milhares de certames municipais com vencedor E
perdedores nominados. Este módulo é o complemento estrutural, não o substituto.

OS TRÊS SCREENS, e a estatística que cada um exige:

  1. **PERDEDORA CONTUMAZ** — participa muito e nunca vence. Sozinho, o sinal é fraco: empresa
     pequena que disputa e perde é o funcionamento normal do mercado. O que informa é a
     COMBINAÇÃO com o par (item 2).
  2. **PAR DE COBERTURA** — o vencedor A e o perdedor B aparecem juntos muito mais do que o acaso
     explicaria. Aqui está o cuidado que faz a diferença: **co-ocorrência bruta não significa
     nada**. Duas empresas do mesmo ramo, no mesmo município, vão se encontrar. A medida certa é
     o LIFT — o quanto a co-ocorrência observada supera a esperada se as participações fossem
     independentes. Lift 1,0 é o acaso; o screen exige bem mais que isso E um número mínimo de
     encontros, porque lift alto sobre 2 certames é ruído.
  3. **RODÍZIO** — dentro de um ente e de uma tipologia, os mesmos poucos nomes se alternam na
     vitória. Concentração alta com alternância é a assinatura clássica; concentração alta SEM
     alternância é monopólio de mercado, que é outro problema (e outra peça).

A LIMITAÇÃO QUE ACOMPANHA TUDO. A fonte identifica o participante por NOME, não por CNPJ.
Homonímia e variação de grafia ("LTDA" × "LTDA."), portanto, contaminam qualquer agregação — o
módulo normaliza o nome e DECLARA que o resultado é pista, não prova. Enriquecer por CNPJ é passo
separado, e enquanto não existir, nenhum destes screens sustenta afirmação sobre pessoa jurídica
determinada.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

# Mínimos para o sinal existir. Abaixo disso é anedota, e anedota com número parece medição.
MIN_PARTICIPACOES = 5      # perdedora contumaz
MIN_ENCONTROS_PAR = 4      # par vencedor×perdedor
LIFT_MINIMO = 3.0          # co-ocorrência 3× acima do acaso
MIN_CERTAMES_ENTE = 10     # rodízio
HHI_CONCENTRADO = 0.25     # Herfindahl de vitórias por ente/tipologia


def normalizar_nome(s: Any) -> str:
    """Forma canônica do participante. Sem CNPJ, é o melhor que se consegue — e não é identidade."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"\b(LTDA|ME|EPP|EIRELI|SA|S/A|S\.A|CIA|COMPANHIA)\b\.?", " ", t)
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _linhas(con: sqlite3.Connection, ano: int | None = None,
            ente: str | None = None) -> list[dict]:
    sql = ["SELECT ente, ano, processo, participante, resultado, tipologia, valor_homologacao "
           "FROM tcerj_licitante WHERE COALESCE(participante,'') <> ''"]
    par: list[Any] = []
    if ano:
        sql.append("AND ano = ?")
        par.append(int(ano))
    if ente:
        sql.append("AND ente = ?")
        par.append(ente)
    try:
        return [dict(r) for r in con.execute(" ".join(sql), par)]
    except sqlite3.OperationalError:
        return []


def _por_certame(linhas: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for x in linhas:
        chave = (x["ente"], x["ano"], x["processo"])
        d = out.setdefault(chave, {"vencedores": set(), "perdedores": set(),
                                   "tipologia": x.get("tipologia") or ""})
        nome = normalizar_nome(x["participante"])
        if not nome:
            continue
        (d["vencedores"] if str(x.get("resultado")).upper() == "VENCEDOR"
         else d["perdedores"]).add(nome)
    return out


_RESSALVA = ("Participante identificado por NOME, não por CNPJ: homonímia e variação de grafia "
             "contaminam a agregação. Resultado é PISTA para conferência, não prova sobre pessoa "
             "jurídica determinada. Cobertura MUNICIPAL (jurisdicionados do TCE-RJ).")


def perdedoras_contumazes(con: sqlite3.Connection, *, ano: int | None = None,
                          ente: str | None = None,
                          min_participacoes: int = MIN_PARTICIPACOES) -> dict[str, Any]:
    """Participa muito e nunca vence. Sinal FRACO isolado — informa junto com o par de cobertura."""
    certames = _por_certame(_linhas(con, ano, ente))
    participacoes: dict[str, int] = {}
    vitorias: dict[str, int] = {}
    for d in certames.values():
        for nome in d["vencedores"] | d["perdedores"]:
            participacoes[nome] = participacoes.get(nome, 0) + 1
        for nome in d["vencedores"]:
            vitorias[nome] = vitorias.get(nome, 0) + 1

    achados = [
        {"participante": nome, "participacoes": n, "vitorias": vitorias.get(nome, 0)}
        for nome, n in participacoes.items()
        if n >= min_participacoes and vitorias.get(nome, 0) == 0
    ]
    achados.sort(key=lambda d: -d["participacoes"])
    return {"achados": achados, "n": len(achados), "n_certames": len(certames),
            "min_participacoes": min_participacoes,
            "nivel": "fraco",
            "motivo": ("empresa que disputa e perde é o funcionamento normal do mercado — este "
                       "screen só informa combinado ao par de cobertura"),
            "ressalva": _RESSALVA}


def pares_cobertura(con: sqlite3.Connection, *, ano: int | None = None, ente: str | None = None,
                    min_encontros: int = MIN_ENCONTROS_PAR,
                    lift_minimo: float = LIFT_MINIMO) -> dict[str, Any]:
    """Pares (vencedor, perdedor) que se encontram MUITO acima do acaso.

    O lift é o que separa sinal de vizinhança de mercado: `observado / esperado`, onde o esperado
    supõe participações independentes. Co-ocorrência bruta colocaria no topo justamente as
    empresas grandes, que aparecem em tudo.
    """
    certames = _por_certame(_linhas(con, ano, ente))
    n_certames = len(certames) or 1
    participa: dict[str, int] = {}
    for d in certames.values():
        for nome in d["vencedores"] | d["perdedores"]:
            participa[nome] = participa.get(nome, 0) + 1

    encontros: dict[tuple[str, str], int] = {}
    for d in certames.values():
        for v in d["vencedores"]:
            for p in d["perdedores"]:
                if v != p:
                    encontros[(v, p)] = encontros.get((v, p), 0) + 1

    achados = []
    for (v, p), n in encontros.items():
        if n < min_encontros:
            continue
        esperado = (participa.get(v, 0) * participa.get(p, 0)) / n_certames
        if esperado <= 0:
            continue
        lift = n / esperado
        if lift < lift_minimo:
            continue
        achados.append({
            "vencedor": v, "perdedor": p, "encontros": n,
            "esperado": round(esperado, 2), "lift": round(lift, 2),
            "vitorias_do_perdedor_contra_outros": 0,
            "texto": (f"{v} venceu e {p} perdeu no mesmo certame {n} vez(es); o acaso explicaria "
                      f"{esperado:.1f} — lift {lift:.1f}×"),
        })
    achados.sort(key=lambda d: (-d["lift"], -d["encontros"]))
    return {"achados": achados, "n": len(achados), "n_certames": len(certames),
            "min_encontros": min_encontros, "lift_minimo": lift_minimo,
            "nivel": "medio" if achados else None,
            "motivo": ("co-ocorrência acima do acaso entre quem ganha e quem perde é a assinatura "
                       "da proposta de cobertura; lift alto sobre poucos encontros é ruído, e por "
                       f"isso o mínimo de {min_encontros} encontros"),
            "ressalva": _RESSALVA}


def rodizio(con: sqlite3.Connection, *, ano: int | None = None, ente: str | None = None,
            min_certames: int = MIN_CERTAMES_ENTE) -> dict[str, Any]:
    """Concentração de vitórias por ente+tipologia, separando rodízio de monopólio.

    Concentração alta COM alternância é a assinatura do rodízio; concentração alta SEM alternância
    é mercado concentrado — outro problema, outra peça. Confundir os dois transforma fornecedor
    único legítimo em suspeito.
    """
    certames = _por_certame(_linhas(con, ano, ente))
    grupos: dict[tuple, list[str]] = {}
    for (ente_k, _ano, _proc), d in certames.items():
        for v in d["vencedores"]:
            grupos.setdefault((ente_k, d["tipologia"]), []).append(v)

    achados = []
    for (ente_k, tipologia), vencedores in grupos.items():
        n = len(vencedores)
        if n < min_certames:
            continue
        contagem: dict[str, int] = {}
        for v in vencedores:
            contagem[v] = contagem.get(v, 0) + 1
        hhi = sum((c / n) ** 2 for c in contagem.values())
        distintos = len(contagem)
        # Alternância: trocas de vencedor entre certames consecutivos, normalizada.
        trocas = sum(1 for a, b in zip(vencedores, vencedores[1:]) if a != b)
        alternancia = trocas / max(1, n - 1)
        if hhi < HHI_CONCENTRADO:
            continue
        rodiziando = distintos >= 2 and alternancia >= 0.5
        achados.append({
            "ente": ente_k, "tipologia": tipologia, "n_certames": n,
            "vencedores_distintos": distintos, "hhi": round(hhi, 3),
            "alternancia": round(alternancia, 3),
            "classe": "rodizio" if rodiziando else "concentracao",
            "nivel": "medio" if rodiziando else "fraco",
            "texto": ((f"{distintos} vencedores se alternam em {n} certames de '{tipologia}' em "
                       f"{ente_k} (HHI {hhi:.2f}, alternância {alternancia:.0%}) — assinatura de "
                       f"rodízio") if rodiziando else
                      (f"{distintos} vencedor(es) concentram {n} certames de '{tipologia}' em "
                       f"{ente_k} (HHI {hhi:.2f}) SEM alternância — mercado concentrado, que é "
                       f"outro problema e outra peça")),
        })
    achados.sort(key=lambda d: (d["classe"] != "rodizio", -d["hhi"]))
    return {"achados": achados, "n": len(achados),
            "n_rodizio": sum(1 for a in achados if a["classe"] == "rodizio"),
            "min_certames": min_certames, "hhi_minimo": HHI_CONCENTRADO,
            "ressalva": _RESSALVA}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Screens de participação (licitantes TCE-RJ)")
    ap.add_argument("--ano", type=int)
    ap.add_argument("--ente")
    ap.add_argument("--screen", choices=("perdedoras", "pares", "rodizio"), default="pares")
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        fn = {"perdedoras": perdedoras_contumazes, "pares": pares_cobertura,
              "rodizio": rodizio}[a.screen]
        r = fn(con, ano=a.ano, ente=a.ente)
        r["achados"] = r["achados"][:25]
        print(json.dumps(r, ensure_ascii=False, indent=2))
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
