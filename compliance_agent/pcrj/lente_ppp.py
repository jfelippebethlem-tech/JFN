# -*- coding: utf-8 -*-
"""Lente específica de PPP/concessão — red flags que os motores de pregão não pegam.

Concessão administrativa de 30 anos não aciona as heurísticas de habilitação de
pregão comum. Esta lente aplica os pontos de exame que a perícia do Souza Aguiar
consolidou (garantia via receita da saúde, aporte, PMI-captura, prazo/valor vs
5% RCL, verificador independente). Determinístico, sobre o TEXTO do edital/contrato.

Honestidade: cada flag é INDÍCIO com base legal e trecho; presença ≠ irregularidade
(muitos são estruturas legais que só pedem verificação). Complementa
``knowledge.fraudes_licitacao`` (padrão ``consulta_ppp_privatizacao_manipulada``).
"""
from __future__ import annotations

import re

# Cada check cruza o achado com a base normativa E a jurisprudência/entendimento dos Tribunais
# de Contas. Honestidade: súmulas TCU e dispositivos conferidos em fonte; entendimentos citados
# como princípio (sem nº de acórdão não confirmado). Competência: PPP municipal do Rio = TCM-RJ;
# precedentes do TCU são persuasivos/analógicos sobre as normas gerais federais.
_CHECKS = [
    {"tipo": "garantia_receita_saude", "gravidade": "alta",
     "base_legal": "CF art. 167, IV e art. 198, §2º/§3º; LC 141/2012; Lei 8.080/90; Lei 11.079 art. 8º, I",
     "jurisprudencia":
        "CF art. 167, IV veda vincular receita de impostos, ressalvada a saúde — mas a exceção é para "
        "CUSTEAR ações e serviços de saúde (ASPS), não para servir de penhor a terceiro. LC 141/2012 + "
        "Lei 8.080/90: recursos do FNS são transferências federais fundo-a-fundo CONDICIONADAS — não são "
        "receita própria do Município, e garantia só recai sobre receita própria. A própria Lei 11.079 "
        "(art. 8º, I) condiciona a vinculação de receitas ao art. 167, IV da CF. O TCU admite receita "
        "PRÓPRIA em garantia de operações do ente, mas o lastro em repasse condicionado da saúde é o ponto "
        "frágil (a confirmar em acórdão específico no portal TCU).",
     "regex": re.compile(r"receitas?\s+vinculad\w+\s+d[oe]\s+(FUNDO NACIONAL DE SA[ÚU]DE|FNS|SA[ÚU]DE)"
                r"|FUNDO NACIONAL DE SA[ÚU]DE.{0,60}garantia|garantia.{0,60}FUNDO NACIONAL DE SA[ÚU]DE", re.I),
     "verificar": "Receita vinculada do SUS/FNS (transferência federal condicionada, não é receita própria) "
        "dada em garantia — verificar legalidade e o piso da saúde."},
    {"tipo": "aporte_publico", "gravidade": "media",
     "base_legal": "Lei 11.079 art. 6º, §2º e art. 7º",
     "jurisprudencia":
        "O aporte público de recursos só é admitido após a disponibilização parcial do objeto (art. 7º) e "
        "com contabilização própria (art. 6º, §2º). Entendimento do TCU: cronograma de aporte deve casar com "
        "a entrega efetiva; aporte antecipado sem contrapartida física transfere risco indevido ao erário.",
     "regex": re.compile(r"APORTE\s+P[ÚU]BLICO|aporte de recursos\s+em favor da\s+CONCESSION", re.I),
     "verificar": "Aporte público à concessionária — verificar cronograma, contrapartida e contabilização."},
    {"tipo": "pmi_privado_ressarcimento", "gravidade": "alta",
     "base_legal": "Lei 14.133 art. 14, I e §1º; Decreto 8.428/2015 art. 6º e arts. 16-18",
     "jurisprudencia":
        "Decreto 8.428/2015 art. 6º: a autorização do PMI é SEM exclusividade e NÃO gera direito de "
        "preferência na licitação; arts. 16-18: os estudos são ressarcidos pelo VENCEDOR (não pelo erário). "
        "Lei 14.133 art. 14, I e §1º: o autor de projeto/estudo — PF ou PJ, e empresas do MESMO GRUPO "
        "ECONÔMICO — não participa, direta ou indiretamente, da licitação do objeto correlato. O TCU trata "
        "a adoção acrítica do modelo do particular como CAPTURA da modelagem (vício de motivação).",
     "regex": re.compile(r"Procedimento de Manifesta[çc][ãa]o de Interesse|\bPMI\b|\bMIP\b|ressarcimento dos estudos", re.I),
     "verificar": "Modelagem por PMI privado + ressarcimento — cruzar QSA do autor dos estudos com a "
        "SPE/financiadores (vedação de o modelador ser contratado, direta ou indiretamente)."},
    {"tipo": "prazo_longo", "gravidade": "media",
     "base_legal": "Lei 11.079 art. 5º, I; LRF (LC 101/2000) arts. 16/17; Lei 11.079 art. 10",
     "jurisprudencia":
        "Prazo de 5 a 35 anos (Lei 11.079 art. 5º, I). Contraprestação por décadas é despesa obrigatória de "
        "caráter continuado (LRF arts. 16/17): exige estimativa de impacto trienal e medidas de compensação. "
        "Lei 11.079 art. 10: a abertura da licitação exige demonstração de conveniência, estimativa de impacto "
        "orçamentário e declaração de compatibilidade com a LRF e a LDO — condição de validade da modelagem.",
     "regex": re.compile(r"\b3[05]\s*\(?\s*(trinta|trinta e cinco)\)?\s*anos|PRAZO DA CONCESS[ÃA]O.{0,40}anos", re.I),
     "verificar": "Prazo longo (≈30+ anos) = despesa obrigatória continuada — exigir estimativa de impacto e "
        "declaração de adequação (LRF/LDO, art. 10)."},
    {"tipo": "valor_vs_rcl", "gravidade": "alta",
     "base_legal": "Lei 11.079 art. 28 (Estados/DF/Municípios); art. 22 (União = 1%)",
     "jurisprudencia":
        "Lei 11.079 art. 28: a União não concede garantia nem transferência voluntária ao ente cujas despesas "
        "de PPP EXCEDAM 5% da RCL do exercício ou projetadas para os 10 anos seguintes (redação da Lei "
        "12.766/2012). Regra objetiva e prudencial — o estouro do teto acarreta perda de garantias/"
        "transferências da União. Exigir a memória de cálculo do estoque de PPPs do Município frente à RCL.",
     "regex": re.compile(r"VALOR ESTIMADO DO CONTRATO|somat[óo]rio de valores devidos.{0,40}CONCESSION", re.I),
     "verificar": "Valor estimado (soma das contraprestações) — confrontar com o teto de 5% da RCL do Município."},
    {"tipo": "verificador_independente", "gravidade": "media",
     "base_legal": "Lei 11.079 art. 5º; princípio da segregação de funções",
     "jurisprudencia":
        "A aferição de desempenho (Lei 11.079 art. 5º) que baliza a contraprestação deve ser INDEPENDENTE "
        "da concessionária. Boa prática consolidada (TCU/doutrina): atenção a QUEM indica e QUEM remunera o "
        "verificador — verificador indicado/pago pela própria SPE compromete a segregação de funções e a "
        "confiabilidade da medição que define o quanto o poder público paga.",
     "regex": re.compile(r"VERIFICADOR INDEPENDENTE", re.I),
     "verificar": "Verificador independente — verificar quem o indica e remunera (independência frente à SPE)."},
    {"tipo": "garantia_publica_conta", "gravidade": "baixa",
     "base_legal": "Lei 11.079 art. 8º; contrato de conta garantia",
     "jurisprudencia":
        "Lei 11.079 art. 8º traz rol TAXATIVO de garantias das obrigações do parceiro público. A garantia "
        "deve ser exequível e não pode comprometer a capacidade fiscal do ente. Verificar a instituição "
        "depositária da conta garantia e as regras de execução (gatilhos, prazos, cascata de acionamento).",
     "regex": re.compile(r"CONTA GARANTIA|GARANTIA P[ÚU]BLICA", re.I),
     "verificar": "Estrutura de garantia pública / conta garantia — verificar depositária e regras de execução."},
]


