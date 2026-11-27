# -*- coding: utf-8 -*-
"""Detectores GENÉRICOS do E10 `detectar` (O5.3 do plano mestre v2 — fatia 1, SOMBRA ⚖️).

Um detector genérico roda sobre o UNIVERSO de uma unidade da E9 (não sobre um órgão, um alvo do Lex ou um sweep),
lê só itens que a E9 declarou elegíveis para ele (invariante 3) e devolve disparos que o estágio converte no contrato
único `dominio.achado`. Contrato de cada módulo (o estágio só fala com isto):

  ID         id no registro (config/qualidade_detectores.yaml) e chave da exigência na E9 (`elegibilidade.DETECTORES`)
  UNIDADE    a unidade da E9 que dá a elegibilidade de cada item (`ob_siafe`, `compra_direta_tcerj`, …)
  VERSAO     versão da régua (muda quando o critério muda; o sha do arquivo entra na versão da execução)
  carregar(con, exercicio) -> Carga   leitura SÓ-LEITURA da coleta bruta: itens (cada um com `chave_e9`) + contexto
  detectar(itens, contexto) -> list[Disparo]   PURA: recebe os itens com o veredito da E9 em `item["e9"]` e só
                                       pode disparar sobre item com veredito 'E' (catraca nos testes)
  grupo_de(disparo) / carregar_grupo(con, grupo)  conferência independente do `efeito`: relê da fonte só o grupo do
                                       disparo e recalcula (mesmo hash de entradas, mesmo disparo)

Fatia 1 (regras únicas que só existiam em scripts, plano §16.3):
  e10.p4_fracionamento_objeto   réguas do sweep_fracionamento_tcerj (MAX por processo, grafias, irmãos; "reforma é
                                obra, mão de obra não é"; aquisição é compra; não-contratação fora) + card P4
  e10.p5_emergencia_recorrente  régua do sweep_emergencia_recorrente (uma linha por PROCESSO — somar itens inflava
                                2,3× — e o enquadramento legal como prova, não só o objeto)
  e10.ob_paga_acima_liquidado   C-PAGO>NL do lex_fatos (soma das OB pagas que citam a NL > valor liquidado)
  e10.ob_antes_da_liquidacao    C-OB<NL do lex_fatos (OB paga emitida antes da NL que cita)

Fatia 2 (fracionamento_siafe_sweep, governo_couto_regras com data de corte, família fachada sem rede):
  e10.candidato_p4_siafe        série de OB por credor × UG abaixo do teto — só `candidato_p4(processos[])`, INCERTO;
                                nunca "fracionamento" (plano §4 item 5: só o P4, por objeto, emite)
  e10.tg_*                      troca de gestão com `corte` parametrizado (D01, D02, D05, D09, D10, D16, D20)
  e10.c_sede_fachada            sede real × endereço × Street View gravados: indício só com 2 sinais convergentes

Regras únicas perdidas que a auditoria de 27/11/2026 achou (mapa O1.2 × sistema novo):
  e10.c_concentracao_nicho      fornecedor com > 60% de um nicho de objeto > R$ 5 mi na unidade/exercício (#14)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from compliance_agent.dominio.achado import Fato

MODULOS = {
    "e10.p4_fracionamento_objeto": "compliance_agent.aplicacao.detectores.fracionamento_objeto",
    "e10.p5_emergencia_recorrente": "compliance_agent.aplicacao.detectores.emergencia_recorrente",
    "e10.ob_paga_acima_liquidado": "compliance_agent.aplicacao.detectores.contabil_siafe:PAGO_ACIMA",
    "e10.ob_antes_da_liquidacao": "compliance_agent.aplicacao.detectores.contabil_siafe:OB_ANTES",
    # fatia 2
    "e10.candidato_p4_siafe": "compliance_agent.aplicacao.detectores.candidato_p4_siafe",
    "e10.tg_direta_salto": "compliance_agent.aplicacao.detectores.troca_gestao:DIRETA_SALTO",
    "e10.tg_emergencial_incumbente": "compliance_agent.aplicacao.detectores.troca_gestao:EMERGENCIAL_INCUMBENTE",
    "e10.tg_concentracao": "compliance_agent.aplicacao.detectores.troca_gestao:CONCENTRACAO",
    "e10.tg_pico_vespera": "compliance_agent.aplicacao.detectores.troca_gestao:PICO_VESPERA",
    "e10.tg_credor_estreante": "compliance_agent.aplicacao.detectores.troca_gestao:CREDOR_ESTREANTE",
    "e10.tg_ob_anulada": "compliance_agent.aplicacao.detectores.troca_gestao:OB_ANULADA",
    "e10.tg_tac_aceleracao": "compliance_agent.aplicacao.detectores.troca_gestao:TAC_ACELERACAO",
    "e10.c_sede_fachada": "compliance_agent.aplicacao.detectores.sede_fachada",
    # 27/11/2026: regras únicas que a auditoria achou perdidas (mapa O1.2 × sistema novo)
    "e10.c_concentracao_nicho": "compliance_agent.aplicacao.detectores.concentracao_nicho",
}


@dataclass
class Disparo:
    """Um resultado do detector sobre UM escopo (cluster, grupo, NL, OB). `chave` é única no detector; `entradas` é
    o que a régua leu (vai ao hash da execução); `valores`, o que ela concluiu. Só INDICIO, INDISPONIVEL ou INCERTO."""
    chave: str
    grupo: str
    estado: str
    observacao: str
    entradas: dict[str, Any]
    valores: dict[str, Any] = field(default_factory=dict)
    processo: str | None = None
    evidencias: list[Fato] = field(default_factory=list)
    motivo_estado: str = ""
    # O4.8: nível de identidade (`dominio.identidade`) do vínculo entre pessoas/credores que sustenta o disparo —
    # None quando o detector não liga pessoas; só 'forte' sustenta grave (`identidade.sustenta_grave`)
    identidade: str | None = None


@dataclass
class Carga:
    """O que `carregar` leu: itens avaliáveis (com `chave_e9`) + contadores do universo que não viram item."""
    itens: list[dict]
    contexto: dict[str, Any] = field(default_factory=dict)


def carregar_detector(did: str):
    """O módulo (ou objeto) do detector `did`. Import tardio: o filho do fluxo só paga o detector que roda."""
    import importlib
    alvo = MODULOS.get(did)
    if alvo is None:
        raise KeyError(f"detector E10 desconhecido: {did!r} (conhecidos: {', '.join(sorted(MODULOS))})")
    mod, _, attr = alvo.partition(":")
    m = importlib.import_module(mod)
    return getattr(m, attr) if attr else m


@lru_cache(maxsize=16)
def sha_modulo(modulo: str) -> str:
    """sha256[:12] do arquivo do módulo — entra na versão da execução (o mesmo código, a mesma versão)."""
    import importlib.util
    spec = importlib.util.find_spec(modulo.partition(":")[0])
    p = Path(spec.origin) if spec and spec.origin else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p and p.is_file() else "indisponivel"


# Versão do CONTRATO do achado do E10 (campos que `detectar.para_achado` grava no resultado). Entra na versão da
# execução: mudar o contrato regrava a rodada (a idempotência é por versão + entradas). o48 = regra_versao na data do
# fato + esfera + identidade (O4.8); o85 = + vínculo ao processo SEI (`vinculo_processo`, O8.5).
CONTRATO_ACHADO = "o85"


def versao_execucao(did: str) -> str:
    det = carregar_detector(did)
    return f"{det.VERSAO}@{sha_modulo(MODULOS[did])}+{CONTRATO_ACHADO}"


def elegivel(item: dict) -> bool:
    """Veredito da E9 'E' — o único que deixa a régua olhar o item ('I:…' inelegível, '?:…' indeterminado, None =
    item sem linha na E9: indeterminado, nunca elegível)."""
    return item.get("e9") == "E"
