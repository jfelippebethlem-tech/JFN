"""
Catálogo de fraudes em licitações e contratos públicos.

Cobre tanto modalidades clássicas (já documentadas pela doutrina e jurisprudência)
quanto esquemas emergentes (digitalização, OSs, PPPs, bolsas, TI, pandemia).

Cada padrão tem:
  - id, nome, categoria, descricao
  - como_detectar: indicadores automáticos mapeáveis no banco
  - red_flags: sinais de alerta em texto (DOERJ, contratos, SEI)
  - base_legal: norma violada
  - casos_associados: IDs de casos reais do RJ
  - risco: alto | médio
"""

from dataclasses import dataclass


@dataclass
class FraudePattern:
    id: str
    nome: str
    categoria: str          # licitação | contrato | pessoal | fiscal | sistêmico
    descricao: str
    como_detectar: list[str]    # regras automáticas aplicáveis
    red_flags: list[str]        # termos/padrões textuais
    base_legal: list[str]
    casos_associados: list[str] # IDs de CasoCorrupcao
    risco: str                  # alto | médio


FRAUDES: list[FraudePattern] = [

    # ── FRAUDES EM LICITAÇÃO ──────────────────────────────────────────────────

    FraudePattern(
        id="direcionamento_edital",
        nome="Direcionamento de Edital",
        categoria="licitação",
        descricao=(
            "O edital é redigido com especificações técnicas, marcas, padrões ou requisitos "
            "de habilitação que só uma empresa específica consegue atender. O processo "
            "aparenta competição, mas o resultado já está decidido antes da publicação."
        ),
        como_detectar=[
            "Apenas 1 proposta válida em processos acima de R$ 100k",
            "Empresa vencedora com mesma CNAE do objeto especificado no edital",
            "Prazo de publicação do edital menor que 5 dias úteis",
            "Empresa vencedora aberta menos de 1 ano antes da licitação",
            "Edital exige 'experiência mínima de 10 anos' em setor específico (afasta concorrentes)",
            "Exige marca específica sem justificativa técnica",
        ],
        red_flags=[
            "características exclusivas", "compatível com", "equivalente não aceito",
            "experiência comprovada de", "único fornecedor", "exclusividade técnica",
            "padrão proprietário", "integração com sistema X já instalado",
        ],
        base_legal=[
            "Lei 14.133/21 art. 9º (vedação ao direcionamento)",
            "Lei 8.429/92 art. 10, VIII",
            "Súmula TCU 274 (especificação de marca)",
        ],
        casos_associados=["cabral_propinas", "esquema_sa_saude", "secretaria_obras_obras"],
        risco="alto",
    ),

    FraudePattern(
        id="fracionamento_objeto",
        nome="Fracionamento de Objeto para Fugir da Licitação",
        categoria="licitação",
        descricao=(
            "O mesmo objeto é dividido em múltiplas contratações menores para que cada "
            "uma fique abaixo do limite de dispensa (R$ 50k serviços, R$ 30k obras — "
            "Lei 14.133/21). Individualmente parecem legais; somadas, deveriam ter licitação."
        ),
        como_detectar=[
            "Mesmo órgão + mesma empresa + N contratos de dispensa no mesmo ano cuja soma > R$ 50k",
            "Contratos com objetos idênticos ou muito similares em datas próximas (< 90 dias)",
            "Vários empenhos de valores iguais ou próximos para mesma empresa",
            "Sequência de notas de empenho: R$ 49.900 + R$ 49.800 + R$ 49.500",
        ],
        red_flags=[
            "fornecimento parcelado", "etapa 1", "etapa 2", "fase I", "fase II",
            "complementação", "continuidade do serviço", "mesma empresa competência anterior",
        ],
        base_legal=[
            "Lei 14.133/21 art. 8º, §1º (vedação ao fracionamento)",
            "Lei 8.666/93 art. 23, §5º (regra anterior ainda aplicável a contratos vigentes)",
            "Súmula TCU 247",
        ],
        casos_associados=["cabral_propinas", "secretaria_obras_obras"],
        risco="alto",
    ),

    FraudePattern(
        id="bid_rigging_cartel",
        nome="Conluio entre Licitantes (Cartel / Jogo Combinado)",
        categoria="licitação",
        descricao=(
            "Empresas concorrentes combinam previamente quem vai vencer, com as demais "
            "apresentando propostas perdedoras deliberadamente. Podem se revezar ao longo "
            "do tempo ('rotatividade de vencedores'). Esquema altamente lucrativo pois "
            "elimina a competição de preços real."
        ),
        como_detectar=[
            "Mesmas empresas se revezando vencendo licitações do mesmo órgão por anos",
            "Proporções de preços entre concorrentes muito constantes (ex.: segundo sempre 3-5% acima)",
            "Empresas 'perdedoras' com mesmo CNPJ raiz ou sócios comuns da vencedora",
            "Propostas com erros de formatação idênticos (mesmo digitador)",
            "Empresas cadastradas no mesmo endereço ou com mesmo representante",
            "Desistência coordenada: várias empresas desistem no mesmo dia",
        ],
        red_flags=[
            "proposta similar", "preços próximos sistematicamente",
            "mesmo contador/representante legal", "empresas irmãs",
        ],
        base_legal=[
            "Lei 12.529/11 art. 36 (cartel — infração concorrencial)",
            "Lei 8.666/93 art. 90 (fraude à licitação — crime)",
            "Lei 14.133/21 art. 178",
            "CP art. 335 (contrato ilícito)"],
        casos_associados=["secretaria_obras_obras"],
        risco="alto",
    ),

    FraudePattern(
        id="inexigibilidade_indevida",
        nome="Inexigibilidade de Licitação Indevida",
        categoria="licitação",
        descricao=(
            "Contratação direta (sem licitação) justificada como 'inexigível' quando na "
            "verdade existe concorrência no mercado. Muito usada em contratos de "
            "consultoria, capacitação, TI e comunicação. O fornecedor é escolhido por "
            "conveniência política e o processo é formalizado após a escolha."
        ),
        como_detectar=[
            "Contratação direta com modalidade 'inexigível' para objeto não-artístico/intelectual",
            "Mesmo objeto contratado por dispensa em outro órgão",
            "Empresa de consultoria com CNPJ < 1 ano",
            "Valor contratado muito acima da mediana do mercado",
            "Empresa só tem um funcionário (o próprio sócio)",
        ],
        red_flags=[
            "notória especialização", "singular", "exclusividade", "inviável competição",
            "fornecedor único", "não há similar no mercado", "patente exclusiva",
        ],
        base_legal=[
            "Lei 14.133/21 art. 74 (hipóteses taxativas de inexigibilidade)",
            "Lei 8.429/92 art. 10, VIII",
            "TCU Acórdão 1.727/2017",
        ],
        casos_associados=["esquema_sa_saude", "witzel_saude_covid"],
        risco="alto",
    ),

    FraudePattern(
        id="dispensa_emergencia_fabricada",
        nome="Emergência Fabricada para Dispensa de Licitação",
        categoria="licitação",
        descricao=(
            "Situação de urgência é criada ou exagerada para justificar contratação "
            "direta (dispensa por emergência). O gestor atrasa deliberadamente o processo "
            "regular até que a situação se torne 'emergencial', ou declara emergência "
            "sem amparo técnico para contratar empresa já escolhida."
        ),
        como_detectar=[
            "Contratos de emergência recorrentes no mesmo órgão (> 2 por ano)",
            "Empresa beneficiada por emergência já contratada anteriormente pelo mesmo órgão",
            "Data da 'emergência' muito próxima ao vencimento do contrato anterior",
            "Ausência de justificativa técnica documentada para a urgência",
            "Processo SEI sem pareceres técnicos anteriores à contratação",
        ],
        red_flags=[
            "caráter emergencial", "urgência comprovada", "situação de risco imediato",
            "impossível aguardar", "dispensa emergência", "art. 75, VIII",
        ],
        base_legal=[
            "Lei 14.133/21 art. 75, VIII (emergência — hipótese taxativa)",
            "Lei 8.429/92 art. 10, VIII",
            "TCU Acórdão 1.066/2016",
        ],
        casos_associados=["witzel_saude_covid"],
        risco="alto",
    ),

    FraudePattern(
        id="habilitacao_excessiva",
        nome="Requisitos de Habilitação Excessivos",
        categoria="licitação",
        descricao=(
            "O edital exige qualificações técnicas ou econômicas muito acima do necessário "
            "para o objeto, eliminando potenciais concorrentes e restringindo a disputa "
            "à empresa já escolhida. Ex.: exigir patrimônio líquido de R$ 10M para "
            "contrato de R$ 500k."
        ),
        como_detectar=[
            "Patrimônio líquido exigido > 10% do valor do contrato (limite legal)",
            "Garantia de proposta > 1% do valor estimado",
            "Exige mais de 3 atestados de capacidade técnica para objeto simples",
            "Somente 1 licitante habilitado em certame com > 5 interessados",
        ],
        red_flags=[
            "patrimônio líquido mínimo", "certificação exclusiva", "ISO específica",
            "credenciamento", "experiência mínima de N anos", "atestado específico",
        ],
        base_legal=[
            "Lei 14.133/21 art. 67 (habilitação — limites)",
            "Lei 8.429/92 art. 10, VIII",
            "Súmula TCU 275",
        ],
        casos_associados=["direcionamento_edital"],
        risco="médio",
    ),

    # ── FRAUDES NA EXECUÇÃO CONTRATUAL ────────────────────────────────────────

    FraudePattern(
        id="superfaturamento_preco",
        nome="Superfaturamento de Preços",
        categoria="contrato",
        descricao=(
            "Objeto contratado por preço muito acima do valor de mercado. Pode ocorrer "
            "desde o orçamento estimativo (BDI inflado, composição falsa de custos) ou "
            "na execução (materiais de qualidade inferior cobrados como premium)."
        ),
        como_detectar=[
            "Valor contratado > 2 desvios padrão acima da mediana da categoria",
            "BDI acima de 27,5% para obras (limite orientativo TCU)",
            "Preço unitário > 30% acima da tabela SINAPI/ORSE",
            "Comparação com contratos similares de outros órgãos: acima de 50%",
        ],
        red_flags=[
            "BDI especial", "preço único de mercado", "cotação exclusiva",
            "material especificado", "custo atípico justificado",
        ],
        base_legal=[
            "Lei 14.133/21 art. 23 (pesquisa de preços obrigatória)",
            "Lei 8.429/92 art. 10, XII",
            "IN SEGES 65/2021 (metodologia de pesquisa de preços)",
        ],
        casos_associados=["cabral_propinas", "secretaria_obras_obras", "witzel_saude_covid"],
        risco="alto",
    ),

    FraudePattern(
        id="aditivo_excessivo",
        nome="Aditivos Contratuais Excessivos",
        categoria="contrato",
        descricao=(
            "Contratos são celebrados com valor aparentemente razoável, mas recebem "
            "sucessivos termos aditivos que ampliam o valor e o prazo muito além do "
            "original. Limite legal: 25% obras/serviços, 50% reformas. "
            "Aditivos são usados para incluir escopo que deveria ter sido licitado."
        ),
        como_detectar=[
            "Soma de aditivos > 25% do valor original (lei 14.133/21)",
            "Mais de 3 aditivos para o mesmo contrato",
            "Aditivo de prazo sem justificativa de força maior",
            "Valor final do contrato 2x ou mais o valor original",
            "Aditivo logo após mudança de governo ou secretário",
        ],
        red_flags=[
            "termo aditivo", "TA nº", "prorrogação de prazo", "acréscimo de objeto",
            "reequilíbrio econômico-financeiro", "reajuste extraordinário",
        ],
        base_legal=[
            "Lei 14.133/21 art. 125 (limite 25%/50%)",
            "Lei 8.429/92 art. 10, XI",
            "TCU Acórdão 2.066/2018",
        ],
        casos_associados=["cabral_propinas", "secretaria_obras_obras", "cedae_quinto_ouro"],
        risco="alto",
    ),

    FraudePattern(
        id="medicao_fraudulenta",
        nome="Medição de Obras/Serviços Fraudulenta",
        categoria="contrato",
        descricao=(
            "Pagamentos são feitos por obras não realizadas, serviços não prestados "
            "ou quantitativos maiores do que os efetivamente executados. O fiscal do "
            "contrato assina medições falsas, geralmente mediante propina."
        ),
        como_detectar=[
            "Obras pagas sem registro fotográfico ou relatório de campo",
            "Pagamento total antes do prazo previsto de conclusão",
            "Inconsistência entre medições e notas fiscais",
            "Fiscal do contrato com empresa própria no mesmo setor",
            "Múltiplos contratos fiscalizados pela mesma pessoa com aditivos constantes",
        ],
        red_flags=[
            "medição aprovada", "boletim de medição", "BM aprovado", "fiscal",
            "ateste do gestor", "certificação de entrega",
        ],
        base_legal=[
            "Lei 14.133/21 art. 117 (fiscalização)",
            "Lei 8.429/92 art. 10, I",
            "CP art. 312 (peculato)",
        ],
        casos_associados=["cabral_propinas", "cedae_quinto_ouro"],
        risco="alto",
    ),

    FraudePattern(
        id="sub_rogacao_ilegal",
        nome="Sub-rogação / Cessão de Contrato Ilegal",
        categoria="contrato",
        descricao=(
            "A empresa vencedora da licitação transfere o contrato para outra empresa "
            "(geralmente menor, sem qualificação ou ligada a terceiros) sem autorização "
            "do órgão contratante. A empresa original retém parte do valor como 'taxa' "
            "sem executar nenhum trabalho real."
        ),
        como_detectar=[
            "CNPJ executor diferente do CNPJ contratado nas notas fiscais",
            "Notas fiscais emitidas por empresa sem CNPJ no contrato original",
            "Empresa vencedora sem funcionários (CAGED/e-Social) no período do contrato",
            "Subcontratação não prevista em edital ou acima do limite permitido",
        ],
        red_flags=[
            "subcontratação", "empresa terceirizada", "parceria operacional",
            "fornecedor autorizado", "execução por terceiros",
        ],
        base_legal=[
            "Lei 14.133/21 art. 122 (proibição de sub-rogação sem autorização)",
            "Lei 8.429/92 art. 10",
        ],
        casos_associados=["esquema_sa_saude"],
        risco="médio",
    ),

    # ── FRAUDES SISTÊMICAS / EMERGENTES ──────────────────────────────────────

    FraudePattern(
        id="os_oss_fraude",
        nome="OSs e OSCIPs como Veículos de Desvio",
        categoria="sistêmico",
        descricao=(
            "Organizações Sociais (OSs) e OSCIPs são contratadas sem licitação para "
            "gerir serviços públicos (hospitais, escolas, cultura). Servem como "
            "intermediárias que repassam contratos a empresas sem licitação, pagam "
            "salários de fantasmas e financiam partidos. A ausência de controle "
            "público direto facilita o desvio."
        ),
        como_detectar=[
            "OS com contratos > R$ 10M e sem histórico de atividade anterior",
            "OS com mesmo endereço de partido político ou sindicato",
            "OS cujos diretores são parentes de políticos",
            "Folha de pessoal da OS com CPFs que não aparecem em nenhuma formação",
            "Contrato com OS para área de atuação diferente da finalidade estatutária",
            "Aquisições pela OS a preços acima do mercado sem licitação própria",
        ],
        red_flags=[
            "organização social", "OS", "OSCIP", "contrato de gestão",
            "termo de parceria", "parceria voluntária", "MROSC",
        ],
        base_legal=[
            "Lei 9.637/98 (OSs — qualificação e controle)",
            "Lei 9.790/99 (OSCIPs)",
            "Lei 13.019/14 (MROSC — parcerias)",
            "TCU Acórdão 3.239/2013",
        ],
        casos_associados=["esquema_sa_saude", "witzel_saude_covid"],
        risco="alto",
    ),

    FraudePattern(
        id="empresa_recente_grande_contrato",
        nome="Empresa Recém-Aberta com Contrato de Grande Valor",
        categoria="contrato",
        descricao=(
            "Empresa aberta há menos de 6 meses obtém contrato de grande valor, "
            "sem histórico de trabalhos anteriores. Padrão clássico de empresa de "
            "fachada criada especificamente para capturar um contrato já direcionado."
        ),
        como_detectar=[
            "Data de abertura da empresa < 180 dias antes do contrato",
            "Capital social < 1% do valor do contrato",
            "Empresa sem funcionários (sem registros CAGED)",
            "Endereço residencial ou coworking",
            "Sócio sem experiência documentada no setor",
        ],
        red_flags=[
            "empresa nova", "recém-constituída", "início das atividades",
        ],
        base_legal=[
            "Lei 14.133/21 art. 67 (qualificação técnica e econômica)",
            "Lei 8.429/92 art. 10",
        ],
        casos_associados=["witzel_saude_covid", "codin_fundo_estado"],
        risco="alto",
    ),

    FraudePattern(
        id="doacao_contrato_reciproco",
        nome="Doação Eleitoral + Contrato (Quid Pro Quo)",
        categoria="sistêmico",
        descricao=(
            "Empresa ou sócio faz doação de campanha para candidato que, após eleito, "
            "direciona contratos para a mesma empresa ou para empresas do mesmo grupo "
            "econômico. Padrão documentado no STF (ADI 4650) e em múltiplos casos de "
            "improbidade administrativa."
        ),
        como_detectar=[
            "Empresa com contrato estadual doou para campanha de secretário/governador",
            "Sócio da empresa contratada fez doação pessoal ao candidato eleito",
            "Doação ocorreu 6 a 24 meses antes do primeiro contrato",
            "Valor do contrato > 100x o valor da doação (ROI suspeito)",
        ],
        red_flags=[
            "empresa patrocinadora", "apoio financeiro de campanha",
            "doador recorrente", "contribuição eleitoral",
        ],
        base_legal=[
            "Lei 9.504/97 art. 81 (doações eleitorais)",
            "Lei 8.429/92 art. 9, I",
            "CF/88 art. 37 (moralidade administrativa)",
        ],
        casos_associados=["cabral_propinas", "unfair_play_olimpiadas"],
        risco="alto",
    ),

    FraudePattern(
        id="ti_contrato_lock_in",
        nome="Contratos de TI com Lock-in Tecnológico",
        categoria="contrato",
        descricao=(
            "Sistema de TI é implementado de forma que apenas o fornecedor original "
            "pode dar manutenção (código proprietário, sem documentação, API fechada). "
            "Isso elimina a concorrência em renovações e cria dependência perpétua. "
            "Altíssimo potencial de superfaturamento em manutenções posteriores."
        ),
        como_detectar=[
            "Renovações de contrato de TI sem licitação por 'inexigibilidade' repetidas",
            "Contrato de TI com cláusula de 'exclusividade de suporte'",
            "Preço de manutenção anual > 20% do valor de aquisição",
            "Ausência de cláusula de entrega de código-fonte",
            "Empresa de TI com único cliente (o órgão contratante)",
        ],
        red_flags=[
            "sistema proprietário", "suporte exclusivo", "manutenção evolutiva",
            "integração legada", "migração inviável", "customização específica",
        ],
        base_legal=[
            "IN SGD/ME 1/2019 (software público)",
            "Lei 14.133/21 art. 74, III (inexigibilidade — limite)",
            "Lei 8.429/92 art. 10, XII",
        ],
        casos_associados=[],
        risco="médio",
    ),

    FraudePattern(
        id="consulta_ppp_privatizacao_manipulada",
        nome="Manipulação de Dados em Privatizações e Concessões",
        categoria="sistêmico",
        descricao=(
            "Dados financeiros ou operacionais são manipulados antes de privatizações "
            "e concessões para alterar o valor do ativo e favorecer determinado comprador "
            "ou grupo. Pode envolver auditores externos cooptados, omissão de passivos "
            "ou inflação artificial de receitas projetadas."
        ),
        como_detectar=[
            "Auditoria de avaliação contratada com empresa ligada ao comprador",
            "Projeções de receita muito acima dos dados históricos (> 50% de crescimento)",
            "Passivos ambientais ou trabalhistas omitidos no prospecto",
            "Consultor do processo de privatização depois contratado pelo comprador",
            "Modelagem financeira não disponível para consulta pública",
        ],
        red_flags=[
            "avaliação econômica", "fluxo de caixa descontado", "valor de outorga",
            "deságio", "VPL da concessão", "modelagem financeira",
        ],
        base_legal=[
            "Lei 13.303/16 art. 76 (estatais — vedações)",
            "Lei 8.429/92 art. 11 (violação de princípios)",
            "CVM Instrução 480 (informação ao mercado)",
        ],
        casos_associados=["cedae_quinto_ouro"],
        risco="alto",
    ),

    FraudePattern(
        id="nomeacao_cargo_retribuicao",
        nome="Nomeação para Cargo em Retribuição a Apoio Político",
        categoria="pessoal",
        descricao=(
            "Cargos comissionados são distribuídos como moeda de troca para garantir "
            "apoio político na Assembleia, em partidos aliados ou para recompensar "
            "apoiadores de campanha. A pessoa nomeada pode ser incompetente, parente "
            "de aliado ou uma forma de transferir renda pública para o grupo político."
        ),
        como_detectar=[
            "Nomeação nos primeiros 30 dias após eleição ou troca de secretário",
            "Pessoa nomeada sem formação ou experiência na área do cargo",
            "Mesmo CPF nomeado em múltiplos cargos em mandatos consecutivos",
            "Nomeado é parente de deputado que votou a favor de projeto do executivo",
            "Altas concentrações de nomeações de um único município ou reduto eleitoral",
        ],
        red_flags=[
            "nomeação", "designação", "exoneração a pedido", "cargo comissionado",
            "DAS", "função gratificada", "secretário adjunto",
        ],
        base_legal=[
            "CF/88 art. 37, II (concurso público — regra geral)",
            "Súmula Vinculante 13 (nepotismo)",
            "Lei 8.429/92 art. 11",
        ],
        casos_associados=["mensalao_alerj", "furna_da_onca", "witzel_saude_covid"],
        risco="médio",
    ),

    FraudePattern(
        id="lavagem_via_empresa_cultura",
        nome="Lavagem via Contratos Culturais / Patrocínios",
        categoria="sistêmico",
        descricao=(
            "Recursos públicos são canalizados para shows, eventos culturais, patrocínios "
            "e prêmios fictícios de artistas ligados ao grupo político. Os valores são "
            "inflados, parte retorna como propina. Muito usado por secretarias de cultura, "
            "turismo e comunicação."
        ),
        como_detectar=[
            "Contrato cultural com empresa sem CNAE de atividade cultural",
            "Valor de cachê > 3x a mediana do mercado para o mesmo tipo de evento",
            "Empresa cultural aberta há < 6 meses com contrato de grande valor",
            "Artista ou empresa tem sócio com laço familiar com secretário",
            "Evento não divulgado publicamente, sem registro de público",
        ],
        red_flags=[
            "show", "evento cultural", "cachê", "patrocínio", "lei de incentivo",
            "espetáculo", "festival", "homenagem", "prêmio cultural",
        ],
        base_legal=[
            "Lei 14.133/21 art. 74 (inexigibilidade para artistas — limite)",
            "Lei 8.429/92 art. 10, XII",
            "Lei 9.613/98 (lavagem de dinheiro)",
        ],
        casos_associados=["cabral_propinas"],
        risco="alto",
    ),

    FraudePattern(
        id="fantasma_folha_orgao",
        nome="Funcionário Fantasma na Folha",
        categoria="pessoal",
        descricao=(
            "Pessoa está registrada na folha de pagamento mas não trabalha. "
            "Pode ser parente do gestor, pessoa que já morreu, CPF fictício ou "
            "pessoa que trabalha em outra atividade (empresa própria, outro emprego). "
            "A remuneração é desviada total ou parcialmente."
        ),
        como_detectar=[
            "CPF sem registros de acesso nos sistemas do órgão",
            "Servidor sem lotação definida ou lotado em unidade inexistente",
            "Remuneração paga regularmente mas sem desconto de INSS/IR compatível",
            "CPF do servidor é sócio de empresa ativa (indicativo de outro emprego)",
            "Nome/CPF que aparece em múltiplos órgãos simultaneamente",
            "Remuneração zerada por vários meses consecutivos",
        ],
        red_flags=[
            "sem lotação", "lotação provisória", "requisitado", "cedido",
            "licença especial", "afastamento", "disponibilidade",
        ],
        base_legal=[
            "Lei 8.429/92 art. 9, II (enriquecimento ilícito)",
            "CP art. 312 (peculato)",
            "CF/88 art. 37, XVI (vedação ao acúmulo)",
        ],
        casos_associados=["esquema_sa_saude", "detran_habilitacoes"],
        risco="alto",
    ),

]


# ── Índices para busca rápida ─────────────────────────────────────────────────

FRAUDES_POR_ID: dict[str, FraudePattern] = {f.id: f for f in FRAUDES}

FRAUDES_POR_CATEGORIA: dict[str, list[FraudePattern]] = {}
for _f in FRAUDES:
    FRAUDES_POR_CATEGORIA.setdefault(_f.categoria, []).append(_f)

TODOS_RED_FLAGS: list[tuple[str, str]] = [
    (flag.lower(), f.id)
    for f in FRAUDES
    for flag in f.red_flags
]
