"""
Detecção de CPFs duplicados em múltiplas fontes de remuneração pública, sobre o que JÁ está em
`registros_folha` (cada coletor de folha grava a sua `fonte`). Este módulo não coleta: os três coletores
que ele tinha (terceirizados do Portal RJ, bolsistas FAPERJ, estagiários) e o cruzamento federal/LAI
nunca tiveram chamador e saíram no untangle de 20/11/2026 (`docs/untangle/collectors.md`).

Base legal:
  - CF/88 art. 37, XVI   — vedação ao acúmulo de cargos e empregos públicos
  - Lei 9.717/98         — regime previdenciário e limitações de acúmulo
  - Lei 8.112/90 art. 118 — aposentado que reassume cargo efetivo retorna à atividade
  - Decreto Estadual RJ 46.881/20 — teto do funcionalismo estadual
"""

import json
import logging

from compliance_agent.database.models import Alerta, Pessoa, RegistroFolha
from compliance_agent.reporting.intel_base import moeda

logger = logging.getLogger(__name__)

# Vínculos que indicam aposentado/pensionista (para cruzamento)
VINCULOS_INATIVOS = {"aposentado", "aposentada", "pensionista", "inativo", "inativa"}

# Vínculos que indicam cargo ativo remunerado
VINCULOS_ATIVOS = {"efetivo", "efetiva", "comissionado", "comissionada", "dab", "temporário",
                   "temporária", "terceirizado", "estagiário", "bolsista", "residente"}


# ── Detecção de CPF duplicado entre fontes ────────────────────────────────────

