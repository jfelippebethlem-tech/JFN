"""
Avaliação da perícia contra um conjunto-ouro — o "teste de regressão" do sistema.

Para o autoaprimoramento ser seguro, precisa de um juiz imparcial: um conjunto
de casos ROTULADOS (o que DEVE disparar e o que NÃO PODE disparar) que mede o
desempenho da perícia inteira a cada mudança de parâmetro. É o mesmo princípio
de uma suíte de testes: nenhuma "melhoria" é aceita se piorar o placar aqui.

O conjunto embutido modela esquemas reais do RJ (OS de saúde na pandemia,
fracionamento em obras, quid pro quo eleitoral, empresa de fachada) e casos
LIMPOS (contratações normais que não podem gerar alarme falso). O perito pode
acrescentar casos próprios em ``data/nucleo_casos_ouro.json`` — cada perícia
confirmada na vida real pode virar um caso-ouro, fechando o ciclo: o sistema
aprende com a própria história.

Métricas: precisão, cobertura (recall) e F1 por indicador + placar global.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from compliance_agent.nucleo.dossie import Contratacao, Dossie, Fornecedor
from compliance_agent.nucleo.indicadores import avaliar_todos


def _arquivo_extra() -> Path:
    return Path(os.environ.get("NUCLEO_CASOS_OURO", "data/nucleo_casos_ouro.json"))


@dataclass
class CasoOuro:
    """Um caso rotulado: dossiê + indicadores esperados/proibidos."""

    id: str
    descricao: str
    dossie: dict                       # kwargs p/ Contratacao/Fornecedor/etc.
    deve_disparar: list[str] = field(default_factory=list)    # indicador_ids
    nao_pode_disparar: list[str] = field(default_factory=list)


# ── Conjunto embutido (modelado nos padrões reais do RJ) ─────────────────────

CASOS_EMBUTIDOS: list[CasoOuro] = [
    CasoOuro(
        id="ouro_os_saude_pandemia",
        descricao="OS de saúde recém-criada, dispensa de vulto, sobrepreço e doação",
        dossie={
            "contratacao": {"valor": 18_500_000, "data": "2024-05-20",
                            "modalidade": "dispensa", "categoria": "saúde",
                            "propostas_validas": 1,
                            "aditivos_valor": 6_000_000, "aditivos_qtd": 2},
            "fornecedor": {"cnpj": "11222333000181", "data_abertura": "2024-02-01",
                           "capital_social": 10_000,
                           "doacoes_eleitorais": [{"valor": 80_000,
                                                   "data": "2023-09-01",
                                                   "candidato": "X"}]},
            "referencia_categoria": {"mediana": 4_000_000,
                                     "desvio_padrao": 1_500_000,
                                     "referencia_mercado": 5_000_000},
        },
        deve_disparar=["IND-EMP-01", "IND-ADT-01", "IND-SUP-01",
                       "IND-QPQ-01", "IND-DIR-01"],
    ),
    CasoOuro(
        id="ouro_fracionamento_obras",
        descricao="3 dispensas seguidas do mesmo fornecedor somando acima do teto",
        dossie={
            "contratacao": {"identificador": "E-1", "valor": 48_500,
                            "data": "2024-05-01", "modalidade": "dispensa"},
            "fornecedor": {"cnpj": "11222333000181"},
            "historico": [
                {"identificador": "E-2", "valor": 49_000, "data": "2024-05-20",
                 "modalidade": "dispensa"},
                {"identificador": "E-3", "valor": 48_000, "data": "2024-06-10",
                 "modalidade": "dispensa"},
            ],
        },
        deve_disparar=["IND-FRAC-01"],
    ),
    CasoOuro(
        id="ouro_sancionada",
        descricao="Fornecedor em CEIS/CNEP recebendo pagamento",
        dossie={
            "contratacao": {"valor": 300_000, "data": "2024-03-01"},
            "fornecedor": {"cnpj": "11222333000181", "sancionado": True},
        },
        deve_disparar=["IND-SAN-01"],
    ),
    CasoOuro(
        id="ouro_aditivo_estouro",
        descricao="Contrato de obra com aditivos de 40% do valor original",
        dossie={
            "contratacao": {"valor": 10_000_000, "aditivos_valor": 4_000_000,
                            "aditivos_qtd": 2, "data": "2023-08-15",
                            "categoria": "obras"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2015-01-01",
                           "capital_social": 8_000_000},
        },
        deve_disparar=["IND-ADT-01"],
        nao_pode_disparar=["IND-EMP-01"],
    ),
    CasoOuro(
        id="ouro_limpo_pregao",
        descricao="Pregão competitivo normal — NÃO pode gerar alarme",
        dossie={
            "contratacao": {"valor": 800_000, "data": "2024-04-10",
                            "modalidade": "pregão", "propostas_validas": 7,
                            "prazo_edital_dias": 20, "categoria": "informática"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2008-06-01",
                           "capital_social": 3_000_000},
            "referencia_categoria": {"mediana": 750_000, "desvio_padrao": 200_000},
        },
        nao_pode_disparar=["IND-EMP-01", "IND-SUP-01", "IND-DIR-01",
                           "IND-FRAC-01", "IND-ADT-01", "IND-QPQ-01"],
    ),
    CasoOuro(
        id="ouro_limpo_dispensa_pequena",
        descricao="Dispensa pequena legítima, única no período — sem alarme",
        dossie={
            "contratacao": {"valor": 12_000, "data": "2024-02-05",
                            "modalidade": "dispensa", "categoria": "manutenção"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2012-03-01",
                           "capital_social": 200_000},
        },
        nao_pode_disparar=["IND-FRAC-01", "IND-EMP-01", "IND-LIM-01"],
    ),
    CasoOuro(
        id="ouro_doacao_sem_roi",
        descricao="Doação pequena e contrato proporcional — ROI normal, sem alarme",
        dossie={
            "contratacao": {"valor": 500_000, "data": "2024-06-01"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2010-01-01",
                           "capital_social": 1_000_000,
                           "doacoes_eleitorais": [{"valor": 50_000,
                                                   "data": "2023-08-01",
                                                   "candidato": "Y"}]},
        },
        nao_pode_disparar=["IND-QPQ-01"],
    ),
    CasoOuro(
        id="ouro_valor_colado_teto",
        descricao="Dispensa com valor cravado logo abaixo do teto legal",
        dossie={
            "contratacao": {"valor": 59_900.00, "data": "2024-01-20",
                            "modalidade": "dispensa"},
            "fornecedor": {"cnpj": "11222333000181",
                           "data_abertura": "2018-01-01",
                           "capital_social": 500_000},
        },
        deve_disparar=["IND-LIM-01"],
    ),
]


def carregar_casos() -> list[CasoOuro]:
    """Conjunto embutido + casos adicionados pelo perito (JSON em data/)."""
    casos = list(CASOS_EMBUTIDOS)
    extra = _arquivo_extra()
    if extra.exists():
        try:
            for c in json.loads(extra.read_text(encoding="utf-8")):
                casos.append(CasoOuro(
                    id=c["id"], descricao=c.get("descricao", ""),
                    dossie=c["dossie"],
                    deve_disparar=c.get("deve_disparar", []),
                    nao_pode_disparar=c.get("nao_pode_disparar", []),
                ))
        except Exception:
            pass
    return casos


def adicionar_caso_ouro(caso: CasoOuro) -> None:
    """
    Promove um caso real (perícia confirmada pelo perito) a caso-ouro.
    É assim que a régua de avaliação também evolui com o uso.
    """
    extra = _arquivo_extra()
    extra.parent.mkdir(parents=True, exist_ok=True)
    atual: list = []
    if extra.exists():
        try:
            atual = json.loads(extra.read_text(encoding="utf-8"))
        except Exception:
            atual = []
    atual = [c for c in atual if c.get("id") != caso.id]
    atual.append({"id": caso.id, "descricao": caso.descricao, "dossie": caso.dossie,
                  "deve_disparar": caso.deve_disparar,
                  "nao_pode_disparar": caso.nao_pode_disparar})
    extra.write_text(json.dumps(atual, ensure_ascii=False, indent=2),
                     encoding="utf-8")


# ── Execução e métricas ──────────────────────────────────────────────────────

def _montar_dossie(spec: dict) -> Dossie:
    return Dossie(
        contratacao=Contratacao(**spec.get("contratacao", {})),
        fornecedor=Fornecedor(**spec.get("fornecedor", {})),
        historico_orgao_fornecedor=[Contratacao(**h)
                                    for h in spec.get("historico", [])],
        referencia_categoria=spec.get("referencia_categoria", {}),
    )


@dataclass
class ResultadoAvaliacao:
    f1_global: float
    precisao: float
    cobertura: float
    acertos: int          # deve_disparar que dispararam
    perdidos: int         # deve_disparar que NÃO dispararam
    falsos_alarmes: int   # nao_pode_disparar que dispararam
    detalhes: list[dict] = field(default_factory=list)


def avaliar_sistema(casos: list[CasoOuro] | None = None) -> ResultadoAvaliacao:
    """
    Roda a perícia sobre todos os casos-ouro e mede o placar global.

    F1 combina precisão (não alarmar à toa) e cobertura (não deixar passar).
    É a nota única que o autoaprimoramento tenta subir — e nunca deixa cair.
    """
    casos = casos if casos is not None else carregar_casos()
    acertos = perdidos = falsos = 0
    detalhes: list[dict] = []
    for caso in casos:
        disparados = {a.indicador_id for a in avaliar_todos(_montar_dossie(caso.dossie))}
        ac = [i for i in caso.deve_disparar if i in disparados]
        pe = [i for i in caso.deve_disparar if i not in disparados]
        fa = [i for i in caso.nao_pode_disparar if i in disparados]
        acertos += len(ac); perdidos += len(pe); falsos += len(fa)
        if pe or fa:
            detalhes.append({"caso": caso.id, "perdidos": pe, "falsos_alarmes": fa})
    precisao = acertos / (acertos + falsos) if (acertos + falsos) else 1.0
    cobertura = acertos / (acertos + perdidos) if (acertos + perdidos) else 1.0
    f1 = (2 * precisao * cobertura / (precisao + cobertura)
          if (precisao + cobertura) else 0.0)
    return ResultadoAvaliacao(
        f1_global=round(f1, 4), precisao=round(precisao, 4),
        cobertura=round(cobertura, 4), acertos=acertos, perdidos=perdidos,
        falsos_alarmes=falsos, detalhes=detalhes,
    )
