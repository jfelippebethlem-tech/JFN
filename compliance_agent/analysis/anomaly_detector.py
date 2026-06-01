"""
Detecção de anomalias estatísticas em OBs — sem dependência de ML externo.

Detecta:
  1. Fracionamento por threshold: valores sistematicamente logo abaixo de
     limites legais (R$49.9k, R$79.9k, R$179.9k) — padrão clássico para
     evitar licitação obrigatória (Lei 14.133/21 art. 75)

  2. Concentração anormal: quando os 3 maiores favorecidos absorvem > 70%
     do total pago no mês — possível direcionamento

  3. Rajada de OBs no fim do mês: > 40% das OBs emitidas nos últimos 3 dias
     úteis do mês — padrão de "queima de orçamento" irregular

  4. Valor outlier: OBs com valor > média + 3×desvio (outliers estatísticos)
     para um dado favorecido ou UG

  5. OBs duplicadas: mesmo favorecido + mesmo valor + mesma UG em < 7 dias
"""

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional


def _dias_uteis_no_mes(d: date) -> list[date]:
    """Retorna lista de dias úteis no mês de `d` (exclui sábados e domingos)."""
    import calendar
    ultimo = calendar.monthrange(d.year, d.month)[1]
    return [
        date(d.year, d.month, day)
        for day in range(1, ultimo + 1)
        if date(d.year, d.month, day).weekday() < 5
    ]


def detectar_fracionamento_threshold(obs: list, session) -> list[dict]:
    """
    Flagea OBs cujo valor está entre 90% e 99% de um limite legal crítico.
    Isso indica tentativa deliberada de evitar o gatilho de licitação.
    """
    LIMITES = {
        "dispensa_servicos":   50_000.0,   # Lei 14.133/21 art. 75, II
        "dispensa_obras":      30_000.0,   # art. 75, I
        "concorrencia_peq":   165_000.0,   # art. 75 §1
        "concorrencia_media": 1_650_000.0,
        "concorrencia_alta":  3_300_000.0,
    }
    alertas = []

    for ob in obs:
        if not ob.valor or ob.status == "cancelada":
            continue
        v = ob.valor
        for nome_limite, limite in LIMITES.items():
            if limite * 0.90 <= v < limite:
                pct = (v / limite) * 100
                alertas.append({
                    "tipo": "threshold_fracionamento",
                    "severidade": "alta",
                    "titulo": (
                        f"OB a {100-pct:.1f}% do limite de licitação — "
                        f"R$ {v:,.2f} ({nome_limite.replace('_',' ')})"
                    ),
                    "descricao": (
                        f"OB nº {ob.numero_ob} para '{ob.favorecido_nome}' "
                        f"tem valor R$ {v:,.2f}, apenas {100-pct:.1f}% abaixo do "
                        f"limite de {nome_limite.replace('_',' ')} "
                        f"(R$ {limite:,.0f}). Padrão clássico de fracionamento "
                        f"para fugir da obrigação de licitar."
                    ),
                    "ob_id": ob.id,
                    "numero_ob": ob.numero_ob,
                    "valor": v,
                    "limite": limite,
                    "pct_do_limite": pct,
                })
                break  # um alerta por OB

    return alertas


