# -*- coding: utf-8 -*-
"""moldura_juridica — o direito administrativo brasileiro dentro do prompt.

POR QUE ESTE MÓDULO EXISTE. A casa tem uma base jurídica boa e ela não chegava à IA. O
`catalogo_vicios` (42 vícios com dispositivos da Lei 14.133/2021 e súmulas do TCU) é usado
pelos detectores em CÓDIGO; nenhum modelo jamais o viu. O resultado era um modelo genérico
opinando sobre licitação brasileira com o que quer que tenha aprendido na internet — e
modelo grátis, sem moldura, erra o dispositivo, cita súmula que não existe e confunde a
Lei 8.666/1993 com a 14.133/2021 como se estivessem ambas em vigor para contratos novos.

O QUE A MOLDURA FAZ, e o que deliberadamente NÃO faz:

  · **Dá o vocabulário fechado.** O modelo escolhe entre vícios que existem no catálogo, com o
    id que o resto do sistema entende. Vício fora da lista é declarado como "não catalogado" e
    vira candidato a revisão humana — não vira achado.
  · **Dá o dispositivo certo.** Cada vício carrega o artigo e a súmula que o sustentam, então o
    modelo cita o que está no catálogo em vez de inventar. Citação inventada é o dano mais caro
    que existe aqui: já encontramos quatro acórdãos impossíveis por aritmética na base curada.
  · **NÃO substitui o gate de citações.** Tudo que sai continua passando por
    `reporting/gate_citacoes`, porque moldura reduz alucinação, não a elimina.
  · **NÃO carrega limiar numérico.** Spec §1.3: número fica no código, nunca no prompt. A
    moldura diz *que* o teto de dispensa é por exercício e de onde ele vem; não diz o valor.

A moldura é montada por FASE (planejamento, seleção, execução) para não gastar contexto com o
que não se aplica ao documento em leitura.
"""
from __future__ import annotations

from compliance_agent.knowledge.catalogo_vicios import CATALOGO

# Vale para qualquer leitura de peça: é o enquadramento que o modelo precisa ter antes de opinar.
_FUNDAMENTO = """MOLDURA JURÍDICA (Brasil — controle externo estadual, Rio de Janeiro)

Regime: Lei 14.133/2021 (Licitações e Contratos), que substituiu a Lei 8.666/1993. Contratos
firmados sob a lei antiga seguem regidos por ela até o encerramento — verifique a data antes de
invocar dispositivo. Complementam: LC 101/2000 (Responsabilidade Fiscal), Lei 12.527/2011
(Acesso à Informação), Lei 8.429/1992 (Improbidade), Lei 12.846/2013 (Anticorrupção) e a
Constituição, art. 37 (legalidade, impessoalidade, moralidade, publicidade, eficiência) e
art. 37, XXI (regra da licitação).

Competência: o Tribunal de Contas do Estado do Rio de Janeiro (TCE-RJ) fiscaliza a
administração estadual e municipal do Estado. A jurisprudência do TCU é referência persuasiva,
não vinculante para o TCE-RJ — cite-a como orientação, nunca como norma obrigatória.

DEVERES DE QUEM ANALISA:
1. Presunção de legitimidade dos atos administrativos. Você aponta INDÍCIO, nunca conclui por
   irregularidade, e jamais imputa dolo, fraude ou improbidade.
2. Ausência de informação é LACUNA declarada, nunca zero e nunca ausência de problema.
3. Nunca invente número, nome, data ou citação. Sem o dado no documento, escreva "não consta".
4. Empenho ≠ liquidação ≠ pagamento. Só a Ordem Bancária comprova pagamento; nunca chame
   empenho de "valor pago".
5. Limites de valor (teto de dispensa, por exemplo) variam POR EXERCÍCIO e são atualizados por
   decreto. Não afirme o valor de memória: diga que o limite é o do exercício e deixe a
   conferência para o sistema.
6. Sempre cite a origem do fato: o documento de onde ele veio."""


def _linha_vicio(v) -> str:
    disp = "; ".join(v.dispositivos) if v.dispositivos else "—"
    sum_ = "; ".join(v.sumulas) if v.sumulas else ""
    extra = f" · {sum_}" if sum_ else ""
    return f"- `{v.id}` — {v.nome}. {v.descricao} [{disp}{extra}]"


def catalogo_para_prompt(fase: str | None = None, *, max_chars: int = 9000) -> str:
    """Lista de vícios com o fundamento legal de cada um, opcionalmente filtrada por fase."""
    vicios = [v for v in CATALOGO if not fase or v.fase == fase]
    if not vicios:
        vicios = list(CATALOGO)
    cabeca = (f"VÍCIOS CATALOGADOS{' — fase ' + fase if fase else ''} "
              f"({len(vicios)}). Use EXATAMENTE estes identificadores. Se o que você observar "
              "não estiver na lista, escreva `nao_catalogado` e descreva o fato — não force o "
              "caso dentro de um rótulo que não serve.")
    linhas, total = [cabeca], len(cabeca)
    for v in vicios:
        linha = _linha_vicio(v)
        if total + len(linha) > max_chars:
            linhas.append(f"- (+{len(vicios) - len(linhas) + 1} vícios omitidos por espaço)")
            break
        linhas.append(linha)
        total += len(linha)
    return "\n".join(linhas)


def moldura(fase: str | None = None, *, com_catalogo: bool = True,
            max_chars: int = 12_000) -> str:
    """Bloco pronto para entrar como `system` de qualquer análise de peça processual."""
    partes = [_FUNDAMENTO]
    if com_catalogo:
        partes.append(catalogo_para_prompt(fase, max_chars=max(2000, max_chars - len(_FUNDAMENTO))))
    return "\n\n".join(partes)


def fases_disponiveis() -> list[str]:
    return sorted({v.fase for v in CATALOGO if v.fase})
