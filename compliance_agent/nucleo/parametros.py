"""
Store central de parâmetros da perícia — a "parametrização" explícita.

PROBLEMA QUE RESOLVE
--------------------
Antes, os limites que decidem "isto é suspeito" estavam espalhados: hardcoded
em ``rules/engine.py``, em prosa dentro de ``knowledge/fraudes_licitacao.py``
(campo ``como_detectar``), ou pior — na "cabeça" de uma IA fraca que precisava
adivinhar o número certo a cada análise. Resultado: parametrização inconsistente,
não-auditável e impossível de calibrar.

Aqui, cada parâmetro de decisão é UM objeto explícito com:
  - valor            : o limite/threshold usado pela perícia
  - unidade          : reais | dias | percentual | contagem | razao
  - fundamento       : a norma ou jurisprudência que justifica o valor
  - descricao        : o que ele controla, em português claro
  - fonte_valor      : de onde saiu o número (lei, TCU, calibração empírica)

Os valores podem ser sobrescritos por um arquivo de overrides
(``data/nucleo_parametros.json``), alimentado tanto por decisão do perito quanto
pelo módulo de aprendizado progressivo (``aprendizado.py``). Assim, calibrar o
sistema é editar DADOS versionados — nunca reescrever um prompt.

Nada aqui depende de IA. É a fonte única de verdade dos limiares.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


# Local do arquivo de overrides (calibração do perito + aprendizado).
ARQUIVO_OVERRIDES = Path(
    os.environ.get("NUCLEO_PARAMS_FILE", "data/nucleo_parametros.json")
)


@dataclass(frozen=True)
class Parametro:
    """Um limiar de decisão da perícia, com valor e fundamento explícitos."""

    id: str
    valor: float
    unidade: str          # reais | dias | percentual | contagem | razao | booleano
    descricao: str
    fundamento: str       # norma/jurisprudência que ancora o valor
    fonte_valor: str      # "lei" | "tcu" | "orientativo" | "empirico"
    minimo: float | None = None   # faixa sã para calibração (evita valores absurdos)
    maximo: float | None = None


# ── Catálogo padrão ──────────────────────────────────────────────────────────
# Cada valor tem procedência. "orientativo"/"empirico" são calibráveis; "lei"
# não deve ser afrouxado (é o limite legal), mas pode ser endurecido.

_PADRAO: list[Parametro] = [
    # Limites de contratação direta (Lei 14.133/2021, valores 2023+ atualizados)
    Parametro(
        "limite_dispensa_compras", 59_906.02, "reais",
        "Teto de dispensa de licitação para compras e serviços comuns.",
        "Lei 14.133/2021, art. 75, II", "lei", minimo=50_000, maximo=120_000,
    ),
    Parametro(
        "limite_dispensa_obras", 119_812.02, "reais",
        "Teto de dispensa para obras e serviços de engenharia.",
        "Lei 14.133/2021, art. 75, I", "lei", minimo=100_000, maximo=240_000,
    ),
    # Fracionamento
    Parametro(
        "fracionamento_janela_dias", 90, "dias",
        "Janela em que contratos do mesmo objeto/órgão/empresa são somados para "
        "testar fuga ao limite de dispensa.",
        "Lei 14.133/2021, art. 8º, §1º; Súmula TCU 247", "orientativo",
        minimo=30, maximo=365,
    ),
    Parametro(
        "fracionamento_min_contratos", 2, "contagem",
        "Nº mínimo de contratos na janela para caracterizar suspeita de fracionamento.",
        "Súmula TCU 247", "orientativo", minimo=2, maximo=10,
    ),
    # Empresa de fachada / recém-aberta
    Parametro(
        "empresa_nova_dias", 180, "dias",
        "Idade máxima da empresa (na data do contrato) para sinalizar 'recém-aberta'.",
        "Lei 14.133/2021, art. 67 (qualificação)", "orientativo",
        minimo=90, maximo=730,
    ),
    Parametro(
        "capital_social_min_frac", 0.01, "razao",
        "Capital social mínimo esperado como fração do valor do contrato.",
        "Lei 14.133/2021, art. 69 (qualificação econômico-financeira)", "orientativo",
        minimo=0.001, maximo=0.10,
    ),
    # Aditivos
    Parametro(
        "aditivo_limite_frac", 0.25, "razao",
        "Acréscimo máximo legal por aditivo sobre o valor original (obras/serviços).",
        "Lei 14.133/2021, art. 125", "lei", minimo=0.25, maximo=0.50,
    ),
    Parametro(
        "aditivo_max_qtd", 3, "contagem",
        "Nº de aditivos a partir do qual o contrato entra em observação reforçada.",
        "TCU Acórdão 2.066/2018", "orientativo", minimo=1, maximo=10,
    ),
    # Superfaturamento
    Parametro(
        "superfat_desvios_padrao", 2.0, "razao",
        "Nº de desvios-padrão acima da mediana da categoria para marcar preço atípico.",
        "Lei 14.133/2021, art. 23; IN SEGES 65/2021", "empirico",
        minimo=1.5, maximo=4.0,
    ),
    Parametro(
        "superfat_delta_min_frac", 0.10, "percentual",
        "Piso de delta RELATIVO sobre a mediana para o caminho estatístico disparar. "
        "Série homogênea de contrato contínuo tem desvio-padrão minúsculo: um reajuste "
        "anual (IPCA/CCT, ~5-8%) vira '2σ+' e marcava superfaturamento — guard anti-FP "
        "(caso MGS Clean: parcela +6% pós-reajuste flagrada indevidamente).",
        "IN SEGES 65/2021 (pesquisa de preços); prática pericial", "empirico",
        minimo=0.05, maximo=0.30,
    ),
    Parametro(
        "superfat_sobrepreco_frac", 0.30, "percentual",
        "Sobrepreço mínimo (fração) sobre referência (SINAPI/ORSE/mediana) para alerta.",
        "Súmula TCU 258; IN SEGES 65/2021", "orientativo",
        minimo=0.10, maximo=1.0,
    ),
    Parametro(
        "bdi_limite", 0.275, "percentual",
        "BDI máximo orientativo para obras; acima disso exige justificativa.",
        "TCU Acórdão 2.622/2013 (BDI referencial)", "tcu",
        minimo=0.20, maximo=0.35,
    ),
    # Concorrência aparente
    Parametro(
        "prazo_edital_min_dias", 5, "dias",
        "Prazo mínimo (dias úteis) de publicação do edital; abaixo indica pressa/direcionamento.",
        "Lei 14.133/2021, art. 55", "orientativo", minimo=3, maximo=15,
    ),
    Parametro(
        "propostas_min_competicao", 2, "contagem",
        "Nº mínimo de propostas válidas esperado; proposta única em vulto alto é red flag.",
        "Lei 14.133/2021, art. 9º", "orientativo", minimo=1, maximo=5,
    ),
    # Pessoal / teto
    Parametro(
        "teto_remuneratorio_rj", 46_366.19, "reais",
        "Teto remuneratório do funcionalismo do RJ (referência).",
        "CF/88, art. 37, XI", "lei", minimo=30_000, maximo=60_000,
    ),
    Parametro(
        "quid_pro_quo_janela_meses", 24, "contagem",
        "Janela (meses) entre doação eleitoral e primeiro contrato para testar retribuição.",
        "Lei 9.504/97, art. 81; Lei 8.429/92, art. 9, I", "orientativo",
        minimo=6, maximo=48,
    ),
    Parametro(
        "quid_pro_quo_roi_min", 100.0, "razao",
        "Razão valor-do-contrato / valor-da-doação a partir da qual o ROI é suspeito.",
        "STF ADI 4650; Lei 8.429/92", "empirico", minimo=10, maximo=1000,
    ),
    # Valores redondos (indício de estimativa forjada)
    Parametro(
        "valor_redondo_tolerancia", 50.0, "reais",
        "Tolerância para considerar um valor 'redondo' (ex.: exatamente R$ 50.000,00).",
        "Boa prática de auditoria (IN SEGES 65/2021)", "empirico",
        minimo=0, maximo=1000,
    ),
]

_REGISTRO: dict[str, Parametro] = {p.id: p for p in _PADRAO}

# Cache de overrides carregados do disco.
_overrides_cache: dict[str, float] | None = None


def _carregar_overrides() -> dict[str, float]:
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache
    dados: dict[str, float] = {}
    if ARQUIVO_OVERRIDES.exists():
        try:
            bruto = json.loads(ARQUIVO_OVERRIDES.read_text(encoding="utf-8"))
            # Aceita {"id": valor} ou {"id": {"valor": x, ...}}
            for k, v in bruto.items():
                if isinstance(v, dict) and "valor" in v:
                    dados[k] = float(v["valor"])
                elif isinstance(v, (int, float)):
                    dados[k] = float(v)
        except Exception:
            dados = {}
    _overrides_cache = dados
    return dados


def _limitar(param: Parametro, valor: float) -> float:
    """Mantém um override dentro da faixa sã declarada no parâmetro."""
    if param.minimo is not None:
        valor = max(param.minimo, valor)
    if param.maximo is not None:
        valor = min(param.maximo, valor)
    return valor


def obter(param_id: str) -> Parametro:
    """Retorna o Parametro efetivo (com override aplicado, se houver)."""
    base = _REGISTRO.get(param_id)
    if base is None:
        raise KeyError(f"Parâmetro desconhecido: {param_id!r}")
    overrides = _carregar_overrides()
    if param_id in overrides:
        return replace(base, valor=_limitar(base, overrides[param_id]),
                       fonte_valor=f"{base.fonte_valor}+calibrado")
    return base


def valor(param_id: str) -> float:
    """Atalho para o valor efetivo de um parâmetro."""
    return obter(param_id).valor


def definir_override(param_id: str, novo_valor: float, motivo: str = "") -> Parametro:
    """
    Grava um override calibrado (perito ou aprendizado) de forma persistente.

    Nunca deixa o valor sair da faixa sã do parâmetro. Retorna o Parametro efetivo.
    """
    base = _REGISTRO.get(param_id)
    if base is None:
        raise KeyError(f"Parâmetro desconhecido: {param_id!r}")
    if base.fonte_valor == "lei":
        # Limites de fonte legal refletem a norma; alterá-los é ato de
        # interpretação jurídica, não calibração empírica. Ficam travados.
        raise ValueError(
            f"{param_id} é limite legal ({base.fundamento}); não é calibrável "
            f"por override. Edite a norma de referência no código se a lei mudar."
        )
    ARQUIVO_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    atual: dict[str, Any] = {}
    if ARQUIVO_OVERRIDES.exists():
        try:
            atual = json.loads(ARQUIVO_OVERRIDES.read_text(encoding="utf-8"))
        except Exception:
            atual = {}
    atual[param_id] = {"valor": float(novo_valor), "motivo": motivo}
    ARQUIVO_OVERRIDES.write_text(
        json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    global _overrides_cache
    _overrides_cache = None  # invalida cache
    return obter(param_id)


def listar() -> list[Parametro]:
    """Todos os parâmetros efetivos, ordenados por id (para relatórios/UI)."""
    return [obter(pid) for pid in sorted(_REGISTRO)]


def recarregar() -> None:
    """Força releitura dos overrides do disco (útil após edição manual)."""
    global _overrides_cache
    _overrides_cache = None