def detectar_concentracao(obs: list) -> list[dict]:
    """
    Calcula quanto do total pago vai para os 3 maiores favorecidos.
    Acima de 70%: suspeito de direcionamento.
    """
    if not obs:
        return []

    total_geral = sum(o.valor or 0 for o in obs if o.valor)
    if total_geral <= 0:
        return []

    por_favorecido: dict[str, float] = defaultdict(float)
    for ob in obs:
        if ob.valor and ob.favorecido_cpf:
            por_favorecido[ob.favorecido_cpf] += ob.valor

    if not por_favorecido:
        return []

    top3 = sorted(por_favorecido.items(), key=lambda x: -x[1])[:3]
    top3_total = sum(v for _, v in top3)
    pct_top3 = (top3_total / total_geral) * 100

    alertas = []
    if pct_top3 > 70 and total_geral > 100_000:
        from compliance_agent.database.models import OrdemBancaria
        nomes = []
        for cpf, val in top3:
            ob_ref = next((o for o in obs if o.favorecido_cpf == cpf), None)
            nome = (ob_ref.favorecido_nome or cpf) if ob_ref else cpf
            nomes.append(f"{nome} (R$ {val:,.0f})")

        alertas.append({
            "tipo": "concentracao_pagamentos",
            "severidade": "alta" if pct_top3 > 85 else "media",
            "titulo": f"Concentração anormal: top 3 favorecidos absorveram {pct_top3:.0f}% dos pagamentos",
            "descricao": (
                f"Os 3 maiores favorecidos receberam {pct_top3:.1f}% do total pago "
                f"(R$ {top3_total:,.0f} de R$ {total_geral:,.0f}). "
                f"Favorecidos: {'; '.join(nomes)}. "
                f"Alta concentração pode indicar direcionamento ou cartel."
            ),
            "pct_top3": pct_top3,
            "total_geral": total_geral,
            "top3": [(cpf, val) for cpf, val in top3],
        })

    return alertas


def detectar_rajada_fim_mes(obs: list, mes_ref: Optional[date] = None) -> list[dict]:
    """
    Detecta emissão em massa de OBs nos últimos 3 dias úteis do mês.
    Padrão de "queima de orçamento" — muitas vezes sem processo adequado.
    """
    if not obs:
        return []

    ref = mes_ref or date.today()
    dias_uteis = _dias_uteis_no_mes(ref)
    if len(dias_uteis) < 4:
        return []

    ultimos_3 = set(dias_uteis[-3:])
    obs_fim = [o for o in obs if o.data_emissao in ultimos_3]
    total_mes = len(obs)

    pct_fim = len(obs_fim) / total_mes if total_mes > 0 else 0

    alertas = []
    if pct_fim > 0.40 and len(obs_fim) >= 5:
        valor_fim = sum(o.valor or 0 for o in obs_fim)
        alertas.append({
            "tipo": "rajada_fim_mes",
            "severidade": "media",
            "titulo": f"Rajada de OBs no fim do mês: {pct_fim:.0%} das OBs nos últimos 3 dias úteis",
            "descricao": (
                f"{len(obs_fim)} de {total_mes} OBs ({pct_fim:.0%}) foram emitidas "
                f"nos últimos 3 dias úteis do mês, totalizando R$ {valor_fim:,.0f}. "
                f"Padrão de 'queima de orçamento' — pagamentos acelerados sem "
                f"processo adequado ao final do período."
            ),
            "obs_fim_mes": len(obs_fim),
            "total_obs_mes": total_mes,
            "valor_fim_mes": valor_fim,
        })

    return alertas


def detectar_valores_outlier(obs: list) -> list[dict]:
    """
    Detecta OBs com valores estatisticamente anômalos (> média + 3×desvio).
    Calcula por UG (contexto da unidade gestora).
    """
    if len(obs) < 5:
        return []

    por_ug: dict[str, list] = defaultdict(list)
    for ob in obs:
        if ob.valor and ob.valor > 0:
            por_ug[ob.ug_codigo or "SEM_UG"].append(ob)

    alertas = []
    for ug, ug_obs in por_ug.items():
        if len(ug_obs) < 5:
            continue
        valores = [o.valor for o in ug_obs]
        media = statistics.mean(valores)
        try:
            desvio = statistics.stdev(valores)
        except statistics.StatisticsError:
            continue
        if desvio == 0:
            continue

        limiar = media + 3 * desvio
        for ob in ug_obs:
            if ob.valor > limiar and ob.valor > 50_000:
                z_score = (ob.valor - media) / desvio
                alertas.append({
                    "tipo": "valor_outlier",
                    "severidade": "alta",
                    "titulo": f"OB com valor outlier na UG {ug} — R$ {ob.valor:,.0f} (z={z_score:.1f}σ)",
                    "descricao": (
                        f"OB nº {ob.numero_ob} para '{ob.favorecido_nome}' tem valor "
                        f"R$ {ob.valor:,.2f}, que é {z_score:.1f} desvios-padrão acima "
                        f"da média da UG {ug} (média R$ {media:,.0f}, DP R$ {desvio:,.0f}). "
                        f"Verificar se o valor tem respaldo em medição/contrato."
                    ),
                    "ob_id": ob.id,
                    "numero_ob": ob.numero_ob,
                    "valor": ob.valor,
                    "media_ug": media,
                    "desvio_ug": desvio,
                    "z_score": z_score,
                })

    return alertas


