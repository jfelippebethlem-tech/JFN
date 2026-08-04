# -*- coding: utf-8 -*-
"""Testes do detector de recomendações não atendidas no SEI (camada determinística, sem LLM/rede)."""
from __future__ import annotations

from compliance_agent import sei_recomendacoes as S


DESP_PGE_NAO = {"ref": "DOC-10", "tipo": "Parecer", "texto":
    "PROCURADORIA GERAL DO ESTADO. Parecer nº 123. Esta Procuradoria RECOMENDA a anulação do item 4 do edital por "
    "restrição à competitividade. Em despacho posterior, verifica-se que a recomendação NÃO FOI ATENDIDA, "
    "permanecendo a ressalva. Reitera-se a impugnação."}
DESP_CGE_OK = {"ref": "DOC-11", "tipo": "Despacho", "texto":
    "CONTROLADORIA GERAL DO ESTADO determina a juntada da pesquisa de preços. Recomendação sanada conforme fls. 50."}
DOC_NEUTRO = {"ref": "DOC-12", "tipo": "Ofício", "texto":
    "Encaminho o processo para pagamento da nota fiscal nº 99, conforme empenho."}


def test_detecta_pge_recomendacao_nao_atendida():
    a = S.detectar([DESP_PGE_NAO])
    assert len(a) == 1
    assert a[0]["emissor"] == "PGE"
    assert a[0]["sinal_nao_atendida"] is True
    assert a[0]["status"] == "INDICIO_NAO_ATENDIDA"
    assert a[0]["trechos_nao_atendida"]


def test_detecta_cge_recomendacao_sem_sinal_de_nao_atendida():
    a = S.detectar([DESP_CGE_OK])
    assert len(a) == 1 and a[0]["emissor"] == "CGE"
    assert a[0]["sinal_nao_atendida"] is False
    assert a[0]["status"] == "RECOMENDACAO_A_CONFERIR"


def test_ignora_doc_sem_orgao_de_controle():
    assert S.detectar([DOC_NEUTRO]) == []


def test_classificar_emissor():
    assert S.classificar_emissor("Assembleia... Assessoria Jurídica opina") == "ASSESSORIA_JURIDICA"
    assert S.classificar_emissor("Tribunal de Contas do Estado") == "TCE"
    assert S.classificar_emissor("memorando interno qualquer") is None


def test_analisar_sem_llm_honesto():
    r = S.analisar([DESP_PGE_NAO, DESP_CGE_OK, DOC_NEUTRO], usar_llm=False)
    assert r["n_candidatos"] == 2
    assert r["n_indicio_nao_atendida"] == 1
    assert "não atendida" in r["leitura"].lower()


def test_leitura_vazia_honesta():
    r = S.analisar([DOC_NEUTRO], usar_llm=False)
    assert r["n_candidatos"] == 0
    assert "INDISPONÍVEL" in r["leitura"]


# ═══ ATENDER a ressalva é acolhê-la — e o objeto decide (2026-08-04) ═══

def test_atendimento_ao_PARECER_e_acolhimento():
    """Medido nos 90 processos de maior risco: 6 de 65 respondiam o parecer ponto a ponto e eram
    acusados de "nenhum documento registra acatamento". Acusar de silêncio quem respondeu é
    acusação sobre servidor nomeado."""
    from compliance_agent.sei_recomendacoes import _RE_ACOLHIMENTO
    for texto in [
        "encaminho o presente expediente em atendimento ao Parecer Nº 130/2022, que condicionou",
        "Recomendação atendida através do documento de Oficialização de Demanda",
        "Em atendimento ao parecer jurídico 82243420, aduz-se o seguinte: Quanto ao item 1",
    ]:
        assert _RE_ACOLHIMENTO.search(texto), texto


def test_atendimento_ao_DESPACHO_nao_e_acolhimento_do_parecer():
    """"Em atendimento ao despacho (89639282), encaminhamos o p.p." é encaminhamento de rotina —
    aceitar "atendida" solto transformaria tramitação em acatamento do controle prévio."""
    from compliance_agent.sei_recomendacoes import _RE_ACOLHIMENTO
    assert not _RE_ACOLHIMENTO.search(
        "Em atendimento ao despacho (89639282), encaminhamos o p.p. com a classificação")


# ───────── quem EMITE está no cabeçalho, não numa citação do corpo (2026-08-04) ─────────

