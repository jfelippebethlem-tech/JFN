# -*- coding: utf-8 -*-
"""Pagamento — INVARIANTE 1 do plano mestre v2 (§3.10): **pago = OB paga do SIAFE.**

- Só a Ordem Bancária do SIAFE (`ob_orcamentaria_siafe`) que passa no predicado canônico é pagamento. Empenho e
  liquidação não são pagamento; o espelho TFE (`ordens_bancarias`) só serve de confronto, nunca de "pago".
- O predicado é o de `compliance_agent.cruzamentos_intel._ob_paga` (fonte única desde 24/09/2026): status
  `Contabilizado`, sem `Erro no Pagamento` no envio, sem `Pagamento Complementar`, sem a 1ª emissão de OB
  reemitida (`ob_reemitida`) e com número de OB. Aqui ele só ganha nome público; a regra não é reescrita.
- A tipologia `natureza_pagamento` / `origem_exercicio` (§4.3, O4.6) mora no fim deste arquivo: funções PURAS, em
  SOMBRA ⚖️ (nenhum detector as lê até o ✅ do dono, O4.10).

PONTE COM O LEGADO: `_ob_paga` consulta o schema pela conexão (PRAGMA), então NÃO é pura. O import fica DENTRO da
função, para `import compliance_agent.dominio` não carregar nada do legado; o par
`compliance_agent.dominio.pagamento -> compliance_agent.cruzamentos_intel` está em `ignore_imports` do
`.importlinter` (e na lista equivalente de `tests/test_dominio_sem_io.py`) — lista que só pode encolher. Sai
quando o predicado migrar para cá como texto SQL puro com as colunas informadas pelo adaptador.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


def ob_paga_sql(con, alias: str = "") -> str:
    """Trecho SQL (WHERE) que seleciona a OB que é pagamento em `ob_orcamentaria_siafe`.
    `alias`: prefixo da tabela na consulta (ex.: "o" → `o.status`). Idêntico a `cruzamentos_intel._ob_paga`."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    return _ob_paga(con, alias)


