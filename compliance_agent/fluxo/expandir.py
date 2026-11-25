# -*- coding: utf-8 -*-
"""Job `expandir:<estágio>` — UM evento que vira N jobs do estágio seguinte (achado 1.1 da revisão de 25/11).

Roda SÓ no processo-filho (`fluxo.executar`, que o despacha antes do registro de estágios): o planejador, no
processo do supervisor, não importa a camada de aplicação (catraca tests/test_fluxo_supervisor.py), e a lista dos N
mora no PG/código do estágio. As rotas que expandem estão em config/fluxo.yaml `nativos.rotas` (formas `aquisicao` e
`detectores`, grafo.EXPANDE):
  · `expandir:texto`    — `capturar/versao_nova` → um `texto:` por versão binária da aquisição (texto.jobs_da_aquisicao);
  · `expandir:detectar` — `elegibilidade/mudou` → um `detectar:<detector>:<exercício|todos>` por detector cuja
    exigência da E9 é da unidade (detectar.exigencia);
  · `expandir:conferir` — `detectar/achados` → um `conferir:achado:<id>` por achado da rodada (o E12 decide por risco);
  · `expandir:caso`     — `detectar/achados` → um `caso:processo:<p>` / `caso:cnpj:<c>` por processo/CNPJ que os
    achados da rodada citam (campos nomeados, igualdade de valor — `citados`).
O payload traz `alvo` = {tipo, contrato, payload base} dos jobs criados (o planejador os tirou do yaml). Idempotente
pela chave (fila.enfileirar); efeito conferido em outra leitura: TODA chave declarada existe na fila com o tipo certo.
"""
from __future__ import annotations

from compliance_agent.aplicacao.estagios import Estagio, ErroPermanente
from compliance_agent.fluxo import fila
from compliance_agent.fluxo.fila import Resultado


def _gerar(tipo: str, payload: dict) -> list[tuple[str, dict]]:
    if tipo == "texto":
        from compliance_agent.aplicacao.estagios import texto as T
        aq = str(payload.get("aquisicao_id") or "").strip()
        if not aq:
            raise ErroPermanente("expandir:texto sem aquisicao_id")
        con = T.conectar(payload.get("dsn"), payload.get("esquema_captura"))
        try:
            return [(j["chave"], j["payload"]) for j in T.jobs_da_aquisicao(con, aq)]
        finally:
            con.close()
    if tipo == "detectar":
        from compliance_agent.aplicacao import detectores as DM
        from compliance_agent.aplicacao.estagios import detectar as D
        unidade, ex = str(payload.get("unidade") or "").strip(), payload.get("exercicio")
        if not unidade:
            raise ErroPermanente("expandir:detectar sem unidade")
        out = []
        for did in sorted(DM.MODULOS):
            try:
                if D.exigencia(did)[0] != unidade:
                    continue
            except ErroPermanente:              # detector sem exigência na E9: fora (o E10 o recusaria igual)
                continue
            out.append((f"detectar:{did}:{ex or 'todos'}", {"detector": did, **({"exercicio": ex} if ex else {})}))
        return out
    if tipo in ("conferir", "caso"):
        rodada = str(payload.get("rodada") or "").strip()
        if ":" not in rodada:
            raise ErroPermanente(f"expandir:{tipo} sem rodada '<detector>:<escopo>': {rodada!r}")
        con = _con_achados(payload)
        try:
            if tipo == "conferir":
                ids = sorted({i for (i,) in con.execute(
                    "SELECT a.id FROM achado a JOIN execucao_regra e ON e.id = a.execucao_regra_id WHERE e.origem "
                    "LIKE %s", (f"e10:{rodada}:%",))})
                return [(f"conferir:achado:{i}", {"alvo": "achado", "ref": str(i)}) for i in ids]
            chaves: set[str] = set()
            for (res,) in con.execute("SELECT e.resultado FROM execucao_regra e WHERE e.origem LIKE %s AND EXISTS "
                                      "(SELECT 1 FROM achado a WHERE a.execucao_regra_id = e.id)",
                                      (f"e10:{rodada}:%",)):
                chaves |= citados(res)
            return [(f"caso:{c}", {"chave": c}) for c in sorted(chaves)]
        finally:
            con.close()
    raise ErroPermanente(f"expandir: estágio sem expansão declarada: {tipo!r}")


