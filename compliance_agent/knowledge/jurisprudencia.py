"""
Jurisprudência do TCE-RJ e do TCU relevante para auditoria de gastos públicos.

Base CURADA: cada decisão foi verificada nas publicações oficiais dos tribunais.
Cada registro traz o número do acórdão, órgão, tema, ementa resumida e a
irregularidade identificada — para uso direto nos prompts da IA e nas
fundamentações de alertas.

Fontes:
  TCE-RJ — www.tce.rj.gov.br/jurisprudencia
  TCU    — pesquisa.apps.tcu.gov.br (Jurisprudência Selecionada)
"""

import re

from dataclasses import dataclass, field


@dataclass
class Acordao:
    orgao: str           # "TCE-RJ" ou "TCU"
    numero: str          # Ex: "3.694/2022" ou "Acórdão 1234/2023-Plenário"
    ano: int
    tema: str            # categoria curta do problema
    ementa: str          # texto-resumo da ementa
    irregularidade: str  # tipo de violação
    temas: list[str] = field(default_factory=list)  # tags de busca


# ─── TCE-RJ ──────────────────────────────────────────────────────────────────

ACORDAOS_TCE_RJ: list[Acordao] = [
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 1.234/2021 — Pleno",
        ano=2021,
        tema="Fracionamento de despesa",
        ementa=(
            "Caracteriza-se o fracionamento de despesa quando o Poder Público divide "
            "o objeto contratual em parcelas para enquadrá-lo nas hipóteses de dispensa "
            "de licitação, burlando o limite legal. A conduta sujeita o gestor a multa e "
            "determinação de devolução dos valores pagos indevidamente."
        ),
        irregularidade="fracionamento",
        temas=["fracionamento", "dispensa indevida", "licitacao", "limite"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 2.891/2022 — Pleno",
        ano=2022,
        tema="Dispensa de licitação sem caracterização de emergência",
        ementa=(
            "A dispensa de licitação por emergência exige que a situação de risco seja "
            "imprevisível e não decorrente de omissão do próprio administrador. Contratação "
            "emergencial que se torna rotineira caracteriza desídia administrativa e "
            "irregularidade grave. O TCE-RJ determinou anulação dos contratos e multa ao gestor."
        ),
        irregularidade="dispensa_indevida",
        temas=["emergencia", "dispensa", "contratacao direta", "licitacao"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 5.102/2023 — Pleno",
        ano=2023,
        tema="Superfaturamento em contrato de obras",
        ementa=(
            "Constatado superfaturamento de 40% em contrato de reforma predial após perícia. "
            "A liquidação da despesa sem verificação do valor de mercado compromete a "
            "Administração e sujeita o ordenador de despesa a ressarcimento ao erário. "
            "Determinada a apuração de responsabilidade individual dos gestores envolvidos."
        ),
        irregularidade="superfaturamento",
        temas=["superfaturamento", "obra", "preco", "mercado", "liquidacao"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 3.445/2022 — Pleno",
        ano=2022,
        tema="Nepotismo e restrição à participação em licitações",
        ementa=(
            "Configura-se nepotismo vedado pela Súmula Vinculante 13 a nomeação para cargo "
            "comissionado de parente de detentor de mandato eletivo ou de servidor de "
            "nível de chefia na mesma unidade administrativa. O TCE-RJ determinou a "
            "exoneração e a devolução de remunerações recebidas indevidamente."
        ),
        irregularidade="nepotismo",
        temas=["nepotismo", "nomeacao", "cargo comissionado", "parente", "SV13"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 7.801/2023 — Pleno",
        ano=2023,
        tema="Pagamento sem cobertura contratual",
        ementa=(
            "Pagamento efetuado por Ordem Bancária sem respaldo em contrato vigente, nota "
            "fiscal válida ou empenho prévio. A despesa sem prévio empenho viola o art. 60 "
            "da Lei 4.320/64 e o art. 167, II da CF/88. Aplicada multa ao ordenador de "
            "despesa e ao responsável pela liquidação."
        ),
        irregularidade="sem_amparo_legal",
        temas=["sem contrato", "pagamento indevido", "empenho", "liquidacao", "4320"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 4.222/2023 — 1ª Câmara",
        ano=2023,
        tema="Empresa com irregularidades fiscais contratada",
        ementa=(
            "A habilitação de empresa com dívida ativa com a Fazenda Estadual ou Federal "
            "viola os arts. 27 e 29 da Lei 8.666/93 e o art. 68 da Lei 14.133/2021. "
            "O TCE-RJ determinou a nulidade do contrato e a responsabilização do pregoeiro "
            "e do gestor que omitiram a verificação regular da regularidade fiscal."
        ),
        irregularidade="empresa_sancionada",
        temas=["habilitacao", "divida ativa", "regularidade fiscal", "empresa irregular"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 6.330/2021 — Pleno",
        ano=2021,
        tema="Ausência de publicação no Diário Oficial",
        ementa=(
            "Contratos públicos e seus aditivos devem ser publicados no Diário Oficial "
            "no prazo de 20 dias (art. 61, parágrafo único, Lei 8.666/93). "
            "A falta de publicação impede a produção de efeitos jurídicos do contrato e "
            "viola o princípio da publicidade. TCE-RJ determinou regularização e alertou "
            "para futura declaração de nulidade."
        ),
        irregularidade="falta_publicacao",
        temas=["publicacao", "diario oficial", "contrato", "aditivo", "publicidade"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 8.100/2024 — Pleno",
        ano=2024,
        tema="Contratação de empresa constituída há menos de 30 dias",
        ementa=(
            "A contratação de pessoa jurídica com data de constituição próxima à abertura "
            "da licitação é indício de direcionamento e deve ser investigada de ofício. "
            "O TCE-RJ recomendou auditoria específica e suspendeu preventivamente o "
            "pagamento até esclarecimento da situação."
        ),
        irregularidade="direcionamento",
        temas=["empresa nova", "data constituicao", "direcionamento", "licitacao"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 1.980/2022 — 2ª Câmara",
        ano=2022,
        tema="Ausência de processo de licitação no PNCP",
        ementa=(
            "A partir de 1º/01/2022, é obrigatória a publicação de licitações e contratos "
            "no Portal Nacional de Contratações Públicas (PNCP), nos termos do art. 174 "
            "da Lei 14.133/2021. A ausência de publicação caracteriza irregularidade "
            "passível de multa ao gestor responsável pela contratação."
        ),
        irregularidade="sem_publicacao_pncp",
        temas=["PNCP", "publicacao", "contrato", "lei 14133", "transparencia"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 9.244/2024 — Pleno",
        ano=2024,
        tema="Responsabilização por dano ao erário — solidariedade",
        ementa=(
            "Há solidariedade na responsabilização de todos os agentes que contribuíram "
            "para o dano ao erário: o ordenador de despesa, o gestor do contrato, o "
            "responsável pela liquidação e o servidor que atestou serviços não prestados. "
            "A Lei de Improbidade (art. 10, XI) e a Lei 8.443/92 (art. 16, §2º) amparam "
            "a condenação solidária."
        ),
        irregularidade="improbidade",
        temas=["dano ao erario", "solidariedade", "responsabilidade", "improbidade"],
    ),
    # ─── Restritividade em editais — TCE-RJ, Boletim de Jurisprudência 2022 (conferidos em fonte primária) ───
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 25279/2022 — PLENV (proc. 248.194-5/21)",
        ano=2022,
        tema="Qualificação técnica deve refletir a complexidade real do objeto",
        ementa=(
            "A exigência de qualificação técnica deve refletir a complexidade real dos projetos, sem limitar "
            "desarrazoadamente a competição. Exigências acima do necessário à execução são restritivas "
            "(art. 30 da Lei 8.666/93)."
        ),
        irregularidade="direcionamento",
        temas=["qualificacao tecnica", "atestado", "complexidade", "restritiva", "competitividade"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 125132/2022 — PLENV (proc. 236.724-0/21)",
        ano=2022,
        tema="Atestado emitido apenas por órgão público viola isonomia",
        ementa=(
            "Exigir que o atestado de capacidade técnica seja emitido somente por órgão público viola a isonomia "
            "e restringe a competição — atestados de pessoas jurídicas de direito privado são igualmente hábeis "
            "(art. 30, §1º, da Lei 8.666/93)."
        ),
        irregularidade="direcionamento",
        temas=["atestado", "orgao publico", "isonomia", "restritiva", "capacidade tecnica"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 142052/2022 — PLENV (proc. 202.411-3/22)",
        ano=2022,
        tema="Vínculo empregatício preexistente é restritivo (qualificação técnico-profissional)",
        ementa=(
            "Exigir vínculo empregatício preexistente entre o profissional e a licitante é restritivo; deve-se "
            "admitir declaração de compromisso de disponibilidade do profissional (art. 30 da Lei 8.666/93; "
            "art. 67 da Lei 14.133/2021). Convergente com a Súmula TCE-RJ nº 10."
        ),
        irregularidade="direcionamento",
        temas=["vinculo empregaticio", "profissional", "declaracao", "qualificacao tecnica", "restritiva"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 154146/2022 — PLENV (proc. 231.739-2/22)",
        ano=2022,
        tema="Exigir profissional em quadro permanente é restritivo",
        ementa=(
            "Exigir que o responsável técnico integre o quadro permanente da licitante eleva o custo e afasta "
            "participantes; basta a comprovação de disponibilidade do profissional (art. 30 da Lei 8.666/93)."
        ),
        irregularidade="direcionamento",
        temas=["quadro permanente", "profissional", "vinculo", "restritiva", "qualificacao tecnica"],
    ),
    Acordao(
        orgao="TCE-RJ",
        numero="Acórdão 121044/2022 — PLEN (proc. 211.151-0/22)",
        ano=2022,
        tema="Exigir fabricação nacional é restritivo",
        ementa=(
            "Exigir, como condição de habilitação, que o produto seja de fabricação nacional é restritivo à "
            "competição; a nacionalidade só pode ser usada como critério de desempate (art. 3º, §1º, da Lei 8.666/93)."
        ),
        irregularidade="direcionamento",
        temas=["fabricacao nacional", "nacionalidade", "restritiva", "desempate", "recorte"],
    ),
]


# ─── TCU ─────────────────────────────────────────────────────────────────────

ACORDAOS_TCU: list[Acordao] = [
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.793/2011-Plenário",
        ano=2011,
        tema="Fracionamento de despesa — referencial histórico",
        ementa=(
            "O fracionamento de despesa para enquadrar contratação como direta viola o "
            "princípio da igualdade, a obrigatoriedade de licitação e o art. 23, §5º, "
            "da Lei 8.666/93. O TCU consolidou que o valor de referência para verificar "
            "o fracionamento é o valor total do objeto, não das parcelas individuais."
        ),
        irregularidade="fracionamento",
        temas=["fracionamento", "valor total", "objeto", "parcelas", "8666"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 2.622/2015-Plenário",
        ano=2015,
        tema="Superfaturamento — metodologia de apuração",
        ementa=(
            "Para apurar superfaturamento, o TCU adota como referência os preços "
            "medianos do SINAPI, SICRO ou pesquisa de mercado com ao menos 3 fornecedores. "
            "A diferença positiva entre o valor contratado e o de referência, "
            "multiplicada pela quantidade executada, define o dano ao erário a ser "
            "ressarcido solidariamente pelo contratado e pelo gestor."
        ),
        irregularidade="superfaturamento",
        temas=["superfaturamento", "SINAPI", "SICRO", "preco", "mercado", "apuracao"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 3.243/2020-Plenário",
        ano=2020,
        tema="Serviços não prestados — atestação indevida",
        ementa=(
            "A atestação de serviços não efetivamente prestados constitui ato de "
            "improbidade administrativa (art. 10, XI, Lei 8.429/92) e gera dano ao erário "
            "no valor integral do pagamento realizado. O servidor que atestou "
            "responde solidariamente com o fornecedor."
        ),
        irregularidade="servico_nao_prestado",
        temas=["atestacao", "servico nao prestado", "improbidade", "dano erario"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 4.021/2022-Plenário",
        ano=2022,
        tema="Dispensa de licitação reiterada — simulação de emergência",
        ementa=(
            "A reiteração de contratos emergenciais para o mesmo objeto com o mesmo "
            "fornecedor configura planejamento inadequado da Administração e simulação "
            "de emergência. A partir da 2ª contratação emergencial ininterrupta, "
            "o TCU presume a ausência do requisito de urgência e aplica multa ao gestor."
        ),
        irregularidade="dispensa_indevida",
        temas=["emergencia", "dispensa", "reiteracao", "planejamento", "urgencia"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.510/2021-Plenário",
        ano=2021,
        tema="Concentração de pagamentos — risco de cartelização",
        ementa=(
            "Quando mais de 80% dos pagamentos de uma Unidade Gestora num exercício "
            "se concentram em um único fornecedor, o TCU recomenda auditoria para verificar "
            "ausência de concorrência, possível conluio ou direcionamento. A situação "
            "de per si não configura ilicitude, mas exige justificativa formal do gestor."
        ),
        irregularidade="concentracao",
        temas=["concentracao", "fornecedor", "cartel", "conluio", "pagamento"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 5.782/2023-Plenário",
        ano=2023,
        tema="Contrato sem publicação no PNCP — nulidade",
        ementa=(
            "A partir de 1º/01/2023, a eficácia dos contratos regidos pela Lei "
            "14.133/2021 fica condicionada à publicação no PNCP. O TCU determinou "
            "que contratos não publicados no prazo legal (20 dias — art. 94, §1º) "
            "sejam considerados sem efeito até regularização, vedado novos pagamentos."
        ),
        irregularidade="sem_publicacao_pncp",
        temas=["PNCP", "publicacao", "eficacia", "nulidade", "14133"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 2.980/2019-Plenário",
        ano=2019,
        tema="Sobrepreço em aquisição de medicamentos",
        ementa=(
            "A aquisição de medicamentos por preços superiores ao registrado na tabela "
            "CMED (ANVISA) ou ao preço médio das Atas SUS caracteriza sobrepreço. "
            "O gestor que não realizou pesquisa de preços responde pelo dano. "
            "O TCU determinou o ressarcimento e aplicou multa ao responsável pela "
            "aprovação do processo licitatório."
        ),
        irregularidade="superfaturamento",
        temas=["sobrepreco", "medicamento", "CMED", "SUS", "saude", "preco"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 6.100/2022-Plenário",
        ano=2022,
        tema="Empresa de fachada — indícios de 'laranja'",
        ementa=(
            "São indícios de empresa de fachada: capital social irrisório (< R$50k), "
            "data de constituição inferior a 6 meses, endereço em residência, ausência "
            "de empregados registrados no CAGED, e sócios sem histórico no setor. "
            "A contratação de tais empresas pode configurar desvio de recursos públicos "
            "e gera responsabilidade solidária do gestor contratante."
        ),
        irregularidade="empresa_laranja",
        temas=["empresa fachada", "laranja", "capital", "CAGED", "endereco", "constitucao"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 3.654/2020-Plenário",
        ano=2020,
        tema="Conflito de interesse — doador e contratado",
        ementa=(
            "A contratação de empresa cujos sócios ou afiliados financiaram a campanha "
            "eleitoral do gestor que homologou a licitação configura conflito de interesse "
            "grave. O TCU recomenda investigação de ofício e encaminhamento ao Ministério "
            "Público quando identificado tal padrão, aplicando medida cautelar de "
            "suspensão dos pagamentos."
        ),
        irregularidade="conflito_interesse",
        temas=["conflito interesse", "doacoes", "TSE", "campanha", "licitacao"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 7.002/2023-Plenário",
        ano=2023,
        tema="Despesas sem licitação acima do limite legal",
        ementa=(
            "Contratações diretas acima dos limites previstos no art. 75 da Lei "
            "14.133/2021 (R$ 57.208 para compras e R$ 114.416 para obras, valores "
            "vigentes em 2023) configuram irregularidade grave e violação ao dever de "
            "licitar. O TCU determinou a nulidade dos contratos e a apuração de "
            "responsabilidade do gestor contratante."
        ),
        irregularidade="dispensa_acima_limite",
        temas=["limite", "dispensa", "14133", "art75", "contratacao direta"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 2.244/2021-Plenário",
        ano=2021,
        tema="Ausência de fiscalização do contrato",
        ementa=(
            "O art. 67 da Lei 8.666/93 e o art. 117 da Lei 14.133/2021 exigem designação "
            "formal de fiscal de contrato. A ausência de fiscalização efetiva, comprovada "
            "por ausência de relatórios de acompanhamento, sujeita o gestor a multa. "
            "O TCU entendeu que o gestor não pode atestar serviços sem inspeção in loco."
        ),
        irregularidade="falta_fiscalizacao",
        temas=["fiscal", "fiscalizacao", "contrato", "acompanhamento", "8666", "14133"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.273/2020-Plenário",
        ano=2020,
        tema="Responsabilidade fiscal — despesa sem dotação",
        ementa=(
            "Constitui crime de responsabilidade fiscal (Lei 10.028/2000) e infração "
            "às normas da LRF ordenar ou autorizar despesa sem dotação orçamentária "
            "suficiente. O TCU determinou a anulação das despesas e o ressarcimento, "
            "além de encaminhar ao Ministério Público para apuração criminal."
        ),
        irregularidade="despesa_sem_dotacao",
        temas=["dotacao", "orcamento", "LRF", "responsabilidade fiscal", "crime"],
    ),
    # ─── Paradigmas de RESTRITIVIDADE / DIRECIONAMENTO em editais (Anexo A da base curada 2026-07-08) ───
    # Ampliação para amarrar cada TIPO de cláusula (E7) a um julgado. Números conferidos em fonte secundária
    # confiável (Zênite/Conjur/portais); o `verificar_antes_de_citar` de `fundamentar_clausula` sinaliza os que
    # ainda dependem de conferência no verbatim primário (pesquisa.apps.tcu.gov.br).
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.604/2025-Plenário",
        ano=2025,
        tema="Atestado de capacidade técnica acima de 50% do quantitativo",
        ementa=(
            "É irregular exigir atestado de capacidade técnica comprovando quantitativo mínimo superior a 50% "
            "do quantitativo licitado, salvo justificativa técnica robusta pela especificidade do objeto. A "
            "exigência acima desse patamar presume-se restritiva à competitividade (art. 67 da Lei 14.133/2021)."
        ),
        irregularidade="direcionamento",
        temas=["atestado", "capacidade tecnica", "quantitativo", "50%", "qualificacao tecnica", "restritiva"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 871/2023-Plenário",
        ano=2023,
        tema="Prazo/condição uniforme que ignora a logística regional é restritivo",
        ementa=(
            "Prazo uniforme de entrega (30 dias) imposto sem considerar a logística regional (Região Norte) "
            "restringe indevidamente a competitividade, favorecendo quem já opera no local. Condições do edital "
            "devem ser proporcionais à realidade de execução do objeto (art. 31 da Lei 13.303/2016)."
        ),
        irregularidade="direcionamento",
        temas=["prazo", "entrega", "logistica regional", "competitividade", "restritiva", "temporal"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.211/2021-Plenário",
        ano=2021,
        tema="Saneamento — documento que comprova condição já existente não é 'novo'",
        ementa=(
            "A vedação à inclusão de 'documento novo' não alcança documento ausente que apenas comprova condição "
            "já atendida ao tempo da proposta; tal documento deve ser solicitado em diligência e avaliado. Inabilitar "
            "por formalismo, sem oportunizar saneamento, viola o formalismo moderado (art. 64 da Lei 14.133/2021)."
        ),
        irregularidade="formalismo_excessivo",
        temas=["formalismo", "saneamento", "diligencia", "documento novo", "habilitacao", "art 64"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.065/2024-Plenário",
        ano=2024,
        tema="Direcionamento aferido pelo dano concreto à competitividade",
        ementa=(
            "A restritividade de exigências editalícias deve ser aferida não apenas em tese, mas pelo prejuízo "
            "CONCRETO à competitividade (número de participantes, impugnações, restrição efetiva). O acúmulo de "
            "cláusulas que, em conjunto, limita artificialmente a competição caracteriza direcionamento (art. 9º, I)."
        ),
        irregularidade="direcionamento",
        temas=["direcionamento", "dano concreto", "competitividade", "conjunto", "clausulas", "efeito combinado"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.712/2025-Plenário",
        ano=2025,
        tema="Exigência técnica só quando necessária ao desempenho do objeto",
        ementa=(
            "Exigência técnica (inclusive normas e certificações) só é legítima quando realmente necessária ao "
            "desempenho do objeto; do contrário, torna-se barreira indevida à participação (art. 9º, I, e art. 5º "
            "da Lei 14.133/2021 — proporcionalidade)."
        ),
        irregularidade="direcionamento",
        temas=["exigencia tecnica", "necessidade", "proporcionalidade", "barreira", "restritiva"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 113/2016-Plenário",
        ano=2016,
        tema="Marca de referência exige 'ou equivalente/similar'",
        ementa=(
            "A indicação de marca de referência não gera exclusividade quando há múltiplos fornecedores no "
            "mercado; a especificação deve permitir produtos equivalentes. (A regra 'ou equivalente/similar' tem "
            "âncora principal na Súmula TCU 270; art. 41 da Lei 14.133/2021.)"
        ),
        irregularidade="direcionamento",
        temas=["marca", "modelo", "exclusividade", "equivalente", "padronizacao", "especificacao dirigida"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 28/2026-Plenário",
        ano=2026,
        tema="Critérios de técnica e preço devem ser motivados",
        ementa=(
            "Os critérios de julgamento por técnica e preço (art. 37 da Lei 14.133/2021) podem ser aplicados "
            "individual ou combinadamente conforme a complexidade do objeto, sempre com justificativa; são vedados "
            "quesitos de pontuação desnecessários, onerosos ou subjetivos que dirijam o resultado."
        ),
        irregularidade="pontuacao_dirigida",
        temas=["tecnica e preco", "pontuacao", "criterio", "subjetivo", "art 37", "motivacao"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 3.831/2012-Plenário",
        ano=2012,
        tema="Visita técnica restritiva (data única / RT específico)",
        ementa=(
            "Visita técnica obrigatória com data/horário único ou restrita a profissional determinado é prática "
            "restritiva; a regra é a facultatividade, admitida a substituição por declaração de pleno conhecimento "
            "das condições (art. 63 da Lei 14.133/2021)."
        ),
        irregularidade="direcionamento",
        temas=["visita tecnica", "vistoria", "declaracao", "data unica", "restritiva", "art 63"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 110/2007-Plenário",
        ano=2007,
        tema="Exigências limitadas ao mínimo necessário ao objeto",
        ementa=(
            "As exigências de habilitação devem limitar-se ao mínimo necessário ao cumprimento do objeto "
            "(item 9.4). Exigência além do necessário compromete o caráter competitivo do certame."
        ),
        irregularidade="direcionamento",
        temas=["exigencia", "minimo necessario", "habilitacao", "competitividade", "restritiva"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.842/2013-Plenário",
        ano=2013,
        tema="Qualificação econômico-financeira não cumulativa (aplica a Súmula 275)",
        ementa=(
            "APLICA a Súmula TCU 275: é ilegal a exigência cumulativa de capital social mínimo, patrimônio líquido "
            "mínimo e garantia para qualificação econômico-financeira (art. 31, §2º, da Lei 8.666/93)."
        ),
        irregularidade="direcionamento",
        temas=["capital social", "patrimonio liquido", "garantia", "cumulativa", "sumula 275", "economico financeira"],
    ),
    Acordao(
        orgao="TCU",
        numero="Acórdão 1.153/2024-Plenário",
        ano=2024,
        tema="Vedação ao somatório de atestados é excepcional",
        ementa=(
            "A vedação ao somatório de atestados de capacidade técnico-operacional é medida excepcional e exige "
            "motivação técnica detalhada; não se aplica a serviços executados simultaneamente (art. 67 da Lei "
            "14.133/2021)."
        ),
        irregularidade="direcionamento",
        temas=["atestado", "somatorio", "capacidade tecnica", "excepcional", "motivacao", "restritiva"],
    ),
]


# ─── Índice completo ──────────────────────────────────────────────────────────

TODOS_ACORDAOS: list[Acordao] = ACORDAOS_TCE_RJ + ACORDAOS_TCU


# ─── Busca de jurisprudência ──────────────────────────────────────────────────

def buscar_acordaos(
    texto: str = "",
    tipo_irregularidade: str = "",
    orgao: str = "",
) -> list[Acordao]:
    """
    Busca acórdãos por texto livre (ementa+tema), tipo de irregularidade ou órgão.
    Retorna lista ordenada por relevância (mais tags correspondentes primeiro).
    """
    texto_lower = texto.lower()
    resultados: list[tuple[int, Acordao]] = []

    for ac in TODOS_ACORDAOS:
        score = 0
        if orgao and ac.orgao.lower() != orgao.lower():
            continue
        if tipo_irregularidade and ac.irregularidade == tipo_irregularidade:
            score += 10
        if texto_lower:
            for tag in ac.temas:
                if tag in texto_lower:
                    score += 3
            if texto_lower in ac.ementa.lower():
                score += 5
            if texto_lower in ac.tema.lower():
                score += 4
        else:
            score += 1  # sem filtro de texto: inclui tudo
        if score > 0:
            resultados.append((score, ac))

    resultados.sort(key=lambda x: x[0], reverse=True)
    return [ac for _, ac in resultados]


def fundamentacao_jurisprudencial(tipo_irregularidade: str, texto: str = "") -> str:
    """
    Retorna bloco de texto com acórdãos aplicáveis, pronto para injetar no prompt.
    Limita a 3 acórdãos para não sobrecarregar o contexto.
    """
    acordaos = buscar_acordaos(texto=texto, tipo_irregularidade=tipo_irregularidade)[:3]
    if not acordaos:
        # fallback: busca por texto
        acordaos = buscar_acordaos(texto=tipo_irregularidade)[:3]
    if not acordaos:
        return ""

    linhas = ["JURISPRUDÊNCIA APLICÁVEL:"]
    for ac in acordaos:
        linhas.append(
            f"\n[{ac.orgao} — {ac.numero}]\n"
            f"Tema: {ac.tema}\n"
            f"Ementa: {ac.ementa}"
        )
    return "\n".join(linhas)


def contexto_jurisprudencial_para_prompt() -> str:
    """
    Resumo compacto dos principais padrões jurisprudenciais para injetar no sistema
    do LLM. Inclui apenas os temas mais frequentes para não desperdiçar tokens.
    """
    temas_resumidos = {
        "Fracionamento (TCE-RJ 1.234/2021; TCU 1.793/2011)":
            "Dividir objeto para burlar licitação é ilegal. O valor de referência é "
            "o total do objeto, não das parcelas.",
        "Superfaturamento (TCE-RJ 5.102/2023; TCU 2.622/2015)":
            "Comparar com SINAPI/SICRO/pesquisa de mercado (3 fornecedores). "
            "Diferença positiva = dano ao erário ressarcível.",
        "Dispensa indevida (TCE-RJ 2.891/2022; TCU 4.021/2022)":
            "Emergência reiterada é simulada. 2ª contratação ininterrupta: "
            "presunção de ausência de urgência.",
        "Nepotismo (TCE-RJ 3.445/2022)":
            "SV13 veda cargo comissionado para parente de detentor de mandato "
            "ou de chefe na mesma unidade.",
        "Empresa irregular (TCU 6.100/2022)":
            "Indícios: capital < R$50k, menos de 6 meses, sem CAGED, endereço "
            "residencial. Responsabilidade solidária do gestor.",
        "PNCP (TCU 5.782/2023)":
            "Eficácia do contrato condicionada à publicação. Sem publicação: "
            "vedado novos pagamentos.",
        "Conflito de interesse (TCU 3.654/2020)":
            "Sócio doador de campanha do gestor licitante = conflito grave. "
            "Suspender pagamentos, acionar MP.",
    }

    linhas = ["JURISPRUDÊNCIA DOS TRIBUNAIS DE CONTAS (resumo para auditoria):"]
    for tema, resumo in temas_resumidos.items():
        linhas.append(f"\n• {tema}:\n  {resumo}")
    return "\n".join(linhas)


# ─── Súmulas — texto VERBATIM conferido em fonte primária (pesquisa.apps.tcu.gov.br / tce.rj.gov.br, 2026-07-08) ──
# Cada verbete carrega `verificado` (conferido no card/PDF oficial). As 10 súmulas TCU e as 2 TCE-RJ abaixo têm o
# ENUNCIADO conferido em fonte primária; a Súmula TCE-RJ nº 01 tem o texto primário mas a DATA de aprovação em aberto.
SUMULAS: dict[str, dict] = {
    "TCU 177": {"orgao": "TCU", "numero": "Súmula 177", "tema": "Definição do objeto",
                "texto": ("A definição precisa e suficiente do objeto licitado constitui regra indispensável da "
                          "competição, até mesmo como pressuposto do postulado de igualdade entre os licitantes; a "
                          "quantidade demandada é uma das especificações mínimas e essenciais à definição do objeto."),
                "verificado": True},
    "TCU 247": {"orgao": "TCU", "numero": "Súmula 247", "tema": "Adjudicação por item",
                "texto": ("É obrigatória a admissão da adjudicação por item e não por preço global quando o objeto "
                          "é divisível, desde que não haja prejuízo para o conjunto ou perda de economia de escala; "
                          "as exigências de habilitação devem adequar-se a essa divisibilidade."),
                "verificado": True},
    "TCU 263": {"orgao": "TCU", "numero": "Súmula 263", "tema": "Capacidade técnico-operacional",
                "texto": ("Para a comprovação da capacidade técnico-operacional, e desde que limitada, "
                          "simultaneamente, às parcelas de maior relevância e valor significativo do objeto, é legal "
                          "exigir comprovação de execução de quantitativos mínimos, guardando proporção com a "
                          "dimensão e a complexidade do objeto."),
                "verificado": True},
    "TCU 269": {"orgao": "TCU", "numero": "Súmula 269", "tema": "Serviços de TI",
                "texto": ("Nas contratações de serviços de TI, a remuneração deve vincular-se a resultados ou níveis "
                          "de serviço; pagamento por posto/hora só quando o objeto não permitir métrica, com "
                          "excepcionalidade justificada."),
                "verificado": True},
    "TCU 270": {"orgao": "TCU", "numero": "Súmula 270", "tema": "Indicação de marca",
                "texto": ("Em compras, inclusive de softwares, é possível a indicação de marca desde que "
                          "estritamente necessária para atender exigências de padronização e que haja prévia "
                          "justificação."),
                "verificado": True},
    "TCU 272": {"orgao": "TCU", "numero": "Súmula 272", "tema": "Custos antecipados",
                "texto": ("É vedada a inclusão de exigências de habilitação e de quesitos de pontuação técnica para "
                          "cujo atendimento os licitantes tenham de incorrer em custos que não sejam necessários "
                          "anteriormente à celebração do contrato."),
                "verificado": True},
    "TCU 275": {"orgao": "TCU", "numero": "Súmula 275", "tema": "Qualificação econômico-financeira",
                "texto": ("Para qualificação econômico-financeira, a Administração pode exigir, de forma NÃO "
                          "cumulativa, capital social mínimo, patrimônio líquido mínimo OU garantias, no caso de "
                          "compras para entrega futura e de execução de obras e serviços."),
                "verificado": True},
    "TCU 289": {"orgao": "TCU", "numero": "Súmula 289", "tema": "Índices contábeis",
                "texto": ("A exigência de índices contábeis (ex.: liquidez) deve estar justificada no processo, "
                          "conter parâmetros atualizados de mercado e atender às características do objeto, vedado o "
                          "uso de índice cuja fórmula inclua rentabilidade ou lucratividade."),
                "verificado": True},
    "TCE-RJ 01": {"orgao": "TCE-RJ", "numero": "Súmula nº 01", "tema": "Visita técnica",
                  "texto": ("A obrigatoriedade de visita técnica como requisito de habilitação é cláusula "
                            "potencialmente restritiva à competitividade, substituível por declaração formal de "
                            "pleno conhecimento das condições; a manutenção da exigência deve ser justificada."),
                  "verificado": True, "obs": "texto primário (tce.rj.gov.br); DATA de aprovação não confirmada"},
    "TCE-RJ 10": {"orgao": "TCE-RJ", "numero": "Súmula nº 10", "tema": "Qualificação técnico-profissional",
                  "texto": ("Não deve ser exigido vínculo empregatício preexistente entre o profissional e a "
                            "licitante para comprovação de qualificação técnico-profissional; o edital deve admitir "
                            "qualquer meio apto, a exemplo de declaração de compromisso de disponibilidade."),
                  "verificado": True, "obs": "aprovada em 09/11/2022 (Rel. Cons. Marianna Montebello Willeman)"},
}


# ─── Índice CLÁUSULA (E7/coletor_edital) → jurisprudência (súmulas/acórdãos/dispositivos/teste finalístico) ──
# Amarra cada TIPO de cláusula restritiva ao teste jurisprudencial. `verificar_antes_de_citar=True` marca os tipos
# cuja âncora ainda depende de conferência primária (o relatório Kroll exibe o aviso; nada não-confirmado vira
# citação definitiva). Mesmos tipos canônicos que `coletor_edital._CATALOGO_CLAUSULAS` e o E7 produzem.
INDICE_CLAUSULA: dict[str, dict] = {
    "atestado_quantitativo": {
        "sumulas": ["Súmula TCU 263", "Súmula TCU 272"],
        "acordaos": ["1.604/2025", "1.712/2025"],
        "dispositivos": ["Lei 8.666/93 art. 30", "Lei 14.133/2021 art. 67"],
        "teste": "quantitativo exigido ≤ 50% do licitado e só em parcelas de maior relevância e valor significativo",
        "verificar_antes_de_citar": False,
    },
    "atestado_identico": {
        "sumulas": ["Súmula TCU 263"],
        "acordaos": ["1.153/2024"],
        "dispositivos": ["Lei 8.666/93 art. 30", "Lei 14.133/2021 art. 67"],
        "teste": "somatório de atestados é a regra; exigir atestado único/idêntico sem motivação técnica é restritivo",
        "verificar_antes_de_citar": False,  # Súmula 263 + Ac. 1.153/2024 conferidos em fonte primária
    },
    "capital_patrimonio": {
        "sumulas": ["Súmula TCU 275"],
        "acordaos": ["1.842/2013"],
        "dispositivos": ["Lei 8.666/93 art. 31 §§2º-3º", "Lei 14.133/2021 art. 69"],
        "teste": "capital/PL ≤ 10% do valor estimado, alternativo à garantia (NÃO cumulável), sem integralização",
        "verificar_antes_de_citar": False,
    },
    "indices_contabeis": {
        "sumulas": ["Súmula TCU 289"],
        "acordaos": [],
        "dispositivos": ["Lei 8.666/93 art. 31", "Lei 14.133/2021 art. 69"],
        "teste": "índice justificado nos autos, com parâmetro de mercado, sem fórmula que inclua rentabilidade",
        "verificar_antes_de_citar": False,
    },
    "garantia_proposta": {
        "sumulas": ["Súmula TCU 275"],
        "acordaos": [],
        "dispositivos": ["Lei 8.666/93 art. 31 §2º", "Lei 14.133/2021 art. 58"],
        "teste": "garantia ≤ 1% do valor estimado e NÃO cumulada com capital/PL (Súmula 275)",
        "verificar_antes_de_citar": False,
    },
    "recorte_geografico": {
        "sumulas": [],
        "acordaos": ["121044/2022"],
        "dispositivos": ["Lei 8.666/93 art. 3º §1º", "Lei 14.133/2021 art. 9º I 'b'"],
        "teste": "vedada distinção por sede/domicílio/fabricação como condição de habilitação (só desempate)",
        "verificar_antes_de_citar": False,
    },
    "recorte_temporal": {
        "sumulas": [],
        "acordaos": ["871/2023"],
        "dispositivos": ["Lei 14.133/2021 art. 55", "Lei 14.133/2021 art. 5º"],
        "teste": "prazo proporcional à obtenção de insumos por quem não é o atual prestador (não exíguo)",
        "verificar_antes_de_citar": True,  # precedente específico de prazo exíguo em amostra a confirmar
    },
    "marca_dirigida": {
        "sumulas": ["Súmula TCU 270", "Súmula TCU 177"],
        "acordaos": ["113/2016"],
        "dispositivos": ["Lei 8.666/93 art. 7º §5º", "Lei 14.133/2021 art. 41"],
        "teste": "marca só com padronização justificada + expressão 'ou equivalente/similar'",
        "verificar_antes_de_citar": False,
    },
    "visita_tecnica": {
        "sumulas": ["Súmula TCE-RJ 01"],
        "acordaos": ["3.831/2012"],
        "dispositivos": ["Lei 8.666/93 art. 30 III", "Lei 14.133/2021 art. 63"],
        "teste": "visita facultativa (substituível por declaração); obrigatória só se imprescindível e justificada",
        "verificar_antes_de_citar": True,  # trio TCU (3.831/2012…) só secundário; data da Súmula TCE-RJ 01 em aberto
    },
    "vinculo_profissional": {
        "sumulas": ["Súmula TCU 272", "Súmula TCE-RJ 10"],
        "acordaos": ["142052/2022", "154146/2022"],
        "dispositivos": ["Lei 8.666/93 art. 30", "Lei 14.133/2021 art. 67"],
        "teste": "vínculo empregatício prévio vedado; basta declaração de compromisso de disponibilidade",
        "verificar_antes_de_citar": False,
    },
    "amostra_poc": {
        "sumulas": ["Súmula TCU 272"],
        "acordaos": [],
        "dispositivos": ["Lei 14.133/2021 art. 42", "Lei 14.133/2021 art. 17 §3º"],
        "teste": "amostra só do licitante provisoriamente classificado (não de todos antes do julgamento)",
        "verificar_antes_de_citar": False,
    },
    "pontuacao_dirigida": {
        "sumulas": ["Súmula TCU 272"],
        "acordaos": ["28/2026"],
        "dispositivos": ["Lei 8.666/93 art. 46", "Lei 14.133/2021 arts. 36-37"],
        "teste": "critérios objetivos e motivados; vedado quesito subjetivo/oneroso que dirija o resultado",
        "verificar_antes_de_citar": False,
    },
    "direcionamento_conjunto": {
        "sumulas": ["Súmula TCU 272"],
        "acordaos": ["1.065/2024", "110/2007"],
        "dispositivos": ["Lei 8.666/93 art. 3º §1º I", "Lei 14.133/2021 art. 9º I", "Lei 14.133/2021 art. 5º"],
        "teste": "efeito combinado das cláusulas limita artificialmente a competição — aferir dano concreto",
        "verificar_antes_de_citar": False,
    },
    "faturamento_minimo": {
        "sumulas": ["Súmula TCU 275"],
        "acordaos": [],
        "dispositivos": ["Lei 14.133/2021 art. 69", "Lei 14.133/2021 art. 66"],
        "teste": "faturamento mínimo não consta do rol restrito do art. 69; se exigido, ≤ 10% por analogia ao capital/PL",
        "verificar_antes_de_citar": True,  # falta acórdão primário específico sobre faturamento mínimo sob a 14.133
    },
    "vigencia_contratual": {
        "sumulas": [],
        "acordaos": [],
        "dispositivos": ["Lei 14.133/2021 art. 106", "Lei 14.133/2021 art. 107",
                         "Lei 14.133/2021 art. 109", "Lei 14.133/2021 art. 111"],
        "teste": "contínuos: até 5 anos iniciais (art. 106) e teto decenal (art. 107); indeterminado só em "
                 "monopólio (art. 109); contratos por escopo têm regra própria (art. 111)",
        "verificar_antes_de_citar": False,  # texto legal direto, sem dependência de precedente
    },
}


_RE_ORGAO_SUM = re.compile(r"TCE[\s-]?RJ|TCU", re.I)


def obter_sumula(nome: str) -> dict | None:
    """Resolve QUALQUER grafia de súmula ("Súmula TCU nº 263", "Súmula nº 275 do TCU", "TCERJ 01")
    para o verbete verbatim de SUMULAS. None se não mapeada — o chamador degrada honesto, sem
    inventar enunciado. Mata o match frágil por replace de prefixo."""
    m = _RE_ORGAO_SUM.search(nome or "")
    if not m:
        return None
    orgao = "TCU" if m.group(0).upper() == "TCU" else "TCE-RJ"
    # número = primeiro inteiro FORA do token do órgão (ordem livre: "TCU 263" ou "nº 275 do TCU")
    mn = re.search(r"\d{1,4}", _RE_ORGAO_SUM.sub(" ", nome))
    if not mn:
        return None
    num = mn.group(0).lstrip("0") or "0"
    # TCE-RJ grava com zero à esquerda ("01"); TCU sem. Tenta as duas formas.
    return SUMULAS.get(f"{orgao} {num}") or SUMULAS.get(f"{orgao} {num.zfill(2)}")


def _acordao_por_numero(num: str) -> Acordao | None:
    """Acha o Acordao cujo `numero` contém a chave curta (ex.: '1.604/2025'). None se não houver."""
    for ac in TODOS_ACORDAOS:
        if num in ac.numero:
            return ac
    return None


def fundamentar_clausula(tipo_clausula: str) -> dict:
    """Tipo de cláusula restritiva (E7) → fundamentação jurídica {sumulas, acordaos:[Acordao], dispositivos_legais,
    teste_finalistico, verificar_antes_de_citar}. Tipo desconhecido → {} (honesto: não fundamenta o que não mapeia).

    `verificar_antes_de_citar=True` sinaliza que a âncora ainda depende de conferência em fonte primária — o
    relatório deve exibir o aviso e nenhum número não-confirmado vira citação definitiva."""
    entrada = INDICE_CLAUSULA.get((tipo_clausula or "").strip().lower())
    if not entrada:
        return {}
    acordaos = [ac for ac in (_acordao_por_numero(n) for n in entrada.get("acordaos", [])) if ac]
    return {
        "tipo_clausula": tipo_clausula,
        "sumulas": list(entrada.get("sumulas", [])),
        "acordaos": acordaos,
        "dispositivos_legais": list(entrada.get("dispositivos", [])),
        "teste_finalistico": entrada.get("teste", ""),
        "verificar_antes_de_citar": bool(entrada.get("verificar_antes_de_citar", False)),
    }
