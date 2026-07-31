# -*- coding: utf-8 -*-
"""O parecer diz o que esta errado E como fica certo.

Pedido do dono: "melhorar MUITO cada uma das analises juridicas". O salto nao e
achar mais vicio — e fechar o outro lado. Ate 2026-07-25 o catalogo dizia o que
estava errado e parava ali; quem vai representar ao tribunal precisa da clausula
REESCRITA, senao o orgao recebe o apontamento e nao sabe o que redigir, e a
diligencia volta com o mesmo vicio escrito de outro jeito.

Regras que este teste trava:
1. vicio que e TEXTO de edital (tem `clausulas`) precisa de redacao-conforme;
2. a redacao cita DISPOSITIVO — redline sem base legal nao se sustenta em
   representacao;
3. e escrita na voz do edital, nao como conselho ao gestor.
"""

import re

import pytest

from compliance_agent.knowledge.catalogo_vicios import CATALOGO, obter

# Vicios que sao CONDUTA e nao texto: nao ha clausula a reescrever. Cada um aqui e
# uma decisao, nao um esquecimento — cartel nao se conserta mudando o edital.
SEM_CLAUSULA_A_REESCREVER = {
    "cartel_rodizio", "propostas_cobertura", "desconto_irrisorio",
    "digitais_compartilhadas", "licitante_unico_supressao", "proposta_dia_nao_util",
    "cotacoes_combinadas", "empresa_fachada", "servidor_socio", "vinculo_politico",
    "sancionada_contratada", "cnae_incompativel", "atestado_cruzado",
    "subcontratacao_cruzada", "inabilitacao_seletiva", "entrega_fantasma",
    "sub_rogacao_ilegal", "execucao_financeira_anomala", "fracionamento_despesa",
    "emergencia_fabricada", "contratacao_direta_indevida", "planejamento_fachada",
    "deserto_fracassado_dirigido", "republicacao_dirigida", "homologado_acima_estimado",
    "clausula_restritiva_combinada",
    # 2026-07-30 — `propostas_gemeas` (J9) e de CONDUTA, como os irmaos de conluio ja aqui
    # (propostas_cobertura, digitais_compartilhadas, cotacoes_combinadas): duas propostas que
    # sao a mesma planilha com um percentual aplicado nao se conserta reescrevendo clausula de
    # edital. O que cabe e diligencia e representacao (Art. 90 Lei 8.666/Art. 337-F CP;
    # Art. 36 Lei 12.529/2011 — CADE).
    "propostas_gemeas",
    # 2026-07-29 — os seis vicios de ADITIVO catalogados hoje (X7..X12). Todos sao de CONDUTA na
    # execucao do contrato, nao de texto de edital: nao ha clausula a reescrever num aditivo
    # assinado depois do fim da vigencia, numa supressao acima do limite, num aditivo sem
    # instrucao, num objeto descaracterizado, num reequilibrio sem alea comprovada nem numa
    # planilha com quantitativos anomalos. O que cabe a cada um e diligencia ou representacao,
    # e isso ja esta no campo `escalada` de cada vicio.
    "reequilibrio_indevido", "aditivo_retroativo", "supressao_abusiva",
    "aditivo_desinstruido", "objeto_descaracterizado", "quantitativos_manipulados",
}


def _com_redacao():
    return [v for v in CATALOGO if (v.redacao_conforme or "").strip()]


def test_existe_redacao_conforme_no_catalogo():
    assert _com_redacao(), "nenhum vicio tem redacao-conforme — o parecer so acusa"


def test_redacao_cita_dispositivo():
    """Redline sem base legal nao se sustenta em representacao."""
    sem_base = [
        v.id for v in _com_redacao()
        if not re.search(r"(art\.|Lei\s+14\.133|Sumula|Súmula)", v.redacao_conforme)
    ]
    assert not sem_base, (
        "redacao-conforme sem dispositivo citado: " + ", ".join(sem_base)
    )


def test_redacao_e_clausula_e_nao_conselho():
    """Voz do edital. 'O orgao deve...' e conselho; a peca precisa do texto pronto."""
    conselho = [
        v.id for v in _com_redacao()
        if re.search(r"\b(o [oó]rg[aã]o deve|recomenda-se|sugere-se|dever[ií]a)\b",
                     v.redacao_conforme, re.I)
    ]
    assert not conselho, (
        "redacao-conforme escrita como conselho, nao como clausula: " + ", ".join(conselho)
    )


@pytest.mark.parametrize("vid", sorted({
    "especificacao_dirigida", "barreira_habilitacao", "atestado_unico",
    "faturamento_minimo_exigido", "garantia_proposta_excessiva", "lote_pacote",
    "recorte_geografico", "aditivo_excessivo", "carona_abusiva",
}))
def test_vicios_de_clausula_criticos_tem_redacao(vid):
    """Os que mais aparecem em edital dirigido. Se um perder a redacao, o teste fala."""
    v = obter(vid)
    assert v is not None, f"vicio {vid} sumiu do catalogo"
    assert (v.redacao_conforme or "").strip(), (
        f"{vid} ({v.nome}) e vicio de CLAUSULA e ficou sem redacao-conforme"
    )


def test_cobertura_declarada_e_honesta():
    """O que falta e DECLARADO, nunca disfarcado.

    Vicio de conduta nao tem clausula a reescrever, e isso e uma decisao — esta na
    lista `SEM_CLAUSULA_A_REESCREVER`. O que nao pode e um vicio de texto ficar sem
    redacao E sem estar declarado: aí a lacuna vira silencio.
    """
    ids = {v.id for v in CATALOGO}
    fantasmas = SEM_CLAUSULA_A_REESCREVER - ids
    assert not fantasmas, (
        "a lista de isencao cita vicio que nao existe mais: " + ", ".join(sorted(fantasmas))
    )
    sem_redacao_e_sem_isencao = sorted(
        v.id for v in CATALOGO
        if not (v.redacao_conforme or "").strip() and v.id not in SEM_CLAUSULA_A_REESCREVER
    )
    assert not sem_redacao_e_sem_isencao, (
        "vicio sem redacao-conforme e sem estar declarado como conduta: "
        + ", ".join(sem_redacao_e_sem_isencao)
        + " — ou escreva a redacao, ou declare na lista com o motivo"
    )
