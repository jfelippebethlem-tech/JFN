# -*- coding: utf-8 -*-
"""FONTE ÚNICA do teto de acréscimo contratual (art. 125) e da natureza do aditivo.

`limites_dispensa.py` existe porque o teto de dispensa foi duplicado cinco vezes, com valores
divergentes, dentro de detectores que produzem alerta de severidade alta. O teto de ADITIVO
estava na mesma situação — cinco cópias — com um agravante: o número é o de menos.

O QUE REALMENTE DIVERGIA. Decidir se um termo aditivo consome o teto do art. 125 é uma questão
JURÍDICA, e havia três respostas diferentes rodando ao mesmo tempo:

  · `contratos/thoughts._e_acrescimo_de_valor` — lia o OBJETO e negava prorrogação, acerto pago
    com revisão à mão (caso AVANTY, 2026-07-11: +R$ 51 mi que era renovação de 12 meses);
  · `cruzamentos_intel.aditivos_estouro` — filtrava por `qualif_acrescimo='1'`, campo que a
    própria casa já havia declarado inútil no `thoughts` ("vem '1' para quase tudo");
  · `pcrj/pericia_gastos.d11` — não classificava nada: `valor_global > valor_inicial * 1.25`,
    somando reajuste, reequilíbrio e prorrogação ao teto de acréscimo.

E nenhuma conhecia o **reequilíbrio do art. 124, II, "d"**, que foi a causa de 45% dos falsos
positivos medidos na estreia da varredura de execução (2026-07-29): um termo de "revisão dos
valores vigentes" com R$ 40,6 mi entrou no teto do art. 125 e produziu achado crítico.

AS QUATRO NATUREZAS, e por que a distinção importa:

  `valor`    acréscimo ou supressão de quantitativo/escopo — **é o único que consome o teto**;
  `prazo`    prorrogação — art. 107, régua própria (X2), não consome teto;
  `reajuste` reajuste, repactuação, revisão e reequilíbrio (arts. 92 §3º e 124, II, "d") —
             RECOMPÕE o valor corroído, não amplia o objeto; não consome teto;
  `outro`    sub-rogação, retificação, correção de erro material — não mexe em valor nem prazo;
  `misto`    o mesmo termo faz revisão E acréscimo, com UM valor cobrindo os dois. Sem memória de
             cálculo não há como repartir: fica fora do teto e a lacuna é DECLARADA. Contar
             inteiro infla o percentual; contar zero esconde acréscimo real. Declarar é a única
             saída honesta.
  `""`       não deu para saber — se carrega dinheiro, vira lacuna declarada, nunca acréscimo.

O TETO EM SI (art. 125 da Lei 14.133/2021; art. 65 §1º da Lei 8.666/93, com o mesmo percentual):
25% do valor inicial atualizado, 50% para REFORMA de edifício ou de equipamento. Acréscimos e
supressões são computados SEPARADAMENTE — não se compensam.
"""
from __future__ import annotations

import re
from typing import Any

# ───────────────────────────── o teto ─────────────────────────────────────────────────────────

TETOS: dict[str, dict[str, float]] = {
    "14133": {"padrao": 0.25, "reforma": 0.50},
    "8666": {"padrao": 0.25, "reforma": 0.50},
}
ATO_NORMATIVO: dict[str, str] = {
    "14133": "Lei 14.133/2021, art. 125",
    "8666": "Lei 8.666/1993, art. 65, §1º",
}
REGIME_VIGENTE = "14133"


def teto_acrescimo(tipo_objeto: str | None = None, *, regime: str = REGIME_VIGENTE) -> float:
    """Teto de acréscimo como FRAÇÃO do valor inicial atualizado (0.25 ou 0.50).

    `regime` desconhecido cai no vigente em vez de quebrar: o teto é o mesmo nos dois regimes e
    negar resposta aqui derrubaria detector por causa de um rótulo.
    """
    tabela = TETOS.get(str(regime), TETOS[REGIME_VIGENTE])
    return tabela["reforma"] if str(tipo_objeto or "").strip().lower().startswith("reforma") \
        else tabela["padrao"]


