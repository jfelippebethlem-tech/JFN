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
from compliance_agent.reporting.intel_base import moeda

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
    "informatic": ["informatic", "software", "tecnologia", "sistemas", "dados", "computador", "programa"],
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
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(str(s)[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# ── sinais (cada um: perfil → dict|None) ─────────────────────────────────────

def _s_situacao(p):
    """Situação na DATA do pagamento, com o MOTIVO (14/11/2026). O retrato de hoje sem data dava peso 32 a
    empresas pagas antes da baixa e a incorporadas (11 das 15 "risco ALTO" do painel). Sem data/motivo
    (perfil antigo), mantém o comportamento anterior e diz que não apurou."""
    sit = _norm(p.get("situacao"))
    if not any(k in sit for k in ("baixad", "inapt", "suspens", "nula")):
        return None
    from compliance_agent.cruzamentos_intel import _MOTIVOS_SUCESSAO
    motivo = str(p.get("motivo_situacao") or "").strip()
    quando, ultima = _para_data(p.get("data_situacao")), _para_data(p.get("ultima_ob"))
    if motivo in _MOTIVOS_SUCESSAO:
        return None  # incorporação/fusão/cisão: a sucessora responde — não é fachada
    if motivo == "15" and quando and (not ultima or ultima >= quando):
        return dict(id="situacao_irregular", peso=40,
                    detalhe=f"Receita declarou INEXISTÊNCIA DE FATO ({sit.upper()} desde {quando:%d/%m/%Y})")
    if quando and ultima and ultima < quando:
        return dict(id="situacao_irregular", peso=6,
                    detalhe=(f"'{sit.upper()}' desde {quando:%d/%m/%Y}, DEPOIS do último pagamento "
                             f"({ultima:%d/%m/%Y}) — estado atual, não à época"))
    if quando and ultima:
        return dict(id="situacao_irregular", peso=32,
                    detalhe=f"'{sit.upper()}' desde {quando:%d/%m/%Y} e pago depois (último {ultima:%d/%m/%Y})")
    return dict(id="situacao_irregular", peso=32,
                detalhe=f"situação cadastral '{sit.upper()}' na Receita (data/motivo não apurados)")


_SEM_FINS = ("instituto", "associacao", "fundacao", "organizacao social",
             " os ", "oscip", "cooperativa", "cruz vermelha", "santa casa",
             "irmandade", "conselho", "federacao")


def _e_sem_fins_lucrativos(p) -> bool:
    # Natureza jurídica 3xx (Receita) = entidade sem fins lucrativos — fonte primária; o nome é só
    # fallback ("CENTRO DE PESQUISAS…", "ESPAÇO CIDADANIA…" não têm 'associação' no nome).
    if str(p.get("natureza_cod") or "").strip().startswith("3"):
        return True
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
                    detalhe=f"capital R$ {moeda(cap)} vs recebido R$ {moeda(tot)}{razao}")


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
                                f"(R$ {moeda(tot)})")


def _s_socio_unico(p):
    n = p.get("n_socios")
    cap = p.get("capital_social")
    if n == 1 and cap is not None and cap <= 5_000 and not _e_sem_fins_lucrativos(p):
        return dict(id="socio_unico_capital_baixo", peso=12,
                    detalhe=f"sócio único, capital R$ {moeda(cap)}")


# "obra" que não é obra: livro (obras paradidáticas/literárias) e terceirização (mão de obra).
_FALSA_OBRA = re.compile(r"mao[\s-]+de[\s-]+obra|obras?\s+(paradidatic|literari|didatic|de\s+arte|bibliograf)")


def _s_cnae(p):
    cnae, obj = _norm(p.get("cnae")), _norm(p.get("objeto_pago"))
    if not cnae or not obj:
        return None
    # CNAE gravado como CÓDIGO ('4644301') não se compara com radicais de texto: era "incompatível"
    # sempre — 56 das 116 marcas do acervo (14/11/2026). Sem a descrição, o sinal não se apura.
    if re.fullmatch(r"[\d\-./ ]+", cnae):
        return None
    obj = _FALSA_OBRA.sub(" ", obj)
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


def _s_sede_sem_substancia(p):
    """Veredito físico do verificador de sede (sem Google/Mapillary).

    Vem de `compliance_agent.geo.sede_real` — coabitação por PRÉDIO na base da
    Receita, sala compartilhada, e-mail raro repetido, OSM/CEP. Complementa o
    `endereco_compartilhado` acima, que conta por `endereco_norm` COM complemento
    e por isso enxerga sala, não prédio (subconta ~3-6×).
    """
    v = p.get("sede_veredito")
    if v == "forte_suspeita":
        peso = 22
    elif v == "suspeita":
        peso = 12
    else:
        return None
    return dict(id="sede_sem_substancia", peso=peso,
                detalhe=f"verificação de sede real: {v} "
                        f"(suspeita {p.get('sede_score_suspeita')})")


