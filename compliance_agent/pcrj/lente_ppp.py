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

# (tipo, gravidade, base_legal, regex, o_que_verificar)
_CHECKS = [
    ("garantia_receita_saude", "alta",
     "CF art. 198/167,IV; LC 141/2012; Lei 11.079 art. 8º,I",
     re.compile(r"receitas?\s+vinculad\w+\s+d[oe]\s+(FUNDO NACIONAL DE SA[ÚU]DE|FNS|SA[ÚU]DE)"
                r"|FUNDO NACIONAL DE SA[ÚU]DE.{0,60}garantia|garantia.{0,60}FUNDO NACIONAL DE SA[ÚU]DE", re.I),
     "Receita vinculada do SUS/FNS (transferência federal condicionada, não é receita própria) "
     "dada em garantia — verificar legalidade e piso da saúde."),
    ("aporte_publico", "media",
     "Lei 11.079 art. 6º, §2º e art. 7º",
     re.compile(r"APORTE\s+P[ÚU]BLICO|aporte de recursos\s+em favor da\s+CONCESSION", re.I),
     "Aporte público de recursos à concessionária — verificar cronograma, contrapartida e contabilização."),
    ("pmi_privado_ressarcimento", "alta",
     "Lei 14.133 art. 14; Decreto 8.428/2015 art. 6º",
     re.compile(r"Procedimento de Manifesta[çc][ãa]o de Interesse|\bPMI\b|\bMIP\b|ressarcimento dos estudos", re.I),
     "Modelagem por PMI privado + ressarcimento — cruzar QSA do autor dos estudos com a SPE/financiadores "
     "(vedação de o modelador ser contratado, direta ou indiretamente)."),
    ("prazo_longo", "media",
     "Lei 11.079 art. 5º, I (prazo 5–35 anos); LRF arts. 16/17 (DOCC)",
     re.compile(r"\b3[05]\s*\(?\s*(trinta|trinta e cinco)\)?\s*anos|PRAZO DA CONCESS[ÃA]O.{0,40}anos", re.I),
     "Prazo longo (≈30+ anos) = despesa obrigatória continuada — exigir estimativa de impacto e adequação (LRF)."),
    ("valor_vs_rcl", "alta",
     "Lei 11.079 art. 28 (teto 5% da RCL, Municípios)",
     re.compile(r"VALOR ESTIMADO DO CONTRATO|somat[óo]rio de valores devidos.{0,40}CONCESSION", re.I),
     "Valor estimado do contrato (soma de contraprestações) — confrontar com o teto de 5% da RCL do Município."),
    ("verificador_independente", "media",
     "Lei 11.079 art. 5º; boa prática de segregação",
     re.compile(r"VERIFICADOR INDEPENDENTE", re.I),
     "Verificador independente — verificar quem o indica e remunera (independência frente à concessionária)."),
    ("garantia_publica_conta", "baixa",
     "Lei 11.079 art. 8º; Conta Garantia",
     re.compile(r"CONTA GARANTIA|GARANTIA P[ÚU]BLICA", re.I),
     "Estrutura de garantia pública / conta garantia — verificar instituição depositária e regras de execução."),
]


def analisar_ppp(texto: str) -> dict:
    """Aplica os checks de PPP sobre o texto. Retorna {flags, grau, n_altas}.

    ``grau``: 🔴 alto se ≥1 flag de gravidade alta; 🟡 médio se só médias; 🟢 baixo caso contrário.
    """
    t = texto or ""
    flags = []
    for tipo, grav, base, rx, verificar in _CHECKS:
        m = rx.search(t)
        if m:
            i = m.start()
            trecho = re.sub(r"\s+", " ", t[max(0, i - 40):i + 180]).strip()
            flags.append({"tipo": tipo, "gravidade": grav, "base_legal": base,
                          "trecho": trecho[:220], "verificar": verificar})
    n_altas = sum(1 for f in flags if f["gravidade"] == "alta")
    if n_altas:
        grau = "🔴 alto"
    elif any(f["gravidade"] == "media" for f in flags):
        grau = "🟡 médio"
    else:
        grau = "🟢 baixo"
    return {"flags": flags, "grau": grau, "n_flags": len(flags), "n_altas": n_altas,
            "ressalva": "Indício ≠ irregularidade; várias estruturas são legais e só pedem verificação."}
