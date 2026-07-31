# -*- coding: utf-8 -*-
"""LIMITES DE FONTE — o que a fonte NÃO tem, e o que já foi tentado e não vai funcionar.

POR QUE ESTE MÓDULO EXISTE. Este conhecimento — caríssimo, comprado com sessões inteiras de tentativa
— morava só em PROSA de handoff (`docs/HANDOFF-2026-07-29.md §4.2`, `§4.3`, os "não repetir" das
retomadas). Quem não leu o handoff certo retenta pelo mesmo caminho e queima o dia de novo. Pior:
quando uma fonte falha calada, o relatório recebe `[]` e escreve "nada encontrado" — que é uma
afirmação FALSA por omissão, e é o oposto do que um laudo deve fazer.

Aqui o limite vira DADO consultável: pelo painel (`/api/fontes/limites`), pelo gerador de peça (para
emitir LACUNA nomeada em vez de silêncio) e por quem for programar a próxima coleta.

REGRA DE OURO desta casa, que este arquivo materializa: **INDISPONÍVEL ≠ 0**. "Não existe ata de
sessão para este certame" e "o PNCP não publica ata de sessão" são frases diferentes, e só a segunda
é verdadeira.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LimiteDeFonte:
    fonte: str
    tipo: str            # "bloqueio" (dá para contornar um dia) | "limite_de_dado" (a fonte não tem)
    o_que_acontece: str
    caminho_alternativo: str
    medido_em: str


# Ordem: os que mais enganam primeiro (falham com aparência de sucesso).
LIMITES: tuple[LimiteDeFonte, ...] = (
    LimiteDeFonte(
        fonte="LexML (lexml.gov.br)",
        tipo="bloqueio",
        o_que_acontece=(
            "HTTP **200** com corpo HTML de 'Verificação de segurança — Senado Federal'. Não é 403 "
            "nem 503: `raise_for_status()` não protege e o `except` devolvia lista vazia, que chegava "
            "ao parecer como 'nenhuma jurisprudência encontrada'. Reconfirmado em 2026-07-30."),
        caminho_alternativo=(
            "Base curada (`knowledge/jurisprudencia.py`) + índice de existência do TCU "
            "(`tools/tcu_indice_existencia`). `collectors.lexml_fetcher.status_lexml()` agora diz se a "
            "consulta ACONTECEU — use para emitir LACUNA."),
        medido_em="2026-07-30",
    ),
    LimiteDeFonte(
        fonte="TCU — acórdãos (contas.tcu.gov.br)",
        tipo="bloqueio",
        o_que_acontece=(
            "HTTP **200** com corpo HTML 'Requisição rejeitada' (WAF). Mesma armadilha do LexML: "
            "sucesso aparente, conteúdo de erro."),
        caminho_alternativo="`tools/tcu_indice_existencia` — já resolvido, 521.090 acórdãos indexados.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="Folha do Estado (GESPERJ / rj.gov.br/remuneracao)",
        tipo="limite_de_dado",
        o_que_acontece=(
            "A API declara **909.916 registros** na competência, mas **congela a paginação na "
            "página 10.000**: dali em diante devolve HTTP 200 com a MESMA fatia de 50, para sempre. "
            "Alcance real = 10.000 × 50 = **500.000 (55%)**. `size` não contorna (>50 → HTTP 400) e "
            "não há filtro de partição: `orgao`, `orgaoId` e `vinculo` são IGNORADOS (o total não "
            "muda) e `nome` exige o nome completo exato. **45% da folha estadual é inalcançável** "
            "por esta porta — e o pior é que a falha se disfarça de sucesso."),
        caminho_alternativo=(
            "Nenhum pela API atual. Caminhos a testar: pedido LAI à SEPLAG pelo dump completo, ou "
            "outra porta do portal que aceite recorte por órgão."),
        medido_em="2026-07-31",
    ),
    LimiteDeFonte(
        fonte="Folha do TJRJ (Anexo VIII CNJ) e Câmara Municipal do Rio",
        tipo="limite_de_dado",
        o_que_acontece=(
            "**Nenhuma das duas publica CPF** — nem mascarado. Medido: 21.767 linhas do TJRJ e "
            "2.286 da Câmara, 100% sem CPF. Cruzar por NOME contra os 78.071 nomes com CPF "
            "conhecidos recupera só **3,2% (764 de 24.053)**; 96,6% não têm correspondência alguma "
            "e 0,2% são homônimos ambíguos. Servidor de tribunal e de câmara em geral não é "
            "favorecido de OB, então o corpus simplesmente não os contém."),
        caminho_alternativo=(
            "Cruzamento por NOME com o contrato honesto de `pcrj/cruzamento` "
            "(`indicio_nome_unico` × `homonimo_ambiguo`) — nunca CPF presumido."),
        medido_em="2026-07-31",
    ),
    LimiteDeFonte(
        fonte="Câmara Municipal do Rio — competência",
        tipo="limite_de_dado",
        o_que_acontece=(
            "O endpoint é uma RELAÇÃO DE SERVIDORES por `ANOINGRESSO`, não uma folha mensal: a "
            "coluna `competencia` recebe um ANO de 4 dígitos ('1978'..'2026') onde as outras fontes "
            "gravam AAAA-MM. Misturar os dois formatos na mesma coluna quebra `MAX()` e qualquer "
            "ordenação — hoje só não quebra por sorte (uma string de 7 chars vence uma de 4)."),
        caminho_alternativo="Não há folha mensal publicada pela Câmara; é outra natureza de dado.",
        medido_em="2026-07-31",
    ),
    LimiteDeFonte(
        fonte="PNCP — ata de sessão",
        tipo="limite_de_dado",
        o_que_acontece=(
            "**Não existe o tipo 'Ata de Sessão' na taxonomia do PNCP.** Ata aparece em ~8,7% dos "
            "certames e, quando aparece, em geral é MINUTA. Não é falha de coletor: é a fonte."),
        caminho_alternativo="Autos do SEI (a ata está no processo), quando o processo é capturável.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="PNCP — propostas dos perdedores",
        tipo="limite_de_dado",
        o_que_acontece=(
            "O PNCP expõe o **VENCEDOR**. Sem a lista de propostas com valor e classificação não há "
            "screen de cobertura (J2) nem comparação de planilha (J9) — e isso é ausência de DADO, "
            "não ausência de conluio."),
        caminho_alternativo="Autos do SEI: as propostas estão anexadas ao processo.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="PNCP — preço por licitante",
        tipo="limite_de_dado",
        o_que_acontece="A fonte traz o valor do CERTAME, não o lance de cada licitante (inviabiliza E.1).",
        caminho_alternativo="Ata/planilha nos autos.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="TCE-RJ — jurisprudência",
        tipo="limite_de_dado",
        o_que_acontece=(
            "A API de dados abertos do TCE-RJ **não tem endpoint de jurisprudência** (tem contratos, "
            "compras diretas e penalidades). O portal de jurisprudência é Angular."),
        caminho_alternativo="Scraping por Chrome CDP, quando valer o custo. A API aberta segue ótima p/ contratos.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="SINAPI (dados.gov.br)",
        tipo="bloqueio",
        o_que_acontece="HTTP 401 — exige credencial.",
        caminho_alternativo="Tabela de referência local, quando houver.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="EMOP",
        tipo="bloqueio",
        o_que_acontece="Redireciona; exige sessão. `GET` simples não resolve.",
        caminho_alternativo="Scraping com sessão, se e quando compensar.",
        medido_em="2026-07-29",
    ),
    LimiteDeFonte(
        fonte="DataJud/CNJ",
        tipo="limite_de_dado",
        o_que_acontece=(
            "Responde 200 sem WAF, mas os documentos trazem **só metadados** (número, classe, assunto, "
            "órgão julgador, movimentos). **Não há nome de parte, CPF/CNPJ nem teor de decisão** "
            "(Portaria CNJ 160/2020). Logo NÃO serve para 'achar processo do fornecedor X pelo CNPJ' — "
            "essa promessa aparece em doc de terceiro e é falsa."),
        caminho_alternativo=(
            "Usar quando o NÚMERO CNJ já é conhecido (veio do SEI, do TCE ou do D.O.), e para medir "
            "judicialização por órgão/classe."),
        medido_em="2026-07-27",
    ),
    LimiteDeFonte(
        fonte="Querido Diário",
        tipo="bloqueio",
        o_que_acontece="Morreu em silêncio; a assinatura é HTTP 200 com `content-type: text/html`.",
        caminho_alternativo="D.O. do RJ pelo coletor próprio (`collectors/doerj.py`).",
        medido_em="2026-07-17",
    ),
)


def limites(fonte: str = "") -> list[dict]:
    """Todos os limites, ou os de uma fonte (casamento por substring, sem diferenciar maiúscula)."""
    f = (fonte or "").strip().lower()
    return [asdict(x) for x in LIMITES if not f or f in x.fonte.lower()]


def explica_vazio(fonte: str) -> str:
    """Frase pronta para o relatório quando a consulta volta vazia.

    É o antídoto do 'nada encontrado': devolve a razão conhecida, para a peça dizer LACUNA e não
    afirmar ausência. Fonte sem limite catalogado devolve string vazia — e aí vazio é vazio mesmo.
    """
    for x in LIMITES:
        if x.fonte.lower().startswith(fonte.strip().lower()[:12]):
            return (f"LACUNA — {x.fonte}: {x.o_que_acontece} "
                    f"Caminho alternativo: {x.caminho_alternativo} (medido em {x.medido_em}).")
    return ""
