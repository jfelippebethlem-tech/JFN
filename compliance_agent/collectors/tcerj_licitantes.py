# -*- coding: utf-8 -*-
"""Licitantes VENCEDORES e PERDEDORES dos certames municipais do RJ (dados abertos do TCE-RJ).

POR QUE ISTO DESTRAVA O EIXO DE DIRECIONAMENTO. Os melhores detectores de julgamento da casa —
J2 (propostas de cobertura), J4 (supressão de propostas / licitante único), J5 (digitais
compartilhadas), J7 (inabilitação seletiva) — dependem da LISTA DE PROPONENTES, e a base tinha
77 linhas em `proposta_item`. Não é falha dos detectores: o registro típico do PNCP traz só o
vencedor, e `indice_certame.py:28-32` já avisava que "1 fornecedor distinto" não prova licitante
único. Sem a lista, todos eles ficam `nao_avaliavel` em massa.

A API de dados abertos do TCE-RJ publica exatamente a lista, certame a certame, com o campo que
resolve a ambiguidade: `QuantidadeParticipante`. Um certame com um participante passa a ser
apurável de verdade, e não inferido pela ausência de registro.

O QUE VEM, e o que NÃO vem — a limitação é estrutural e precisa ficar declarada:

    Ente · Ano · Mes · ProcessoLicitatorio · Participante · Resultado (VENCEDOR|PERDEDOR)
    TipoParticipacao · DataHomologacao · Modalidade · Objeto · QuantidadeParticipante
    ValorHomologacao · ValorEstimado · Tipologia

  · **`Participante` é NOME, não CNPJ.** Cruzar por nome é o caminho da homonímia, que já custou
    correção nesta casa. O grafo de vínculos trata nome sem documento como aresta de força 0,10
    justamente por isso; o enriquecimento por CNPJ é passo separado, e enquanto não existir o
    vínculo entre licitantes vale como PISTA, não como prova.
  · **Cobertura é MUNICIPAL.** São os municípios jurisdicionados ao TCE-RJ. Contratações do
    Estado não estão aqui, e chamar isso de "os certames do RJ" seria erro de cobertura.
  · Não há valor por PROPOSTA: `ValorHomologacao` é do certame, não do lance de cada licitante.
    Isso limita o J2 (screens de dispersão de preço) — que precisa dos lances, não do resultado.
    O que a fonte alimenta bem é licitante único (J4), desconto (J3) e o CRI.

Escreve em tabela própria (`tcerj_licitante`) no banco principal, como os demais coletores.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

BASE_URL = "https://dados.tcerj.tc.br/api/v1"
ROTAS = {"vencedor": ("licitante_vencedor_municipio", "LicitantesVencedores"),
         "perdedor": ("licitante_perdedor_municipio", "LicitantesPerdedores")}
PAGINA = 1000

DDL = """
CREATE TABLE IF NOT EXISTS tcerj_licitante (
    ente TEXT, ano INTEGER, mes INTEGER, processo TEXT,
    participante TEXT, resultado TEXT, tipo_participacao TEXT,
    data_homologacao TEXT, modalidade TEXT, objeto TEXT,
    qtd_participantes INTEGER, valor_homologacao REAL, valor_estimado REAL,
    tipologia TEXT, coletado_em TEXT,
    PRIMARY KEY (ente, ano, processo, participante, resultado)
);
CREATE INDEX IF NOT EXISTS ix_tcerj_lic_proc ON tcerj_licitante(ente, ano, processo);
CREATE INDEX IF NOT EXISTS ix_tcerj_lic_part ON tcerj_licitante(participante);
"""


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalizar(reg: dict, resultado_padrao: str = "") -> dict | None:
    """Registro da API → linha da tabela. `None` quando falta o que identifica o certame.

    Sem `ProcessoLicitatorio` ou sem `Participante` a linha não identifica nada e não pode entrar:
    uma chave incompleta vira duplicata silenciosa na próxima coleta.
    """
    processo = str(reg.get("ProcessoLicitatorio") or "").strip()
    participante = str(reg.get("Participante") or "").strip()
    ente = str(reg.get("Ente") or "").strip()
    if not processo or not participante or not ente:
        return None
    return {
        "ente": ente,
        "ano": _int(reg.get("Ano")),
        "mes": _int(reg.get("Mes")),
        "processo": processo,
        "participante": participante,
        "resultado": str(reg.get("Resultado") or resultado_padrao).strip().upper(),
        "tipo_participacao": str(reg.get("TipoParticipacao") or "").strip(),
        "data_homologacao": str(reg.get("DataHomologacao") or "")[:10],
        "modalidade": str(reg.get("Modalidade") or "").strip(),
        "objeto": str(reg.get("Objeto") or "").strip(),
        "qtd_participantes": _int(reg.get("QuantidadeParticipante")),
        "valor_homologacao": _float(reg.get("ValorHomologacao")),
        "valor_estimado": _float(reg.get("ValorEstimado")),
        "tipologia": str(reg.get("Tipologia") or "").strip(),
    }


def _buscar_http(rota: str, params: dict) -> dict:
    import httpx
    r = httpx.get(f"{BASE_URL}/{rota}", params=params, timeout=120)
    r.raise_for_status()
    dados = r.json()
    if not isinstance(dados, dict):
        # A API já devolveu HTML de erro com status 200 em outros endpoints da casa; um corpo que
        # não é objeto JSON é falha, não resposta vazia (lição do Querido Diário morto em silêncio).
        raise ValueError("resposta não é objeto JSON — provável página de erro com status 200")
    return dados


def coletar(tipo: str, *, ano: int | None = None, municipio: str | None = None,
            limite_total: int | None = None, pagina: int = PAGINA,
            buscar: Callable[[str, dict], dict] | None = None) -> Iterator[dict]:
    """Itera registros normalizados de `vencedor` ou `perdedor`, paginando.

    `buscar` é injetável para teste — nenhum teste desta casa toca a rede.
    """
    if tipo not in ROTAS:
        raise ValueError(f"tipo desconhecido: {tipo!r} (use {tuple(ROTAS)})")
    rota, chave = ROTAS[tipo]
    buscar = buscar or _buscar_http
    inicio, vistos = 0, 0
    while True:
        params: dict[str, Any] = {"inicio": inicio, "limite": pagina}
        if ano:
            params["ano"] = int(ano)
        if municipio:
            params["municipio"] = municipio
        try:
            corpo = buscar(rota, params)
        except Exception as exc:  # noqa: BLE001 — página que falha interrompe, não corrompe
            logger.warning("tcerj_licitantes: página %s de %s falhou: %s", inicio, rota,
                           str(exc)[:120])
            return
        registros = corpo.get(chave) or []
        if not registros:
            return
        for reg in registros:
            linha = normalizar(reg, resultado_padrao=tipo.upper())
            if linha is None:
                continue
            yield linha
            vistos += 1
            if limite_total and vistos >= limite_total:
                return
        if len(registros) < pagina:
            return
        inicio += pagina


def gravar(con: sqlite3.Connection, linhas: Iterable[dict], *, tentativas: int = 8) -> int:
    """Persiste em `tcerj_licitante`. Devolve quantas linhas foram escritas.

    Espera o escritor concorrente sair. O `compliance.db` é compartilhado com o cron `sweep_sei.sh`,
    que mantém transação de escrita aberta por minutos: na coleta de 2026-07-29 a gravação de 2026
    morreu com `database is locked` **depois** de baixar 6.497 linhas de vencedor, e a lista de
    perdedores daquele ano não entrou. Coleta que trunca por lock deixa a base parecendo completa.
    """
    import time
    from datetime import datetime

    con.executescript(DDL)
    agora = datetime.now().isoformat(timespec="seconds")
    dados = [(x["ente"], x["ano"], x["mes"], x["processo"], x["participante"], x["resultado"],
              x["tipo_participacao"], x["data_homologacao"], x["modalidade"], x["objeto"],
              x["qtd_participantes"], x["valor_homologacao"], x["valor_estimado"],
              x["tipologia"], agora) for x in linhas]
    espera = 3.0
    for tentativa in range(1, tentativas + 1):
        try:
            con.executemany(
                "INSERT OR REPLACE INTO tcerj_licitante VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                dados)
            con.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if tentativa == tentativas:
                raise
            logger.warning("base ocupada (tentativa %d/%d); aguardando %.0fs",
                        tentativa, tentativas, espera)
            time.sleep(espera)
            espera = min(espera * 1.8, 60.0)
    return len(dados)


# ── ponte para os detectores e para o CRI ─────────────────────────────────────────────────────

def contexto_certame(con: sqlite3.Connection, ente: str, ano: int, processo: str) -> dict:
    """Monta o contexto de um certame no formato que J4, J3 e o CRI consomem.

    `proponentes_medios_mercado` vem da MESMA tipologia, no mesmo exercício — é o que transforma
    "1 participante" em bandeira ou em monopólio natural. Sem tipologia comparável, o campo sai
    `None` e o CRI marca a bandeira como indisponível em vez de acendê-la no escuro.
    """
    linhas = [dict(r) for r in con.execute(
        "SELECT * FROM tcerj_licitante WHERE ente=? AND ano=? AND processo=?",
        (ente, int(ano), processo))]
    if not linhas:
        return {"certame": processo, "encontrado": False,
                "motivo": "certame não consta da coleta do TCE-RJ"}

    vencedores = [x for x in linhas if x["resultado"] == "VENCEDOR"]
    perdedores = [x for x in linhas if x["resultado"] == "PERDEDOR"]
    ref = vencedores[0] if vencedores else linhas[0]
    tipologia = ref.get("tipologia") or ""

    media_mercado = None
    if tipologia:
        r = con.execute(
            "SELECT AVG(q) FROM (SELECT DISTINCT processo, ente, qtd_participantes q "
            "FROM tcerj_licitante WHERE tipologia=? AND ano=? AND qtd_participantes IS NOT NULL "
            "AND processo<>?)", (tipologia, int(ano), processo)).fetchone()
        media_mercado = r[0] if r and r[0] is not None else None

    # A contagem declarada pela fonte é mais confiável que o número de linhas coletadas: a coleta
    # pode estar parcial, e contar linhas faria certame incompleto parecer certame de licitante
    # único — exatamente o falso positivo que este módulo existe para evitar.
    n_declarado = ref.get("qtd_participantes")
    n_coletado = len({x["participante"] for x in linhas})
    return {
        "certame": processo, "encontrado": True, "ente": ente, "ano": int(ano),
        "objeto": ref.get("objeto"), "modalidade": ref.get("modalidade"),
        "tipologia": tipologia,
        "vencedor": vencedores[0]["participante"] if vencedores else None,
        "perdedores": [x["participante"] for x in perdedores],
        "n_proponentes": n_declarado,
        "n_proponentes_coletados": n_coletado,
        "coleta_completa": (n_declarado is not None and n_coletado >= n_declarado),
        "proponentes_medios_mercado": media_mercado,
        "valor": ref.get("valor_homologacao"),
        "valor_estimado": ref.get("valor_estimado"),
        "desconto": ((ref["valor_estimado"] - ref["valor_homologacao"]) / ref["valor_estimado"]
                     if ref.get("valor_estimado") and ref.get("valor_homologacao") else None),
        "criterio_julgamento": ref.get("modalidade"),
        "aviso_publicado": None,          # a fonte não informa — INDISPONÍVEL, não False
        "dias_publicidade": None,
        "dias_ate_decisao": None,
        "ressalva": ("`participante` é NOME, não CNPJ: cruzamento entre licitantes por nome é "
                     "PISTA, não prova (homonímia). Cobertura MUNICIPAL — o Estado não está "
                     "nesta fonte."),
    }


def certames(con: sqlite3.Connection, *, ano: int | None = None,
             ente: str | None = None) -> list[tuple[str, int, str]]:
    """Chaves `(ente, ano, processo)` dos certames coletados."""
    sql = ["SELECT DISTINCT ente, ano, processo FROM tcerj_licitante WHERE 1=1"]
    par: list[Any] = []
    if ano:
        sql.append("AND ano = ?")
        par.append(int(ano))
    if ente:
        sql.append("AND ente = ?")
        par.append(ente)
    sql.append("ORDER BY ente, ano, processo")
    return [(r[0], r[1], r[2]) for r in con.execute(" ".join(sql), par)]


def ranking_por_ente(con: sqlite3.Connection, *, ano: int | None = None,
                     minimo_certames: int = 10) -> list[dict]:
    """CRI agregado por município — a fila de quem merece auditoria temática.

    É o produto que o `indice_certame` não consegue entregar: aquele índice pontua com o que se
    SABE de cada certame, então um município com edital capturado pontua diferente de um sem, e a
    diferença mede a coleta. Aqui todas as bandeiras vêm do mesmo registro, disponível para todos.

    Municípios abaixo de `minimo_certames` saem na lista com `comparavel=False` em vez de sumirem:
    esconder amostra pequena faz a fila parecer completa quando não é.
    """
    from compliance_agent.editais.cri import agregar

    por_ente: dict[str, list[dict]] = {}
    for ente, a, processo in certames(con, ano=ano):
        ctx = contexto_certame(con, ente, a, processo)
        if ctx.get("encontrado"):
            por_ente.setdefault(ente, []).append(ctx)

    saida = []
    for ente, ctxs in por_ente.items():
        r = agregar(ctxs, minimo_certames=minimo_certames)
        saida.append({"ente": ente, **r})
    # Não comparáveis vão para o fim: aparecem, mas não disputam o topo da fila.
    saida.sort(key=lambda d: (not d.get("comparavel"), -(d.get("cri_medio") or 0)))
    return saida


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse

    from compliance_agent.emendas.db import _DB_PADRAO

    ap = argparse.ArgumentParser(description="Coleta licitantes municipais (TCE-RJ dados abertos)")
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--municipio")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--db", default=str(_DB_PADRAO))
    a = ap.parse_args(argv)

    con = sqlite3.connect(a.db, timeout=60)
    total = 0
    try:
        for tipo in ("vencedor", "perdedor"):
            linhas = list(coletar(tipo, ano=a.ano, municipio=a.municipio, limite_total=a.limite))
            n = gravar(con, linhas)
            print(f"  {tipo}: {n} linhas")
            total += n
    finally:
        con.close()
    print(f"total: {total}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
