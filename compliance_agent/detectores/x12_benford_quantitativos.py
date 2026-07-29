# -*- coding: utf-8 -*-
"""X12 · BENFORD NOS QUANTITATIVOS — o dígito que denuncia o número escolhido a dedo.

A IDEIA, e ela tem literatura específica no Brasil. A Lei de Benford descreve a distribuição dos
primeiros dígitos em séries que crescem por processos naturais — e quantitativos de planilha
orçamentária, quando derivados de projeto, obedecem razoavelmente a ela. Quando alguém ESCOLHE os
números — para inflar o item caro e enxugar o barato, que é o jogo de planilha — a assinatura
digital muda. O IBRAOP publicou a aplicação para exatamente esse fim.

POR QUE ESTE CARD É DE TRIAGEM, E O SCORE É LIMITADO. Benford sobre quantitativos é mais fraco do
que sobre pagamentos, e por razões estruturais que nada tem a ver com fraude:

  · quantidade de engenharia sai de medição geométrica, e área/volume têm restrições que
    distorcem a distribuição naturalmente;
  · planilha real tem muito "1" legítimo (1 unidade de equipamento, 1 verba, 1 serviço);
  · itens em unidades diferentes (m², m³, kg, verba) misturam escalas incomparáveis.

Por isso o card **nunca passa de `medio` sozinho** — é fila de conferência, não achado. Ele existe
para ORDENAR quais planilhas o X5 (jogo de planilha) e a curva ABC devem olhar primeiro, num
acervo em que ler todas à mão é impossível.

O QUE O CARD FAZ ALÉM DE RODAR BENFORD:

  T1 NÃO CONFORMIDADE do 1º dígito (MAD de Nigrini) ................................. medio
  T2 EXCESSO DE ARREDONDAMENTO — fração de quantitativos "redondos" muito acima do
     esperado; número escolhido tende a terminar em 0 ou 5 .......................... medio
  T3 CONVERGÊNCIA — não conformidade E arredondamento excessivo no mesmo contrato ... forte

HONESTIDADE JFN, e aqui há um número que foi MEDIDO, não herdado. O `min_n` padrão do módulo de
Benford é 50 — e nesse tamanho a faixa de Nigrini não significa nada: 200 séries sintéticas
perfeitamente benfordianas foram rotuladas "NÃO CONFORMIDADE" em 100% das vezes com n=50, 95% com
n=100, 64% com n=200 e 20% com n=400 (medição de 2026-07-29, tabela em
`analysis/benford.N_CONFIAVEL_MAD`). O card exige n ≥ 800 e só LÊ a faixa quando o módulo a
declara legível. Amostra pequena não produz achado — produz `nao_avaliavel` com o n declarado.
Verba e itens sem quantidade entram como lacuna, nunca como zero.
"""
from __future__ import annotations

from compliance_agent.analysis.benford import N_CONFIAVEL_MAD, benford
from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora, evidencia

# Mínimo de itens para a análise valer. NÃO é o default do módulo de Benford (50) — medido nesta
# base em 2026-07-29, com n=50 CEM POR CENTO das séries perfeitamente benfordianas são rotuladas
# "NÃO CONFORMIDADE" por ruído amostral, e em n=400 ainda são 20%. Ver a tabela em
# `analysis/benford.N_CONFIAVEL_MAD`. Baixar o limiar "para caber no dado que existe" é como um
# teste estatístico vira decoração — e aqui a decoração custaria uma planilha inocente na fila.
MIN_ITENS = N_CONFIAVEL_MAD
# Fração de quantitativos terminados em 0 ou 5 acima da qual o arredondamento chama atenção.
# Numa planilha de engenharia derivada de projeto, o esperado gira em torno de 20%.
FRAC_REDONDOS_ESPERADA = 0.20
FRAC_REDONDOS_ALERTA = 0.45


def _num(v) -> float | None:
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def fracao_redondos(quantitativos: list[float]) -> float:
    """Fração de valores cuja parte inteira termina em 0 ou 5.

    Quantidade escolhida a dedo tende ao redondo; quantidade calculada, não. A medida é grosseira
    de propósito — serve para ordenar fila, e a precisão viria do que não temos (a memória de
    cálculo do projeto).
    """
    inteiros = [int(abs(q)) for q in quantitativos if q is not None]
    if not inteiros:
        return 0.0
    return sum(1 for i in inteiros if i % 5 == 0) / len(inteiros)