# ══ O4.6 — natureza do pagamento e origem do exercício (dois eixos independentes) ⚖️ SOMBRA ══════════════════════
#
# Base: doutrina da casa `~/vault/notas/doutrina/MAPA-DE-REGIMES.md` §1 (fluxo de decisão) e §3 (taxonomia), nota
# `10-contabilidade-publica-4320-mcasp.md`; textos conferidos VERBATIM em `~/vault/fontes/juridicas/` (24/11/2026):
#   manuais/STN-MCASP-11a-ed.pdf (md5 16e7f095b37baa97ffd3bdd10cb6f6fb), Parte I, lista de modalidades de aplicação:
#     "20 Transferências à União · 22 Execução Orçamentária Delegada à União · 30 Transferências a Estados e ao
#     Distrito Federal · 31 [...] Fundo a Fundo · 32 Execução Orçamentária Delegada a Estados [...] · 35/36 [...]
#     Fundo a Fundo [...] LC 141 · 40 Transferências a Municípios · 41 [...] Fundo a Fundo · 42 Execução Orçamentária
#     Delegada a Municípios · 45/46 [...] · 50 Transferências a Instituições Privadas sem Fins Lucrativos · 60
#     Transferências a Instituições Privadas com Fins Lucrativos · 67 Execução de Contrato de Parceria Público-Privada
#     – PPP · 70 Transferências a Instituições Multigovernamentais · 71 Transferências a Consórcios Públicos mediante
#     contrato de rateio · 72 Execução Orçamentária Delegada a Consórcios Públicos · [...] 80 Transferências ao
#     Exterior · 90 Aplicações Diretas · 91 Aplicação Direta Decorrente de Operação entre Órgãos, Fundos e Entidades
#     Integrantes dos Orçamentos Fiscal e da Seguridade Social · 92 Aplicação Direta de Recursos Recebidos de Outros
#     Entes [...]"; 50/60: "devem ser associadas com os elementos de despesa que não representem contraprestação
#     direta em bens ou serviços."
#   Elementos (mesmo manual): "37 – Locação de Mão-de-Obra [...] nos casos em que o contrato especifique o quantitativo
#     físico do pessoal"; "41 - Contribuições - utilizado para transferências"; "42 - Auxílios - utilizado para
#     transferências de capital"; "43 - Subvenções Sociais - utilizado para transferências"; "45 - Subvenções
#     Econômicas - utilizado para transferências"; "81 - Distribuição Constitucional ou Legal de Receitas - utilizado
#     para transferências aos entes da Federação"; "85 - Contrato de Gestão Despesas orçamentárias decorrentes de
#     transferências às organizações sociais"; "47 – Obrigações Tributárias e Contributivas [...] pagamento de tributos";
#     "91 – Sentenças Judiciais"; "92 – Despesas de Exercícios Anteriores [...] art. 37 da Lei nº 4.320/1964";
#     "93 – Indenizações e Restituições"; "94 Indenizações e Restituições Trabalhistas"; grupo "1 Pessoal e Encargos
#     Sociais"; elementos de pessoal/benefício "01 Aposentadorias [...] 03 Pensões [...] 05/06/08 [...] benefícios
#     [...] 10 Seguro Desemprego e Abono Salarial · 11/12 Vencimentos e Vantagens Fixas · 13 Obrigações Patronais ·
#     14/15 Diárias · 16/17 Outras Despesas Variáveis · 18 Auxílio Financeiro a Estudantes · 46 Auxílio-Alimentação ·
#     48 Outros Auxílios Financeiros a Pessoas Físicas · 49 Auxílio-Transporte (Portaria 163)".
#   L4320.htm (md5 c8dc41dbb1f96350603e90f21e733111) art. 36 "Consideram-se Restos a Pagar as despesas empenhadas mas
#     não pagas até o dia 31 de dezembro distinguindo-se as processadas das não processadas"; art. 37 "As despesas de
#     exercícios encerrados [...] poderão ser pagas à conta de dotação específica consignada no orçamento,
#     discriminada por elementos".
#
# OS/OSC é FORNECEDOR com regime próprio (plano §4.3): a natureza continua TRANSFERENCIA (fora do art. 75), mas
# `credor_e_fornecedor=True` — o credor NÃO sai dos rankings de fornecedor nem da fiscalização (meta, subcontratação).
#
# O4.10 (decisões delegadas de 24/11/2026; fontes e efeito em ~/vault/refatoracao/RELATORIO-JURIDICO-UNICO-20261124.md):
#   D5  modalidade 50 com elemento 41 (contribuição) ou 43 (subvenção social) — MCASP: "não representem contraprestação
#       direta em bens ou serviços"; Lei 4.320 art. 12 §3º I — pode ser parceria MROSC (fornecedor de regime próprio,
#       decisão do dono) OU descentralização a unidade executora escolar (Associação de Apoio à Escola: a Lei 13.019
#       art. 3º VII tira do MROSC as transferências do PDDE/PNAE às escolas; TCU 3061/2019-P: transferência). Sem o
#       instrumento, `credor_e_fornecedor=None` (não se sabe) — nem fornecedor, nem excluído. Contrato de gestão
#       (elemento 85) segue fornecedor (dono).
#   D7  elemento 37 SEM vínculo conferido → INDETERMINADO (não PARCELA_CONTRATO inferida): o elemento diz como a NE
#       foi classificada, não que o contrato exista (TCU 1181/2012-P: despesa sem cobertura contratual). Continua fora
#       da soma do art. 75 §1º (`nao_e_contratacao_nova=True`: locação de mão de obra é serviço contínuo — regra do dono
#       de 23/11), e o credor continua fornecedor.


class NaturezaPagamento(str, Enum):
    TRANSFERENCIA = "TRANSFERENCIA"
    PARCELA_CONTRATO = "PARCELA_CONTRATO"
    INDENIZACAO = "INDENIZACAO"
    CONTRATACAO_NOVA = "CONTRATACAO_NOVA"
    FOLHA_BENEFICIO = "FOLHA_BENEFICIO"
    INDETERMINADO = "INDETERMINADO"


class OrigemExercicio(str, Enum):
    CORRENTE = "corrente"
    RP = "RP"
    DEA = "DEA"
    INDETERMINADO = "INDETERMINADO"


@dataclass(frozen=True)
class DecisaoPagamento:
    natureza: NaturezaPagamento
    fonte: str
    nao_e_contratacao_nova: bool        # True ⇒ fora da régua do art. 75 (soma do §1º, "dispensa acima do teto")
    credor_e_fornecedor: bool | None    # OS/OSC = True mesmo sendo transferência; None = não se sabe
    regime_proprio: str = ""
    ressalvas: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DecisaoOrigem:
    origem: OrigemExercicio
    fonte: str
    exercicio_de_origem: int | None = None


_MOD_TRANSFERENCIA = {"20", "22", "30", "31", "32", "35", "36", "40", "41", "42", "45", "46", "50", "60",
                      "70", "71", "72", "73", "74", "75", "76", "80"}