_PARECER_DIRJUR = """Governo do Estado do Rio de Janeiro
Fundação Saúde
Diretoria Jurídica
PARECER Nº 2848/2024 FS/DIRJUR
PROCESSO Nº SEI-080002/020895/2024
DATA: Rio de Janeiro, 17 de setembro de 2024
INTERESSADO: Fundação Saúde do Estado do Rio de Janeiro
Assunto: Análise de Minuta de Termo de Ajuste de Contas. Incidência do Enunciado nº 08 da PGE-RJ.
Indenização pelos serviços prestados. Recomendações."""


def test_parecer_do_juridico_do_proprio_orgao_nao_e_da_PGE():
    """A regra casava qualquer menção no texto inteiro, e um parecer que apenas CITA a PGE virava
    parecer DA PGE. Medido em 2026-08-04 nos 755 pareceres do acervo: **67 dos 210 rotulados PGE
    (32%)** são da diretoria/assessoria jurídica do próprio órgão. Como PGE vale nível 3 (controle
    EXTERNO) e o jurídico próprio vale 1, a casa creditava a si mesma o controle externo — a mesma
    confusão que a correção do art. 53 desfez em 2026-08-03.
    """
    assert S.classificar_emissor(_PARECER_DIRJUR) == "ASSESSORIA_JURIDICA"


def test_parecer_da_PGE_de_verdade_continua_PGE():
    texto = ("Governo do Estado do Rio de Janeiro\nProcuradoria Geral do Estado\n"
             "PARECER PGE Nº 12/2024\nAssunto: minuta de contrato.")
    assert S.classificar_emissor(texto) == "PGE"


def test_sem_bloco_institucional_o_corpo_ainda_vale():
    """Parecer cujo timbre não foi capturado (OCR) não pode virar 'emissor desconhecido' —
    INDISPONÍVEL de captura não é ausência de emissor."""
    assert S.classificar_emissor("segue manifestação da Procuradoria Geral do Estado nos autos") == "PGE"


def test_a_ementa_nao_decide_o_emissor():
    """"Assunto:"/"Ementa:" abre a parte que descreve o MÉRITO e cita normas de outros órgãos; sem
    esse corte, a janela de cabeçalho não resolveria nada."""
    texto = "Secretaria X\nControle Interno\nPARECER 9\nEmenta: aplica-se o enunciado da PGE-RJ."
    assert S.classificar_emissor(texto) == "CONTROLE_INTERNO"


# ───────── "reitera-se" sozinho é conectivo, não descumprimento (2026-08-04) ─────────

def test_reitera_se_retorico_nao_e_sinal_de_nao_atendida():
    """Medido nos 755 pareceres do acervo: dos 73 documentos com sinal de "não atendida",
    **49 (67%) tinham como ÚNICO gatilho "reitera-se"** — o conectivo de qualquer texto jurídico.
    Exemplo real, do Parecer 2848/2024 FS/DIRJUR que autoriza um TAC de R$ 6,5 mi."""
    texto = ("Desta feita, entende-se que, caso ausente a má-fé do particular (que, reitera-se, "
             "caso existente deverá ser comprovada nos autos), poderá ocorrer a indenização.")
    assert not S._RE_NAO_ATENDIDA.search(texto)


def test_reiterar_uma_RECOMENDACAO_continua_sendo_sinal():
    """A intenção do padrão era esta e continua valendo: o parecer que reitera um apontamento
    está dizendo que ele não foi atendido."""
    for texto in ("reitera-se a recomendação de juntada do parecer",
                  "reitera a ressalva do parecer anterior",
                  "reitero a determinação desta Corte",
                  "reiteramos as recomendações não cumpridas"):
        assert S._RE_NAO_ATENDIDA.search(texto), texto


def test_reiterar_pedido_de_cotacao_nao_e_controle():
    """"Reiterada a solicitação de cotação" é reenvio de pedido de preço — não há apontamento
    nenhum sendo repetido."""
    assert not S._RE_NAO_ATENDIDA.search(
        "o primeiro e-mail foi enviado em 20/02/2024, sendo reiterada a solicitação em 27/02/2024")


def test_os_outros_gatilhos_seguem_valendo():
    for texto in ("a ressalva não foi atendida", "houve descumprimento do parecer",
                  "permanece a pendência apontada", "a recomendação não foi sanada"):
        assert S._RE_NAO_ATENDIDA.search(texto), texto
