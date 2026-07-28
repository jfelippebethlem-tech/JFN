# -*- coding: utf-8 -*-
"""ug_nomes — a SUBORDINAÇÃO de uma UG ao longo do tempo (quem responde por ela em cada ano).

⚠️ LEIA ISTO ANTES DE USAR. Este módulo NÃO diz que nome tem a unidade — para isso existe
`compliance_agent/ugs.py`, que é a fonte canônica e usa `despesa_execucao.nome_ug`, onde o
nome da unidade é ESTÁVEL (UG 133100 é sempre "INST. DE TERRAS E CARTOGR. DO EST. RJ" = ITERJ).

O QUE ESTE MÓDULO MEDE, e por que isso é outra coisa. As Ordens Bancárias rotulam a UG com o
nome do ÓRGÃO SUPERIOR, não da unidade — aprendizado já registrado no `ugs.py` em 2026-06-06.
Esse rótulo MUDA quando a unidade é transferida de secretaria:

    UG 133100 (ITERJ)   2019-2020  INST. DE TERRAS E CARTOGR. DO EST. RJ
                        2021-2022  Secretaria de Estado de Cidades
                        2023       Secretaria de Estado de Infraestrutura e Cidades
                        2024-2026  Secretaria de Estado de Infraestrutura e Obras Públicas

O ITERJ não virou secretaria: ele passou a ser subordinado a ela. Isso importa para controle
externo porque **muda quem responde** — o ordenador de despesas, a autoridade homologadora e a
cadeia de responsabilidade acompanham a subordinação, não o código.

ERRO QUE ESTE CABEÇALHO EXISTE PARA IMPEDIR (cometido aqui em 2026-07-28): ler a troca de
rótulo como "o código foi reaproveitado por outro órgão" e concluir que somar a série mistura
entidades. Não mistura — é a mesma unidade, sob outra secretaria. A confirmação veio de
`despesa_execucao`, que dá um nome só por UG em todo o histórico.

O salto de R$ 369 mil (2021) para R$ 120 milhões (2025) na UG 133100 também NÃO é troca de
entidade; é mudança de perfil de execução da mesma unidade, e quem quiser explicá-lo tem de
olhar o objeto das despesas, não o nome no rótulo.

USO:
    subordinacao("133100", 2023)      -> "Secretaria de Estado de Infraestrutura e Cidades"
    mudou_de_subordinacao("133100", 2019, 2026)   -> True
    alerta_serie("133100", 2019, 2026)            -> aviso pronto para o relatório
"""
from __future__ import annotations

import logging
import os
import sqlite3
from functools import lru_cache

logger = logging.getLogger(__name__)


def _abrir(db: str | None = None) -> sqlite3.Connection:
    caminho = db or os.environ.get("JFN_DB", "data/compliance.db")
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=20)


@lru_cache(maxsize=8)
def _mapa(db: str | None = None) -> dict[tuple[str, int], str]:
    """{(código, exercício): nome} — o nome mais frequente daquela UG naquele ano.

    "Mais frequente" e não "qualquer um" porque o dado tem grafias concorrentes dentro do mesmo
    exercício (abreviação, acento, caixa); a moda é o desempate honesto e estável.
    """
    contagem: dict[tuple[str, int], dict[str, int]] = {}
    try:
        con = _abrir(db)
        for cod, ano, nome, n in con.execute(
            "SELECT ug_codigo, exercicio, ug_nome, COUNT(*) FROM ordens_bancarias "
            "WHERE COALESCE(ug_nome,'') <> '' AND COALESCE(ug_codigo,'') <> '' "
            "GROUP BY ug_codigo, exercicio, ug_nome"
        ):
            try:
                chave = (str(cod).strip(), int(ano))
            except (TypeError, ValueError):
                continue
            contagem.setdefault(chave, {})[str(nome).strip()] = int(n or 0)
        con.close()
    except sqlite3.Error as e:
        logger.warning("mapa de UG indisponível (%s)", str(e)[:90])
        return {}
    return {k: max(v.items(), key=lambda x: (x[1], x[0]))[0] for k, v in contagem.items()}


def subordinacao(codigo: str, exercicio: int | None = None, *, db: str | None = None) -> str | None:
    """Órgão superior sob o qual a UG aparecia NAQUELE exercício. `None` quando não se sabe.

    Para o NOME DA UNIDADE use `compliance_agent.ugs.nome_canonico` — são perguntas diferentes.
    Sem `exercicio`, devolve a subordinação mais recente conhecida.
    """
    cod = str(codigo or "").strip()
    if not cod:
        return None
    mapa = _mapa(db)
    if exercicio is not None:
        return mapa.get((cod, int(exercicio)))
    anos = sorted((a for (c, a) in mapa if c == cod), reverse=True)
    return mapa.get((cod, anos[0])) if anos else None


def historico(codigo: str, *, db: str | None = None) -> list[tuple[int, str]]:
    """[(exercício, nome)] em ordem cronológica — a linha do tempo do código."""
    cod = str(codigo or "").strip()
    return sorted((a, n) for (c, a), n in _mapa(db).items() if c == cod)


