# -*- coding: utf-8 -*-
"""Job `expandir:<estágio>` — UM evento que vira N jobs do estágio seguinte (achado 1.1 da revisão de 25/11).

Roda SÓ no processo-filho (`fluxo.executar`, que o despacha antes do registro de estágios): o planejador, no
processo do supervisor, não importa a camada de aplicação (catraca tests/test_fluxo_supervisor.py), e a lista dos N
mora no PG/código do estágio. As rotas que expandem estão em config/fluxo.yaml `nativos.rotas` (formas `aquisicao` e
`detectores`, grafo.EXPANDE):
  · `expandir:texto`    — `capturar/versao_nova` → um `texto:` por versão binária da aquisição (texto.jobs_da_aquisicao);
  · `expandir:detectar` — `elegibilidade/mudou` → um `detectar:<detector>:<exercício|todos>` por detector cuja
    exigência da E9 é da unidade (detectar.exigencia).
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
    raise ErroPermanente(f"expandir: estágio sem expansão declarada: {tipo!r}")


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
