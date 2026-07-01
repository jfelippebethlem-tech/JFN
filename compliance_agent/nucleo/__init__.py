"""
Núcleo de Inteligência Progressiva (NIP) da perícia JFN.

Inverte o papel da IA fraca: ela só extrai campos factuais (validados por código);
toda a perícia — indicadores, limiares legais, score de risco e base legal — é
determinística, parametrizada e auditável.

Peças:
  parametros        — store central de limiares com fundamento legal (calibrável)
  dossie            — esquema de evidências + validadores (CNPJ, datas, reais)
  indicadores       — testes executáveis (os `como_detectar` viram código)
  scoring           — agregação em risco (matriz TCU Probabilidade×Impacto)
  extracao_robusta  — extração confiável com modelo fraco (schema+reparo+votação)
  aprendizado       — precisão por indicador + sugestão de calibração
  nucleo            — orquestrador: periciar(...) → Laudo

Entrada rápida:
    from compliance_agent.nucleo.nucleo import periciar
"""

from compliance_agent.nucleo.nucleo import Laudo, periciar  # noqa: F401

__all__ = ["periciar", "Laudo"]
