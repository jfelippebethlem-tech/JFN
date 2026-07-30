# -*- coding: utf-8 -*-
"""J9 · PROPOSTAS GÊMEAS — planilha derivada e texto copiado entre concorrentes.

PEDIDO DO DONO (2026-07-30), verbatim: "criar um detector de semelhança de propostas, se dois
concorrentes respondem com as mesmas frases, parágrafos, ou se simplesmente simulam uma proposta
alterando valores de forma fixa, como diferença de 5% em todos os itens por exemplo."

POR QUE ESTE ARQUIVO É FINO. O motor **já existia** — `compliance_agent/sei/conluio_propostas.py`,
com markup uniforme (o exemplo dos 5% está no docstring dele desde a Onda 5), preços quase idênticos
e similaridade textual — e estava **ÓRFÃO**: fora do próprio arquivo, só era citado num comentário de
`editais/screens_conluio.py:11` e num teste. Zero callers. Sexto caso do padrão "construído, testado,
nunca rodado" nesta casa. Então aqui não se reimplementa nada: embrulha-se o motor no schema de
detector para ele ficar ALCANÇÁVEL pelo pipeline, pelo score do processo e pelo relatório.

O QUE MUDOU NO MOTOR (e é o que faltava para o pedido do dono):
  • `frases_identicas` — devolve os TRECHOS verbatim, não um índice. Ninguém instaura processo com
    "Jaccard 0,87"; o que um tribunal confere é o parágrafo, lado a lado. É exatamente o que o J5 já
    exige na rubrica ("erros idênticos improváveis") e não tinha como medir.
  • `markup_linear` — regressão pela origem, para o caso que o CV por item deixa passar: faixa de
    preço larga com as linhas baratas arredondadas.
  • `_chave_item` deixou de DESCARTAR números: "PARAFUSO INOX 3/8" e "1/2" colidiam, e a planilha
    inteira colapsava num item só.

FRONTEIRA COM OS IRMÃOS (spec: não reimplementar). J2 mede a DISPERSÃO das coberturas (CV) sobre
valor total por licitante; J3 mede desconto rente ao teto; J5 mede AUTORIA (metadado, contato, IP).
J9 é o único que olha o CONTEÚDO: a planilha item a item e o texto da peça.

HONESTIDADE. Indício ≠ acusação. Sem ≥2 propostas com itens ou texto → `nao_avaliavel` com motivo
explícito (campo ausente ≠ 0) — e o gap é o mesmo do J2: o PNCP só expõe o VENCEDOR, então a fonte
real deste detector são os AUTOS (o acervo SEI), não o portal.
"""
from __future__ import annotations

from compliance_agent.detectores.base import Detector, ResultadoDetector, ancora
from compliance_agent.sei import conluio_propostas as CP

_MIN_PROPOSTAS = 2

# Grau por tipo de indício. Trecho LITERAL idêntico e razão constante em toda a lista são os dois
# achados fortes: nenhum dos dois acontece por acaso entre concorrentes independentes. Preço idêntico
# e similaridade de vocabulário são mais fracos — commodity e template de mercado os produzem
# licitamente, e por isso têm exculpatória embutida no motor.
_FORCA = {
    "markup_uniforme": "forte",
    "markup_linear": "forte",
    "frases_identicas": "forte",
    "precos_identicos": "medio",
    "texto_similar": "fraco",
}


class J9PropostasGemeas(Detector):
    """Duas propostas 'concorrentes' que são a mesma peça com valores mexidos."""

    id = "J9"
    nome = "Propostas gêmeas (planilha derivada e texto copiado)"
    familia = "conluio"  # peso 0.85 na convergência §7.2, igual a J1-J8

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        res = self._novo(processo, status="nao_avaliavel")

        propostas = [p for p in (contexto.get("propostas") or []) if isinstance(p, dict)]
        uteis = [p for p in propostas if p.get("itens") or p.get("texto")]

        # ── sem par, não há o que comparar. Vazio por AUSÊNCIA de dado, nunca por regularidade ──
        if len(uteis) < _MIN_PROPOSTAS:
            res.motivo_refutacao = (
                f"nao_avaliavel: {len(uteis)} proposta(s) com itens ou texto (mínimo {_MIN_PROPOSTAS}). "
                "Semelhança entre propostas exige, por definição, DUAS peças para comparar. "
                "O PNCP só expõe o vencedor — a fonte deste detector são os AUTOS (acervo SEI). "
                "Campo ausente ≠ ausência de conluio."
            )
            res.valores = {"n_propostas": len(propostas), "n_com_conteudo": len(uteis),
                           "fonte_esperada": "autos/SEI (PNCP não publica a lista de propostas)"}
            return res

        bruto = CP.detectar(
            uteis,
            mercado_homogeneo=bool(contexto.get("mercado_homogeneo")),
            template_de_mercado=bool(contexto.get("template_de_mercado")),
        )
        indicios = bruto.get("indicios") or []

        res.valores = {
            "n_propostas": len(uteis),
            "n_indicios": len(indicios),
            "por_tipo": {t: sum(1 for i in indicios if i["tipo"] == t) for t in _FORCA
                         if any(i["tipo"] == t for i in indicios)},
            "indicios": indicios,
            "exculpatorias": bruto.get("exculpatorias", {}),
        }

        if not indicios:
            res.status = "descartado"
            res.motivo_refutacao = (
                f"{len(uteis)} propostas comparadas par a par sem coincidência de planilha nem de texto — "
                "dispersão compatível com concorrência real."
            )
            res.explicacao_inocente = "Propostas independentes: preços com dispersão irregular e redação própria."
            return res

        # grau = o indício MAIS FORTE encontrado; exculpatória declarada rebaixa um degrau
        forcas = [_FORCA.get(i["tipo"], "fraco") for i in indicios]
        ordem = ["fraco", "medio", "forte"]
        pior = max(forcas, key=ordem.index)
        if any(i.get("grau_rebaixado") for i in indicios) and pior != "fraco":
            pior = ordem[ordem.index(pior) - 1]

        res.status = "confirmado"
        res.score = ancora(pior)
        # a EVIDÊNCIA é o trecho/número, não a conclusão — é o que vai lado a lado no laudo
        for i in indicios[:8]:
            res.add_evidencia(f"proposta:{i['a']} × {i['b']}", i["obs"])
            for t in (i.get("trechos") or [])[:2]:
                res.add_evidencia(f"trecho idêntico:{i['a']} = {i['b']}", t)
        res.explicacao_inocente = (
            "Cotação a partir de tabela de fabricante comum, insumo de preço regulado ou modelo de "
            "proposta de associação comercial podem produzir planilha e texto parecidos licitamente. "
            "Confirmar com a autoria dos arquivos (J5) e a estrutura de custo do mercado antes de concluir."
        )
        return res
