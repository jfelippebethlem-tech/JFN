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


# ───────── citar um órgão de controle não faz do documento uma manifestação dele ─────────

_CLAUSULA_CONTRATUAL = (
    "CONTRATO Nº 01/2025 que entre si celebram o Estado do Rio de Janeiro e a empresa X. "
    "6.12.2 O CONTRATANTE poderá adotar os atos necessários para garantir o recebimento de seus "
    "créditos, na forma recomendada pela Procuradoria Geral do Estado. "
    "6.12.3 Persistindo a irregularidade, o CONTRATANTE deverá adotar as medidas necessárias à "
    "rescisão, em caso de descumprimento de obrigações pela CONTRATADA.")


def test_contrato_que_cita_a_PGE_nao_entra_como_parecer():
    """Medido em 2026-08-04: dos **99 documentos** com sinal de "não atendida" no acervo, só 19
    eram parecer — 20 eram CONTRATO e o resto anexo, termo de referência, recurso, ETP. Cláusula
    contratual padrão ("Persistindo a irregularidade, o CONTRATANTE deverá adotar as medidas")
    virava prova de recomendação ignorada e subia na fila do fiscal. Depois do portão: 99 -> 20,
    com os 19 pareceres verdadeiros preservados."""
    doc = {"ref": "Contrato Nº 01/2025", "tipo": "contrato", "texto": _CLAUSULA_CONTRATUAL}
    assert S.e_manifestacao_de_controle(doc) is False
    assert S.detectar([doc]) == []


def test_parecer_de_verdade_continua_entrando():
    doc = {"ref": "Parecer 2848", "tipo": "parecer",
           "texto": "Fundação Saúde\nDiretoria Jurídica\nPARECER Nº 2848\nrecomenda-se a juntada."}
    assert S.e_manifestacao_de_controle(doc) is True
    assert len(S.detectar([doc])) == 1


def test_nota_tecnica_sem_tipo_canonico_entra_pelo_TITULO():
    """Documento cujo `tipo` o classificador não resolveu, mas cujo título o anuncia."""
    doc = {"ref": "Nota Técnica 12 da Assessoria", "tipo": "outro",
           "texto": "Assessoria Jurídica\nNOTA TÉCNICA 12\nrecomenda-se a revisão da minuta."}
    assert S.e_manifestacao_de_controle(doc) is True


def test_documento_cujo_CABECALHO_nomeia_orgao_de_controle_entra():
    """Sem título revelador, o bloco institucional ainda identifica a manifestação."""
    doc = {"ref": "Documento 55", "tipo": "outro",
           "texto": "Governo do Estado\nControladoria Geral do Estado\nOfício 9\n"
                    "Assunto: auditoria.\nrecomenda-se sanar a falha apontada."}
    assert S.e_manifestacao_de_controle(doc) is True


def test_anexo_qualquer_que_mencione_a_PGE_no_corpo_fica_de_fora():
    doc = {"ref": "Anexo Declarações", "tipo": "anexo",
           "texto": "Declaro para os devidos fins, conforme orientação da Procuradoria Geral do "
                    "Estado, que a empresa recomenda a análise dos documentos."}
    assert S.e_manifestacao_de_controle(doc) is False


def test_suficiencia_nao_aceita_MENCAO_a_PGE_como_parecer_da_PGE():
    """Medido em 2026-08-04: sem o portão de identidade, um contrato, uma certidão de FGTS ou uma
    tela do portal de contratação que MENCIONE a PGE fazia o processo passar por "tem parecer da
    PGE" (nível 3, controle externo). Nos 2.174 processos do acervo, **391 mudam de veredito** —
    e a amostra dos documentos barrados não tem um parecer sequer."""
    docs = [{"ref": "Contrato Nº 01/2025", "tipo": "contrato", "texto": _CLAUSULA_CONTRATUAL}]
    r = S.suficiencia_parecer(docs, "contratacao_direta")
    assert r["veredito"] == "SEM_PARECER_LOCALIZADO"
    assert r["emissores"] == []


def test_suficiencia_com_parecer_de_verdade_da_PGE():
    docs = [{"ref": "Parecer PGE 12", "tipo": "parecer",
             "texto": "Governo do Estado\nProcuradoria Geral do Estado\nPARECER 12\n"
                      "Assunto: dispensa.\nrecomenda-se a instrução."}]
    r = S.suficiencia_parecer(docs, "contratacao_direta")
    assert r["veredito"] == "SUFICIENTE" and "PGE" in r["emissores"]


def test_suficiencia_so_com_juridico_proprio_e_INSUFICIENTE_na_dispensa():
    """O art. 53 entrega a análise ao jurídico do próprio órgão; a exigência de nível 3 é da
    contratação DIRETA, e aí o parecer da casa não basta sozinho."""
    docs = [{"ref": "Parecer 2848", "tipo": "parecer",
             "texto": "Fundação Saúde\nDiretoria Jurídica\nPARECER 2848\n"
                      "Assunto: TAC.\nrecomenda-se a juntada."}]
    r = S.suficiencia_parecer(docs, "contratacao_direta")
    assert r["veredito"] == "PARECER_DE_EMISSOR_INSUFICIENTE"
    assert S.suficiencia_parecer(docs, "contrato")["veredito"] == "SUFICIENTE"
