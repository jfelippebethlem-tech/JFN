# -*- coding: utf-8 -*-
"""Rotina DIÁRIA da perícia contábil de todos os contratos → resumo para o painel (Estado › Perícia contábil).

Roda a mesma régua do relatório de 13/11/2026 (`pericia_contabil.avaliar_estado` + `avaliar_prefeitura`) sem gerar
PDF e grava `data/pericia_contabil_resumo.json`:
  · placar por esfera — conforme / acima do valor contratado / à frente do pró-rata / abaixo do devido (encerrado,
    em curso) / indeterminado;
  · os maiores "acima do valor contratado" (pago − devido) — indício a conferir nos termos aditivos;
  · OBs repetidas (mesma UG, NL, competência e valor, em dias distintos, todas confirmadas pelo banco, nenhuma
    devolvida) — sinal que NÃO muda a classe; as sem confirmação do banco saem contadas à parte (INDISPONÍVEL);
  · o motivo de cada indeterminado, contado.

Pago no Estado = SÓ OB Contabilizada do SIAFE (a régua já filtra); Prefeitura = total pago no SIAFIC-Rio por contrato.
Esferas nunca se misturam. CPF mascarado em todo texto que sai. Indício ≠ acusação.

Uso:  nice -n 15 timeout 5400 python -m compliance_agent.pericia_contabil_rotina [--saida data/...json]
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

from compliance_agent import pericia_contabil as P
from compliance_agent.rotina_base import DATA, agora_iso, executar, gravar_json, ler_json

NOME = "pericia_contabil_rotina"
SAIDA = DATA / "pericia_contabil_resumo.json"
TOP = 60
_CAMPOS = ("esfera", "orgao", "ug", "contrato", "processo", "fornecedor", "fornecedor_doc", "objeto", "categoria",
           "subtipo", "motivo", "valor_atualizado", "devido", "pago", "diferenca", "excesso_global", "n_obs",
           "vig_inicio", "vig_fim", "encerrado", "corte", "obs_mesma_nl", "valor_mesma_nl", "obs_mesma_competencia",
           "valor_mesma_competencia", "obs_mesma_nl_mesmo_dia", "obs_mesma_nl_nao_confirmadas",
           "valor_mesma_nl_nao_confirmadas", "criterio_devido", "ressalvas", "fonte_pago")


def _mascarar(x):
    from compliance_agent.governo_couto import _mascarar_tudo
    return _mascarar_tudo(x)


def _linha(r: dict) -> dict:
    d = {k: r.get(k) for k in _CAMPOS}
    d["verificacao"] = "PENDENTE"           # número reproduzível; a conclusão exige o documento
    if r.get("esfera") == P.ESTADO and r.get("processo"):
        d["prova_primaria"] = (f"{r.get('n_obs') or 0} OB Contabilizada(s) do SIAFE no processo {r['processo']} "
                               f"(credor {r.get('fornecedor_doc') or '—'})")
    elif r.get("esfera") == P.PREFEITURA:
        d["prova_primaria"] = f"total pago do contrato {r.get('contrato')} no Contas Rio (coleta {r.get('corte')})"
    d["objeto"] = (d["objeto"] or "")[:220]
    d["ressalvas"] = (d["ressalvas"] or "")[:300]
    d["rotulo"] = P.ROTULO.get(r["categoria"], r["categoria"])
    if r.get("motivo"):
        d["motivo_txt"] = P.MOTIVOS.get(r["motivo"], r["motivo"])
    return d


def resumir(resultados: list[dict], *, top: int = TOP) -> dict:
    """Payload da aba a partir das linhas da perícia. Função pura (testada com dados sintéticos)."""
    rs = P.resumo(resultados)
    esferas = {}
    for esf, e in rs.items():
        da_esfera = [r for r in resultados if r["esfera"] == esf]
        a_maior = sorted((r for r in da_esfera if r["categoria"] == "A_MAIOR"),
                         key=lambda r: -float(r.get("diferenca") or 0))
        dup = sorted((r for r in da_esfera if (r.get("obs_mesma_nl") or 0) > 0),
                     key=lambda r: -float(r.get("valor_mesma_nl") or 0))
        cortes = Counter(r.get("corte") for r in da_esfera if r.get("corte"))
        esferas[esf] = {
            "n": e["n"],
            "placar": {c: e[c] for c in P.CATEGORIAS},
            "rotulos": dict(P.ROTULO),
            "pago_determinado": round(e["pago_determinado"], 2),
            "devido_determinado": round(e["devido_determinado"], 2),
            "excesso_a_maior": round(e["excesso_a_maior"], 2),
            "adiantado": round(e["adiantado"], 2),
            "excesso_global": round(e["excesso_global"], 2),
            "deficit_encerrado": round(e["deficit_encerrado"], 2),
            "subtipos": {P.SUBTIPO.get(k, k): v for k, v in e["subtipos"].items()},
            "art125": {"aferivel": e["n_art125_aferivel"], "estouro": e["n_estouro_art125"]},
            "motivos_indeterminado": [{"motivo": k, "texto": P.MOTIVOS.get(k, k), "n": v}
                                      for k, v in e["motivos"].items()],
            # corte por contrato: no Estado é um só (última OB coletada); na Prefeitura é a data da coleta de cada
            # contrato — mostrar o intervalo, nunca "o mais comum" (seria apresentar um corte que não vale para todos)
            "corte": min(cortes) if len(cortes) == 1 else None,
            "corte_min": min(cortes) if cortes else None, "corte_max": max(cortes) if cortes else None,
            "fonte_pago": next((r["fonte_pago"] for r in da_esfera if r.get("fonte_pago")), ""),
            "proveniencia": {
                "fonte_contratos": ("contratos_tcerj (dados abertos do TCE-RJ) + termos do PNCP" if esf == P.ESTADO
                                    else "contasrio_contrato (Contas Rio / SIAFIC-Rio, consulta CCON)"),
                "cobertura": ("OB do SIAFE a partir de 2021; vigência anterior, vínculo OB↔contrato ambíguo e par "
                              "UG/exercício com coleta parcial saem INDETERMINADO (contados abaixo, não somados)"
                              if esf == P.ESTADO else "contratos publicados no Contas Rio na data da coleta"),
            },
            "verificacao": {
                "placar": ("VERIFICADO — régua determinística sobre a fonte primária; cada número é reproduzível pelo "
                           "comando da rotina"),
                "listas": ("PENDENTE — cada linha é indício a conferir nos documentos (NL, nota fiscal, termo aditivo, "
                           "medição); a diferença não é conclusão de dano"),
            },
            "n_a_maior_listados": min(top, len(a_maior)),
            "a_maior": [_linha(r) for r in a_maior[:top]],
            "duplicidades": {"aferivel": False, "n_contratos": None, "itens": [],
                             "motivo": "o Contas Rio publica o total pago por contrato, não as OB — duplicidade de NL "
                                       "não é aferível nesta esfera (INDISPONÍVEL, não zero)"}
            if esf == P.PREFEITURA else {
                "aferivel": True,
                "n_contratos": len(dup),
                "n_obs_repetidas": sum(int(r.get("obs_mesma_nl") or 0) for r in dup),
                "valor_repetido": round(sum(float(r.get("valor_mesma_nl") or 0) for r in dup), 2),
                # sem confirmação do banco na coleta: devolução + reemissão não descartada — INDISPONÍVEL, não zero
                "n_obs_nao_confirmadas": sum(int(r.get("obs_mesma_nl_nao_confirmadas") or 0) for r in da_esfera),
                "valor_nao_confirmado": round(sum(float(r.get("valor_mesma_nl_nao_confirmadas") or 0)
                                                  for r in da_esfera), 2),
                "n_obs_mesmo_dia": sum(int(r.get("obs_mesma_nl_mesmo_dia") or 0) for r in da_esfera),
                "itens": [_linha(r) for r in dup[:top]],
            },
        }
    return _mascarar({
        "gerado_em": agora_iso(),
        "regua": "compliance_agent.pericia_contabil (devido até o corte × pago)",
        "tolerancia": f"|diferença| < {P.TOL_PCT:.0%} do devido ou < R$ {P.fmt_brl(P.TOL_ABS)} = conforme",
        "definicoes": {
            "pago_estado": "SÓ Ordem Bancária do SIAFE com status Contabilizado; empenho e liquidação nunca entram",
            "pago_prefeitura": "total pago por contrato no SIAFIC-Rio (Contas Rio/CCON)",
            "duplicidade": ("mesma UG + mesma NL + mesma competência + mesmo valor em OBs de DIAS DISTINTOS, todas "
                            "com o crédito confirmado pelo banco ('Processado e Pago') e nenhuma devolvida — sinal a "
                            "conferir na NF, não muda a classe e não é duplicidade comprovada. OBs do mesmo dia para a "
                            "mesma NL são parcelas (uma NL liquida vários documentos). OB repetida SEM confirmação do "
                            "banco na coleta é INDISPONÍVEL: a devolução posterior não aparece até recoletar o status"),
            "devolucao": ("só pelo SIAFE: com a Guia de Devolução coletada (tela Guia de Devolução, vínculo OB + UG), "
                          "pago = valor da OB − valor devolvido; sem guia coletada, 'Erro no Pagamento' = devolvida "
                          "inteira (0,00) e GD com outro status = valor devolvido desconhecido → a OB sai da soma e o "
                          "pago vira piso"),
            "acima_do_valor": ("pago acima do valor registrado/atualizado do contrato. No Estado a fonte (TCE-RJ) não "
                               "publica termos aditivos: é indício a conferir nos termos, não dano apurado"),
            "adiantado": ("pago à frente do pró-rata linear, mas dentro do valor contratado — não é pagamento a maior "
                          "(licença anual, curso, parcela única de parceria)"),
            "abaixo_do_devido": ("Prefeitura: pago menor que o LIQUIDADO (o que se deve); saldo contratual não "
                                 "executado não entra. Estado: pago menor que o valor/pró-rata — sem a liquidação por "
                                 "contrato na base, é saldo não pago OU não executado"),
            "indeterminado": "sem base para afirmar a maior/a menor — o motivo vem ao lado; INDISPONÍVEL ≠ zero",
        },
        "ressalva": "Indício não é acusação. Diferença é sinal para requerer documentos, não conclusão de dano.",
        "esferas": esferas,
    })


def _rodar(log, saida: Path) -> int:
    t = time.time()
    res = P.avaliar_estado()
    log.info("Estado: %d contratos avaliados em %.0f s", len(res), time.time() - t)
    t = time.time()
    pref = P.avaliar_prefeitura()
    log.info("Prefeitura: %d contratos avaliados em %.0f s", len(pref), time.time() - t)
    payload = resumir(res + pref)
    anterior = ler_json(saida) or {}
    payload["efeito"] = {"contratos": len(res) + len(pref), "estado": len(res), "prefeitura": len(pref)}
    # AO VIVO: `ultimo_efeito_iso` só avança quando a rotina PRODUZ (contratos avaliados > 0)
    payload["ultimo_efeito_iso"] = payload["gerado_em"] if res or pref else anterior.get("ultimo_efeito_iso")
    gravar_json(saida, payload)
    for esf, e in payload["esferas"].items():
        p = e["placar"]
        log.info("%s: n=%d conforme=%d a_maior=%d a_menor_enc=%d a_menor_curso=%d indeterminado=%d "
                 "duplicidades=%s", esf, e["n"], p["CONFORME"], p["A_MAIOR"], p["A_MENOR_ENCERRADO"],
                 p["A_MENOR_EM_CURSO"], p["INDETERMINADO"],
                 "n/a" if e["duplicidades"]["n_contratos"] is None else e["duplicidades"]["n_contratos"])
    log.info("gravado %s", saida)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Perícia contábil diária → resumo do painel.")
    ap.add_argument("--saida", default=str(SAIDA))
    a = ap.parse_args(argv)
    return executar(NOME, lambda log: _rodar(log, Path(a.saida)))


if __name__ == "__main__":
    raise SystemExit(main())