def teto_supressao(tipo_objeto: str | None = None, *, regime: str = REGIME_VIGENTE) -> float:
    """Teto de SUPRESSÃO — sempre 25%, inclusive em reforma.

    O texto do art. 125 é explícito e a assimetria passa despercebida com facilidade: "o
    contratado será obrigado a aceitar ... acréscimos ou supressões de até 25% ..., e, no caso de
    reforma de edifício ou de equipamento, **o limite para os ACRÉSCIMOS será de 50%**". A
    elevação para 50% é só do acréscimo; a supressão continua nos 25% em qualquer objeto.

    Usar `teto_acrescimo()` para os dois lados daria 50% de folga a uma supressão em reforma —
    falso negativo silencioso justamente no tipo de contrato onde a supressão costuma esvaziar o
    objeto contratado depois de vencida a licitação. Texto conferido no Planalto em 2026-07-29.
    """
    return TETOS.get(str(regime), TETOS[REGIME_VIGENTE])["padrao"]


def ato_normativo(regime: str = REGIME_VIGENTE) -> str:
    """Dispositivo a citar na peça. Sem isso o percentual é inverificável."""
    return ATO_NORMATIVO.get(str(regime), ATO_NORMATIVO[REGIME_VIGENTE])


# ───────────────────────────── a natureza do aditivo ──────────────────────────────────────────
# Vocabulário consolidado das três implementações anteriores mais o que a base real ensinou em
# 2026-07-29 (extratos do PNCP, que não usam a redação do texto corrido do processo SEI).

_RE_SEM_ACRESCIMO = re.compile(r"sem\s+acr[ée]scimo\s+de\s+valor", re.I)
_RE_REEQUILIBRIO = re.compile(
    # A janela entre "revisão" e "dos valores" não é frescura: o extrato real diz "a revisão, a
    # contar de 01/06/2025, dos valores vigentes do benefício" — com a data encaixada no meio.
    # Exigir as palavras coladas foi o que deixou passar R$ 40,6 mi para dentro do art. 125.
    r"reequil[íi]brio|revis[ãa]o\b[^.;]{0,80}?\bd[oe]s?\s+(?:pre[çc]|valor)|repactua|reajust|"
    r"corre[çc][ãa]o\s+monet|\bIPCA\b|\bINCC\b|\bIGP-?M\b", re.I)
_RE_ACRESCIMO = re.compile(
    r"acr[ée]scim|acrescer|supress[ãa]o|suprimir|aditamento\s+de\s+valor|majora|\baporte\b|"
    r"altera[çc][ãa]o\s+quantitativ|alterac?[ãa]o\s*\(quantitativa\)|quantitativ", re.I)
_RE_PRAZO = re.compile(
    r"prorroga|prazo\s+de\s+vig[êe]ncia|prazo\s+contratual|dilata[çc][ãa]o\s+de\s+prazo", re.I)
_RE_OUTRO = re.compile(
    r"sub-?roga|retifica|rerratifica|erro\s+material|adequa[çc][ãa]o|altera[çc][ãa]o\s+da\s+"
    r"vers[ãa]o|altera[çc][ãa]o\s+de\s+cl[áa]usula|transfer[êe]ncia\s+d[ao]\s+contratante|"
    r"aditamento\b", re.I)
_RE_SUPRESSAO = re.compile(r"supress[ãa]o|suprimir", re.I)
# ── fundamento legal citado no termo ──────────────────────────────────────────────────────────
# O art. 124 NÃO é "o artigo do reequilíbrio": ele lista TODAS as hipóteses de alteração, e os
# incisos vão para lados opostos do teto (texto conferido no Planalto em 2026-07-29):
#
#   art. 124, I     alteração UNILATERAL — a alínea "b" é "modificação do valor contratual em
#                   decorrência de acréscimo ou diminuição quantitativa de seu objeto, NOS
#                   LIMITES PERMITIDOS POR ESTA LEI" → é acréscimo, e ENTRA no teto do art. 125;
#   art. 124, II-d  "restabelecer o equilíbrio econômico-financeiro inicial ... em caso de força
#                   maior, caso fortuito ou fato do príncipe ..." → recomposição, FORA do teto;
#   art. 124, II-a/b/c  garantia, regime de execução, forma de pagamento → não mexem no valor;
#   art. 134        alteração de preços por criação/alteração/extinção de TRIBUTOS → recomposição;
#   art. 135        repactuação de serviços contínuos com mão de obra → recomposição.
#
# Tratar todo "art. 124" como recomposição seria o erro INVERSO ao que este módulo veio corrigir:
# em vez de contar reequilíbrio no teto, passaria a EXCLUIR acréscimo quantitativo dele. Medido
# na base real: 5 termos do contrato 28538734000148-2-000383/2025, um deles de +R$ 2,84 mi com
# fundamento no art. 124, I, "b", sairiam do cálculo do art. 125.
_RE_FUND_124_IId = re.compile(
    r"art(?:igo)?\.?\s*124[^.;]{0,40}?\bII\b[^.;]{0,30}?[\"'“”]?\s*\bd\b", re.I)
