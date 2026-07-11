"""
Núcleo de Inteligência Progressiva — orquestrador da perícia.

Junta as peças na ordem certa e devolve um laudo pericial estruturado:

    dados brutos / documentos
        │
        ▼  (IA fraca só aqui, blindada por extracao_robusta + validadores)
    Dossiê normalizado e validado
        │
        ▼  (100% determinístico, parametrizado, citado)
    Achados  →  Veredito (matriz TCU)  →  Laudo

Ponto central: a IA fraca contribui no máximo com a EXTRAÇÃO de campos, e ainda
assim cada campo é validado por código. A perícia (indicadores + score + base
legal) não depende de IA nenhuma. É reproduzível e oponível.

Uso típico no sistema real:

    from compliance_agent.llm.free_llm import best_free_chat
    laudo = periciar(
        contratacao={...}, fornecedor={...},
        documento_edital=texto, llm_fn=lambda p, s: best_free_chat(p, system=s),
    )
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from compliance_agent.nucleo import parametros as P
from compliance_agent.nucleo.dossie import Contratacao, Dossie, Fornecedor
from compliance_agent.nucleo.extracao_robusta import Campo, LLMFn, extrair
from compliance_agent.nucleo.indicadores import Achado, avaliar_todos
from compliance_agent.nucleo.scoring import Veredito, pontuar


# Campos que a IA fraca pode extrair de um edital/contrato (só factuais).
CAMPOS_EDITAL = [
    Campo("objeto", "texto", "Objeto/descrição da contratação."),
    Campo("valor", "reais", "Valor total ou estimado do contrato.",
          exemplo='"R$ 1.234.567,89"', critico=True),
    Campo("modalidade", "texto",
          "Modalidade: pregão, concorrência, dispensa, inexigibilidade."),
    Campo("data", "data", "Data de assinatura ou publicação.", exemplo='"2024-03-15"'),
    Campo("propostas_validas", "inteiro", "Nº de propostas/licitantes válidos."),
    Campo("cnpj_vencedor", "cnpj", "CNPJ da empresa vencedora.", critico=True),
]


@dataclass
class Laudo:
    """Saída da perícia — pronta para relatório e para o aprendizado."""

    veredito: Veredito
    dossie: Dossie
    extracao_avisos: list[str] = field(default_factory=list)
    fontes: dict[str, str] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        """Serialização amigável (para API/relatório JSON)."""
        return {
            "risco_score": self.veredito.risco_score,
            "classificacao": self.veredito.classificacao,
            "matriz_tcu": {"probabilidade": self.veredito.probabilidade,
                           "impacto": self.veredito.impacto},
            "confianca": self.veredito.confianca,
            "resumo": self.veredito.resumo,
            "base_legal": self.veredito.base_legal,
            "achados": [asdict(a) for a in self.veredito.achados],
            "avisos": self.dossie.avisos + self.extracao_avisos,
            "fontes": self.fontes,
        }

    def texto(self) -> str:
        """Laudo em texto para ofício/relatório (sem IA, tudo citado)."""
        v = self.veredito
        linhas = [
            "═" * 68,
            f"LAUDO DE PERÍCIA — Risco {v.classificacao.upper()} ({v.risco_score:.0f}/100)",
            f"Matriz TCU: Probabilidade {v.probabilidade}/5 × Impacto {v.impacto}/5"
            f" · Confiança {v.confianca:.0%}",
            "═" * 68,
        ]
        if not v.achados:
            linhas.append("Nenhum indicador de irregularidade disparou.")
        for i, a in enumerate(v.achados, 1):
            linhas += [
                f"\n[{i}] {a.titulo}  ({a.severidade.upper()}, confiança {a.confianca:.0%})",
                f"    Observado: {a.observado}",
                f"    Critério : {a.limite}",
                f"    Base legal: {'; '.join(a.base_legal)}",
                f"    Indicador : {a.indicador_id} · padrão {a.fraude_id}",
            ]
        if self.dossie.avisos or self.extracao_avisos:
            linhas.append("\n— Ressalvas de qualidade dos dados —")
            for w in self.dossie.avisos + self.extracao_avisos:
                linhas.append(f"    • {w}")
        linhas.append("═" * 68)
        return "\n".join(linhas)


def periciar(
    *,
    contratacao: dict[str, Any] | Contratacao | None = None,
    fornecedor: dict[str, Any] | Fornecedor | None = None,
    historico: list[dict | Contratacao] | None = None,
    referencia_categoria: dict[str, float] | None = None,
    documento_edital: str | None = None,
    llm_fn: LLMFn | None = None,
    usar_memoria: bool = False,
) -> Laudo:
    """
    Executa a perícia completa sobre uma contratação.

    - ``contratacao``/``fornecedor``: dados estruturados (dos collectors) OU parciais.
    - ``documento_edital`` + ``llm_fn``: se passados, a IA fraca preenche os campos
      faltantes do edital, com extração robusta e validada.
    - Se ``llm_fn`` for None, a perícia roda 100% sem IA sobre os dados estruturados.
    - ``usar_memoria=True`` liga a inteligência progressiva: a referência de preço
      vem das perícias anteriores (se não for informada) e este laudo é registrado
      na memória ao final — cada perícia deixa o sistema mais calibrado.
    """
    avisos_extracao: list[str] = []
    fontes: dict[str, str] = {}

    # 1. Base estruturada.
    c = contratacao if isinstance(contratacao, Contratacao) else Contratacao(
        **(contratacao or {}))
    f = fornecedor if isinstance(fornecedor, Fornecedor) else Fornecedor(
        **(fornecedor or {}))
    if c.fonte:
        fontes["contratacao"] = c.fonte
    if f.fonte:
        fontes["fornecedor"] = f.fonte

    # 2. Enriquecimento por IA fraca (opcional, blindado).
    if documento_edital and llm_fn is not None:
        res = extrair(documento_edital, CAMPOS_EDITAL, llm_fn)
        avisos_extracao = res.avisos
        d = res.dados
        # Só preenche o que ainda não veio de fonte estruturada (fonte > IA).
        if not c.objeto and d.get("objeto"):
            c.objeto = d["objeto"]
        if c.valor is None and d.get("valor") is not None:
            c.valor = d["valor"]
        if not c.modalidade and d.get("modalidade"):
            c.modalidade = d["modalidade"]
        if c.data is None and d.get("data"):
            from compliance_agent.nucleo.dossie import para_data
            c.data = para_data(d["data"])
        if c.propostas_validas is None and d.get("propostas_validas") is not None:
            c.propostas_validas = d["propostas_validas"]
        if not f.cnpj and d.get("cnpj_vencedor"):
            f.cnpj = d["cnpj_vencedor"]
        fontes["extracao_llm"] = f"{res.tentativas} chamada(s) à IA fraca"

    # 3. Monta e valida o dossiê. Sem referência explícita, a memória pericial
    #    fornece a referência aprendida com as perícias anteriores.
    ref = referencia_categoria or {}
    if usar_memoria and not ref and c.categoria:
        from compliance_agent.nucleo import memoria_pericial
        ref = memoria_pericial.obter_referencia(c.categoria, c.orgao)
        if ref:
            fontes["referencia_categoria"] = (
                f"memória pericial (n={int(ref.get('n', 0))} perícias)")
    hist = [h if isinstance(h, Contratacao) else Contratacao(**h)
            for h in (historico or [])]
    dossie = Dossie(
        contratacao=c, fornecedor=f, historico_orgao_fornecedor=hist,
        referencia_categoria=ref,
    )

    # 4. Perícia determinística.
    achados: list[Achado] = avaliar_todos(dossie)
    veredito: Veredito = pontuar(achados, valor_contrato=c.valor)

    laudo = Laudo(veredito=veredito, dossie=dossie,
                  extracao_avisos=avisos_extracao, fontes=fontes)

    # 5. Aprende: registra a perícia na memória (inteligência progressiva).
    if usar_memoria:
        from compliance_agent.nucleo import memoria_pericial
        try:
            memoria_pericial.registrar_laudo(laudo, referencia=c.identificador)
        except Exception:
            pass  # memória indisponível nunca derruba a perícia
    return laudo


def diagnostico_parametros() -> str:
    """Lista todos os parâmetros efetivos e sua procedência (para a UI/perito)."""
    linhas = ["Parâmetros da perícia (fonte única de verdade):", ""]
    for p in P.listar():
        linhas.append(
            f"  {p.id}: {p.valor} {p.unidade}  [{p.fonte_valor}]  — {p.fundamento}"
        )
    return "\n".join(linhas)
