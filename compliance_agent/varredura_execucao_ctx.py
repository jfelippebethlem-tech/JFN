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

from compliance_agent.execucao_fatos import _natureza  # ordem reajuste → prazo → valor

# Reforma de edifício/equipamento tem teto de 50% no art. 125 (os demais, 25%). Quem aplica é o
# X1 — aqui só se classifica o objeto, com o mesmo padrão já usado em `execucao_fatos`.
_RE_REFORMA = re.compile(r"reforma\s+(?:de\s+)?(?:edif[íi]cio|pr[ée]dio|im[óo]vel|equipamento|"
                         r"cobertura)|reforma\s+d[ao]\s", re.I)
_RE_SUPRESSAO = re.compile(r"supress[ãa]o|suprimir", re.I)


# ── vocabulário aprendido na PRIMEIRA varredura sobre a base real (2026-07-29) ────────────────
# `execucao_fatos._natureza` foi escrito para o texto corrido do processo SEI e não cobre a
# redação dos extratos do PNCP. Na estreia, a lacuna produziu um achado CRÍTICO fabricado: o
# contrato 30051023000196-2-000348/2024 (MPRJ, auxílio alimentação) teve R$ 40,6 mi de "revisão
# ... dos valores vigentes do benefício", com fundamento no art. 124, II, "d", somados ao teto
# do art. 125 como se fossem acréscimo quantitativo — X1 confirmado com score 1.0. Revisão do
# art. 124 é REEQUILÍBRIO: recompõe o valor, não amplia o escopo, e não consome teto nenhum.
_RE_REEQUILIBRIO = re.compile(
    # A janela `[^.;]{0,80}` entre "revisão" e "dos valores" não é frescura: o extrato real diz
    # "a revisão, a contar de 01/06/2025, dos valores vigentes do benefício" — com a data
    # encaixada no meio. Exigir as palavras coladas foi o que deixou passar os R$ 40,6 mi.
    r"reequil[íi]brio|revis[ãa]o\b[^.;]{0,80}?\bd[oe]s?\s+(?:pre[çc]|valor)|repactua|reajust|"
    r"art(?:igo)?\.?\s*124\b|corre[çc][ãa]o\s+monet|\bIPCA\b|\bINCC\b|\bIGP-?M\b", re.I)
_RE_ACRESCIMO = re.compile(
    r"acr[ée]scim|acrescer|supress[ãa]o|suprimir|aditamento\s+de\s+valor|majora|"
    r"\baporte\b|alter[aç][çã][ãa]o\s+quantitativ", re.I)
_RE_PRAZO = re.compile(r"prorroga|prazo\s+de\s+vig[êe]ncia|dilata[çc][ãa]o\s+de\s+prazo", re.I)
# Termos que não mexem em valor nem em prazo — trocam a parte, corrigem erro material, ajustam
# cláusula. Reconhecê-los evita que caiam no balaio 'indeterminado' e pareçam lacuna de leitura.
_RE_OUTRO = re.compile(
    r"sub-?roga|retifica|rerratifica|erro\s+material|adequa[çc][ãa]o|altera[çc][ãa]o\s+da\s+"
    r"vers[ãa]o|altera[çc][ãa]o\s+de\s+cl[áa]usula|transfer[êe]ncia\s+d[ao]\s+contratante", re.I)


def _flag(v: Any) -> bool:
    """Qualificador do PNCP é texto ('1'/'0'/'true'). Ausente ≠ falso, mas aqui só interessa o sim."""
    return str(v or "").strip().lower() in {"1", "true", "sim", "s"}


def _tipo_do_aditivo(ad: sqlite3.Row) -> tuple[str, str]:
    """(tipo, origem). O OBJETO manda; o qualificador do PNCP é o último recurso.

    Tipos: `valor` (entra no teto do art. 125) · `prazo` · `reajuste` (inclui reequilíbrio do
    art. 124) · `misto` (faz revisão E acréscimo no mesmo termo, com um valor só) · `outro`
    (sub-rogação, retificação, erro material) · `""` (não deu para saber).

    `misto` existe porque a base tem termos assim e eles não têm resposta certa: o
    `valor_acrescido` cobre as duas coisas e não há memória de cálculo para repartir. Contar
    inteiro infla o percentual do art. 125; contar zero esconde acréscimo real. Declarar a
    ambiguidade é a única saída honesta.
    """
    objeto = ad["objeto"] or ""
    tem_reeq = bool(_RE_REEQUILIBRIO.search(objeto))
    tem_acre = bool(_RE_ACRESCIMO.search(objeto))
    if tem_reeq and tem_acre:
        return "misto", "objeto"
    if tem_reeq:
        return "reajuste", "objeto"
    if _RE_PRAZO.search(objeto):
        return "prazo", "objeto"
    if tem_acre:
        return "valor", "objeto"
    # `execucao_fatos._natureza` é a régua do texto do SEI; fica como segunda opinião.
    nat = _natureza(objeto)
    if nat:
        return nat, "objeto"
    if _RE_OUTRO.search(objeto):
        return "outro", "objeto"
    if _RE_REEQUILIBRIO.search(ad["fundamento_legal"] or ""):
        return "reajuste", "fundamento_legal"
    if _flag(ad["qualif_reajuste"]):
        return "reajuste", "qualificador_pncp"
    if _flag(ad["qualif_vigencia"]) or (ad["prazo_aditado_dias"] or 0) > 0:
        return "prazo", "qualificador_pncp"
    if _flag(ad["qualif_acrescimo"]):
        return "valor", "qualificador_pncp"
    return "", "indeterminado"


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
            "tipo": tipo, "valor": valor, "origem_tipo": origem,
            "descricao_objeto": ad["objeto"] or "",
            "justificativa": ad["objeto"] or "",
            "data": (ad["vigencia_fim"] or None) if tipo == "prazo" else None,
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
    if not aditivos and (row["num_aditivos"] or 0) > 0:
        # O contrato declara ter aditivos que não foram coletados: isso é lacuna de CAPTURA, e
        # precisa aparecer como tal — senão "sem achado" se confunde com "sem aditivo".
        lacunas.append("aditivos_nao_coletados")
    return ctx
