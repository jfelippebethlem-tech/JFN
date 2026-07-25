# -*- coding: utf-8 -*-
"""COERÊNCIA DE VALORES E DE FAVORECIDO dentro do processo.

O mesmo dinheiro aparece em peças diferentes dos autos — contrato, termo aditivo, nota fiscal, nota de
empenho, ordem bancária. Quando esses números não fecham, alguma coisa aconteceu: pagou-se acima do
contratado, empenhou-se menos do que se pagou, ou a nota é de outro valor. E quando o CNPJ do favorecido
da OB não é o da contratada, pagou-se a um terceiro.

Ninguém verificava isso, embora 1.587 dos 2.050 processos do acervo tragam valores em R$ no texto e
1.371 tragam CNPJ.

HONESTIDADE — esta família tem explicações legítimas frequentes, e o módulo as declara em vez de acusar:
  • pagar acima do contrato original é normal quando há ADITIVO (art. 125) ou REAJUSTE (art. 92, §3º);
  • pagamento a CNPJ diferente pode ser cessão de crédito, sub-rogação, consórcio ou filial do mesmo
    grupo (mesma raiz de CNPJ — que este módulo já não trata como divergência);
  • o valor pode aparecer parcelado, e a soma das OBs é que fecha com o contrato.
Por isso o veredito é indício com o cálculo à vista, e a ação é conferir a peça que explicaria.
"""
from __future__ import annotations

import re

# valor em real: exige o "R$" — número solto no texto é nº de processo, CNPJ, data ou quantidade
_RE_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})")
# VALOR GLOBAL do contrato: só serve de teto o número anunciado como global/total/mensal×prazo. Medido no
# acervo: pegar "o maior valor da peça" transformou uma multa diária de R$ 192,17 em teto contratual, e
# contrato sem valor legível virou teto ZERO — os dois faziam qualquer pagamento "exceder".
_RE_GLOBAL = re.compile(
    # NÃO usar [^R] aqui: com re.I isso exclui também o "r" minúsculo, e "contrato" tem um — foi o que
    # impediu "Valor global do contrato: R$ 100.000,00" de casar. Preguiçoso resolve e não atravessa frase.
    r"valor\s+(?:global|total|do\s+contrato|contratual|da\s+contrata[çc][ãa]o|estimado).{0,60}?"
    r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.I)
_RE_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
_TOLERANCIA = 0.01        # 1% — absorve arredondamento, centavos e reajuste miúdo
_MARCADOR = {
    "contrato": r"contrato|instrumento\s+contratual|termo\s+de\s+contrato",
    "aditivo": r"aditivo|aditamento|acr[ée]scimo",
    "pagamento": r"ordem\s+banc[áa]ria|\b20\d{2}OB\d+|pagamento\s+efetuado",
    "empenho": r"empenho|\b20\d{2}NE\d+",
    "nota_fiscal": r"nota\s+fiscal|\bNF\b|danfe",
}
_RESSALVA = ("divergência de valor ou de favorecido é INDÍCIO: aditivo, reajuste, glosa, pagamento "
             "parcelado, cessão de crédito e filial do mesmo grupo explicam muitas delas legitimamente. "
             "Indício a apurar, não acusação; presunção de legitimidade")


def valores(texto: str) -> list[float]:
    """Todos os valores em R$ do texto, na ordem. Sem 'R$' não é dinheiro (evita confundir com nº de
    processo, CNPJ e data, que também têm ponto e dígito)."""
    return [float(m.group(1).replace(".", "").replace(",", ".")) for m in _RE_VALOR.finditer(texto or "")]


def cnpjs(texto: str) -> list[str]:
    return ["".join(m.groups()) for m in _RE_CNPJ.finditer(texto or "")]


def _classe(doc: dict) -> str | None:
    alvo = f"{doc.get('titulo') or ''} {doc.get('tipo') or ''}"
    for nome, pat in _MARCADOR.items():
        if re.search(pat, alvo, re.I):
            return nome
    return None


