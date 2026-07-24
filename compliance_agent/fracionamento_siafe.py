# -*- coding: utf-8 -*-
"""FRACIONAMENTO pela ótica do PAGAMENTO (SIAFE) — triagem, não veredito.

O dono autorizou aproveitar a fonte SIAFE (2026-07-24: "já que temos esses dados, aproveite tudo"). O que
ela adiciona, e ninguém mais tem:

  • **DATA** de cada pagamento — é o que destrava os sinais temporais do art. 75 (dispensas coladas no
    tempo), hoje desligados no P4 porque `compras_diretas_tcerj` não tem data;
  • **pagamento EFETIVO** — Ordem Bancária é dinheiro que saiu (§2), não empenho nem liquidação.

O que ela NÃO tem: descrição do OBJETO (o campo `finalidade` é um código numérico) e a MODALIDADE da
contratação. E o número de processo do SIAFE ('2026-06041596') não casa com o do SEI
('SEI-120001/009348/2022') — os formatos são de sistemas diferentes, então não há cruzamento automático
confiável com a fonte que tem objeto e modalidade.

Consequência assumida: **isto é uma FILA DE CANDIDATOS, não um achado de fracionamento.** O grau é sempre
`a_verificar`, e cada candidato carrega os números de processo para o auditor puxar os autos e conferir o
que falta. Afirmar fracionamento sem objeto nem modalidade seria inventar — o mesmo erro que a casa evita
em toda parte (INDISPONÍVEL ≠ irregular).

Sinal usado (todo ele objetivo): mesma UNIDADE GESTORA (art. 75, §1º, I) + mesmo CREDOR + mesmo
EXERCÍCIO, com ≥3 Ordens Bancárias de valor individual ABAIXO do limite de dispensa do ano e SOMA ACIMA
dele. Prioriza pela proximidade temporal entre os pagamentos.
"""
from __future__ import annotations

import re
import sqlite3
import statistics
from datetime import date, datetime

from compliance_agent.limites_dispensa import ato_normativo, limite_dispensa

MIN_OBS = 3          # o padrão do art. 75 §1º é a REPETIÇÃO; duas compras não fazem série
_STATUS_NAO_PAGO = ("exclu", "cancelad", "estornad", "anulad")
# credores que não são fornecedor licitável: folha, tributos, encargos, sentenças, transferências.
# Não se "fraciona" folha de pagamento — somá-los produziria uma fila cheia de ruído.
_CREDOR_NAO_LICITAVEL = re.compile(
    r"folha\s+de\s+pagamento|pessoal|sal[áa]rio|INSS|FGTS|PASEP|IRRF|DARF|GRU|tributo|imposto|"
    r"contribui[çc][ãa]o|senten[çc]a|precat[óo]rio|dep[óo]sito\s+judicial|di[áa]ria|suprimento\s+de\s+fundos|"
    r"restitui[çc][ãa]o|transfer[êe]ncia|repasse|fundo\s+especial|encargo|"
    # ÓRGÃO PÚBLICO como credor = tributo/repasse entre entes, não compra. (No dado real, "MINISTÉRIO DA
    # FAZENDA" liderava a fila de 2025 com 252 OBs — puro ruído.)
    r"minist[ée]rio|secretaria\s+de|prefeitura|munic[íi]pio\s+de|estado\s+do|uni[ãa]o\b|"
    r"receita\s+federal|tesouro|banco\s+central|caixa\s+econ[ôo]mica|tribunal|assembleia|"
    # CONCESSIONÁRIA de utilidade pública: contratação por INEXIGIBILIDADE (art. 74) — hipótese própria,
    # não dispensa por valor. Somá-la produziria acusação contra conta de água e de luz.
    r"companhia\s+estadual|CEDAE|[áa]guas\s+de|energia|light\b|enel\b|telef[ôo]nica|claro\b|vivo\b|"
    r"oi\s+s\.?a|correios|concession[áa]ria", re.I)


