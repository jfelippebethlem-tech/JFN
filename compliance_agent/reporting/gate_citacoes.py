# -*- coding: utf-8 -*-
"""Gate de CITAÇÕES — nenhuma peça sai com acórdão que não existe.

Irmão do `reporting/neutralidade`: aquele barra menção interna, este barra citação inventada.
Ambos rodam sobre o texto final, no último instante antes de virar entregável.

**Por que existe.** Em 2026-07-27, ao confrontar `knowledge/jurisprudencia.py` com o acervo
oficial do TCU, apareceram 4 acórdãos numericamente impossíveis, 1 citação inteiramente trocada
(o nº 1273/2020 existe, mas trata de tempo de serviço religioso) e 1 erro de ano no clássico do
BDI (2.622/2015 → 2.622/2013). Tudo isso alimentava prompt de LLM e podia sair impresso num
parecer endereçado ao TCE-RJ. Citação inexistente desqualifica a peça inteira.

**Por que não levanta exceção.** `garantir_neutro` pode explodir: termo interno é sempre erro
nosso e o conserto é imediato. Aqui não — `nao_confirmado` é dúvida legítima (a Jurisprudência
Selecionada é um recorte), e derrubar a geração de um parecer no meio de um sweep noturno por
causa de uma dúvida seria pior que o problema. O gate **saneia e registra**; o modo `estrito`
existe para quem quiser falhar alto.

Comportamento por estado:
  `numero_impossivel`  → citação REMOVIDA do texto e substituída por marcador. Não existe.
  `colegiado_diverge`  → colegiado CORRIGIDO no texto (sabemos o certo pelo acervo).
  `nao_confirmado`     → mantida, e listada na nota de auditoria como "conferir na fonte".
  `fora_do_escopo`     → intocada (TCE-RJ/TCM não são cobertos por este índice).
  `indice_ausente`     → gate desliga e diz que desligou; nunca finge que conferiu.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from compliance_agent.knowledge import tcu_juris_index as T

logger = logging.getLogger(__name__)

_MARCA_REMOVIDA = "[citação suprimida — acórdão inexistente no acervo do TCU]"

_COLEGIADO_NO_TEXTO = re.compile(
    r"\s*[-–—,]?\s*(plen[áa]rio|primeira\s+c[âa]mara|segunda\s+c[âa]mara|"
    r"1[ªa]\s*c[âa]mara|2[ªa]\s*c[âa]mara)\b", re.IGNORECASE)


def auditar(texto: str, db: str | Path | None = None) -> dict:
    """Classifica toda citação do texto. Não altera nada."""
    achados = T.verificar_citacao(texto or "", db=db)
    por_estado: dict[str, list[dict]] = {}
    for a in achados:
        por_estado.setdefault(a["status"], []).append(a)
    return {
        "total": len(achados),
        "impossiveis": por_estado.get("numero_impossivel", []),
        "colegiado_errado": por_estado.get("colegiado_diverge", []),
        "nao_confirmadas": por_estado.get("nao_confirmado", []),
        "confirmadas": por_estado.get("confirmado", []),
        "fora_do_escopo": por_estado.get("fora_do_escopo", []),
        "indice_ausente": bool(por_estado.get("indice_ausente")),
        "limpo": not por_estado.get("numero_impossivel")
        and not por_estado.get("colegiado_diverge"),
    }


def aplicar(texto: str, db: str | Path | None = None, estrito: bool = False,
            contexto: str = "parecer") -> tuple[str, dict]:
    """Devolve `(texto_saneado, relatorio)`.

    `estrito=True` levanta AssertionError em vez de sanear — para teste e para quem quiser
    que a geração falhe alto.
    """
    rel = auditar(texto, db=db)
    if rel["indice_ausente"]:
        logging.warning("gate_citacoes: índice do TCU ausente — citações de %s NÃO foram "
                        "conferidas (rode `python -m compliance_agent.knowledge."
                        "tcu_juris_index indexar`)", contexto)
        return texto, rel

    if estrito and not rel["limpo"]:
        ruins = [c["citacao"] for c in rel["impossiveis"] + rel["colegiado_errado"]]
        raise AssertionError(f"{contexto} contém citação defeituosa: {ruins}")

    saneado = texto or ""

    # 1) o que não pode existir sai do texto
    for c in rel["impossiveis"]:
        saneado = saneado.replace(c["citacao"], _MARCA_REMOVIDA)
        logging.warning("gate_citacoes: removida citação inexistente em %s: %s (teto do %s em "
                        "%s é %s)", contexto, c["citacao"],
                        c.get("colegiado_citado") or "colegiado", c["ano"], c.get("teto_do_ano"))

    # 2) colegiado errado a gente conserta — o acervo diz qual é o certo
    for c in rel["colegiado_errado"]:
        reais = c.get("colegiado_real") or []
        if len(reais) != 1:
            continue
        corrigida = _COLEGIADO_NO_TEXTO.sub(f"-{reais[0]}", c["citacao"], count=1)
        saneado = saneado.replace(c["citacao"], corrigida)
        logging.warning("gate_citacoes: colegiado corrigido em %s: %s → %s",
                        contexto, c["citacao"], corrigida)

    return saneado, rel


def nota_de_auditoria(rel: dict) -> str:
    """Rodapé para o entregável. Silencioso quando não há o que declarar.

    A nota é PARA O LEITOR DA PEÇA: ele precisa saber que as citações foram conferidas contra o
    acervo oficial, e quais ficaram pendentes de conferência na fonte.
    """
    if rel.get("indice_ausente"):
        return ("\n\n_Nota: as citações jurisprudenciais deste documento **não** foram conferidas "
                "contra o acervo oficial do TCU (índice indisponível no momento da emissão)._")
    if not rel.get("total"):
        return ""
    linhas = [
        "", "",
        f"_Nota de conferência: {rel['total']} citação(ões) verificada(s) contra a Jurisprudência "
        f"Selecionada do TCU (dados abertos oficiais); {len(rel['confirmadas'])} confirmada(s)._",
    ]
    if rel["impossiveis"]:
        linhas.append(
            f"_{len(rel['impossiveis'])} citação(ões) foram **suprimidas** por não existirem no "
            f"acervo do tribunal._")
    if rel["colegiado_errado"]:
        linhas.append(f"_{len(rel['colegiado_errado'])} tiveram o colegiado corrigido._")
    if rel["nao_confirmadas"]:
        nums = ", ".join(c["citacao"] for c in rel["nao_confirmadas"][:6])
        linhas.append(
            f"_{len(rel['nao_confirmadas'])} não constam do recorte selecionado e devem ser "
            f"conferidas na fonte antes de uso em peça formal — o que **não** significa que "
            f"inexistam: {nums}._")
    return "\n".join(linhas)


def sanear_parecer(texto: str, db: str | Path | None = None,
                   contexto: str = "parecer") -> str:
    """Atalho de uso: saneia e já anexa a nota de conferência ao pé do documento."""
    saneado, rel = aplicar(texto, db=db, contexto=contexto)
    return saneado + nota_de_auditoria(rel)


def sanear_canal(texto: str, db: str | Path | None = None,
                 contexto: str = "canal") -> str:
    """Saneia para canal conversacional (Telegram, CLI) — nota de UMA linha, e só se mudou algo.

    O `sanear_parecer` anexa a nota completa de conferência, que é o certo numa peça e é ruído
    numa resposta de chat. Aqui a citação impossível é suprimida do mesmo jeito — o dano de
    afirmar um acórdão que não existe é igual nos dois canais —, mas o rodapé só aparece quando
    houve supressão ou correção, e cabe numa linha.

    Nunca levanta: uma dúvida de citação não pode derrubar a resposta ao usuário. O gate
    protege contra afirmar o inexistente, não contra responder.
    """
    try:
        saneado, rel = aplicar(texto, db=db, contexto=contexto, estrito=False)
    except Exception as e:  # noqa: BLE001 — canal não pode cair por causa do gate
        logger.warning("gate de citações não rodou em %s (%s)", contexto, str(e)[:90])
        return texto

    # Índice ausente: NÃO dá para suprimir (o teto por colegiado e ano vem dele, e inventar
    # teto seria trocar um erro por outro) — mas calar faz a citação chegar ao destinatário
    # idêntica a uma que passou pela conferência. O `logging.warning` que já existia ninguém
    # lê no chat. INDISPONÍVEL ≠ OK, dentro do próprio gate que existe para barrar citação
    # fabricada. Texto sem citação nenhuma não ganha aviso: aí seria ruído puro.
    if rel.get("indice_ausente") and rel.get("total"):
        return (texto or "") + ("\n\n_⚖️ Citações NÃO conferidas: índice de jurisprudência "
                                "indisponível nesta máquina._")

    # As chaves são as de `aplicar()`: impossiveis (suprimidas), colegiado_errado (corrigidas)
    # e nao_confirmadas (mantidas, mas declaradas). Ler o contrato em vez de supor os nomes.
    n_sup = len(rel.get("impossiveis") or [])
    n_cor = len(rel.get("colegiado_errado") or [])
    n_dub = len(rel.get("nao_confirmadas") or [])
    if not (n_sup or n_cor or n_dub):
        return saneado
    partes = []
    if n_sup:
        partes.append(f"{n_sup} suprimida(s) por numeração impossível")
    if n_cor:
        partes.append(f"{n_cor} com colegiado corrigido")
    if n_dub:
        partes.append(f"{n_dub} não confirmada(s) no índice")
    return saneado + f"\n\n_⚖️ Conferência de citações: {'; '.join(partes)}._"