CAMPOS_PROCESSO = ("processo", "processos", "processo_pagamento", "processo_contrato")
CAMPOS_CNPJ = ("cnpj", "credor", "cnpj_credor", "fornecedor", "cnpj_fornecedor")


def citados(resultado) -> set[str]:
    """Chaves do E14 (`processo:<canônico>`, `cnpj:<14 dígitos>`) que o resultado de um achado cita: igualdade de
    VALOR nos campos nomeados (nunca substring do JSON cru — lição casar-palavra-no-json-cru). Pura."""
    import re

    from compliance_agent.dominio import processo_id as PI
    out: set[str] = set()

    def anda(v, k=None):
        if isinstance(v, dict):
            for kk, vv in v.items():
                anda(vv, kk)
        elif isinstance(v, list):
            for x in v:
                anda(x, k)
        elif isinstance(v, str) and k in CAMPOS_PROCESSO:
            c = PI.chave_processo(v)
            if c:
                out.add(f"processo:{c}")
        elif isinstance(v, (str, int)) and k in CAMPOS_CNPJ:
            d = re.sub(r"\D", "", str(v))
            if len(d) == 14 and (str(v) == d or re.fullmatch(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", str(v))):
                out.add(f"cnpj:{d}")
    anda(resultado)
    return out


def _con_achados(payload: dict):
    """Conexão no esquema dos achados do E10 (`JFN_E10_ESQUEMA`, padrão `sombra`)."""
    import os

    import psycopg

    from compliance_agent.aplicacao.estagios import detectar as D
    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo.schema import validar_esquema
    con = psycopg.connect(payload.get("dsn") or dsn_vigente(), autocommit=True)
    con.execute(f'SET search_path TO "{validar_esquema(os.environ.get(D.ENV_ESQUEMA) or D.ESQUEMA_PADRAO)}"')
    return con


def _handler(payload: dict, ctx) -> Resultado:
    alvo = payload.get("alvo") or {}
    tipo = alvo.get("tipo") or ctx.tipo.split(":", 1)[1]
    c, base = alvo.get("contrato") or {}, alvo.get("payload") or {}
    jobs = _gerar(tipo, payload)
    con = fila.conectar()
    try:
        criados = sum(fila.enfileirar(con, tipo, chave, {**base, **proprio}, prioridade=c.get("prioridade", 100),
                                      recursos=c.get("recursos"), volta=c.get("volta"),
                                      no_preferido=c.get("no_preferido"),
                                      correlation_id=ctx.correlation_id) is not None for chave, proprio in jobs)
    finally:
        con.close()
    return Resultado(efeito={"tipo": tipo, "chaves": [k for k, _ in jobs], "criados": criados,
                             "ja_existentes": len(jobs) - criados}, eventos=[])


def _efeito(payload: dict, ctx, resultado: Resultado) -> bool:
    ef = resultado.efeito
    chaves = list(ef.get("chaves") or [])
    con = fila.conectar()
    try:
        achados = {k for (k,) in con.execute("SELECT chave FROM jobs WHERE chave = ANY(%s) AND tipo = %s",
                                             (chaves, ef.get("tipo")))}
    finally:
        con.close()
    faltam = sorted(set(chaves) - achados)
    # a lista é relida do PG/código, não da palavra do handler: N declarado = N que a fonte dá agora
    relido = [k for k, _ in _gerar(ef.get("tipo") or "", payload)]
    ef["conferencia"] = {"declarados": len(chaves), "na_fila": len(achados), "faltam": faltam[:20],
                         "relidos": len(relido), "iguais_ao_relido": sorted(relido) == sorted(chaves)}
    return not faltam and sorted(relido) == sorted(chaves)


VERSAO = "1"
ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_leve"], prioridade=60)
