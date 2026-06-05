"""
Configuração padrão de auditoria do JFN.

Arquivo único de referência para regras, limites e diretrizes que o Hermes
deve seguir em toda análise de OBs, independentemente da UO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class RegraLimite:
    tipo: str
    valor: float
    fundamento: str


@dataclass(frozen=True)
class ConfiguracaoAuditoria:
    limites_dispensa: List[RegraLimite] = field(
        default_factory=lambda: [
            RegraLimite(
                tipo="obras e serviços de engenharia",
                valor=119_812.02,
                fundamento="Lei 14.133/2021, arts. 29 e 75, §5º",
            ),
            RegraLimite(
                tipo="compras e serviços comuns",
                valor=59_906.02,
                fundamento="Lei 14.133/2021, art. 75, caput",
            ),
        ]
    )

    limites_convite: List[RegraLimite] = field(
        default_factory=lambda: [
            RegraLimite(
                tipo="obras",
                valor=176_000.00,
                fundamento="Lei 14.133/2021, arts. 29 e 75, §5º",
            ),
            RegraLimite(
                tipo="compras",
                valor=80_000.00,
                fundamento="Lei 14.133/2021, art. 75, caput",
            ),
        ]
    )

    regras_dispensa: List[RegraLimite] = field(
        default_factory=lambda: [
            RegraLimite(
                tipo="obras e serviços de engenharia",
                valor=119_812.02,
                fundamento="Lei 14.133/2021, arts. 29 e 75, §5º",
            ),
            RegraLimite(
                tipo="compras e serviços comuns",
                valor=59_906.02,
                fundamento="Lei 14.133/2021, art. 75, caput",
            ),
        ]
    )

    valores_redondos_tolerancia: float = 50.0

    dominio_siafe: str = "https://siafe2.fazenda.rj.gov.br/Siafe/"
    dominio_sei: str = "https://sei.fazenda.rj.gov.br/sei"
    portal_pncp: str = "https://pncp.gov.br"

    campos_obrigatorios_sei: Tuple[str, ...] = (
        "numero_processo",
        "numero_sei",
    )
    campos_credor: Tuple[str, ...] = (
        "favorecido_nome",
        "favorecido_cpf",
    )

    janela_analise_dias: int = 30

    max_pagamentos_mesmo_favorecido_ug_para_alerta: int = 3
    concentracao_ultimos_dias_uteis_n: int = 5
    min_alertas_concentracao_revisao_manual: int = 3
    min_qtd_pagamentos_fracionamento: int = 2

    palavras_chave_obras: Tuple[str, ...] = (
        "obra",
        "engenharia",
        "construção",
        "reforma",
        "reurbanização",
        "pavimentação",
        "infraestrutura",
        "elétrica",
        "hidráulica",
        "manutenção predial",
    )

    principios_administrativos: Tuple[str, ...] = (
        "legalidade",
        "impessoalidade",
        "moralidade",
        "publicidade",
        "eficiência",
        "economicidade",
    )

    limites_suspeita: Dict[str, object] = field(
        default_factory=lambda: {
            "valor_exato_ou_redondo_tolerancia": 50.0,
            "concentracao_ug_mesmo_favorecido_qtd": 3,
            "fracionamento_limite_abaixo_valor_justificativa_absoluta": 50_000.0,
            "observacoes_revisao_manual_prioritaria": True,
        }
    )

    ugs_comuns_rj: Tuple[str, ...] = (
        "300100",
        "200100",
    )

    def obter_limite_por_categoria(self, categoria: str) -> float | None:
        categoria = (categoria or "").strip().lower()
        if "obra" in categoria:
            return next(r.valor for r in self.regras_dispensa if r.tipo == "obras e serviços de engenharia")
        if categoria in {"compras", "servicos", "serviço"}:
            return next(r.valor for r in self.regras_dispensa if r.tipo == "compras e serviços comuns")
        return None

    def regras_resumidas(self) -> str:
        linhas = [
            "=== CONFIGURAÇÃO PADRÃO DE AUDITORIA JFN ===",
            f"Domínio SIAFE    : {self.dominio_siafe}",
            f"Domínio SEI      : {self.dominio_sei}",
            f"Portal PNCP      : {self.portal_pncp}",
            "",
            "Limites de dispensa de licitação (Lei 14.133/21):",
        ]
        for r in self.regras_dispensa:
            linhas.append(f"- {r.tipo}: R$ {r.valor:.2f} ({r.fundamento})")

        linhas.append("")
        linhas.append("Limites de convite:")
        for r in self.limites_convite:
            linhas.append(f"- {r.tipo}: R$ {r.valor:.2f}")

        linhas += [
            "",
            "Princípios aplicáveis: " + ", ".join(self.principios_administrativos),
            "",
            "Regras adicionais:",
            "- Obrigatoriedade de processo SEI/processo associado a cada OB;",
            "  publicidade no PNCP como condição de eficácia.",
            "- Vedação a fracionamento de despesas para burlar limites de dispensa.",
            "- Aferição de valores redondos/suscetíveis de direcionamento.",
            "- Análise de concentração por UG e favorecido em janela de 30 dias.",
            "- Cruzamento de nomes com servidores/políticos para nepotismo conforme SV 13/STF.",
            "",
            "UGs comuns no RJ consideradas para análise contextual:",
            ", ".join(self.ugs_comuns_rj),
        ]
        return "\n".join(linhas)


CONFIG_PADRAO = ConfiguracaoAuditoria()
