"""
Indicadores executáveis da perícia.

Converte os ``como_detectar`` (prosa) de ``knowledge/fraudes_licitacao.py`` em
FUNÇÕES que medem um Dossiê contra os parâmetros legais de ``parametros.py`` e
devolvem um Achado citado. Cada Achado carrega:

  - o indicador que disparou e o padrão de fraude (fraude_id) associado,
  - o valor OBSERVADO e o LIMITE aplicado (prova numérica),
  - a base legal (para o achado ser oponível num relatório de CPI/TCE),
  - uma confiança 0–1 (quão determinística é a evidência).

Isto é o núcleo da virada: a IA fraca não decide mais nada aqui. A perícia é
determinística, reproduzível e auditável. A IA fraca só entregou os campos do
Dossiê — e esses já foram validados em ``dossie.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from compliance_agent.nucleo import parametros as P
from compliance_agent.nucleo.dossie import Dossie, idade_em_dias


@dataclass
class Achado:
    """Resultado de um indicador que disparou."""

    indicador_id: str
    fraude_id: str            # id em FRAUDES (knowledge/fraudes_licitacao.py)
    titulo: str
    severidade: str           # alta | média | baixa
    confianca: float          # 0–1: quão sólida é a evidência
    observado: str            # o que se mediu (texto pronto p/ relatório)
    limite: str               # o parâmetro/limite aplicado
    base_legal: list[str] = field(default_factory=list)
    parametros_usados: list[str] = field(default_factory=list)


@dataclass
class Indicador:
    """
    Um teste determinístico sobre o Dossiê.

    ``avaliar`` retorna um Achado se disparar, ou None. É função pura: mesmos
    dados → mesmo resultado, sempre.
    """

    id: str
    fraude_id: str
    titulo: str
    severidade: str
    base_legal: list[str]
    avaliar: Callable[[Dossie], Achado | None]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _r(v: float | None) -> str:
    if v is None:
        return "—"
    # padrão brasileiro: milhar '.' e decimal ','
    return "R$ " + f"{v:,.2f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


def _achado(ind: "Indicador", confianca: float, observado: str, limite: str,
            params: list[str]) -> Achado:
    return Achado(
        indicador_id=ind.id, fraude_id=ind.fraude_id, titulo=ind.titulo,
        severidade=ind.severidade, confianca=round(confianca, 3),
        observado=observado, limite=limite, base_legal=ind.base_legal,
        parametros_usados=params,
    )


# ── Definição dos indicadores ────────────────────────────────────────────────
# Cada função recebe (dossie) e o próprio Indicador é injetado via closure.

def _fracionamento(d: Dossie) -> Achado | None:
    c = d.contratacao
    if not c.data:
        return None
    janela = P.valor("fracionamento_janela_dias")
    min_ct = int(P.valor("fracionamento_min_contratos"))
    limite_disp = (P.valor("limite_dispensa_obras")
                   if c.categoria == "obras"
                   else P.valor("limite_dispensa_compras"))
    # Contratações próximas (mesmo órgão×fornecedor) dentro da janela.
    proximas = [c]
    for h in d.historico_orgao_fornecedor:
        if h.data and abs((h.data - c.data).days) <= janela:
            proximas.append(h)
    soma = sum(x.valor or 0 for x in proximas)
    todas_dispensa = all(
        (x.modalidade or "").lower().startswith(("dispensa", "inexig"))
        for x in proximas
    )
    if len(proximas) >= min_ct and soma > limite_disp and todas_dispensa:
        return _POR_ID["IND-FRAC-01"]._mk(
            confianca=0.9,
            observado=(f"{len(proximas)} contratações do mesmo fornecedor no mesmo "
                       f"órgão em ≤{int(janela)} dias somam {_r(soma)}, todas por "
                       f"dispensa/inexigibilidade."),
            limite=(f"Soma > teto de dispensa ({_r(limite_disp)}) exigiria licitação."),
            params=["fracionamento_janela_dias", "fracionamento_min_contratos",
                    "limite_dispensa_compras", "limite_dispensa_obras"],
        )
    return None


def _empresa_recente(d: Dossie) -> Achado | None:
    c, f = d.contratacao, d.fornecedor
    idade = idade_em_dias(f.data_abertura, c.data)
    if idade is None:
        return None
    limite = int(P.valor("empresa_nova_dias"))
    if 0 <= idade < limite and (c.valor or 0) > 0:
        conf = 0.7
        extra = ""
        cap_min = (c.valor or 0) * P.valor("capital_social_min_frac")
        if f.capital_social is not None and f.capital_social < cap_min:
            conf = 0.9
            extra = (f" Capital social {_r(f.capital_social)} < mínimo esperado "
                     f"{_r(cap_min)} para o porte do contrato.")
        return _POR_ID["IND-EMP-01"]._mk(
            confianca=conf,
            observado=(f"Empresa aberta há {idade} dias na data do contrato "
                       f"({_r(c.valor)}).{extra}"),
            limite=f"Idade < {limite} dias sinaliza possível empresa de fachada.",
            params=["empresa_nova_dias", "capital_social_min_frac"],
        )
    return None


def _aditivo_excessivo(d: Dossie) -> Achado | None:
    c = d.contratacao
    if not c.valor or c.valor <= 0:
        return None
    frac_lim = P.valor("aditivo_limite_frac")
    qtd_lim = int(P.valor("aditivo_max_qtd"))
    frac = c.aditivos_valor / c.valor if c.valor else 0
    if frac > frac_lim or c.aditivos_qtd > qtd_lim:
        motivos = []
        if frac > frac_lim:
            motivos.append(f"aditivos somam {frac*100:.1f}% do valor original")
        if c.aditivos_qtd > qtd_lim:
            motivos.append(f"{c.aditivos_qtd} aditivos")
        return _POR_ID["IND-ADT-01"]._mk(
            confianca=0.85 if frac > frac_lim else 0.6,
            observado=("Contrato de " + _r(c.valor) + " com " + " e ".join(motivos) + "."),
            limite=f"Limite legal de acréscimo: {frac_lim*100:.0f}% (art. 125).",
            params=["aditivo_limite_frac", "aditivo_max_qtd"],
        )
    return None


def _superfaturamento(d: Dossie) -> Achado | None:
    c = d.contratacao
    ref = d.referencia_categoria
    if not c.valor or not ref:
        return None
    mediana = ref.get("mediana")
    desvio = ref.get("desvio_padrao")
    achou = None
    # Caminho 1: estatístico (desvios-padrão acima da mediana).
    if mediana and desvio and desvio > 0:
        n_sd = (c.valor - mediana) / desvio
        if n_sd >= P.valor("superfat_desvios_padrao"):
            achou = (0.75,
                     f"Valor {_r(c.valor)} está {n_sd:.1f} desvios-padrão acima da "
                     f"mediana da categoria ({_r(mediana)}).",
                     f"Limiar: {P.valor('superfat_desvios_padrao'):.1f} desvios-padrão.",
                     ["superfat_desvios_padrao"])
    # Caminho 2: sobrepreço direto sobre referência de mercado/SINAPI.
    referencia = ref.get("referencia_mercado") or mediana
    if referencia and referencia > 0:
        sobre = (c.valor - referencia) / referencia
        if sobre >= P.valor("superfat_sobrepreco_frac"):
            cand = (0.8,
                    f"Valor {_r(c.valor)} está {sobre*100:.0f}% acima da referência "
                    f"de mercado ({_r(referencia)}).",
                    f"Limiar: {P.valor('superfat_sobrepreco_frac')*100:.0f}% de sobrepreço.",
                    ["superfat_sobrepreco_frac"])
            if achou is None or cand[0] > achou[0]:
                achou = cand
    if achou:
        return _POR_ID["IND-SUP-01"]._mk(
            confianca=achou[0], observado=achou[1], limite=achou[2], params=achou[3])
    return None


def _proposta_unica(d: Dossie) -> Achado | None:
    c = d.contratacao
    if c.propostas_validas is None:
        return None
    min_prop = int(P.valor("propostas_min_competicao"))
    limite_vulto = P.valor("limite_dispensa_compras")
    if c.propostas_validas < min_prop and (c.valor or 0) > limite_vulto:
        return _POR_ID["IND-DIR-01"]._mk(
            confianca=0.6,
            observado=(f"Apenas {c.propostas_validas} proposta(s) válida(s) em "
                       f"certame de {_r(c.valor)}."),
            limite=(f"Esperado ≥ {min_prop} propostas acima de {_r(limite_vulto)}; "
                    f"competição aparente."),
            params=["propostas_min_competicao", "limite_dispensa_compras"],
        )
    return None


def _prazo_curto(d: Dossie) -> Achado | None:
    c = d.contratacao
    if c.prazo_edital_dias is None:
        return None
    minimo = int(P.valor("prazo_edital_min_dias"))
    if 0 <= c.prazo_edital_dias < minimo:
        return _POR_ID["IND-DIR-02"]._mk(
            confianca=0.55,
            observado=f"Edital publicado com {c.prazo_edital_dias} dias de prazo.",
            limite=f"Mínimo saudável: {minimo} dias úteis (art. 55).",
            params=["prazo_edital_min_dias"],
        )
    return None


def _empresa_sancionada(d: Dossie) -> Achado | None:
    f = d.fornecedor
    if f.sancionado:
        return _POR_ID["IND-SAN-01"]._mk(
            confianca=0.95,
            observado=f"Fornecedor {f.nome or f.cnpj} consta em cadastro de sanções (CEIS/CNEP).",
            limite="Empresa sancionada não pode contratar (art. 156, Lei 14.133/21).",
            params=[],
        )
    return None


_SITUACOES_IRREGULARES = ("BAIXAD", "INAPT", "SUSPENS", "NULA")


def _situacao_cadastral_irregular(d: Dossie) -> Achado | None:
    f = d.fornecedor
    sit = (f.situacao or "").upper()
    if any(s in sit for s in _SITUACOES_IRREGULARES):
        return _POR_ID["IND-SIT-01"]._mk(
            confianca=0.9,
            observado=(f"Fornecedor {f.nome or f.cnpj} consta HOJE como "
                       f"'{sit}' no cadastro da Receita Federal — verificar a "
                       "situação vigente na data do pagamento."),
            limite=("Liquidação de despesa exige credor regular "
                    "(arts. 62-63, Lei 4.320/64); CNPJ baixado/inapto não "
                    "emite nota fiscal válida."),
            params=[],
        )
    return None


def _quid_pro_quo(d: Dossie) -> Achado | None:
    c, f = d.contratacao, d.fornecedor
    if not f.doacoes_eleitorais or not c.data or not c.valor:
        return None
    from compliance_agent.nucleo.dossie import para_data, para_reais
    janela_meses = P.valor("quid_pro_quo_janela_meses")
    roi_min = P.valor("quid_pro_quo_roi_min")
    for doacao in f.doacoes_eleitorais:
        dv = para_reais(doacao.get("valor"))
        dd = para_data(doacao.get("data"))
        if not dv or not dd or dv <= 0:
            continue
        meses = (c.data.year - dd.year) * 12 + (c.data.month - dd.month)
        roi = c.valor / dv
        if 0 <= meses <= janela_meses and roi >= roi_min:
            return _POR_ID["IND-QPQ-01"]._mk(
                confianca=0.7,
                observado=(f"Doação de {_r(dv)} a {doacao.get('candidato','—')} "
                           f"{meses} meses antes de contrato de {_r(c.valor)} "
                           f"(razão {roi:.0f}x)."),
                limite=(f"Janela ≤ {int(janela_meses)} meses e razão ≥ {roi_min:.0f}x "
                        f"caracterizam ROI eleitoral atípico."),
                params=["quid_pro_quo_janela_meses", "quid_pro_quo_roi_min"],
            )
    return None


def _valor_no_limite(d: Dossie) -> Achado | None:
    """Valor colado logo abaixo do teto de dispensa — indício de ajuste ao limite."""
    c = d.contratacao
    if not c.valor:
        return None
    tol = P.valor("valor_redondo_tolerancia")
    for pid in ("limite_dispensa_compras", "limite_dispensa_obras"):
        teto = P.valor(pid)
        # entre 90% e 100% do teto, e "redondo"
        if teto * 0.90 <= c.valor <= teto:
            resto = c.valor % 100
            redondo = resto <= tol or resto >= (100 - tol)
            if redondo:
                return _POR_ID["IND-LIM-01"]._mk(
                    confianca=0.5,
                    observado=(f"Valor {_r(c.valor)} logo abaixo do teto de dispensa "
                               f"{_r(teto)} e arredondado."),
                    limite="Valores colados ao teto sugerem ajuste para evitar licitação.",
                    params=[pid, "valor_redondo_tolerancia"],
                )
    return None


# ── Registro dos indicadores ─────────────────────────────────────────────────
# Cada Indicador ganha um _mk() para produzir seu Achado sem repetição.

def _com_mk(ind: Indicador) -> Indicador:
    def _mk(confianca: float, observado: str, limite: str, params: list[str]) -> Achado:
        return _achado(ind, confianca, observado, limite, params)
    ind._mk = _mk  # type: ignore[attr-defined]
    return ind


INDICADORES: list[Indicador] = [
    _com_mk(Indicador(
        "IND-FRAC-01", "fracionamento_objeto",
        "Fracionamento de objeto para fugir da licitação", "alta",
        ["Lei 14.133/2021, art. 8º, §1º", "Súmula TCU 247", "Lei 8.429/92, art. 10"],
        _fracionamento)),
    _com_mk(Indicador(
        "IND-EMP-01", "empresa_recente_grande_contrato",
        "Empresa recém-aberta com contrato de grande valor", "alta",
        ["Lei 14.133/2021, art. 67", "Lei 8.429/92, art. 10"],
        _empresa_recente)),
    _com_mk(Indicador(
        "IND-ADT-01", "aditivo_excessivo",
        "Aditivos contratuais acima do limite legal", "alta",
        ["Lei 14.133/2021, art. 125", "TCU Acórdão 2.066/2018"],
        _aditivo_excessivo)),
    _com_mk(Indicador(
        "IND-SUP-01", "superfaturamento_preco",
        "Superfaturamento de preço frente à referência", "alta",
        ["Lei 14.133/2021, art. 23", "IN SEGES 65/2021", "Súmula TCU 258"],
        _superfaturamento)),
    _com_mk(Indicador(
        "IND-DIR-01", "direcionamento_edital",
        "Proposta única em certame de vulto (competição aparente)", "média",
        ["Lei 14.133/2021, art. 9º"],
        _proposta_unica)),
    _com_mk(Indicador(
        "IND-DIR-02", "direcionamento_edital",
        "Prazo de publicação de edital abaixo do mínimo", "média",
        ["Lei 14.133/2021, art. 55"],
        _prazo_curto)),
    _com_mk(Indicador(
        "IND-SAN-01", "empresa_recente_grande_contrato",
        "Fornecedor sancionado (CEIS/CNEP) contratado", "alta",
        ["Lei 14.133/2021, art. 156"],
        _empresa_sancionada)),
    _com_mk(Indicador(
        "IND-SIT-01", "empresa_recente_grande_contrato",
        "Pagamento a empresa com situação cadastral irregular", "alta",
        ["Lei 4.320/64, arts. 62-63", "IN RFB 2.119/2022"],
        _situacao_cadastral_irregular)),
    _com_mk(Indicador(
        "IND-QPQ-01", "doacao_contrato_reciproco",
        "Doação eleitoral seguida de contrato (quid pro quo)", "alta",
        ["Lei 9.504/97, art. 81", "Lei 8.429/92, art. 9, I", "STF ADI 4650"],
        _quid_pro_quo)),
    _com_mk(Indicador(
        "IND-LIM-01", "fracionamento_objeto",
        "Valor ajustado logo abaixo do teto de dispensa", "baixa",
        ["Lei 14.133/2021, art. 75"],
        _valor_no_limite)),
]

_POR_ID: dict[str, Indicador] = {i.id: i for i in INDICADORES}


def avaliar_todos(dossie: Dossie) -> list[Achado]:
    """
    Roda todos os indicadores sobre um Dossiê e devolve os achados que dispararam,
    ordenados por (severidade, confiança) desc. Determinístico e sem IA.
    """
    dossie.validar()
    achados: list[Achado] = []
    for ind in INDICADORES:
        try:
            r = ind.avaliar(dossie)
        except Exception:
            r = None  # um indicador nunca derruba a perícia inteira
        if r is not None:
            achados.append(r)
    ordem = {"alta": 0, "média": 1, "baixa": 2}
    achados.sort(key=lambda a: (ordem.get(a.severidade, 9), -a.confianca))
    return achados
