# -*- coding: utf-8 -*-
"""X10 · ADITIVO DESINSTRUÍDO — o termo existe, e os autos não sustentam.

A PERGUNTA QUE ESTE CARD RESPONDE. "O aditivo é bem feito?" não se responde só pelo percentual.
Um acréscimo de 10% pode ser irregular e um de 24% pode ser impecável: o que separa os dois é a
INSTRUÇÃO — o que os autos trazem para justificar a alteração. É exatamente o que um analista de
Tribunal de Contas confere primeiro, e o que o motor não olhava.

O CHECKLIST, e a fonte de cada item:

  1. **parecer jurídico prévio** — art. 53 da Lei 14.133 exige controle prévio de legalidade;
     admite-se parecer referencial nas hipóteses padronizadas;
  2. **justificativa técnica específica** — art. 124 abre com "com as devidas justificativas";
     justificativa genérica ("necessidade do serviço") é o vício mais comum e o mais fácil de ver;
  3. **pesquisa de preços do acréscimo** — ou manifestação técnica fundamentando sua dispensa;
     item novo sem preço aferido é onde o sobrepreço entra sem disputa;
  4. **previsão orçamentária** — despesa sem dotação é vício autônomo (Lei 4.320 e LRF);
  5. **anuência do contratado** quando a alteração excede o que ele é obrigado a aceitar;
  6. **publicação do extrato** — eficácia do ato (art. 94);
  7. **manutenção do DESCONTO da proposta nos itens novos** — o TCU e a doutrina são convergentes:
     preservar o desconto reduz a chance de reconfiguração de preços em favor do contratado. É o
     item que quase nunca é conferido e o que mais protege o erário.

A LINHA QUE ESTE CARD NÃO CRUZA. Documento ausente na CAPTURA não é documento ausente nos AUTOS.
Foi a lição de 59% das 9.863 red flags do sweep SEI, que eram queixa de captura e não vício. Por
isso cada item tem TRÊS estados — `presente`, `ausente_declarado` (o processo foi lido inteiro e
o documento não está lá) e `nao_capturado` — e só o segundo pontua. O terceiro entra na cobertura.

TESTES OBJETIVOS: percentual de instrução sobre os itens APURÁVEIS; ausência do parecer jurídico
ou da dotação pesa mais que a do extrato, porque uma é condição de validade e a outra é de
eficácia.
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora, evidencia

# Peso de cada item na nota de instrução. Não é opinião: separa condição de VALIDADE (parecer,
# justificativa, dotação) de condição de EFICÁCIA (publicação) e de boa prática (desconto).
ITENS: dict[str, dict] = {
    "parecer_juridico": {
        "peso": 3, "nome": "parecer jurídico prévio",
        "fundamento": "Lei 14.133/2021, art. 53 (admite-se parecer referencial)",
        "gravidade": "validade"},
    "justificativa_tecnica": {
        "peso": 3, "nome": "justificativa técnica específica",
        "fundamento": "Lei 14.133/2021, art. 124, caput ('com as devidas justificativas')",
        "gravidade": "validade"},
    "dotacao_orcamentaria": {
        "peso": 3, "nome": "previsão orçamentária / dotação",
        "fundamento": "Lei 4.320/1964; LC 101/2000, arts. 15 a 17",
        "gravidade": "validade"},
    "pesquisa_precos": {
        "peso": 2, "nome": "pesquisa de preços do acréscimo (ou dispensa fundamentada)",
        "fundamento": "Lei 14.133/2021, art. 23; IN SEGES 65/2021",
        "gravidade": "validade"},
    "anuencia_contratado": {
        "peso": 1, "nome": "anuência do contratado, quando exigida",
        "fundamento": "Lei 14.133/2021, art. 124, II (alteração por acordo)",
        "gravidade": "validade"},
    "desconto_preservado": {
        "peso": 2, "nome": "manutenção do desconto da proposta nos itens novos",
        "fundamento": "prática recomendada; reduz reconfiguração de preços em favor do contratado",
        "gravidade": "protecao_erario"},
    "publicacao_extrato": {
        "peso": 1, "nome": "publicação do extrato",
        "fundamento": "Lei 14.133/2021, art. 94 (eficácia)",
        "gravidade": "eficacia"},
}

ESTADOS = ("presente", "ausente_declarado", "nao_capturado")

# Faixas da nota de instrução (fração do peso APURÁVEL efetivamente atendido).
_NOTA_CRITICA = 0.40
_NOTA_FORTE = 0.60
_NOTA_MEDIA = 0.80


class X10AditivoDesinstruido(Detector):
    """Detector X10 — instrução do termo aditivo nos autos.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato/processo.
      contexto["instrucao"]: dict {item: estado}, com `estado` em ESTADOS. Item ausente do dict é
          tratado como `nao_capturado` — nunca como falta.
      contexto["evidencias_instrucao"]: opcional dict {item: {"doc": ..., "folha": ...}} para a
          citação por documento e folha.
      contexto["exige_anuencia"]: opcional bool — quando False, o item de anuência sai da conta
          (alteração dentro do que o contratado é obrigado a aceitar).

    Honesto: sem `instrucao` → nao_avaliavel. Nenhum item apurável → nao_avaliavel, não nota zero."""

    id = "X10"
    nome = "Aditivo desinstruído (checklist de instrução dos autos)"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        bruto = contexto.get("instrucao")
        if not isinstance(bruto, dict) or not bruto:
            res.motivo_refutacao = ("nao_avaliavel: sem o checklist de instrução no contexto — "
                                    "campo ausente ≠ instrução ausente")
            res.valores = {"tem_instrucao": False}
            return res

        exige_anuencia = contexto.get("exige_anuencia")
        evid = contexto.get("evidencias_instrucao") or {}

        presentes, faltantes, nao_capturados = [], [], []
        peso_apuravel = peso_atendido = 0
        for item, meta in ITENS.items():
            if item == "anuencia_contratado" and exige_anuencia is False:
                continue                       # alteração dentro do que ele é obrigado a aceitar
            estado = str(bruto.get(item) or "nao_capturado").strip().lower()
            if estado not in ESTADOS:
                estado = "nao_capturado"
            if estado == "nao_capturado":
                nao_capturados.append(item)
                continue
            peso_apuravel += meta["peso"]
            if estado == "presente":
                peso_atendido += meta["peso"]
                presentes.append(item)
            else:
                faltantes.append(item)

        valores = {
            "tem_instrucao": True,
            "presentes": presentes, "faltantes": faltantes, "nao_capturados": nao_capturados,
            "peso_apuravel": peso_apuravel, "peso_atendido": peso_atendido,
            "cobertura": round(len(presentes) + len(faltantes), 0),
            "frac_apuravel": round((len(presentes) + len(faltantes)) / max(1, len(ITENS)), 3),
        }

        if peso_apuravel == 0:
            res.motivo_refutacao = (
                "nao_avaliavel: nenhum item do checklist foi apurado — o processo não foi lido o "
                "bastante para afirmar falta de instrução. Documento ausente na CAPTURA não é "
                "documento ausente nos AUTOS.")
            res.valores = valores
            return res

        nota = peso_atendido / peso_apuravel
        valores["nota_instrucao"] = round(nota, 3)

        if not faltantes:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            res.motivo_refutacao = (
                f"instrução completa entre os {len(presentes)} item(ns) apurado(s) "
                f"(nota {nota:.0%})"
                + (f"; {len(nao_capturados)} item(ns) não capturado(s), a conferir nos autos."
                   if nao_capturados else ""))
            return res

        nivel = ("critico" if nota < _NOTA_CRITICA else "forte" if nota < _NOTA_FORTE
                 else "medio" if nota < _NOTA_MEDIA else "fraco")
        # Faltar condição de VALIDADE nunca é achado fraco, por melhor que seja a nota.
        if any(ITENS[i]["gravidade"] == "validade" for i in faltantes) and nivel == "fraco":
            nivel = "medio"

        linhas = []
        for item in faltantes:
            meta = ITENS[item]
            ref = evid.get(item) or {}
            onde = (f" [{ref.get('doc')}" + (f", fl. {ref.get('folha')}" if ref.get("folha") else "")
                    + "]") if ref.get("doc") else ""
            linhas.append(
                f"AUSENTE nos autos: {meta['nome']} ({meta['fundamento']}; condição de "
                f"{meta['gravidade'].replace('_', ' ')}){onde}")
        linhas.insert(0, (
            f"Nota de instrução {nota:.0%} — {peso_atendido} de {peso_apuravel} pontos de peso "
            f"entre os {len(presentes) + len(faltantes)} itens apurados"))
        if nao_capturados:
            linhas.append(
                f"COBERTURA: {len(nao_capturados)} item(ns) do checklist não foram capturados "
                f"({', '.join(ITENS[i]['nome'] for i in nao_capturados)}) — não entram na nota, e "
                f"a conferência nos autos pode alterá-la nos dois sentidos")

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        res.evidencia = [evidencia("autos do processo (SEI)", t) for t in linhas]
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "A instrução pode estar completa e dispersa: parecer referencial que dispensa parecer "
            "individualizado, dotação indicada no próprio termo, pesquisa de preços juntada ao "
            "processo principal e não ao apenso do aditivo. O achado é sobre o que foi LIDO — a "
            "apuração pede a íntegra do processo antes de afirmar ausência.")
        return res
