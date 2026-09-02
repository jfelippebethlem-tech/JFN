# -*- coding: utf-8 -*-
"""Contexto de EXECUÇÃO CONTRATUAL a partir do banco — o insumo que faltava para X1 e X2.

`execucao_fatos` já monta o contexto de execução a partir do TEXTO do processo SEI, e é a fonte
mais rica quando o processo está capturado. Só que ela depende de o processo estar no arquivo, e
a base tem 54.624 contratos em `pcrj_contratos` contra 3.927 processos no `sei_arvore`. Este
módulo cobre a via estruturada: monta o mesmo contrato de entrada a partir de `pcrj_contratos` +
`contrato_aditivo`, que é dado tabular já coletado do PNCP.

O QUE ESTE MÓDULO NÃO FAZ (e por que):

  · Não classifica natureza de aditivo pelo qualificador do PNCP quando há objeto. `qualif_acrescimo`
    vem '1' para quase tudo, e o período renovado é gravado em `valorAcrescido` — medido em
    `contratos/thoughts` no caso AVANTY, uma renovação de 12 meses que entrava como +R$ 51 mi de
    acréscimo quantitativo. Quem discrimina é o OBJETO; o qualificador é o último recurso, e a
    origem da classificação fica registrada em `origem_tipo` para quem for auditar.
  · Não converte ausência em zero. `valor_inicial` igual a 0 ou nulo vira `None` e entra em
    `lacunas` — o denominador do art. 125 valendo zero produziria percentual infinito, isto é,
    acusação fabricada a partir de dado faltante.
  · Não inventa vantajosidade. A base não guarda se houve pesquisa de mercado na prorrogação;
    `pesquisa_vantajosidade` fica `None` (INDISPONÍVEL), nunca 'ausente' — que o X2 leria como
    prorrogação desamparada.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from compliance_agent.limites_aditivo import classificar_natureza as _classificar

# Reforma de edifício/equipamento tem teto de 50% no art. 125 (os demais, 25%). Quem aplica é o
# X1 — aqui só se classifica o objeto, com o mesmo padrão já usado em `execucao_fatos`.
_RE_REFORMA = re.compile(r"reforma\s+(?:de\s+)?(?:edif[íi]cio|pr[ée]dio|im[óo]vel|equipamento|"
                         r"cobertura)|reforma\s+d[ao]\s", re.I)
_RE_SUPRESSAO = re.compile(r"supress[ãa]o|suprimir", re.I)


def _tipo_do_aditivo(ad: sqlite3.Row) -> tuple[str, str]:
    """(tipo, origem) pela régua ÚNICA de `limites_aditivo.classificar_natureza`.

    Este módulo chegou a ter vocabulário próprio, aprendido na estreia da varredura sobre a base
    real (2026-07-29) — foi ele que descobriu que a "revisão dos valores" do art. 124, II, "d"
    estava entrando no teto do art. 125 e produzindo 45% de falso positivo. O vocabulário foi
    promovido para `limites_aditivo`, que agora é a mesma régua do X1, do `contratos/thoughts`,
    do `cruzamentos_intel` e do `pericia_gastos` — antes, três respostas diferentes para a mesma
    pergunta jurídica rodavam ao mesmo tempo.
    """
    return _classificar(
        ad["objeto"], fundamento_legal=ad["fundamento_legal"],
        qualif_acrescimo=ad["qualif_acrescimo"], qualif_vigencia=ad["qualif_vigencia"],
        qualif_reajuste=ad["qualif_reajuste"], prazo_aditado_dias=ad["prazo_aditado_dias"])


def _campo(linha, nome: str):
    """Lê uma coluna que pode não existir no schema local — base parcial degrada, não quebra."""
    try:
        return linha[nome] or None
    except (IndexError, KeyError):
        return None


def montar_contexto(con: sqlite3.Connection, numero_controle_pncp: str) -> dict[str, Any]:
    """Contexto de execução de um contrato, no formato que X1 e X2 consomem.

    Devolve sempre um dicionário — contrato inexistente produz contexto vazio COM a lacuna
    declarada, nunca exceção nem zeros que pareçam medição.
    """
    lacunas: list[str] = []
    ctx: dict[str, Any] = {
        "contrato": numero_controle_pncp, "valor_inicial": None, "tipo_objeto": None,
        "aditivos": [], "prorrogacoes": [], "n_aditivos": 0, "lacunas": lacunas,
        "fonte": "varredura_execucao_ctx (pcrj_contratos + contrato_aditivo)",
    }

    row = con.execute(
        "SELECT * FROM pcrj_contratos WHERE numero_controle_pncp = ? LIMIT 1",
        (numero_controle_pncp,)).fetchone()
    if row is None:
        lacunas.append("contrato")
        return ctx

    objeto = row["objeto"] or ""
    ctx["objeto"] = objeto
    ctx["orgao_cnpj"] = row["orgao_cnpj"] or ""
    ctx["orgao_nome"] = row["orgao_nome"] or ""
    ctx["fornecedor_documento"] = row["fornecedor_documento"] or ""
    ctx["fornecedor_nome"] = row["fornecedor_nome"] or ""
    ctx["valor_global"] = row["valor_global"] or None
    ctx["tipo_objeto"] = "reforma" if _RE_REFORMA.search(objeto) else None

    valor_inicial = row["valor_inicial"]
    if valor_inicial and float(valor_inicial) > 0:
        ctx["valor_inicial"] = float(valor_inicial)
    else:
        lacunas.append("valor_inicial")

    ctx["vigencia_inicio"] = row["vigencia_ini"] or None
    ctx["data_inicio_execucao"] = row["vigencia_ini"] or row["data_assinatura"] or None
    vigencia_fim = row["vigencia_fim"] or None

    aditivos, prorrogacoes = [], []
    for ad in con.execute(
            "SELECT * FROM contrato_aditivo WHERE numero_controle_pncp = ? "
            "ORDER BY COALESCE(sequencial_termo, 0), id", (numero_controle_pncp,)):
        tipo, origem = _tipo_do_aditivo(ad)
        bruto = ad["valor_acrescido"]
        valor = float(bruto) if bruto not in (None, "") else None
        if tipo == "prazo":
            # Prorrogação NÃO consome o teto do art. 125, mesmo quando o PNCP grava um valor no
            # campo de acréscimo — é o período renovado, não aumento de escopo.
            valor = None
        elif tipo == "misto":
            # Um valor só cobrindo revisão + acréscimo: sem memória de cálculo, não se reparte.
            if valor:
                lacunas.append("aditivo_misto")
            valor = None
        elif tipo == "" and valor:
            # Traz dinheiro mas não diz a que título. Fora do teto E declarado — senão o silêncio
            # vira "contrato limpo" quando na verdade é "não consegui ler".
            lacunas.append("aditivo_sem_natureza")
            valor = None
        elif tipo == "valor" and valor is not None and _RE_SUPRESSAO.search(ad["objeto"] or ""):
            valor = -valor  # art. 125 computa supressão à parte; quem separa é o X1

        aditivos.append({
            "numero_termo": ad["numero_termo"] or str(ad["sequencial_termo"] or ""),
            # A DATA DE ASSINATURA do termo — o que o X8 (aditivo retroativo) precisa e que o
            # cabeçalho de `varredura_execucao` dizia não existir. Existia a partir de 2026-08-09,
            # quando o coletor do PNCP passou a guardar `dataAssinatura`: 1.684 dos 1.770 termos
            # (95,1%) a têm. O comentário que a declarava ausente caducou e ninguém releu — por
            # isso o detector seguia fora da varredura.
            "data_assinatura": _campo(ad, "data_assinatura"),
            "vigencia_fim": ad["vigencia_fim"] or None,
            "tipo": tipo, "valor": valor, "origem_tipo": origem,
            "descricao_objeto": ad["objeto"] or "",
            "justificativa": ad["objeto"] or "",
            # `data` É A DATA DO ATO, não a nova vigência. Ela guardava `vigencia_fim` para termos
            # de prazo, e isso virou defeito no dia em que o X8 entrou (2026-08-11): ele usa
            # `data_assinatura or data` como data da assinatura, então TODA prorrogação — cuja nova
            # vigência é, por definição, posterior ao fim da antiga — aparecia como termo assinado
            # fora do prazo. Pego ao conferir à mão um contrato de R$ 199 mi cujos três termos têm
            # `data_assinatura` NULA e mesmo assim saíam confirmados.
            # Ninguém mais dependia do valor antigo: o X1 lê `data` só de termos de VALOR (onde já
            # era None) e o X2 usa a lista `prorrogacoes`, que segue intacta.
            "data": _campo(ad, "data_assinatura"),
            "prazo_aditado_dias": ad["prazo_aditado_dias"] or 0,
            "fundamento_legal": ad["fundamento_legal"] or "",
        })
        if tipo == "prazo":
            dias = ad["prazo_aditado_dias"] or 0
            prorrogacoes.append({
                "data": ad["vigencia_fim"] or None,
                "anos": round(dias / 365.0, 2) if dias else None,
                # A base não registra se houve pesquisa de mercado: INDISPONÍVEL, não 'ausente'.
                "pesquisa_vantajosidade": None,
            })
            # A vigência que vale é a MAIOR data, não a da última linha: um termo posterior pode
            # ser retificação e trazer data anterior, e aí a vigência "encolheria" — fazendo o X2
            # subestimar justamente a perpetuidade que ele existe para achar. Datas em ISO
            # (AAAA-MM-DD) comparam corretamente como texto; formato diferente é ignorado em vez
            # de convertido no escuro.
            nova = str(ad["vigencia_fim"] or "")
            if len(nova) >= 10 and nova[4] == "-" and (not vigencia_fim or nova > str(vigencia_fim)):
                vigencia_fim = nova

    ctx["aditivos"] = aditivos
    ctx["prorrogacoes"] = prorrogacoes
    ctx["n_aditivos"] = len(aditivos)
    ctx["vigencia_fim_atual"] = vigencia_fim
    # X8 compara a assinatura do termo com a vigência ORIGINAL do contrato (a que valia antes das
    # prorrogações); `vigencia_fim_atual` já veio estendida pelos termos de prazo e não serve.
    ctx["vigencia_fim"] = row["vigencia_fim"] or None
    if not aditivos and (row["num_aditivos"] or 0) > 0:
        # O contrato declara ter aditivos que não foram coletados: isso é lacuna de CAPTURA, e
        # precisa aparecer como tal — senão "sem achado" se confunde com "sem aditivo".
        lacunas.append("aditivos_nao_coletados")
    return ctx