_MOD_APLICACAO_DIRETA = {"90", "91", "92", "93", "94", "95", "96"}
_EL_TRANSFERENCIA = {"41", "42", "43", "45", "81", "85"}
_EL_INDENIZACAO = {"91", "93", "94"}
_EL_SEM_CONTRAPRESTACAO_OSC = {"41", "43"}     # D5: contribuição / subvenção social a entidade sem fins lucrativos
_EL_FOLHA_BENEFICIO = {"01", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16",
                       "17", "18", "19", "46", "48", "49"}
_FONTE_MCASP = "MCASP 11ª ed., Parte I (modalidades de aplicação e elementos de despesa)"


def decompor_natureza(cod: str | None) -> dict | None:
    """'339039' / '3.3.90.39' / '33903911' → {categoria, grupo, modalidade, elemento}. Fora do formato → None."""
    d = "".join(ch for ch in str(cod or "") if ch.isdigit())
    if len(d) < 6 or d[0] not in "34" or d[1] not in "123456":
        return None
    return {"categoria": d[0], "grupo": d[1], "modalidade": d[2:4], "elemento": d[4:6]}


def _regime_entidade(modalidade: str, elemento: str, natureza_juridica_credor: str | None) -> str:
    if elemento == "85":
        return "OS — contrato de gestão (Lei 9.637)"
    if modalidade == "50":
        return "OSC/entidade sem fins lucrativos — parceria (Lei 13.019) ou subvenção; instrumento a confirmar"
    if str(natureza_juridica_credor or "").startswith("3"):
        return "entidade sem fins lucrativos (natureza jurídica 3xxx) — instrumento a confirmar"
    return ""


def natureza_pagamento(*, natureza_despesa: str | None, vinculo_contrato: bool | None = None,
                       natureza_juridica_credor: str | None = None) -> DecisaoPagamento:
    """Natureza do pagamento pela classificação da despesa da NE (modalidade, elemento) + vínculo com contrato +
    natureza jurídica do credor (só para o regime próprio de OS/OSC — NUNCA pelo nome). Função pura.

    vinculo_contrato  True = a NE/OB está ligada a contrato/ata/credenciamento/PPP; False = conferido que não está;
                      None = não se sabe (aplicação direta sem vínculo conhecido → INDETERMINADO, não "contratação")."""
    nd = decompor_natureza(natureza_despesa)
    if nd is None:
        return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, "natureza da despesa ausente ou fora do formato "
                                "C.G.MM.EE (sem NE ligada à OB)", False, None)
    g, m, e = nd["grupo"], nd["modalidade"], nd["elemento"]
    reg = _regime_entidade(m, e, natureza_juridica_credor)
    os_osc = bool(reg) and (e == "85" or m == "50" or str(natureza_juridica_credor or "").startswith("3"))
    if g == "1" or (e in _EL_FOLHA_BENEFICIO and m in _MOD_APLICACAO_DIRETA):
        return DecisaoPagamento(NaturezaPagamento.FOLHA_BENEFICIO, f"{_FONTE_MCASP}: grupo {g} / elemento {e} "
                                "(pessoal, encargos, benefício a pessoa física)", True, False)
    if m == "50" and e in _EL_SEM_CONTRAPRESTACAO_OSC:     # D5 (O4.10)
        return DecisaoPagamento(NaturezaPagamento.TRANSFERENCIA, f"{_FONTE_MCASP}: modalidade 50 / elemento {e} — "
                                "contribuição/subvenção a entidade sem fins lucrativos, sem contraprestação direta "
                                "(Lei 4.320 art. 12 §3º I); fora do art. 75", True, None,
                                reg or "entidade sem fins lucrativos — instrumento a confirmar",
                                ("D5: parceria MROSC (fornecedor de regime próprio) ou descentralização a unidade "
                                 "executora escolar (AAE; Lei 13.019 art. 3º VII) — sem o instrumento, não se sabe",))
    if m in _MOD_TRANSFERENCIA or e in _EL_TRANSFERENCIA:
        return DecisaoPagamento(NaturezaPagamento.TRANSFERENCIA, f"{_FONTE_MCASP}: modalidade {m} / elemento {e} — "
                                "transferência sem contraprestação direta; fora do art. 75 (MAPA-DE-REGIMES §1, "
                                "passos 1–2)", True, True if os_osc else False, reg)
    if m == "67":
        return DecisaoPagamento(NaturezaPagamento.PARCELA_CONTRATO, f"{_FONTE_MCASP}: modalidade 67 — execução de "
                                "contrato de PPP (contraprestação de contrato licitado)", True, True,
                                "PPP (Lei 11.079)")
    if e in _EL_INDENIZACAO:
        return DecisaoPagamento(NaturezaPagamento.INDENIZACAO, f"{_FONTE_MCASP}: elemento {e} (sentença, indenização "
                                "ou restituição) — obrigação sem contraprestação contratual nova", True, False)
    if e == "92":
        return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, "elemento 92 (DEA, Lei 4.320 art. 37): obrigação de "
                                "exercício encerrado — a natureza do fato gerador não sai do elemento; nunca "
                                "contratação nova", True, None, ressalvas=("origem_exercicio = DEA",))
    if e == "47":
        return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, f"{_FONTE_MCASP}: elemento 47 (obrigação tributária "
                                "e contributiva) — não é contratação; fora das classes do enum", True, False)
    if g in ("2", "6"):
        return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, f"{_FONTE_MCASP}: grupo {g} (serviço da dívida) — "
                                "não é contratação", True, False)
    if m in _MOD_APLICACAO_DIRETA:
        if str(natureza_juridica_credor or "").startswith("1"):
            reg = reg or ("ente público (natureza jurídica 1xxx): contratação entre órgãos (14.133 art. 75 IX) ou "
                          "tributo — fora da soma do §1º pela elegibilidade (E9), não por esta função")
        if vinculo_contrato:
            return DecisaoPagamento(NaturezaPagamento.PARCELA_CONTRATO, f"{_FONTE_MCASP}: aplicação direta "
                                    f"(modalidade {m}) com vínculo a contrato/ata (Lei 4.320 arts. 62–63)", True,
                                    True, reg)
        if e == "37" and vinculo_contrato is None:             # D7 (O4.10)
            return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, f"{_FONTE_MCASP}: elemento 37 (locação de "
                                    "mão-de-obra: 'o contrato especifique o quantitativo físico do pessoal') sem "
                                    "vínculo conferido — o elemento não prova o contrato (D7)", True, True, reg,
                                    ("serviço contínuo pelo elemento: fora da soma do art. 75 §1º",
                                     "vínculo ao contrato não conferido: parcela ou execução sem contrato"))
        if vinculo_contrato is False:
            return DecisaoPagamento(NaturezaPagamento.CONTRATACAO_NOVA, f"{_FONTE_MCASP}: aplicação direta "
                                    f"(modalidade {m}) sem contrato vigente que a lastreie (MAPA-DE-REGIMES §1, "
                                    "passo 6)", False, True, reg)
        return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, f"aplicação direta (modalidade {m}) sem saber se há "
                                "contrato que lastreie a NE — parcela ou contratação nova (passos 5–6)", False, True,
                                reg)
    return DecisaoPagamento(NaturezaPagamento.INDETERMINADO, f"modalidade {m} não mapeada (99 = a definir, vedada a "
                            "execução)", False, None)