def _tokens(nome: str) -> frozenset[str]:
    """Conjunto de palavras significativas do nome, para comparar por CONTENÇÃO.

    Comparar sequência de palavras produzia falso positivo em massa: o mesmo órgão aparece
    truncado no dado ("Assembleia Legislativa" e "Assembleia Legislativa do Rio de Janeiro",
    "Instituto de Pesos e Medidas do RIO" e "...do RJ"). Conjunto + contenção trata truncamento
    e abreviação como o que são — a mesma entidade escrita de dois jeitos.
    """
    import re
    import unicodedata

    t = "".join(ch for ch in unicodedata.normalize("NFD", str(nome or ""))
                if unicodedata.category(ch) != "Mn").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    vazias = {"de", "do", "da", "dos", "das", "e", "estado", "secretaria", "agencia", "fundo",
              "rio", "janeiro", "rj", "est", "governo", "sec"}
    return frozenset(p for p in t.split() if len(p) > 2 and p not in vazias)


def _mesmo_orgao(a: str, b: str) -> bool:
    """Dois nomes designam o mesmo órgão? Contenção de tokens, nos dois sentidos."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return True                      # sem informação não se afirma reestruturação
    return ta <= tb or tb <= ta


def _agrupar_orgaos(nomes) -> list[str]:
    """Colapsa grafias do mesmo órgão; devolve um representante por órgão distinto."""
    grupos: list[list[str]] = []
    for n in sorted(set(nomes), key=len, reverse=True):
        for g in grupos:
            if _mesmo_orgao(n, g[0]):
                g.append(n)
                break
        else:
            grupos.append([n])
    return [g[0] for g in grupos]


def mudancas_no_exercicio(codigo: str, exercicio: int,
                          *, db: str | None = None) -> list[dict]:
    """Órgãos superiores distintos sob os quais a UG apareceu DENTRO de um mesmo exercício.

    Reestruturação vem por decreto e não espera a virada do ano. Medido em 2026-07-28: a UG
    135300 designou, em 2025, tanto a Secretaria de Desenvolvimento Regional/Pesca quanto a
    EMATER — entidades distintas, no mesmo exercício. Um mapa por (código, ano) que devolve a
    MODA esconderia isso, que é justamente o caso em que somar o ano inteiro está errado.

    Devolve [] quando o ano é homogêneo — o caso normal.
    """
    linhas: dict[str, list[str]] = {}
    try:
        con = _abrir(db)
        for nome, data in con.execute(
            "SELECT ug_nome, MIN(data_emissao) FROM ordens_bancarias "
            "WHERE ug_codigo = ? AND exercicio = ? AND COALESCE(ug_nome,'') <> '' "
            "GROUP BY ug_nome", (str(codigo).strip(), int(exercicio))
        ):
            linhas.setdefault(str(nome).strip(), []).append(str(data or ""))
        con.close()
    except (sqlite3.Error, TypeError, ValueError):
        return []
    if len(_agrupar_orgaos(linhas)) < 2:
        return []
    return sorted(({"nome": n, "primeira_ob": min(d for d in ds if d) if any(ds) else None}
                   for n, ds in linhas.items() if n in _agrupar_orgaos(linhas)),
                  key=lambda x: (x["primeira_ob"] or ""))


def mudou_de_subordinacao(codigo: str, ano_ini: int, ano_fim: int, *, db: str | None = None) -> bool:
    """A UG trocou de órgão superior no intervalo? Muda quem responde por ela.

    Compara por CONTENÇÃO de tokens, não pelo nome cru: "Secretaria de Estado de
    Desenvolvimento Econômico, Indústria" e "Secretaria de Desenvolvimento Econômico,
    Indústria" são o mesmo órgão escrito de dois jeitos, e acusá-las encheria a saída de ruído.

    Verifica também mudança DENTRO de cada exercício — transferência vem por decreto e não
    espera a virada do ano (a UG 135300 trocou em 2025), e o mapa anual guarda só a moda.
    """
    nomes = [n for a, n in historico(codigo, db=db) if ano_ini <= a <= ano_fim]
    if len(_agrupar_orgaos(nomes)) > 1:
        return True
    # Mudança DENTRO de um exercício não aparece no histórico anual (que guarda a moda) —
    # e é onde a reestruturação por decreto se esconde.
    return any(mudancas_no_exercicio(codigo, a, db=db)
               for a in range(int(ano_ini), int(ano_fim) + 1))


def alerta_serie(codigo: str, ano_ini: int, ano_fim: int, *, db: str | None = None) -> str | None:
    """Aviso pronto para o relatório, ou `None` quando a série é comparável."""
    if not mudou_de_subordinacao(codigo, ano_ini, ano_fim, db=db):
        return None
    linha = historico(codigo, db=db)
    trechos = [f"{a}: {n[:52]}" for a, n in linha if ano_ini <= a <= ano_fim]
    from compliance_agent.ugs import nome_canonico
    unidade = nome_canonico(codigo) or f"UG {codigo}"
    return (f"ⓘ {unidade} trocou de órgão superior entre {ano_ini} e {ano_fim}. A UNIDADE é a "
            f"mesma — a série é somável —, mas a cadeia de responsabilidade (ordenador, "
            f"autoridade homologadora) acompanha a subordinação. Histórico: "
            + " · ".join(trechos))