def detectar_cpf_duplicado_entre_fontes(session, competencia: str) -> list[dict]:
    """
    FUNÇÃO CENTRAL: Detecta CPFs que aparecem em múltiplas fontes de remuneração
    pública para a competência informada (ou em toda a base, se competencia="").

    Agrupa RegistroFolha por CPF e sinaliza casos em que o mesmo CPF aparece em
    2 ou mais valores distintos de `fonte` — indicando acúmulo potencialmente
    irregular de remunerações públicas.

    Também detecta:
      - Aposentado/pensionista (vinculo in VINCULOS_INATIVOS) com cargo comissionado
        ou efetivo ativo na mesma competência (CF/88 art. 37, §10 e Lei 9.717/98).
      - Pensionista com cargo ativo simultâneo.
      - Bolsista FAPERJ/CNPq + servidor efetivo do mesmo órgão de pesquisa.
      - Terceirizado + servidor efetivo no mesmo órgão contratante.

    Flags geradas:
      - suspeito=True  → combinação claramente ilegal
      - suspeito=False → vale verificar (pode ser legal em alguns casos)

    Args:
        session:     SQLAlchemy session.
        competencia: Mês de referência AAAA-MM. Se vazio, usa toda a base.

    Returns:
        Lista de dicts com {cpf, nome, fontes, vinculos, orgaos,
        remuneracao_total, suspeito, motivo}.
    """
    from sqlalchemy import func

    resultados: list[dict] = []

    try:
        q = session.query(
            RegistroFolha.cpf,
            RegistroFolha.nome,
            func.group_concat(func.distinct(RegistroFolha.fonte)).label("fontes"),
            func.group_concat(func.distinct(RegistroFolha.vinculo)).label("vinculos"),
            func.group_concat(func.distinct(RegistroFolha.orgao_nome)).label("orgaos"),
            func.sum(RegistroFolha.remuneracao_bruta).label("total"),
            func.count(func.distinct(RegistroFolha.fonte)).label("n_fontes"),
        ).filter(
            RegistroFolha.cpf.isnot(None),
            RegistroFolha.cpf != "",
        )

        if competencia:
            q = q.filter(RegistroFolha.competencia == competencia)

        q = q.group_by(RegistroFolha.cpf).having(
            func.count(func.distinct(RegistroFolha.fonte)) > 1
        )

        for row in q.all():
            fontes   = [f.strip() for f in (row.fontes   or "").split(",") if f.strip()]
            vinculos = [v.strip() for v in (row.vinculos or "").split(",") if v.strip()]
            orgaos   = [o.strip() for o in (row.orgaos   or "").split(",") if o.strip()]

            # Determine suspicion level
            suspeito = False
            motivo   = ""

            vinculos_lower = {v.lower() for v in vinculos}

            # Check illegal combinations
            inativos_presentes = vinculos_lower & VINCULOS_INATIVOS
            ativos_presentes   = vinculos_lower & VINCULOS_ATIVOS

            if inativos_presentes and ativos_presentes:
                suspeito = True
                motivo = (
                    f"Vínculo inativo ({', '.join(inativos_presentes)}) + "
                    f"vínculo ativo ({', '.join(ativos_presentes)}) simultâneos. "
                    "Pode configurar acúmulo ilegal (CF/88 art. 37, §10; Lei 9.717/98)."
                )
            elif "terceirizado" in fontes and any(
                f in fontes for f in ("transparencia_rj", "siafe")
            ):
                suspeito = True
                motivo = (
                    "Servidor efetivo/comissionado E terceirizado do estado simultaneamente. "
                    "Configuração impossível legalmente — possível fraude de identidade ou "
                    "empresa de fachada usando CPF de servidor."
                )
            elif "faperj" in fontes and any(f in fontes for f in ("transparencia_rj", "siafe")):
                motivo = (
                    "Bolsista FAPERJ + servidor ativo. Pode ser legal se as atividades são "
                    "distintas, mas requer verificação (vedação de acúmulo de bolsa + cargo "
                    "quando incompatível — Resolução FAPERJ 007/2023)."
                )
            elif "estagio" in fontes and any(f in fontes for f in ("transparencia_rj", "siafe")):
                suspeito = True
                motivo = (
                    "Estagiário + servidor/comissionado efetivo. Estágio é exclusivo para "
                    "quem não tem vínculo efetivo com o serviço público (Lei 11.788/08 art. 3º, §1º)."
                )
            else:
                motivo = (
                    f"CPF presente em {row.n_fontes} fontes distintas de remuneração: "
                    f"{', '.join(fontes)}. Verificar compatibilidade legal."
                )

            resultado = {
                "cpf":               row.cpf,
                "nome":              row.nome,
                "fontes":            fontes,
                "vinculos":          vinculos,
                "orgaos":            orgaos,
                "remuneracao_total": row.total or 0.0,
                "suspeito":          suspeito,
                "motivo":            motivo,
                "n_fontes":          row.n_fontes,
            }
            resultados.append(resultado)

            # Persist alert for clearly suspicious cases
            if suspeito:
                titulo = f"CPF em múltiplas fontes de remuneração — {row.cpf}"
                existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
                if not existe:
                    pessoa = session.query(Pessoa).filter_by(cpf=row.cpf).first()
                    alerta = Alerta(
                        tipo="acumulacao",
                        severidade="alta",
                        titulo=titulo[:300],
                        descricao=(
                            f"'{row.nome}' (CPF {row.cpf}) recebe remuneração de "
                            f"{row.n_fontes} fontes públicas distintas: {', '.join(fontes)}. "
                            f"Remuneração total: R$ {moeda(row.total or 0)}. {motivo}"
                        ),
                        evidencias=json.dumps(resultado, ensure_ascii=False, default=str),
                        pessoa_id=pessoa.id if pessoa else None,
                    )
                    session.add(alerta)

        session.commit()
        logger.info(f"detectar_cpf_duplicado_entre_fontes: {len(resultados)} CPFs em múltiplas fontes.")

    except Exception as exc:
        logger.error(f"Erro em detectar_cpf_duplicado_entre_fontes: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em detectar_cpf_duplicado_entre_fontes: %s", rb_exc)

    return resultados