def _data(s: str | None) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime((s or "")[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _pago(status: str | None) -> bool:
    """§2: só a OB efetivamente paga conta. 'Excluído'/'Cancelado' é dinheiro que NÃO saiu."""
    s = (status or "").strip().lower()
    return not any(k in s for k in _STATUS_NAO_PAGO)


FAIXA_RENTE_AO_TETO = 0.8      # valor individual entre 80% e 100% do limite = "encaixado" no teto


def _prioridade(intervalo_mediano: float | None, razao_soma: float, n: int,
                fracao_rente_ao_teto: float = 0.0) -> float:
    """0-1: ordem da FILA (não probabilidade de fraude).

    O peso maior é o do valor RENTE AO TETO: comprar três vezes por R$ 59 mil quando o limite é R$ 59,9
    mil denuncia encaixe deliberado; comprar duzentas vezes por R$ 5 mil é rotina de almoxarifado. Foi o
    que separou o joio no dado real — sem isso, TODOS os primeiros colocados saturavam em 1,00 e a fila
    não ordenava nada. A soma entra em escala logarítmica pelo mesmo motivo (60× e 22× o teto precisam
    se distinguir), e a proximidade temporal continua, com peso menor."""
    import math
    p_teto = max(0.0, min(1.0, fracao_rente_ao_teto))
    p_tempo = 0.5 if intervalo_mediano is None else max(0.0, min(1.0, (60 - intervalo_mediano) / 60))
    p_soma = max(0.0, min(1.0, math.log10(max(razao_soma, 1.0)) / 2.0))    # 1×→0 · 10×→0,5 · 100×→1
    p_n = max(0.0, min(1.0, (n - MIN_OBS) / 20.0))
    return round(0.45 * p_teto + 0.25 * p_soma + 0.20 * p_tempo + 0.10 * p_n, 3)


def triagem(con: sqlite3.Connection, *, exercicio: int, tipo: str = "compras",
            min_obs: int = MIN_OBS, limite_ug: str | None = None) -> dict:
    """Fila de candidatos a fracionamento no exercício, pela ótica do pagamento (OB do SIAFE).

    Retorna {candidatos:[...], obs_lidas, obs_descartadas_status, obs_descartadas_credor, limite, ato}.
    Cada candidato traz UG, credor, n_obs, soma, intervalo mediano, prioridade, processos e a ressalva
    honesta do que a fonte NÃO permite afirmar."""
    con.row_factory = sqlite3.Row
    sql = ("SELECT ug_emitente, credor, nome_credor, data_emissao, valor, processo, numero_ob, status "
           "FROM ob_orcamentaria_siafe WHERE exercicio = ?")
    params: list = [exercicio]
    if limite_ug:
        sql += " AND ug_emitente = ?"
        params.append(limite_ug)
    linhas = con.execute(sql, params).fetchall()
    limite = limite_dispensa(exercicio, tipo)
    grupos: dict[tuple, list[dict]] = {}
    desc_status = desc_credor = 0
    for r in linhas:
        if not _pago(r["status"]):
            desc_status += 1
            continue
        nome = (r["nome_credor"] or "").strip()
        if not nome or _CREDOR_NAO_LICITAVEL.search(nome):
            desc_credor += 1
            continue
        valor = float(r["valor"] or 0)
        if valor <= 0 or valor >= limite:      # acima do teto ⇒ não é a manobra da dispensa por valor
            continue
        chave = (r["ug_emitente"], (r["credor"] or nome).strip())
        grupos.setdefault(chave, []).append(
            {"data": _data(r["data_emissao"]), "valor": valor, "processo": r["processo"],
             "numero_ob": r["numero_ob"], "nome_credor": nome})
    candidatos = []
    desc_processo_unico = 0
    for (ug, credor), obs in grupos.items():
        if len(obs) < min_obs:
            continue
        # FRACIONAMENTO é picar a MESMA necessidade em CONTRATAÇÕES separadas. Várias Ordens Bancárias
        # do MESMO processo são parcelas de um contrato só (medido no real: 84 OBs no mesmo dia ao
        # mesmo credor). Exige-se, portanto, pelo menos `min_obs` PROCESSOS distintos.
        processos_distintos = {o["processo"] for o in obs if o["processo"]}
        if len(processos_distintos) < min_obs:
            desc_processo_unico += 1
            continue
        soma = sum(o["valor"] for o in obs)
        if soma <= limite:
            continue
        rente = [o for o in obs if o["valor"] >= limite * FAIXA_RENTE_AO_TETO]
        datas = sorted(o["data"] for o in obs if o["data"])
        intervalos = [(b - a).days for a, b in zip(datas, datas[1:])] if len(datas) > 1 else []
        mediana = statistics.median(intervalos) if intervalos else None
        candidatos.append({
            "grau": "a_verificar",             # NUNCA vermelho: falta objeto e modalidade
            "ug_emitente": ug, "credor": credor, "nome_credor": obs[0]["nome_credor"],
            "exercicio": exercicio, "n_obs": len(obs), "n_processos": len(processos_distintos),
            "soma": round(soma, 2),
            "limite_dispensa": limite, "razao_soma_limite": round(soma / limite, 2),
            "intervalo_mediano_dias": mediana,
            "primeira_ob": datas[0].isoformat() if datas else None,
            "ultima_ob": datas[-1].isoformat() if datas else None,
            "n_rente_ao_teto": len(rente),
            "prioridade": _prioridade(mediana, soma / limite, len(obs), len(rente) / len(obs)),
            "processos": [o["processo"] for o in obs if o["processo"]][:20],
            "obs": [o["numero_ob"] for o in obs][:20],
            "resumo": (f"{len(obs)} Ordens Bancárias ({len(processos_distintos)} processos distintos) "
                       f"pagas à mesma empresa pela UG {ug} em {exercicio}, "
                       f"todas abaixo do limite de dispensa (R$ {limite:,.2f}) e somando "
                       f"R$ {soma:,.2f} — {soma/limite:.1f}× o teto"
                       + (f", com intervalo mediano de {mediana:.0f} dia(s) entre pagamentos" if mediana
                          is not None else "")
                       + (f". {len(rente)} pagamento(s) ficaram RENTES ao teto (≥80% do limite) — encaixe "
                          "no valor da dispensa é o sinal mais forte desta família" if rente else "") + "."),
            "acao": ("puxar os processos listados (SEI) e verificar OBJETO e MODALIDADE: se forem do mesmo "
                     "ramo de atividade e contratados por dispensa em razão do valor, há indício de "
                     "fracionamento (art. 75, §1º); se forem contrato licitado, ata de registro de preços "
                     "ou hipótese própria de dispensa/inexigibilidade, não há."),
            "ressalva": ("TRIAGEM, não achado: o SIAFE não informa o OBJETO nem a MODALIDADE da "
                         "contratação, e seu número de processo não casa com o do SEI — por isso não se "
                         "afirma fracionamento aqui. Pagamento ≠ irregularidade; presunção de legitimidade."),
            "fundamento": f"art. 75, §1º, I e II, Lei 14.133/2021 · limite do exercício: {ato_normativo(exercicio)}",
            "fonte": "fracionamento_siafe (OB paga — §2)",
        })
    candidatos.sort(key=lambda c: (-c["prioridade"], -c["soma"]))
    return {"candidatos": candidatos, "obs_lidas": len(linhas),
            "obs_descartadas_status": desc_status, "obs_descartadas_credor": desc_credor,
            "grupos_descartados_processo_unico": desc_processo_unico,
            "exercicio": exercicio, "limite_dispensa": limite, "ato": ato_normativo(exercicio),
            "fonte": "fracionamento_siafe (OB paga — §2)"}