def analisar_ppp(texto: str) -> dict:
    """Aplica os checks de PPP sobre o texto. Retorna {flags, grau, n_altas}.

    Cada flag traz ``base_legal``, ``jurisprudencia`` (entendimento dos Tribunais de Contas) e o
    ``trecho`` do edital/contrato. ``grau``: 🔴 alto se ≥1 flag alta; 🟡 médio se só médias; 🟢 baixo.
    """
    t = texto or ""
    flags = []
    for chk in _CHECKS:
        m = chk["regex"].search(t)
        if m:
            i = m.start()
            trecho = re.sub(r"\s+", " ", t[max(0, i - 40):i + 180]).strip()
            flags.append({"tipo": chk["tipo"], "gravidade": chk["gravidade"],
                          "base_legal": chk["base_legal"], "jurisprudencia": chk["jurisprudencia"],
                          "trecho": trecho[:220], "verificar": chk["verificar"]})
    n_altas = sum(1 for f in flags if f["gravidade"] == "alta")
    if n_altas:
        grau = "🔴 alto"
    elif any(f["gravidade"] == "media" for f in flags):
        grau = "🟡 médio"
    else:
        grau = "🟢 baixo"
    return {"flags": flags, "grau": grau, "n_flags": len(flags), "n_altas": n_altas,
            "ressalva": "Indício ≠ irregularidade; várias estruturas são legais e só pedem verificação."}
