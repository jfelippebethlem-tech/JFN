# -*- coding: utf-8 -*-
"""Índice doutrinário — as teses que o motor precisa citar, com a procedência de cada uma.

POR QUE UM ÍNDICE SEPARADO. `jurisprudencia.py` guarda súmulas e acórdãos; `base_legal.py` guarda
dispositivos. Falta o meio de campo: a TESE — a proposição jurídica que liga o dispositivo ao
caso e que aparece na fundamentação de qualquer peça séria. Sem ela, o texto ou repete o artigo
(e não argumenta) ou argumenta de memória do modelo (e inventa).

A DISCIPLINA É A MESMA DA CASA, e é o que torna este índice utilizável: verbete sem fonte
primária conferida carrega `verificado=False` e a marca `verificar_antes_de_citar`. A auditoria de
2026-07-27 achou quatro acórdãos aritmeticamente impossíveis dentro da base curada da própria
casa; um índice doutrinário sem essa trava repetiria o erro num terreno onde ele é ainda mais
difícil de detectar, porque tese soa plausível por construção.

O QUE ENTRA AQUI. Só tese com efeito OPERACIONAL — que muda o que o código faz ou o que a peça
pede. Doutrina interessante e inconsequente fica de fora: índice que cresce sem critério vira
enciclopédia que ninguém consulta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verbete:
    id: str
    tese: str
    fonte: str
    tipo: str                 # "lei" | "jurisprudencia" | "orientacao" | "doutrina"
    verificado: bool          # conferido em fonte primária?
    onde_confere: str = ""    # URL ou base onde foi conferido
    efeito: str = ""          # o que MUDA no motor por causa desta tese
    dispositivos: tuple[str, ...] = ()


VERBETES: dict[str, Verbete] = {
    # ── improbidade pós-Lei 14.230/2021 ───────────────────────────────────────────────────────
    "dolo_especifico": Verbete(
        "dolo_especifico",
        "Improbidade exige DOLO ESPECÍFICO: 'a vontade livre e consciente de alcançar o resultado "
        "ilícito tipificado nos arts. 9º, 10 e 11 desta Lei, não bastando a voluntariedade do "
        "agente'. A modalidade culposa foi extinta.",
        "Lei 8.429/1992, art. 1º §§1º e 2º (redação da Lei 14.230/2021)",
        "lei", verificado=True,
        onde_confere="planalto.gov.br/ccivil_03/leis/l8429.htm (conferido em 2026-07-29)",
        efeito="nenhum achado meramente formal pode ser rotulado como improbidade",
        dispositivos=("Lei 8.429/1992 art. 1º §2º",)),
    "mero_exercicio_da_funcao": Verbete(
        "mero_exercicio_da_funcao",
        "'O mero exercício da função ou desempenho de competências públicas, sem comprovação de "
        "ato doloso com fim ilícito, afasta a responsabilidade por ato de improbidade.'",
        "Lei 8.429/1992, art. 1º §3º (incluído pela Lei 14.230/2021)",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="ordenador de despesa não responde por assinar; responde por finalidade ilícita",
        dispositivos=("Lei 8.429/1992 art. 1º §3º",)),
    "dano_efetivo": Verbete(
        "dano_efetivo",
        "A lesão ao erário exige perda patrimonial 'efetiva e comprovadamente' demonstrada; o "
        "inciso VIII (frustrar licitude ou dispensar indevidamente) só configura improbidade "
        "'acarretando perda patrimonial efetiva'.",
        "Lei 8.429/1992, art. 10, caput e VIII (redação da Lei 14.230/2021)",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="fracionamento sem sobrepreço provado não fecha o art. 10",
        dispositivos=("Lei 8.429/1992 art. 10 VIII",)),
    "finalidade_de_beneficio": Verbete(
        "finalidade_de_beneficio",
        "Frustrar o caráter concorrencial só é improbidade quando feito 'em ofensa à "
        "imparcialidade' e 'com vistas à obtenção de benefício próprio, direto ou indireto, ou de "
        "terceiros'.",
        "Lei 8.429/1992, art. 11, V (redação da Lei 14.230/2021)",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="cláusula restritiva sem beneficiário identificado não é improbidade",
        dispositivos=("Lei 8.429/1992 art. 11 V",)),
    "elementos_nao_presumidos": Verbete(
        "elementos_nao_presumidos",
        "A sentença deve 'indicar de modo preciso os fundamentos que demonstram os elementos a "
        "que se referem os arts. 9º, 10 e 11 desta Lei, que não podem ser presumidos'.",
        "Lei 8.429/1992, art. 17-C, I (incluído pela Lei 14.230/2021)",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="standard probatório de improbidade é 'clara e convincente'; grau C não alcança",
        dispositivos=("Lei 8.429/1992 art. 17-C I",)),
    "consequencialismo_na_improbidade": Verbete(
        "consequencialismo_na_improbidade",
        "A sentença deve 'considerar as consequências práticas da decisão' e 'os obstáculos e as "
        "dificuldades reais do gestor e as exigências das políticas públicas a seu cargo' — a "
        "LINDB trazida para dentro da lei de improbidade.",
        "Lei 8.429/1992, art. 17-C, II e III; LINDB arts. 20 a 22",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="seção obrigatória de consequências e de obstáculos do gestor no entregável",
        dispositivos=("Lei 8.429/1992 art. 17-C II e III", "LINDB arts. 20-22")),

    # ── alteração contratual ──────────────────────────────────────────────────────────────────
    "art124_incisos_opostos": Verbete(
        "art124_incisos_opostos",
        "O art. 124 lista TODAS as hipóteses de alteração, e os incisos vão para lados opostos do "
        "teto: o I, 'b' é 'modificação do valor contratual em decorrência de acréscimo ou "
        "diminuição quantitativa de seu objeto, nos limites permitidos por esta Lei' (sujeito ao "
        "art. 125); o II, 'd' é 'restabelecer o equilíbrio econômico-financeiro inicial' "
        "(recomposição, fora do teto).",
        "Lei 14.133/2021, art. 124, I 'b' e II 'd'",
        "lei", verificado=True,
        onde_confere="planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm (2026-07-29)",
        efeito="classificação de natureza do aditivo em limites_aditivo",
        dispositivos=("Lei 14.133/2021 art. 124", "Lei 14.133/2021 art. 125")),
    "recomposicao_tributaria": Verbete(
        "recomposicao_tributaria",
        "Os preços contratados são alterados se, após a apresentação da proposta, houver criação, "
        "alteração ou extinção de tributos ou encargos legais com comprovada repercussão sobre "
        "eles — é recomposição, não acréscimo.",
        "Lei 14.133/2021, art. 134",
        "lei", verificado=True,
        onde_confere="planalto.gov.br (conferido em 2026-07-29)",
        efeito="fundamento no art. 134 classifica o termo como recomposição",
        dispositivos=("Lei 14.133/2021 art. 134",)),
    "bdi_iss_municipal": Verbete(
        "bdi_iss_municipal",
        "Na composição do BDI, deve-se utilizar o percentual de ISS compatível com a legislação "
        "tributária do município onde os serviços serão prestados, observada a forma de definição "
        "da base de cálculo prevista na legislação municipal.",
        "TCU, Acórdão 2.622/2013-Plenário",
        "jurisprudencia", verificado=True,
        onde_confere="data/tcu_juris.db — status 'confirmado' (2026-07-29)",
        efeito="teste de BDI na análise de obra; corrigiu a citação errada '2.622/2015'",
        dispositivos=("Lei 14.133/2021 art. 23",)),

    # ── verbetes ainda NÃO conferidos em fonte primária ────────────────────────────────────────
    # Entram porque orientam o motor, e entram MARCADOS: quem for citá-los numa peça precisa
    # conferir antes. Índice que mistura conferido com lembrado é pior que índice pequeno.
    "jogo_planilha_independe_de_dolo": Verbete(
        "jogo_planilha_independe_de_dolo",
        "A caracterização do jogo de planilha independe da demonstração de dolo das partes — o "
        "que sustenta representação e ressarcimento sem vencer a barreira do dolo específico.",
        "TCU (entendimento reiterado; número do acórdão a conferir)",
        "jurisprudencia", verificado=False,
        onde_confere="",
        efeito="X5 e a tipicidade do jogo de planilha; VERIFICAR ANTES DE CITAR EM PEÇA",
        dispositivos=("Lei 14.133/2021 art. 125",)),
    "prorrogacao_dentro_da_vigencia": Verbete(
        "prorrogacao_dentro_da_vigencia",
        "A prorrogação deve ser celebrada dentro da vigência: contrato extinto pela fluência do "
        "prazo não se prorroga, por inexistir objeto a ser aditado.",
        "Orientação Normativa AGU nº 3/2009 (a conferir na fonte)",
        "orientacao", verificado=False,
        onde_confere="",
        efeito="detector X8 (aditivo retroativo); VERIFICAR ANTES DE CITAR EM PEÇA",
        dispositivos=("Lei 14.133/2021 art. 107",)),
    "standard_ressarcimento": Verbete(
        "standard_ressarcimento",
        "Ao ressarcimento ao erário, de natureza indenizatória, aplica-se a preponderância de "
        "provas; à sanção por improbidade, a prova clara e convincente.",
        "doutrina de standards probatórios em improbidade (a conferir na obra)",
        "doutrina", verificado=False,
        onde_confere="",
        efeito="knowledge/standard_prova; VERIFICAR ANTES DE CITAR EM PEÇA",
        dispositivos=("Lei 8.429/1992 art. 17-C I",)),
}

MARCA_NAO_VERIFICADO = "[verificar antes de citar]"


def obter(vid: str) -> Verbete | None:
    return VERBETES.get(str(vid or "").strip())


def citar(vid: str) -> str:
    """Texto pronto para a fundamentação. Verbete não conferido sai MARCADO, sempre."""
    v = obter(vid)
    if v is None:
        return ""
    marca = "" if v.verificado else f" {MARCA_NAO_VERIFICADO}"
    return f"{v.tese} ({v.fonte}){marca}"


def por_dispositivo(dispositivo: str) -> list[Verbete]:
    alvo = str(dispositivo or "").strip().lower()
    return [v for v in VERBETES.values()
            if any(alvo in d.lower() for d in v.dispositivos)] if alvo else []


def nao_verificados() -> list[str]:
    """Os verbetes que exigem conferência — a lista que nunca deve ficar escondida."""
    return sorted(v.id for v in VERBETES.values() if not v.verificado)


def resumo() -> dict[str, Any]:
    total = len(VERBETES)
    verificados = sum(1 for v in VERBETES.values() if v.verificado)
    por_tipo: dict[str, int] = {}
    for v in VERBETES.values():
        por_tipo[v.tipo] = por_tipo.get(v.tipo, 0) + 1
    return {"total": total, "verificados": verificados,
            "nao_verificados": total - verificados,
            "por_tipo": por_tipo, "pendentes": nao_verificados()}


def validar() -> list[str]:
    """Todo verbete diz o que MUDA no motor, e o conferido diz ONDE foi conferido."""
    erros = []
    for vid, v in VERBETES.items():
        if vid != v.id:
            erros.append(f"{vid}: id divergente ({v.id})")
        if not v.efeito:
            erros.append(f"{vid}: sem efeito operacional declarado — não deveria estar no índice")
        if v.verificado and not v.onde_confere:
            erros.append(f"{vid}: marcado como verificado sem dizer onde")
        if not v.verificado and "VERIFICAR" not in v.efeito.upper():
            erros.append(f"{vid}: não verificado sem o aviso no efeito")
    return erros