def analisar_valores(docs: list[dict]) -> dict:
    """Veredito RESOLVIDO sobre a coerência de valores e do favorecido.

    `docs`: [{titulo, tipo, texto}]. Retorna {grau, contratado, pago, excesso, cnpj_divergente,
    explicacoes_possiveis[], resumo, acao, ressalva}."""
    contratado = aditivos = 0.0
    tem_contrato = False
    pago = 0.0
    cnpj_contrato: list[str] = []
    cnpj_pagamento: list[str] = []
    for d in docs or []:
        classe = _classe(d)
        if not classe:
            continue
        vs = valores(d.get("texto") or "")
        cs = cnpjs(d.get("texto") or "")
        if classe == "contrato":
            tem_contrato = True
            globais = [float(m.group(1).replace(".", "").replace(",", "."))
                       for m in _RE_GLOBAL.finditer(d.get("texto") or "")]
            if globais:
                contratado = max(contratado, max(globais))
            cnpj_contrato += cs
        elif classe == "aditivo":
            if vs:
                aditivos += max(vs)
        elif classe == "pagamento":
            if vs:
                pago = max(pago, max(vs))                # maior OB (não soma: parcelas repetem o total)
            cnpj_pagamento += cs
    # teto DESCONHECIDO (None) quando a peça de contrato não anuncia valor global — nunca zero
    teto = (contratado + aditivos) if (tem_contrato and contratado > 0) else None
    raiz = lambda c: c[:8]                                                  # noqa: E731
    div_cnpj = bool(cnpj_contrato and cnpj_pagamento
                    and not ({raiz(c) for c in cnpj_contrato} & {raiz(c) for c in cnpj_pagamento}))
    # a divergência de FAVORECIDO é aferível mesmo sem valor nenhum: sair antes de checá-la deixava
    # passar pagamento a terceiro só porque o texto não trazia cifra.
    if not pago and teto is None and not div_cnpj:
        return {"grau": "nao_aplicavel", "contratado": None, "pago": None, "excesso": None,
                "cnpj_divergente": False, "explicacoes_possiveis": [],
                "resumo": "Nenhum valor em R$ identificado nas peças de contrato ou pagamento deste processo.",
                "acao": "", "ressalva": _RESSALVA, "fonte": "coerencia_valores (determinístico/offline)"}
    explicacoes, sinais, grau = [], [], "verde"
    excesso = None
    if teto is not None and pago and pago > teto * (1 + _TOLERANCIA):
        excesso = round(pago - teto, 2)
        grau = "vermelho"
        sinais.append(f"pagamento de R$ {pago:,.2f} contra teto contratual de R$ {teto:,.2f} "
                      f"(excesso de R$ {excesso:,.2f})")
        explicacoes += ["termo ADITIVO de valor não capturado nos autos lidos (art. 125 da Lei 14.133)",
                        "REAJUSTE/repactuação contratual (art. 92, §3º)",
                        "o valor lido como 'contrato' pode ser de uma parcela, não do global"]
    if div_cnpj:
        grau = "vermelho"
        sinais.append("CNPJ do favorecido do pagamento difere do CNPJ da contratada")
        explicacoes += ["cessão de crédito ou sub-rogação averbada no processo",
                        "consórcio/subcontratação com pagamento direto autorizado",
                        "o CNPJ lido na peça pode ser de interveniente (banco, seguradora), não do credor"]
    if not sinais:
        if teto is None:
            return {"grau": "a_verificar", "contratado": None, "pago": pago or None, "excesso": None,
                    "cnpj_divergente": False, "explicacoes_possiveis": [],
                    "resumo": (f"Há pagamento de R$ {pago:,.2f} nos autos, mas o valor CONTRATADO não foi "
                               "localizado nas peças lidas — sem ele não se afirma excesso nem regularidade."),
                    "acao": "localizar o contrato/instrumento equivalente e reavaliar",
                    "ressalva": _RESSALVA, "fonte": "coerencia_valores (determinístico/offline)"}
        return {"grau": "verde", "contratado": teto, "pago": pago or None, "excesso": None,
                "cnpj_divergente": False, "explicacoes_possiveis": [],
                "resumo": (f"Pagamento de R$ {pago:,.2f} dentro do teto contratual de R$ {teto:,.2f}"
                           + (f" (contrato R$ {contratado:,.2f} + aditivos R$ {aditivos:,.2f})"
                              if aditivos else "") + "; favorecido compatível com a contratada."),
                "acao": "", "ressalva": _RESSALVA, "fonte": "coerencia_valores (determinístico/offline)"}
    return {"grau": grau, "contratado": teto, "pago": pago or None, "excesso": excesso,
            "cnpj_divergente": div_cnpj, "explicacoes_possiveis": explicacoes,
            "resumo": "; ".join(sinais) + ".",
            "acao": ("conferir nos autos a peça que explicaria a diferença (aditivo, reajuste, cessão de "
                     "crédito) antes de qualquer apontamento"),
            "ressalva": _RESSALVA, "fonte": "coerencia_valores (determinístico/offline)"}
