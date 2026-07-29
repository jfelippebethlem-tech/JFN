# -*- coding: utf-8 -*-
"""Auto-consistência do VEREDITO — N amostras, mediana de âncora nomeada, divergência declarada.

POR QUE ISTO NÃO EXISTIA. A casa tem auto-consistência para EXTRAÇÃO — `nucleo/extracao_robusta`
vota o valor majoritário de campos críticos — e não tem para JUÍZO. Cada parecer de direcionamento,
cada rubrica de detector, cada classificação de cumprimento de parecer é UMA amostragem, com
`temperature=0.1`. Um modelo que hesita entre "amarelo" e "vermelho" devolve um dos dois e o
sistema trata a resposta como se fosse determinística.

TRÊS DECISÕES QUE DEFINEM O COMPORTAMENTO:

  1. **Mediana de âncora NOMEADA, nunca média de número.** A casa já proíbe o LLM escolher valor
     contínuo (`detectores/base.ANCORAS`); a agregação segue a mesma regra. Média de 'verde' e
     'vermelho' não é 'amarelo' — é invenção. A mediana de posições ordinais devolve um nível que
     ao menos UM dos votos afirmou.
  2. **Divergência é resultado, não ruído a suavizar.** Se as amostras discordam em ≥1 nível, o
     caso sai marcado — é a mesma lógica de `direcionamento_cerebro.fundir_graus`, que manda a
     divergência entre camadas para o pacote humano em vez de resolvê-la em silêncio.
  3. **Empate resolve para o MENOS severo.** Ao contrário da fusão det×LLM, onde prevalece o mais
     severo porque as camadas são independentes e nenhuma pode ser silenciada, aqui as amostras
     vêm do MESMO modelo sobre o MESMO texto: a discordância mede incerteza, não achado adicional.
     Na dúvida entre acusar e não acusar, presunção de legitimidade.

CUSTO. N amostras custam N chamadas. Por isso `escalonar_por_severidade` existe: N=1 na triagem
em massa, N=3 só quando o veredito preliminar é grave ou o caso vai virar peça. Rodar tudo em N=3
gastaria o triplo para melhorar o que não estava em dúvida.
"""
from __future__ import annotations

import statistics
from typing import Any, Callable, Sequence

# Temperaturas das amostras. A primeira é a de produção (0.1); as outras abrem o leque só o
# suficiente para revelar hesitação — temperatura alta demais mede ruído, não incerteza.
TEMPERATURAS_PADRAO = (0.1, 0.4, 0.7)


def _posicao(valor: Any, escala: Sequence[str]) -> int | None:
    v = str(valor or "").strip().lower()
    for i, nome in enumerate(escala):
        if v == str(nome).strip().lower():
            return i
    return None


def votar(gerar: Callable, prompt: str, sistema: str, *, escala: Sequence[str],
          chave: str = "grau", n: int = 3,
          temperaturas: Sequence[float] = TEMPERATURAS_PADRAO) -> dict[str, Any]:
    """Roda `n` amostras e agrega por mediana ordinal da `escala` (do menos ao mais severo).

    `gerar` pode aceitar `temperatura=` como keyword; se não aceitar, as amostras saem com a
    temperatura padrão do provedor e a variação vem da própria amostragem — o resultado continua
    válido, e o campo `temperaturas_aplicadas` declara o que de fato aconteceu.

    Devolve `{valor, n_validos, votos, divergencia, unanime, respostas}`. `valor=None` quando
    nenhuma amostra produziu nível da escala — INDISPONÍVEL, nunca o nível mais brando por omissão.
    """
    from compliance_agent.llm.json_resposta import parse_json_llm

    votos: list[dict] = []
    aplicadas: list[Any] = []
    for i in range(max(1, int(n))):
        temp = temperaturas[i % len(temperaturas)] if temperaturas else None
        try:
            try:
                bruto = gerar(prompt, sistema, temperatura=temp)
                aplicadas.append(temp)
            except TypeError:
                # `gerar` da casa é (prompt, sistema); não impor assinatura nova a quem já existe.
                bruto = gerar(prompt, sistema)
                aplicadas.append(None)
        except Exception as exc:  # noqa: BLE001 — amostra perdida não derruba a votação
            votos.append({"i": i, "valor": None, "erro": str(exc)[:80]})
            continue
        j = parse_json_llm(bruto)
        valor = (j or {}).get(chave) if isinstance(j, dict) else None
        votos.append({"i": i, "valor": valor, "resposta": j if isinstance(j, dict) else None})

    posicoes = [p for p in (_posicao(v.get("valor"), escala) for v in votos) if p is not None]
    if not posicoes:
        return {"valor": None, "n_validos": 0, "votos": votos, "divergencia": None,
                "unanime": False, "temperaturas_aplicadas": aplicadas,
                "motivo": "nenhuma amostra produziu nível da escala — INDISPONÍVEL"}

    # Mediana BAIXA: com número par de votos, o empate resolve para o menos severo.
    idx = statistics.median_low(posicoes)
    unanime = len(set(posicoes)) == 1
    amplitude = max(posicoes) - min(posicoes)
    divergencia = None
    if not unanime:
        divergencia = {
            "amplitude": amplitude,
            "niveis": sorted({escala[p] for p in posicoes}, key=lambda x: _posicao(x, escala)),
            "nota": ("As amostras do MESMO modelo sobre o MESMO texto discordaram — isso mede "
                     "incerteza do juízo, não achado adicional. O empate resolveu para o nível "
                     "menos severo (presunção de legitimidade); a divergência vai para o pacote "
                     "humano."),
        }
    return {"valor": escala[idx], "n_validos": len(posicoes), "votos": votos,
            "divergencia": divergencia, "unanime": unanime,
            "temperaturas_aplicadas": aplicadas,
            "motivo": ("unânime" if unanime else
                       f"mediana de {len(posicoes)} amostras (amplitude {amplitude})")}


def escalonar_por_severidade(grau_preliminar: Any, *, escala: Sequence[str],
                             a_partir_de: str, n_grave: int = 3, n_padrao: int = 1) -> int:
    """Quantas amostras vale a pena gastar neste caso.

    Rodar N=3 em tudo triplica o custo para melhorar justamente o que não estava em dúvida. A
    escalada por severidade concentra a inferência onde o erro é caro: veredito grave, ou caso
    que vai virar peça.
    """
    p, corte = _posicao(grau_preliminar, escala), _posicao(a_partir_de, escala)
    if p is None or corte is None:
        return n_padrao
    return n_grave if p >= corte else n_padrao


def aplicar(resultado: dict, votacao: dict, *, campo: str = "grau") -> dict:
    """Escreve o resultado da votação num dict de veredito, preservando o rastro.

    Nunca sobrescreve com `None`: votação indisponível deixa o veredito como estava e registra o
    motivo — o mesmo contrato de honestidade das rubricas (INDISPONÍVEL ≠ decidido).
    """
    r = dict(resultado or {})
    if votacao.get("valor") is not None:
        r[campo] = votacao["valor"]
    r["autoconsistencia"] = {
        "n_validos": votacao.get("n_validos", 0),
        "unanime": votacao.get("unanime"),
        "divergencia": votacao.get("divergencia"),
        "motivo": votacao.get("motivo", ""),
        "valores": [v.get("valor") for v in votacao.get("votos", [])],
    }
    return r
