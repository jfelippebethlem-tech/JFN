"""
Varredura simples de OBs (ciclo do Auditor 24h do Hermes, `hermes_goal._ciclo_auditor_completo`).

Gera alertas `sem_sei`, `valor_redondo`, `concentracao_favorecido_ug` (o antigo `fracionamento_suspeito` saiu na
O4.8) e uma pendência fixa de investigação complementar (TCU 6.100/2022 — empresa irregular; TCU 3.654/2020 —
conflito de interesse; publicação no PNCP), sem apontar culpado enquanto a base não tiver esses dados integrados.
"""
from __future__ import annotations

import json
from collections import defaultdict

from compliance_agent.database.models import get_session, init_db, Alerta
from compliance_agent.reporting.intel_base import moeda

# Limiares desta varredura (antes num `ConfiguracaoAuditoria` de 180 linhas do qual só estes três eram lidos).
TOLERANCIA_VALOR_REDONDO = 50.0
MIN_PAGAMENTOS_MESMO_FAVORECIDO_UG = 3


def gerar_alerta(tipo: str, severidade: str, id_ob: int | None, descricao: str, referencia: str | None = None):
    from compliance_agent.database.models import OrdemBancaria
    sess = get_session()
    try:
        num_ob = None
        if id_ob is not None:
            ob = sess.query(OrdemBancaria).filter_by(id=id_ob).first()
            if ob:
                num_ob = ob.numero_ob
        alerta = Alerta(
            tipo=tipo,
            severidade=severidade,
            titulo=(referencia or num_ob or f"OB {id_ob}"),
            descricao=descricao,
            data_referencia=None,
            evidencias=json.dumps({"id_ob": id_ob, "numero_ob": num_ob}, ensure_ascii=False),
        )
        sess.add(alerta)
        sess.commit()
    finally:
        sess.close()
    return num_ob


def gerar_alertas(session=None) -> int:
    """
    Gera alertas de compliance varrendo todas as OBs e retorna a CONTAGEM.
    Reaproveita uma session se fornecida (senão abre/fecha a própria).
    """
    init_db()
    from sqlalchemy import select
    from compliance_agent.database.models import OrdemBancaria

    sess = session or get_session()
    fechar = session is None
    try:
        rows = sess.execute(select(OrdemBancaria)).scalars().all()
    finally:
        if fechar:
            sess.close()

    obs = []
    for o in rows:
        obs.append({
            "id": o.id,
            "numero_ob": o.numero_ob,
            "data_emissao": str(o.data_emissao) if o.data_emissao else "",
            "valor": float(o.valor) if o.valor is not None else 0.0,
            "favorecido_nome": o.favorecido_nome or "",
            "favorecido_cpf": (o.favorecido_cpf or "").strip(),
            "ug_codigo": o.ug_codigo or "",
            "numero_processo": (o.numero_processo or "").strip(),
            "numero_sei": (o.numero_sei or "").strip(),
            "categoria": o.categoria or "",
        })

    count = 0

    # 1) Sem SEI
    for o in obs:
        if not o["numero_sei"]:
            txt = (
                f"OB {o['numero_ob']} está sem SEI vinculado. "
                "Indício de pagamento irregular por falta de transparência/controle processual."
            )
            gerar_alerta("sem_sei", "alta", o["id"], txt, referencia=o["numero_ob"])
            count += 1

    # 2) Valores redondos
    for o in obs:
        v = o["valor"]
        if v >= 5_000 and abs(v - round(v, -2)) < TOLERANCIA_VALOR_REDONDO:
            txt = (
                f"OB {o['numero_ob']} tem valor redondo suspeito: R$ {moeda(v)}. "
                "Pode indicar estimativa sem cotação real ou direcionamento."
            )
            gerar_alerta("valor_redondo", "media", o["id"], txt, referencia=o["numero_ob"])
            count += 1

    # 3) Concentração por favorecido + UG
    chaves = defaultdict(list)
    for o in obs:
        chave = f"{(o['favorecido_nome'] or '').strip()}|{(o['ug_codigo'] or '').strip()}"
        chaves[chave].append(o)
    for chave, itens in chaves.items():
        if len(itens) >= MIN_PAGAMENTOS_MESMO_FAVORECIDO_UG:
            total = sum(i["valor"] for i in itens)
            txt = (
                f"Concentração de {len(itens)} pagamentos para "
                f"'{chave}' totalizando R$ {moeda(total)}. "
                "Pode indicar direcionamento ou dispensa indevida."
            )
            gerar_alerta("concentracao_favorecido_ug", "alta", itens[0]["id"], txt, referencia=chave)
            count += 1

    # 4) "Fracionamento suspeito por mês" — DEPRECATED e SEM emissão (O4.8, plano mestre v2 §4.5): somava OB por
    #    favorecido × UG × mês contra o teto de dispensa (agregação por CREDOR × teto). Fracionamento é o mesmo
    #    OBJETO em contratações distintas na mesma UG e exercício; só o P4 por objeto emite
    #    (`aplicacao/detectores/fracionamento_objeto.py`). Catraca: tests/test_o48_fracionamento.py.

    # 5) Regras de empresa irregular e conflito de interesse via política
    #    Como ainda não temos base consolidada de empresas/CNPJs, sócios, doações e servidores,
    #    essas regras serão geradas como pendências estruturadas de investigação,
    #    sem indicar culpados sem dados integrados.
    pendencias = [
        "Empresa irregular (TCU 6.100/2022): validar capital social, tempo de abertura, CAGED e endereço.",
        "Conflito de interesse (TCU 3.654/2020): cruzar favorecidos/base de doadores de campanha do gestor e políticos/servidores do órgão.",
        "Publicação PNCP: verificar se contratos/OBs relevantes estão publicados no PNCP.",
    ]
    txt = "Investigações complementares pendentes: " + " | ".join(pendencias)
    gerar_alerta("pendencias_investigacao", "baixa", None, txt, referencia="politica_complementar")
    count += 1

    return count


def main() -> int:
    count = gerar_alertas()
    print(f"Alertas gerados: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