_RE_FUND_124_I = re.compile(r"art(?:igo)?\.?\s*124[^.;]{0,20}?\bI\b(?!\s*I)", re.I)
_RE_FUND_124_II = re.compile(r"art(?:igo)?\.?\s*124[^.;]{0,20}?\bII\b", re.I)
_RE_FUND_RECOMPOSICAO = re.compile(
    r"art(?:igo)?\.?\s*13[45]\b|art(?:igo)?\.?\s*92[^.;]{0,20}?§?\s*3", re.I)
_RE_FUND_125 = re.compile(r"art(?:igo)?\.?\s*125\b|art(?:igo)?\.?\s*65\b", re.I)

NATUREZAS = ("valor", "prazo", "reajuste", "outro", "misto")


def _flag(v: Any) -> bool:
    """Qualificador do PNCP é texto ('1'/'0'/'true'). Ausente ≠ falso; aqui só o 'sim' interessa."""
    return str(v or "").strip().lower() in {"1", "true", "sim", "s"}


def classificar_natureza(objeto: str | None, *, fundamento_legal: str | None = None,
                         qualif_acrescimo: Any = None, qualif_vigencia: Any = None,
                         qualif_reajuste: Any = None,
                         prazo_aditado_dias: Any = None) -> tuple[str, str]:
    """`(natureza, origem)`. A ORIGEM fica registrada para quem for auditar o achado.

    Hierarquia, da mais confiável para a menos: objeto → fundamento legal → qualificador do PNCP.
    O qualificador é o último recurso porque `qualif_acrescimo` vem '1' para quase tudo — medido
    em `contratos/thoughts`, e a razão de `cruzamentos_intel` estar contando prorrogação como
    acréscimo até aqui.
    """
    obj = objeto or ""
    nega_acrescimo = bool(_RE_SEM_ACRESCIMO.search(obj))
    tem_reeq = bool(_RE_REEQUILIBRIO.search(obj))
    tem_acre = bool(_RE_ACRESCIMO.search(obj)) and not nega_acrescimo
    tem_prazo = bool(_RE_PRAZO.search(obj))

    if tem_reeq and tem_acre:
        return "misto", "objeto"
    if tem_reeq:
        return "reajuste", "objeto"
    if tem_prazo:
        return "prazo", "objeto"
    if tem_acre:
        return "valor", "objeto"
    if _RE_OUTRO.search(obj) or nega_acrescimo:
        # "Alteração quantitativa, SEM ACRÉSCIMO DE VALOR" é o termo declarando, ele próprio, que
        # não mexe no valor. Isso é `outro` — não é lacuna de leitura. Tratá-lo como natureza
        # indeterminada geraria um alerta de "não consegui classificar" sobre um texto que está
        # perfeitamente claro, e ruído desse tipo é o que faz uma lista de lacunas ser ignorada.
        return "outro", "objeto"

    fund = fundamento_legal or ""
    # Ordem: a hipótese MAIS específica primeiro. "124, II, d" tem de ser testada antes de
    # "124, II", e esta antes de "124, I", senão o inciso genérico engole o específico.
    if _RE_FUND_124_IId.search(fund) or _RE_FUND_RECOMPOSICAO.search(fund) \
            or _RE_REEQUILIBRIO.search(fund):
        return "reajuste", "fundamento_legal"
    if _RE_FUND_124_I.search(fund) or _RE_FUND_125.search(fund):
        return "valor", "fundamento_legal"
    if _RE_FUND_124_II.search(fund):
        # II-a garantia · II-b regime de execução · II-c forma de pagamento: alteram o contrato
        # sem alterar o valor. Classificar como acréscimo inflaria o teto; como recomposição,
        # esvaziaria. 'outro' é o que o texto legal autoriza afirmar.
        return "outro", "fundamento_legal"

    if _flag(qualif_reajuste):
        return "reajuste", "qualificador_pncp"
    if _flag(qualif_vigencia) or (int(prazo_aditado_dias or 0) > 0):
        return "prazo", "qualificador_pncp"
    if _flag(qualif_acrescimo):
        return "valor", "qualificador_pncp"
    return "", "indeterminado"


