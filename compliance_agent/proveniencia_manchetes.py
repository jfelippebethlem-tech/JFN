# -*- coding: utf-8 -*-
"""Bloco `proveniencia` das rotas que servem manchetes do painel (PAD-01/02/06/07).

Cada manchete inventariada em `config/qualidade_inventario.yaml` diz, no próprio payload, de onde vem o número
(fonte), de quando é o dado (data_ref), que fração do universo a fonte enxerga (cobertura), o estado da
verificação (VERIFICADO/PENDENTE/INDISPONIVEL/REFUTADO), o que o valor é (natureza) e de que ente trata (esfera).

Estado: indício de detector é PENDENTE até conferência na fonte primária item a item — a taxa de falso positivo
medida em amostra (COR-04) fica em `config/qualidade_detectores.yaml`, não promove o número a VERIFICADO.
Medição do próprio sistema (frescor, motores) é VERIFICADO: o número é lido agora, na fonte.
"""
from __future__ import annotations

from datetime import datetime

# rota → bloco fixo; `data_ref` sai do payload (campo de geração) e `cobertura` pode ganhar os números do payload
PROVENIENCIA: dict[str, dict] = {
    "/api/comparador/economia": {
        "fonte": "PNCP — itens homologados (pncp_resultado, pncp_ente) no compliance.db",
        "cobertura": "compras homologadas no PNCP do Estado do RJ e da Prefeitura do Rio, fora de ata, com o mesmo "
                     "item na mesma unidade; quantidade homologada, não OB paga",
        "estado": "PENDENTE", "natureza": "estimado", "esfera": "mista_com_quebra",
    },
    "/api/comparador/vedada": {
        "fonte": "PNCP (pncp_resultado, pncp_ente) × CEIS/CNEP (sancoes_federais) no compliance.db",
        "cobertura": "compras homologadas no PNCP do Estado do RJ e da Prefeitura do Rio com sanção vigente na data e "
                     "alcance sobre o comprador; quantidade homologada, não OB paga",
        "estado": "PENDENTE", "natureza": "estimado", "esfera": "mista_com_quebra",
    },
    "/api/comparador/dossie": {
        "fonte": "PNCP (pncp_resultado, pncp_ente) × CEIS/CNEP (sancoes_federais) × fantasma_score no compliance.db",
        "cobertura": "itens homologados no PNCP do Estado do RJ e da Prefeitura do Rio ≥ 3× a mediana do mesmo item",
        "estado": "PENDENTE", "natureza": "contagem", "esfera": "mista_com_quebra",
    },
    "/api/intel/radar": {
        "fonte": "cache do radar (data/cache_intel) ← fantasma_score, favorecido_resumo, pncp_resultado, "
                 "socios_fornecedor, sancoes_federais",
        "cobertura": "fornecedores pagos pelo Estado do RJ com ao menos um sinal registrado; score é triagem interna",
        "estado": "PENDENTE", "natureza": "indice", "esfera": "estadual",
    },
    "/api/intel/fenix": {
        "fonte": "SIAFE-Rio — OB Orçamentária paga (ob_orcamentaria_siafe, filtro _ob_paga) × Receita Federal "
                 "(situação cadastral e data da situação)",
        "cobertura": "credores PJ do Estado do RJ com data de baixa/inaptidão no dump da Receita; sem data de baixa "
                     "fica fora da manchete",
        "estado": "PENDENTE", "natureza": "pago", "esfera": "estadual",
    },
    "/api/intel/comunidades": {
        "fonte": "cache de comunidades (data/cache_intel) ← socios_receita, pncp_resultado, ob_orcamentaria_siafe",
        "cobertura": "grafo família-empresa-órgão dos fornecedores do Estado do RJ com QSA conhecido",
        "estado": "PENDENTE", "natureza": "contagem", "esfera": "estadual",
    },
    "/api/intel/ninho_sala": {
        "fonte": "Receita Federal (estabelecimentos: endereço + complemento) × SIAFE-Rio (OB paga, favorecido_resumo)",
        "cobertura": "CNPJs com complemento que identifica a sala/andar no dump da Receita e que receberam OB do "
                     "Estado do RJ",
        "estado": "PENDENTE", "natureza": "contagem", "esfera": "estadual",
    },
    "/api/intel/lift": {
        "fonte": "sinal_ledger e fantasma_score × CEIS/CNEP (sancoes_federais) — gabarito de sanção de qualquer época",
        "cobertura": "fornecedores do PNCP com sinal registrado; sanção não mede irregularidade nem vigência à época",
        "estado": "PENDENTE", "natureza": "indice", "esfera": "estadual",
    },
    "/api/compliance/painel": {
        "fonte": "tabela alertas (motor de regras) e SIAFE-Rio — OB Orçamentária (ob_orcamentaria_siafe) no compliance.db",
        "cobertura": "alertas não descartados do motor de regras; OB do SIAFE já coletadas (ver Sistema › Motores)",
        "estado": "PENDENTE", "natureza": "contagem", "esfera": "estadual",
    },
    "/api/compliance/painel#obs": {
        "fonte": "SIAFE-Rio — OB Orçamentária (ob_orcamentaria_siafe), status Contabilizado; tfe_* é o espelho TFE (parcial)",
        "cobertura": "OB do SIAFE já coletadas; o último dia é o último com OB coletada, não necessariamente hoje",
        "estado": "VERIFICADO", "natureza": "pago", "esfera": "estadual",
    },
    "/api/fontes/frescor": {
        "fonte": "tabelas das coletas no compliance.db e travas dos coletores (medido no momento da leitura)",
        "cobertura": "as coletas listadas em `fontes`; fonte fora da lista não é medida aqui",
        "estado": "VERIFICADO", "natureza": "contagem", "esfera": "sistema",
    },
    "/api/ao-vivo/estado": {
        "fonte": "systemd e travas dos motores (compliance_agent/aovivo/motores.yaml), lidos no momento",
        "cobertura": "os motores declarados em motores.yaml; eventos são os mais recentes (lista com teto)",
        "estado": "VERIFICADO", "natureza": "contagem", "esfera": "sistema",
    },
}

_CAMPOS_DATA = ("gerado_em", "gerado", "atualizado_em", "atualizado", "em")


def _data_ref(d: dict) -> str:
    for c in _CAMPOS_DATA:
        if d.get(c):
            return str(d[c])
    return datetime.now().isoformat(timespec="seconds")


def anexar(rota: str, d):
    """Devolve o payload com `proveniencia` (não sobrescreve um bloco que a rota já monte). Erro fica sem bloco:
    a rota que falhou diz INDISPONÍVEL pelo próprio `ok: false`, não por uma proveniência inventada."""
    base = PROVENIENCIA.get(rota)
    if not base or not isinstance(d, dict) or d.get("ok") is False or isinstance(d.get("proveniencia"), dict):
        return d
    return {**d, "proveniencia": {**base, "data_ref": _data_ref(d)}}
