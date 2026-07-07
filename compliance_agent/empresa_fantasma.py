# -*- coding: utf-8 -*-
"""
Detector de empresa FANTASMA / de FACHADA — determinístico, sem LLM.

Metodologia: nenhuma foto e nenhum sinal isolado condenam. Cruza indícios
objetivos que, juntos, caracterizam empresa sem substância real por trás do
contrato — o padrão clássico de laranja/nota fria/direcionamento:

  situacao_irregular        BAIXADA/INAPTA/SUSPENSA na Receita (recebendo)
  capital_incompativel      capital social ínfimo perante o total recebido
  endereco_compartilhado    dezenas de empresas no MESMO endereço (ninho)
  endereco_residencial      sede em casa/apto (sem estrutura p/ o objeto)
  aberta_as_vesperas        aberta poucos meses antes do 1º grande pagamento
  socio_unico_capital_baixo unipessoal com capital simbólico
  cnae_incompativel         ramo cadastral não casa com o objeto pago
  sancionada                consta em CEIS/CNEP

Saída: {score 0-100, classificacao, sinais:[{id,peso,detalhe}]}. É TRIAGEM
(indício ≠ acusação): manda verificar, não acusa. Alto valor + score alto =
alvo prioritário de fiscalização in loco / foto de fachada (ver
tools/fachada_capturar.py).

A montagem do perfil a partir do banco vive em `perfil_do_cnpj`; a lógica pura
em `avaliar_perfil` (testável offline, tests/test_empresa_fantasma.py).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime

logger = logging.getLogger(__name__)

RISCOS = ("baixo", "medio", "alto")

# palavras-âncora do objeto → radicais de CNAE aderentes (para incompatibilidade)
_OBJ_CNAE = {
    "obra": ["constru", "engenharia", "edific", "reforma", "instala"],
    "constru": ["constru", "engenharia", "edific", "reforma"],
    "reforma": ["constru", "engenharia", "edific", "reforma", "pintura"],
    "medicament": ["farmac", "medicament", "hospital", "saude", "drogaria"],
    "aliment": ["aliment", "refei", "restaurante", "food", "merenda"],
    "refei": ["aliment", "refei", "restaurante"],
    "limpeza": ["limpeza", "conserva", "asseio", "facilit", "apoio"],
    "vigilan": ["vigilan", "seguran", "monitora"],
    "transport": ["transport", "logistic", "frete", "locacao de veiculo"],
    "informatic": ["informatic", "software", "tecnologia", "sistemas", "dados"],
    "combustivel": ["combustivel", "posto", "petroleo"],
    "mobiliario": ["moveis", "mobiliario", "marcenaria"],
}
_ENDERECO_RESIDENCIAL = ("apto", "apartamento", " ap ", "casa", "bloco", "cond ",
                         "condominio", "fundos", "quadra", "lote")


def _norm(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t).strip()


def _para_data(s):
    if isinstance(s, (date, datetime)):
        return s if isinstance(s, date) else s.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s)[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# ── sinais (cada um: perfil → dict|None) ─────────────────────────────────────

def _s_situacao(p):
    sit = _norm(p.get("situacao"))
    if any(k in sit for k in ("baixad", "inapt", "suspens", "nula")):
        return dict(id="situacao_irregular", peso=32,
                    detalhe=f"situação cadastral '{sit.upper()}' na Receita")


_SEM_FINS = ("instituto", "associacao", "fundacao", "organizacao social",
             " os ", "oscip", "cooperativa", "cruz vermelha", "santa casa",
             "irmandade", "conselho", "federacao")


def _e_sem_fins_lucrativos(p) -> bool:
    return any(k in f" {_norm(p.get('razao_social'))} " for k in _SEM_FINS)


def _s_capital(p):
    cap, tot = p.get("capital_social"), p.get("total_recebido")
    if cap is None or tot is None or tot <= 0:
        return None
    if cap <= 0 or tot / cap >= 500:
        razao = f" ({tot / cap:.0f}×)" if cap > 0 else " (capital zero/nulo)"
        # OS/OSCIP/associação legitimamente têm capital ínfimo — sinal fraco,
        # não pode dominar a triagem (senão a lista vira só entidade sem fins)
        peso = 6 if _e_sem_fins_lucrativos(p) else 22
        return dict(id="capital_incompativel", peso=peso,
                    detalhe=f"capital R$ {cap:,.2f} vs recebido R$ {tot:,.2f}{razao}")


def _s_endereco_compartilhado(p):
    n = p.get("empresas_no_endereco") or 0
    if n >= 10:
        return dict(id="endereco_compartilhado", peso=20,
                    detalhe=f"{n} empresas no mesmo endereço normalizado")


def _s_endereco_residencial(p):
    end = _norm(p.get("endereco_bruto"))
    if end and any(t in f" {end} " for t in _ENDERECO_RESIDENCIAL):
        return dict(id="endereco_residencial", peso=10,
                    detalhe="endereço com marca residencial (casa/apto/lote)")


def _s_aberta_as_vesperas(p):
    ab, ob = _para_data(p.get("data_abertura")), _para_data(p.get("primeira_ob"))
    tot = p.get("total_recebido") or 0
    if ab and ob:
        dias = (ob - ab).days
        if 0 <= dias <= 365 and tot >= 500_000:
            return dict(id="aberta_as_vesperas", peso=18,
                        detalhe=f"aberta {dias} dias antes do 1º pagamento "
                                f"(R$ {tot:,.2f})")


def _s_socio_unico(p):
    n = p.get("n_socios")
    cap = p.get("capital_social")
    if n == 1 and cap is not None and cap <= 5_000 and not _e_sem_fins_lucrativos(p):
        return dict(id="socio_unico_capital_baixo", peso=12,
                    detalhe=f"sócio único, capital R$ {cap:,.2f}")


def _s_cnae(p):
    cnae, obj = _norm(p.get("cnae")), _norm(p.get("objeto_pago"))
    if not cnae or not obj:
        return None
    for ancora, radicais in _OBJ_CNAE.items():
        if ancora in obj:
            if not any(r in cnae for r in radicais):
                return dict(id="cnae_incompativel", peso=16,
                            detalhe=f"objeto '{obj[:40]}' vs CNAE '{cnae[:40]}'")
            return None
    return None


def _s_sancionada(p):
    if p.get("sancionada"):
        return dict(id="sancionada", peso=24,
                    detalhe="consta em CEIS/CNEP (sanção)")


_SINAIS = [_s_situacao, _s_capital, _s_endereco_compartilhado,
           _s_endereco_residencial, _s_aberta_as_vesperas, _s_socio_unico,
           _s_cnae, _s_sancionada]


def avaliar_perfil(perfil: dict) -> dict:
    """Perfil (dict) → {score 0-100, classificacao, sinais:[...]}. Puro."""
    sinais = [s for f in _SINAIS if (s := f(perfil))]
    score = min(100, sum(s["peso"] for s in sinais))
    cls = "alto" if score >= 60 else "medio" if score >= 30 else "baixo"
    return {"cnpj": perfil.get("cnpj"), "razao_social": perfil.get("razao_social"),
            "score": score, "classificacao": cls, "sinais": sinais}


# ── montagem do perfil a partir do banco ─────────────────────────────────────

def perfil_do_cnpj(session, cnpj: str) -> dict | None:
    """
    Monta o perfil de sinais a partir do compliance.db. Defensivo: campo
    ausente vira None e o sinal dependente simplesmente não dispara.
    """
    from sqlalchemy import text
    cnpj = re.sub(r"\D", "", str(cnpj or ""))
    if len(cnpj) != 14:
        return None
    p = {"cnpj": cnpj}
    try:
        emp = session.execute(text(
            "SELECT razao_social, situacao, capital_social, data_abertura, "
            "atividade_princ FROM empresas WHERE cnpj=:c"), {"c": cnpj}).fetchone()
    except Exception:
        emp = None
    if emp:
        p.update(razao_social=emp[0], situacao=emp[1], capital_social=emp[2],
                 data_abertura=emp[3], cnae=emp[4])
    # total recebido e 1ª OB
    try:
        r = session.execute(text(
            "SELECT SUM(valor), MIN(data_emissao), "
            "(SELECT observacao FROM ordens_bancarias WHERE favorecido_cpf=:c "
            " ORDER BY valor DESC LIMIT 1) "
            "FROM ordens_bancarias WHERE favorecido_cpf=:c"), {"c": cnpj}).fetchone()
        if r:
            p.update(total_recebido=r[0], primeira_ob=r[1], objeto_pago=r[2] or "")
    except Exception as exc:
        logger.warning("consulta de OBs falhou p/ CNPJ %s (total_recebido/1ª OB sem dado): %s", cnpj, exc)
    # endereço + quantas empresas no mesmo endereço normalizado
    try:
        e = session.execute(text(
            "SELECT endereco, endereco_norm FROM endereco_fornecedor WHERE cnpj=:c"),
            {"c": cnpj}).fetchone()
        if e:
            p["endereco_bruto"] = e[0]
            if e[1]:
                n = session.execute(text(
                    "SELECT COUNT(DISTINCT cnpj) FROM endereco_fornecedor "
                    "WHERE endereco_norm=:e"), {"e": e[1]}).fetchone()
                p["empresas_no_endereco"] = n[0] if n else 1
    except Exception as exc:
        logger.warning("consulta de endereço/co-localizados falhou p/ CNPJ %s: %s", cnpj, exc)
    # nº de sócios
    try:
        emp_id = session.execute(text("SELECT id FROM empresas WHERE cnpj=:c"),
                                 {"c": cnpj}).fetchone()
        if emp_id:
            n = session.execute(text(
                "SELECT COUNT(*) FROM empresa_socios WHERE empresa_id=:i"),
                {"i": emp_id[0]}).fetchone()
            p["n_socios"] = n[0] if n else None
    except Exception as exc:
        logger.warning("consulta de nº de sócios falhou p/ CNPJ %s: %s", cnpj, exc)
    # sanção vigente (reusa a lógica do Núcleo)
    try:
        from compliance_agent.nucleo.adaptador_db import _tem_sancao_vigente
        p["sancionada"] = _tem_sancao_vigente(session, cnpj, date.today())
    except Exception as exc:
        logger.warning("checagem de sanção CEIS/CNEP falhou p/ CNPJ %s (sinal 'sancionada' mudo): %s", cnpj, exc)
    return p


def avaliar_cnpj(session, cnpj: str) -> dict | None:
    perfil = perfil_do_cnpj(session, cnpj)
    return avaliar_perfil(perfil) if perfil else None