class X12BenfordQuantitativos(Detector):
    """Detector X12 — assinatura digital dos quantitativos da planilha contratual.

    `avaliar(contexto)` espera:
      contexto["processo"]: id do contrato.
      contexto["itens"]: list[dict] com `quantidade` (ou `quantidade_contratada`). Item sem
          quantidade entra como lacuna, não como zero.
      contexto["min_itens"]: opcional int (default 800, medido) — abaixar isto é decisão de quem
          chama, e o achado registra o limiar usado; abaixo de 800 a faixa de Nigrini deixa de ser
          lida, então o card passa a depender só do arredondamento.

    Honesto: amostra insuficiente → nao_avaliavel com o n declarado. Score nunca passa de `medio`
    sem convergência: Benford é triagem, não prova."""

    id = "X12"
    nome = "Benford nos quantitativos da planilha"
    familia = "execucao"

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        itens = [i for i in (contexto.get("itens") or []) if isinstance(i, dict)]
        if not itens:
            res.motivo_refutacao = ("nao_avaliavel: sem itens de planilha no contexto — não há "
                                    "tabela de itens de contrato na base (campo ausente ≠ 0)")
            res.valores = {"n_itens": 0}
            return res

        quantidades: list[float] = []
        sem_quantidade = 0
        for i in itens:
            q = _num(i.get("quantidade") if i.get("quantidade") is not None
                     else i.get("quantidade_contratada"))
            if q is None:
                sem_quantidade += 1
            else:
                quantidades.append(q)

        min_itens = int(contexto.get("min_itens") or MIN_ITENS)
        r = benford(quantidades, min_n=min_itens)
        valores = {
            "n_itens": len(itens), "n_com_quantidade": len(quantidades),
            "sem_quantidade": sem_quantidade, "min_itens": min_itens,
            "benford_n": r["n"], "suficiente": r["suficiente"],
            "mad_primeiro": r["primeiro_digito"].get("mad"),
            "faixa_primeiro": r["primeiro_digito"].get("faixa_nigrini"),
            "faixa_confiavel": r["primeiro_digito"].get("faixa_confiavel"),
            "faixa_nota": r["primeiro_digito"].get("faixa_nota"),
        }

        if not r["suficiente"]:
            res.motivo_refutacao = (
                f"nao_avaliavel: {r['n']} quantitativo(s) analisável(is), abaixo do mínimo de "
                f"{min_itens} — Benford com amostra pequena não é indício, é ruído. Baixar o "
                f"limiar para caber no dado transformaria o teste em decoração."
                + (f" {sem_quantidade} item(ns) sem quantidade informada." if sem_quantidade else ""))
            res.valores = valores
            return res

        sinais: list[str] = []
        # A faixa só é lida quando o `n` a torna legível — o próprio módulo agora diz isso.
        nao_conforme = (bool(r["primeiro_digito"].get("faixa_confiavel"))
                        and str(r["primeiro_digito"].get("faixa_nigrini") or "").upper()
                        .startswith("NÃO CONFORMIDADE"))
        if nao_conforme:
            sinais.append(
                f"NÃO CONFORMIDADE do 1º dígito: MAD {r['primeiro_digito']['mad']:.4f} "
                f"({r['primeiro_digito']['faixa_nigrini']}, faixas de Nigrini) sobre "
                f"{r['n']} quantitativos")

        frac = fracao_redondos(quantidades)
        valores["frac_redondos"] = round(frac, 3)
        redondo_demais = frac >= FRAC_REDONDOS_ALERTA
        if redondo_demais:
            sinais.append(
                f"ARREDONDAMENTO: {frac:.0%} dos quantitativos terminam em 0 ou 5 (esperado em "
                f"torno de {FRAC_REDONDOS_ESPERADA:.0%} numa planilha derivada de projeto) — "
                f"quantidade escolhida tende ao redondo; quantidade calculada, não")

        if not sinais:
            res.status = "descartado"
            res.score = 0.0
            res.valores = valores
            res.motivo_refutacao = (
                f"assinatura digital dos {r['n']} quantitativos dentro do esperado "
                f"({r['primeiro_digito']['faixa_nigrini']}; {frac:.0%} de valores redondos)")
            return res

        # Convergência: os dois sinais juntos passam de triagem a indício que merece a planilha na
        # mesa. Um sozinho fica em `medio` — Benford não sustenta afirmação, e o card assume isso.
        nivel = "forte" if (nao_conforme and redondo_demais) else "medio"
        if sem_quantidade:
            sinais.append(
                f"COBERTURA: {sem_quantidade} de {len(itens)} itens sem quantidade informada — "
                f"ficaram fora da análise e podem alterá-la nos dois sentidos")

        res.status = "confirmado"
        res.score = ancora(nivel)
        res.valores = valores
        res.evidencia = [evidencia("planilha contratual", s) for s in sinais]
        res.motivo_refutacao = ""
        res.explicacao_inocente = (
            "Quantitativo de engenharia sai de medição geométrica, e área e volume têm restrições "
            "que distorcem a distribuição naturalmente; planilha real tem muito '1' legítimo "
            "(uma verba, um equipamento) e mistura unidades de escalas incomparáveis. Este card é "
            "FILA DE CONFERÊNCIA: ele diz qual planilha o X5 e a curva ABC devem olhar primeiro, "
            "não que houve jogo de planilha.")
        return res
