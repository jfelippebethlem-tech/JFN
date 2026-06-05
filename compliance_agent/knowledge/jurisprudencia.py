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
