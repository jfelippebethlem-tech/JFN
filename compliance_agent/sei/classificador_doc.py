# -*- coding: utf-8 -*-
"""Classifica cada documento da árvore do SEI por TIPO, a partir do título (keywords; sem chute).

Onda 5 (SEI funcional). Os rótulos foram calibrados com os títulos reais que o SEI-RJ usa (a Onda B —
piloto — salva a árvore real e confirma/expande esta lista). Honesto: título sem match → 'outros'.
Os tipos que carregam PREÇO UNITÁRIO são DOCS_COM_PRECO (prioridade do extrator)."""
from __future__ import annotations

import unicodedata

# Rótulos CALIBRADOS com os títulos reais do SEI-RJ (piloto Onda B/C, processos SRP da UG 270060):
# vistos: "Nota de Empenho Original - NE", "Nota de Autorização de Despesa - NAD", "Despacho de
# Encaminhamento de Processo", "Recibo", "E-mail", "Ofício", "Anexo". A ARP/tabela de preço NÃO aparece
# nos processos de EXECUÇÃO (empenho); vive no processo de LICITAÇÃO/pregão (SRP) — alvo do varredor.
# Ordem IMPORTA: tipos específicos/de alto valor primeiro (o 1º match vence). Calibrado com árvores reais
# (piloto SRP UG 270060) + estrutura legal do processo (Lei 14.133: DFD→ETP/TR→edital→PARECER JURÍDICO→
# sessão/mapa→homologação→ARP/contrato→empenho→liquidação→OB). Insight do dono: o PARECER JURÍDICO (PGE/
# assessoria do órgão) é onde as FALHAS do processo aparecem → alto valor para o Lex.
TIPOS: dict[str, list[str]] = {
    "parecer_juridico": ["parecer", "procuradoria", " pge", "analise juridica", "nota juridica",
                         "manifestacao juridica", "assessoria juridica", "cota juridica"],
    "homologacao": ["homologacao", "termo de homologacao", "homologa", "termo de adjudicacao", "adjudicacao"],
    "ata_rp": ["ata de registro de preco", "ata de registro de precos", "registro de precos", "arp"],
    "contrato": ["termo de contrato", "contrato n", "instrumento contratual", "termo aditivo"],
    "mapa_lances": ["mapa de lances", "mapa de apuracao", "apuracao de lances", "ata da sessao",
                    "resultado por fornecedor", "termo de julgamento"],
    "planilha_preco": ["planilha de preco", "planilha de custos", "proposta de preco", "proposta comercial",
                       "mapa de preco", "quadro de precos", "cotacao"],
    "pesquisa_precos": ["pesquisa de preco", "cesta de preco", "estimativa de preco", "pesquisa mercadologica"],
    "etp": ["estudo tecnico preliminar", "etp", "estudo preliminar"],
    "tr": ["termo de referencia", "projeto basico"],
    "edital": ["edital", "aviso de licitacao", "pregao eletronico", "pregao presencial"],
    "empenho": ["nota de empenho", "empenho"],
    "liquidacao": ["nota de liquidacao", "liquidacao"],
    "autorizacao_despesa": ["autorizacao de despesa", "nota de autorizacao de despesa", "nad"],
    "tramitacao": ["despacho de encaminhamento", "despacho", "informacao", "oficio", "memorando",
                   "e-mail", "email", "recibo", "comprovante", "anexo", "capa"],
}

# documentos que carregam a tabela de itens com preço unitário (prioridade do varredor de preços)
DOCS_COM_PRECO = ("homologacao", "ata_rp", "contrato", "mapa_lances", "planilha_preco")

# VALOR fiscalizatório do documento → define O QUE GUARDAR (pedido do dono: nem todo ofício é útil):
#  alto  = extrair e GUARDAR o texto/itens (revela objeto, preço, falhas — alimenta Lex/extrator);
#  medio = guardar metadados + valor (empenho/liquidação/NAD);
#  baixo = guardar só título + contagem (NÃO o texto): tramitação/ruído.
_VALOR = {
    "alto": {"parecer_juridico", "homologacao", "ata_rp", "contrato", "mapa_lances", "planilha_preco",
             "pesquisa_precos", "etp", "tr", "edital"},
    "medio": {"empenho", "liquidacao", "autorizacao_despesa"},
}


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def classificar_doc(titulo: str) -> str:
    """Tipo do documento pelo título. 'outros' quando nenhum rótulo casa (honesto, não chuta)."""
    t = _n(titulo)
    for tipo, kws in TIPOS.items():
        if any(_n(k) in t for k in kws):
            return tipo
    return "outros"


def tem_preco(tipo: str) -> bool:
    """True se o tipo de documento tende a conter a tabela de preço unitário."""
    return tipo in DOCS_COM_PRECO


def valor_doc(tipo: str) -> str:
    """Valor fiscalizatório do tipo: 'alto' | 'medio' | 'baixo'. Decide o que guardar."""
    if tipo in _VALOR["alto"]:
        return "alto"
    if tipo in _VALOR["medio"]:
        return "medio"
    return "baixo"


def deve_guardar_texto(tipo: str) -> bool:
    """Política de storage (pedido do dono — nem todo ofício é útil): guardar o TEXTO só de docs alto/médio.
    Ruído (tramitação/ofício/e-mail/recibo/anexo) → guardar só título + contagem, não o conteúdo."""
    return valor_doc(tipo) in ("alto", "medio")