def acrescimo_computavel(aditivos: list[dict] | None) -> dict:
    """Separa o que entra no teto do art. 125 do que não entra, e declara o que não deu para ler.

    Cada aditivo aceita as chaves do PNCP (`objeto`, `valor_acrescido`, `qualif_*`,
    `prazo_aditado_dias`, `fundamento_legal`) ou já classificado (`tipo`, `valor`).

    Devolve `{acrescimo, supressao, n, n_por_tipo, fora_do_teto, lacunas, itens}`. Supressão vem
    à parte porque o art. 125 as computa separadamente — não abatem o acréscimo.
    """
    acrescimo = supressao = 0.0
    n_por_tipo: dict[str, int] = {}
    fora: dict[str, float] = {}
    lacunas: list[str] = []
    itens: list[dict] = []

    for ad in aditivos or []:
        tipo = ad.get("tipo")
        origem = ad.get("origem_tipo") or "pre_classificado"
        if not tipo:
            tipo, origem = classificar_natureza(
                ad.get("objeto"), fundamento_legal=ad.get("fundamento_legal"),
                qualif_acrescimo=ad.get("qualif_acrescimo"),
                qualif_vigencia=ad.get("qualif_vigencia"),
                qualif_reajuste=ad.get("qualif_reajuste"),
                prazo_aditado_dias=ad.get("prazo_aditado_dias"))
        bruto = ad.get("valor") if ad.get("valor") is not None else ad.get("valor_acrescido")
        valor = float(bruto) if bruto not in (None, "") else 0.0
        n_por_tipo[tipo or ""] = n_por_tipo.get(tipo or "", 0) + 1

        if tipo == "valor":
            if valor < 0 or _RE_SUPRESSAO.search(ad.get("objeto") or ""):
                supressao += abs(valor)
            else:
                acrescimo += valor
        else:
            if valor:
                fora[tipo or "sem_natureza"] = fora.get(tipo or "sem_natureza", 0.0) + abs(valor)
            if tipo == "misto" and valor and "aditivo_misto" not in lacunas:
                lacunas.append("aditivo_misto")
            if not tipo and valor and "aditivo_sem_natureza" not in lacunas:
                lacunas.append("aditivo_sem_natureza")

        itens.append({**ad, "tipo": tipo, "origem_tipo": origem, "valor_computado": valor})

    return {"acrescimo": acrescimo, "supressao": supressao, "n": len(aditivos or []),
            "n_por_tipo": n_por_tipo, "fora_do_teto": fora, "lacunas": lacunas, "itens": itens}


def estouro(valor_inicial: float | None, aditivos: list[dict] | None,
            tipo_objeto: str | None = None, *, regime: str = REGIME_VIGENTE) -> dict:
    """Percentual de acréscimo × teto. `valor_inicial` ausente ou ≤ 0 ⇒ `nao_aferivel`.

    Denominador zero produziria percentual infinito, isto é, acusação fabricada a partir de dado
    faltante — a razão pela qual isto devolve `nao_aferivel` em vez de um número.
    """
    comp = acrescimo_computavel(aditivos)
    teto = teto_acrescimo(tipo_objeto, regime=regime)
    if not valor_inicial or float(valor_inicial) <= 0:
        return {**comp, "aferivel": False, "motivo": "valor_inicial ausente ou zero",
                "teto": teto, "ato": ato_normativo(regime), "pct": None, "estourou": None}
    pct = comp["acrescimo"] / float(valor_inicial)
    return {**comp, "aferivel": True, "motivo": "", "teto": teto, "ato": ato_normativo(regime),
            "pct": pct, "estourou": pct > teto,
            "pct_supressao": comp["supressao"] / float(valor_inicial)}
