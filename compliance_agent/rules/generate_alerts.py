"""
Configuração padrão de auditoria do JFN.

Arquivo único de referência para regras, limites e diretrizes que o Hermes
deve seguir em toda análise de OBs, independentemente da UO.

Regras adicionais:
- Vedacao ao fracionamento de despesas para fugir da licitacao (Lei 14.133/2021, art. 8, paragrafo 1).
- Limites de dispensa de licitação (Lei 14.133/2021, art. 75, I e II).
- Verificacao de empresa irregular conforme TCU 6.100/2022 (capital, tempo de abertura,
  CAGED, endereco residencial) — quando houver dados complementares.
- Verificacao de conflito de interesse conforme TCU 3.654/2020, cruzando
  favorecidos com politicos/servidores do orgao (requer base de pessoas/doacoes).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import List

from compliance_agent.database.models import get_session, init_db, Alerta
from compliance_agent.rules.default_audit_config import CONFIG_PADRAO

DB = Path(__file__).resolve().parent.parent.parent / "data" / "compliance.db"


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
    cfg = CONFIG_PADRAO
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
        if v >= 5_000 and abs(v - round(v, -2)) < cfg.valores_redondos_tolerancia:
            txt = (
                f"OB {o['numero_ob']} tem valor redondo suspeito: R$ {v:,.2f}. "
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
        if len(itens) >= cfg.max_pagamentos_mesmo_favorecido_ug_para_alerta:
            total = sum(i["valor"] for i in itens)
            ids = [i["id"] for i in itens[:3]]
            txt = (
                f"Concentração de {len(itens)} pagamentos para "
                f"'{chave}' totalizando R$ {total:,.2f}. "
                "Pode indicar direcionamento ou dispensa indevida."
            )
            gerar_alerta("concentracao_favorecido_ug", "alta", ids[0], txt, referencia=chave)
            count += 1

    # 4) Fracionamento suspeito por mês
    chaves_mes = defaultdict(list)
    for o in obs:
        chave = f"{(o['favorecido_nome'] or '').strip()}|{(o['ug_codigo'] or '').strip()}|{o['data_emissao'][:7]}"
        chaves_mes[chave].append(o)
    for chave, itens in chaves_mes.items():
        if len(itens) >= cfg.min_qtd_pagamentos_fracionamento:
            total = sum(i["valor"] for i in itens)
            menor = min(i["valor"] for i in itens)
            if total > 60_000 and menor < 50_000:
                ids = [i["id"] for i in itens[:3]]
                txt = (
                    f"Possível fracionamento em {len(itens)} pagamentos para "
                    f"'{chave}' no mês, totalizando R$ {total:,.2f}. "
                    "Verificar fraude à licitação e dispensa indevida."
                )
                gerar_alerta("fracionamento_suspeito", "alta", ids[0], txt, referencia=chave)
                count += 1

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