_SINAIS = [_s_situacao, _s_capital, _s_endereco_compartilhado,
           _s_endereco_residencial, _s_aberta_as_vesperas, _s_socio_unico,
           _s_cnae, _s_sancionada, _s_sede_sem_substancia]


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
    from sqlalchemy.exc import SQLAlchemyError
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
    # Receita primária (dump local, 0 ms/CNPJ): data e MOTIVO da situação, e o cadastro de quem não está
    # na tabela `empresas` — 1.089 das 1.921 empresas do alvo do radar ficavam "sem_cadastro" (não
    # avaliadas) com o cadastro disponível no dump (14/11/2026).
    _receita_primaria(p, cnpj)
    # total recebido e 1ª/última OB — OB SIAFE contabilizada (pagamento efetivo); o espelho TFE só
    # entra se o SIAFE não tiver o credor, e a fonte fica registrada.
    try:
        r = session.execute(text(
            "SELECT SUM(valor), MIN(substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||"
            "substr(data_emissao,1,2)), MAX(substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||"
            "substr(data_emissao,1,2)) FROM ob_orcamentaria_siafe WHERE credor=:c AND status='Contabilizado' "
            "AND data_emissao LIKE '__/__/____'"), {"c": cnpj}).fetchone()
        if r and r[0]:
            p.update(total_recebido=r[0], primeira_ob=r[1], ultima_ob=r[2], fonte_total="SIAFE (OB contabilizada)")
    except SQLAlchemyError as exc:  # tabela/coluna ausente: total fica sem dado (INDISPONÍVEL ≠ 0)
        logger.warning("consulta de OB SIAFE falhou p/ CNPJ %s: %s", cnpj, exc)
    try:
        r = session.execute(text(
            "SELECT SUM(valor), MIN(data_emissao), "
            "(SELECT observacao FROM ordens_bancarias WHERE favorecido_cpf=:c "
            " ORDER BY valor DESC LIMIT 1) "
            "FROM ordens_bancarias WHERE favorecido_cpf=:c"), {"c": cnpj}).fetchone()
        if r:
            p["objeto_pago"] = r[2] or ""
            if not p.get("total_recebido"):
                p.update(total_recebido=r[0], primeira_ob=r[1], fonte_total="TFE (espelho)")
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
    # veredito de sede real (tools/sweep_sede_real). Ausente = sinal simplesmente
    # não dispara — nunca vira acusação por falta de dado.
    try:
        s = session.execute(text(
            "SELECT veredito, score_suspeita FROM verificacao_sede_real WHERE cnpj=:c"),
            {"c": cnpj}).fetchone()
        if s:
            p["sede_veredito"], p["sede_score_suspeita"] = s[0], s[1]
    except SQLAlchemyError as exc:  # tabela ainda não criada = sweep nunca rodou
        logger.warning("veredito de sede indisponível p/ CNPJ %s (sinal mudo): %s", cnpj, exc)
    # sanção vigente (reusa a lógica do Núcleo)
    try:
        from compliance_agent.nucleo.adaptador_db import _tem_sancao_vigente
        p["sancionada"] = _tem_sancao_vigente(session, cnpj, date.today())
    except Exception as exc:
        logger.warning("checagem de sanção CEIS/CNEP falhou p/ CNPJ %s (sinal 'sancionada' mudo): %s", cnpj, exc)
    return p


def _receita_primaria(p: dict, cnpj: str) -> None:
    """Completa o perfil com o dump da Receita (`data/receita_estab.db`): situação + data + motivo sempre;
    razão/capital/abertura/CNAE só se a tabela `empresas` não trouxe. Base ausente → nada (sinal mudo)."""
    import sqlite3
    from pathlib import Path
    base = Path("data/receita_estab.db")
    if not base.exists():
        return
    try:
        con = sqlite3.connect(f"file:{base}?mode=ro", uri=True, timeout=10)
        try:
            e = con.execute("SELECT situacao_cadastral, data_situacao, motivo_situacao, data_inicio_atividade, "
                            "cnae_principal FROM estabelecimentos WHERE cnpj=?", (cnpj,)).fetchone()
            m = con.execute("SELECT razao_social, capital_social, natureza_cod FROM empresas WHERE cnpj_basico=?",
                            (cnpj[:8],)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        logger.warning("dump da Receita indisponível p/ %s: %s", cnpj, exc)
        return
    if e:
        # a situação vem do MESMO registro que dá a data e o motivo (o cadastro enriquecido diverge do
        # dump em 31,5% dos irregulares — ver investigacao_dd H-SITUACAO "fontes DIVERGEM")
        if e[0]:
            p["situacao"] = e[0]
        p["data_situacao"] = e[1] if e[1] and e[1] != "00000000" else None
        p["motivo_situacao"] = e[2]
        if not p.get("data_abertura"):
            p["data_abertura"] = e[3]
        if not p.get("cnae"):
            p["cnae"] = e[4]
    if m:
        if not p.get("razao_social"):
            p["razao_social"] = m[0]
        if p.get("capital_social") is None:
            p["capital_social"] = m[1]
        p["natureza_cod"] = m[2]


def avaliar_cnpj(session, cnpj: str) -> dict | None:
    perfil = perfil_do_cnpj(session, cnpj)
    return avaliar_perfil(perfil) if perfil else None