_TIPO_OB_RP = {"RPP", "RPNP Liquidados no Exercício", "RPNP Liquidados em Exercícios Anteriores"}
TIPO_OB_RP = frozenset(_TIPO_OB_RP)   # vocabulário público do SIAFE para OB de restos a pagar (Lei 4.320 art. 36)


def origem_exercicio(*, tipo_ob: str | None = None, elemento: str | None = None, exercicio_ob: int | None = None,
                     exercicio_empenho: int | None = None) -> DecisaoOrigem:
    """Eixo SEPARADO da natureza: de que exercício é a despesa paga. DEA (elemento 92) > RP (tipo da OB ou empenho de
    ano anterior) > corrente. `tipo_ob` fora do vocabulário do SIAFE (colunas deslocadas na coleta) não decide."""
    if str(elemento or "") == "92":
        return DecisaoOrigem(OrigemExercicio.DEA, "elemento 92 — Lei 4.320 art. 37 (despesa de exercício encerrado)")
    t = (tipo_ob or "").strip()
    if t in _TIPO_OB_RP:
        return DecisaoOrigem(OrigemExercicio.RP, f"tipo da OB '{t}' — Lei 4.320 art. 36 (restos a pagar)",
                             exercicio_empenho)
    if exercicio_ob and exercicio_empenho:
        if int(exercicio_empenho) < int(exercicio_ob):
            return DecisaoOrigem(OrigemExercicio.RP, "empenho de exercício anterior ao da OB — Lei 4.320 art. 36",
                                 int(exercicio_empenho))
        if int(exercicio_empenho) == int(exercicio_ob):
            return DecisaoOrigem(OrigemExercicio.CORRENTE, "empenho e OB no mesmo exercício", int(exercicio_ob))
    if t == "Orçamentária":
        return DecisaoOrigem(OrigemExercicio.CORRENTE, "tipo da OB 'Orçamentária' (execução do exercício)",
                             int(exercicio_ob) if exercicio_ob else None)
    return DecisaoOrigem(OrigemExercicio.INDETERMINADO, "tipo da OB ausente/fora do vocabulário e exercício do "
                         "empenho desconhecido")
