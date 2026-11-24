# -*- coding: utf-8 -*-
"""E10 `detectar:<detector>` — detectores genéricos sobre o universo, só onde a E9 deixa (O5.3, fatia 1, SOMBRA ⚖️).

⚖️ SOMBRA. Grava `execucao_regra` + `achado` no contrato único (`dominio/achado.py`, O5.2) num esquema PRÓPRIO do PG
`jfn_evidencias` (padrão `sombra`; ADR-001 linha D3: execucao_regra/achados moram no PG, escritor = E10). Nada aqui
muda o que o painel mostra: nenhuma rota lê o esquema `sombra`, e os detectores entram no registro como Tier 3.

handler(payload, ctx) — chave do job = (detector, escopo):
  · `payload.detector` (ou o sufixo do tipo `detectar:<detector>`) ∈ `aplicacao/detectores.MODULOS`;
    `payload.exercicio` (opcional) é o escopo ('todos' sem ele);
  · lê a coleta bruta SÓ-LEITURA (`mode=ro&immutable=1`; na parada, o snapshot de 24/11 ou o extrato dele conferido
    por md5 na VM-2) e o veredito da E9 (`dominio.elegibilidade`, versão corrente) na exigência que
    `elegibilidade.DETECTORES` declara para o detector — item sem 'E' não entra na régua (invariante 3);
  · converte cada disparo em `Achado` (triagem; INDICIO só com Fato de suporte) e grava de forma IDEMPOTENTE:
    origem `e10:<detector>:<escopo>:<chave>` + versão + sha256 das entradas é único — reexecução sobre a mesma
    entrada grava 0 linha. Uma `execucao_regra` de RESUMO (`…:resumo`, sem achado) guarda universo, determinável,
    cobertura e o que ficou INDISPONÍVEL, com R$ (invariante 2: zero achado nunca é "limpo" sem o denominador);
  · `rodada` = hash determinístico (versão, escopo, versão da E9, hashes das entradas): marca as linhas desta
    execução (a de mesma entrada tem a mesma rodada).
efeito(payload, ctx, resultado) — em OUTRO processo, relê o mundo: (1) recontagem no PG dos achados da rodada =
declarados e o resumo da rodada presente com o mesmo número; (2) amostra sorteada de achados RECALCULADA do zero:
relê da fonte só o grupo do achado (NL, unidade × exercício), aplica a E9 de novo, roda a régua e exige o MESMO
disparo com o MESMO hash de entradas.

CLI:
    python -m compliance_agent.aplicacao.estagios.detectar schema aplicar
    python -m compliance_agent.aplicacao.estagios.detectar rodar --detector e10.ob_antes_da_liquidacao
           [--exercicio 2025] [--fonte <compliance.db só-leitura>] [--amostra 10]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time

from compliance_agent.aplicacao.detectores import MODULOS, carregar_detector, versao_execucao
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import elegibilidade as E9
from compliance_agent.dominio.achado import Achado, ExecucaoRegra, StatusAchado, hash_entradas
from compliance_agent.dominio.estados import EstadoSaida
from compliance_agent.fluxo.fila import Resultado

ESQUEMA_PADRAO = "sombra"
ENV_ESQUEMA = "JFN_E10_ESQUEMA"
ENV_FONTE = "JFN_DETECTAR_FONTE"
LOTE_E9 = 20000


# ── escopo e registro ───────────────────────────────────────────────────────────────────────────────────────────
def _escopo(payload: dict, ctx: Contexto | None = None) -> tuple[str, int | None, str]:
    did = payload.get("detector") or (ctx.tipo.split(":", 1)[1] if ctx and ":" in ctx.tipo else "")
    if did not in MODULOS:
        raise ErroPermanente(f"detector E10 inválido: {did!r} (válidos: {', '.join(sorted(MODULOS))})")
    ex = payload.get("exercicio")
    ex = int(ex) if ex else None
    return did, ex, str(ex or "todos")


def exigencia(did: str) -> tuple[str, str]:
    """(unidade, exigência) da E9 para o detector — a fonte é `elegibilidade.DETECTORES` (uma só verdade)."""
    det = carregar_detector(did)
    mapa = E9.exiges_do_detector(did) if did in E9.DETECTORES else {}
    if det.UNIDADE not in mapa:
        raise ErroPermanente(f"{did}: sem exigência da E9 na unidade {det.UNIDADE} (elegibilidade.DETECTORES)")
    return det.UNIDADE, mapa[det.UNIDADE]


def _registro(did: str) -> dict:
    return E9.carregar_registro().get(did) or {}


def esquema_vigente(payload: dict | None = None) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema((payload or {}).get("esquema") or os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO)


def esquema_e9(payload: dict | None = None) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema((payload or {}).get("esquema_e9") or E9.esquema_vigente())


def abrir_fonte(payload: dict):
    return E9.abrir_fonte(payload.get("fonte") or os.environ.get(ENV_FONTE) or None)


def conectar(payload: dict):
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    dsn = payload.get("dsn") or dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    return psycopg.connect(dsn, autocommit=True)


def aplicar_schema(con, esquema: str) -> None:
    from compliance_agent.adaptadores.achados import aplicar_schema as aplicar
    aplicar(con, esquema)


# ── E9: veredito por item ────────────────────────────────────────────────────────────────────────────────────────
def vereditos(con, esq_e9: str, unidade: str, exige: str, chaves) -> dict[str, str]:
    """chave → código da E9 ('E', 'I:…', '?:…') na versão corrente; chave sem linha fica fora (→ indeterminada)."""
    chaves = sorted({str(k) for k in chaves if k is not None})
    out: dict[str, str] = {}
    for i in range(0, len(chaves), LOTE_E9):
        for k, v in con.execute(f'SELECT chave, exiges ->> %s FROM "{esq_e9}".elegibilidade '
                                "WHERE unidade = %s AND versao = %s AND chave = ANY(%s)",
                                (exige, unidade, E9.VERSAO, chaves[i:i + LOTE_E9])):
            out[k] = v
    return out


def anotar(itens: list[dict], ver: dict[str, str]) -> None:
    for c in itens:
        c["e9"] = ver.get(str(c["chave_e9"])) if c.get("chave_e9") is not None else None


# ── disparo → contrato único ─────────────────────────────────────────────────────────────────────────────────────
def origem(did: str, escopo: str, chave: str) -> str:
    return f"e10:{did}:{escopo}:{chave}"


def para_achado(did: str, versao: str, escopo: str, rodada: str, d) -> Achado:
    reg = _registro(did)
    afirma = str(reg.get("afirma") or did)
    hip = [h["hipotese"] for h in reg.get("hipoteses_inocentes") or [] if h.get("hipotese")]
    exe = ExecucaoRegra(regra_id=did, versao=versao, entradas_hash=hash_entradas(d.entradas),
                        resultado={"geracao": "e10", "rodada": rodada, "escopo": escopo, "chave": d.chave,
                                   "grupo": d.grupo, "valores": d.valores, "entradas": d.entradas,
                                   "e9_versao": E9.VERSAO, "tier": reg.get("tier")},
                        processo=d.processo, origem=origem(did, escopo, d.chave))
    return Achado.de_regra(execucao=exe, status=StatusAchado.TRIAGEM, estado=EstadoSaida(d.estado),
                           motivo_estado=d.motivo_estado, observacao=d.observacao, inferencia=afirma,
                           qualificacao=None, hipotese=afirma, hipoteses_alternativas=hip, evidencias=d.evidencias)


def rodada_de(did: str, versao: str, escopo: str, hashes: list[str]) -> str:
    corpo = json.dumps([did, versao, escopo, E9.VERSAO, sorted(hashes)])
    return hashlib.sha256(corpo.encode()).hexdigest()[:24]


def gravar(con, esquema: str, did: str, versao: str, escopo: str, rodada: str, achados: list[Achado],
           resumo: dict) -> dict:
    """achados (idempotente pela execução) + a execução de RESUMO da rodada (sem achado)."""
    from psycopg.types.json import Jsonb

    from compliance_agent.adaptadores.achados import gravar as gravar_achados
    r = gravar_achados(con, esquema, achados)
    res = {**resumo, "rodada": rodada, "escopo": escopo, "n_achados": len(achados), "e9_versao": E9.VERSAO,
           "geracao": "e10"}
    eh = hash_entradas({"rodada": rodada, "resumo": resumo})
    novo = con.execute(
        f'INSERT INTO "{esquema}".execucao_regra (regra_id, regra_versao, processo, entradas_hash, resultado, origem) '
        "VALUES (%s,%s,NULL,%s,%s,%s) ON CONFLICT (origem, regra_id, regra_versao, entradas_hash) DO NOTHING "
        "RETURNING id", (did, versao, eh, Jsonb(res), origem(did, escopo, "resumo"))).fetchone()
    return {"achados_novos": r["gravados"], "resumo_novo": novo is not None}


# ── estágio (contrato do §3.2) ──────────────────────────────────────────────────────────────────────────────────
def _handler(payload: dict, ctx: Contexto) -> Resultado:
    did, ex, escopo = _escopo(payload, ctx)
    det = carregar_detector(did)
    unidade, exige = exigencia(did)
    versao = versao_execucao(did)
    t0 = time.monotonic()
    src = abrir_fonte(payload)
    try:
        carga = det.carregar(src, ex)
    finally:
        src.close()
    esq, esq9 = esquema_vigente(payload), esquema_e9(payload)
    pg = conectar(payload)
    try:
        anotar(carga.itens, vereditos(pg, esq9, unidade, exige, (c["chave_e9"] for c in carga.itens)))
        disparos = det.detectar(carga.itens, carga.contexto)
        resumo = {**carga.contexto, **det.resumo(carga.itens, disparos), "unidade_e9": unidade, "exigencia": exige}
        resumo["itens_sem_linha_e9"] = sum(1 for c in carga.itens if c.get("e9") is None)
        rodada = rodada_de(did, versao, escopo, [hash_entradas(d.entradas) for d in disparos])
        achados = [para_achado(did, versao, escopo, rodada, d) for d in disparos]
        aplicar_schema(pg, esq)
        g = gravar(pg, esq, did, versao, escopo, rodada, achados, resumo)
    finally:
        pg.close()
    novos = g["achados_novos"]
    return Resultado(efeito={"detector": did, "escopo": escopo, "exercicio": ex, "versao": versao, "rodada": rodada,
                             "esquema": esq, "achados": len(achados), "achados_novos": novos,
                             "resumo_novo": g["resumo_novo"], "segundos": round(time.monotonic() - t0, 1),
                             "resumo": json.loads(json.dumps(resumo, default=str))},
                     eventos=[{"fonte": "detectar", "tipo": "achados", "chave": f"{did}:{escopo}"}] if novos else [])


def contar(con, esquema: str, did: str, versao: str, escopo: str, rodada: str) -> tuple[int, int | None]:
    """(achados da rodada, n_achados declarado no resumo da rodada — None se o resumo não existe)."""
    n = con.execute(f'SELECT count(*) FROM "{esquema}".execucao_regra e JOIN "{esquema}".achado a '
                    "ON a.execucao_regra_id = e.id WHERE e.regra_id = %s AND e.regra_versao = %s "
                    "AND e.origem LIKE %s AND e.resultado ->> 'rodada' = %s",
                    (did, versao, f"e10:{did}:{escopo}:%", rodada)).fetchone()[0]
    r = con.execute(f'SELECT (resultado ->> \'n_achados\')::int FROM "{esquema}".execucao_regra WHERE regra_id = %s '
                    "AND regra_versao = %s AND origem = %s AND resultado ->> 'rodada' = %s",
                    (did, versao, origem(did, escopo, "resumo"), rodada)).fetchone()
    return n, (r[0] if r else None)


def conferir_amostra(pg, src, payload: dict, did: str, versao: str, escopo: str, ex: int | None, rodada: str,
                     n: int) -> dict:
    """Sorteia `n` achados da rodada e recalcula cada um DO ZERO pela fonte (só o grupo dele) + E9."""
    det = carregar_detector(did)
    unidade, exige = exigencia(did)
    esq, esq9 = esquema_vigente(payload), esquema_e9(payload)
    linhas = pg.execute(f'SELECT resultado ->> \'grupo\', resultado ->> \'chave\', entradas_hash FROM "{esq}".'
                        "execucao_regra e JOIN " f'"{esq}".achado a ON a.execucao_regra_id = e.id WHERE e.regra_id '
                        "= %s AND e.regra_versao = %s AND e.origem LIKE %s AND e.resultado ->> 'rodada' = %s",
                        (did, versao, f"e10:{did}:{escopo}:%", rodada)).fetchall()
    amostra = random.sample(linhas, min(n, len(linhas)))
    divergentes = []
    for grupo, chave, h in amostra:
        carga = det.carregar_grupo(src, grupo, ex)
        anotar(carga.itens, vereditos(pg, esq9, unidade, exige, (c["chave_e9"] for c in carga.itens)))
        achou = [d for d in det.detectar(carga.itens, carga.contexto) if d.chave == chave]
        if len(achou) != 1 or hash_entradas(achou[0].entradas) != h.strip():
            divergentes.append(chave)
    return {"amostra": len(amostra), "divergentes": divergentes}


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    ef = resultado.efeito or {}
    did, ex, escopo = _escopo(payload, ctx)
    if ef.get("detector") != did or ef.get("escopo") != escopo or not ef.get("rodada"):
        return False
    declarados = int(ef.get("achados") or 0)
    pg = conectar(payload)
    src = abrir_fonte(payload)
    try:
        esq = esquema_vigente(payload)
        n, n_resumo = contar(pg, esq, did, ef["versao"], escopo, ef["rodada"])
        am = conferir_amostra(pg, src, payload, did, ef["versao"], escopo, ex, ef["rodada"],
                              int(payload.get("amostra") or 10))
    finally:
        pg.close()
        src.close()
    ef["conferencia"] = {"contados": n, "resumo_declara": n_resumo, **am}
    return (n == declarados and n_resumo == declarados and not am["divergentes"]
            and (am["amostra"] > 0 or declarados == 0))


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_pesado"], prioridade=45)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E10 detectar (sombra O5.3)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("acao", choices=("aplicar",))
    r = sub.add_parser("rodar")
    r.add_argument("--detector", required=True, choices=sorted(MODULOS))
    r.add_argument("--exercicio", type=int)
    r.add_argument("--fonte")
    r.add_argument("--amostra", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "schema":
        con = conectar({})
        try:
            aplicar_schema(con, esquema_vigente())
        finally:
            con.close()
        print(json.dumps({"esquema": esquema_vigente(), "ok": True}))
        return 0
    payload = {"detector": a.detector, "exercicio": a.exercicio, "fonte": a.fonte, "amostra": a.amostra}
    ctx = Contexto(no=os.environ.get("JFN_NO", "cli"), tipo=f"detectar:{a.detector}",
                   chave=f"detectar:{a.detector}:{a.exercicio or 'todos'}", ficha=0, tentativa=1)
    res = _handler(payload, ctx)
    ok = _efeito(payload, ctx, res)
    print(json.dumps(res.efeito, ensure_ascii=False, default=str))
    if not ok:
        print("detectar: EFEITO NÃO CONFERIDO", file=sys.stderr)
        return 1
    print(f"detectar: {res.efeito['achados']} achado(s) conferido(s) em {res.efeito['esquema']}.achado "
          f"({a.detector}, escopo {res.efeito['escopo']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