def detectar_obs_duplicadas(obs: list) -> list[dict]:
    """
    Detecta OBs com mesmo favorecido + mesmo valor + mesma UG em < 7 dias.
    Pode indicar pagamento duplicado ou conluio.
    """
    alertas = []
    n = len(obs)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = obs[i], obs[j]
            if not (a.valor and b.valor and a.favorecido_cpf and b.favorecido_cpf):
                continue
            if (
                a.favorecido_cpf == b.favorecido_cpf
                and a.ug_codigo == b.ug_codigo
                and abs(a.valor - b.valor) < 0.01
                and abs((a.data_emissao - b.data_emissao).days) <= 7
            ):
                alertas.append({
                    "tipo": "ob_duplicada",
                    "severidade": "alta",
                    "titulo": (
                        f"Possível pagamento duplicado — R$ {a.valor:,.2f} "
                        f"para {a.favorecido_nome or a.favorecido_cpf}"
                    ),
                    "descricao": (
                        f"OBs {a.numero_ob} e {b.numero_ob} têm mesmo favorecido "
                        f"'{a.favorecido_nome}' (CNPJ/CPF {a.favorecido_cpf}), "
                        f"mesmo valor R$ {a.valor:,.2f} e mesma UG {a.ug_codigo}, "
                        f"com diferença de apenas "
                        f"{abs((a.data_emissao - b.data_emissao).days)} dia(s). "
                        f"Verificar se é pagamento duplicado ou parcelas de fracionamento."
                    ),
                    "ob_a": a.numero_ob,
                    "ob_b": b.numero_ob,
                    "valor": a.valor,
                    "favorecido": a.favorecido_nome,
                    "ug": a.ug_codigo,
                })

    return alertas


async def rodar_deteccao_anomalias(session, target_date: date = None) -> list[dict]:
    """
    Pipeline completo de detecção estatística para o dia.
    Salva alertas no banco e retorna lista.
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta

    target_date = target_date or date.today()
    mes_ref = date(target_date.year, target_date.month, 1)

    # OBs do mês para análise estatística
    obs_mes = (
        session.query(OrdemBancaria)
        .filter(
            OrdemBancaria.data_emissao >= mes_ref,
            OrdemBancaria.data_emissao <= target_date,
            OrdemBancaria.status != "cancelada",
        )
        .all()
    )

    todos_alertas = []
    todos_alertas += detectar_fracionamento_threshold(obs_mes, session)
    todos_alertas += detectar_concentracao(obs_mes)
    todos_alertas += detectar_rajada_fim_mes(obs_mes, target_date)
    todos_alertas += detectar_valores_outlier(obs_mes)
    todos_alertas += detectar_obs_duplicadas(obs_mes)

    # Salva no banco
    for a in todos_alertas:
        titulo = a.get("titulo", "")[:300]
        existe = session.query(Alerta).filter_by(titulo=titulo).first()
        if not existe:
            alerta = Alerta(
                tipo=a.get("tipo", "anomalia"),
                severidade=a.get("severidade", "media"),
                titulo=titulo,
                descricao=a.get("descricao", ""),
                evidencias=str({k: v for k, v in a.items()
                                if k not in ("titulo", "descricao", "tipo", "severidade")}),
                data_referencia=target_date,
                ordem_bancaria_id=a.get("ob_id"),
            )
            session.add(alerta)

    session.commit()
    return todos_alertas
