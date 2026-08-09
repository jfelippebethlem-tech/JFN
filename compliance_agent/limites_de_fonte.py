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
        fonte="SIAFE-Rio 2 — tela de OB Orçamentária (a NOSSA fonte canônica de pagamento)",
        tipo="bloqueio",
        o_que_acontece=(
            "A consulta devolve no máximo **1.000 registros**. Uma varredura feita só com "
            "`--por-ug` numa UG grande para exatamente nesse número, sem erro e sem aviso: a "
            "tabela fica truncada e toda soma por UG mente para baixo. Medido em 2026-08-04, "
            "**23 pares (UG, ano) de 642** estavam parados em 1.000 — R$ 8,46 bi no SIAFE contra "
            "R$ 19,26 bi no espelho TFE nesses mesmos pares (137.654 OBs a menos). Apareceu ao "
            "perseguir um fornecedor da UG 294200 (Fundação Saúde) que o espelho mostrava com "
            "5,5× mais pagamento que a fonte canônica."),
        caminho_alternativo=(
            "`siafe_ob_orcamentaria` já fura o teto por três caminhos: `chkRemoveLimit` (checkbox "
            "da tela), `--por-numero` (prefixo do Número, com subdivisão) e `--por-ug X "
            "--ug-grande` (UG + prefixo). Quem está truncado, e o comando de cada um, sai em "
            "`reporting.cobertura_siafe.medir()` e em `/api/siafe/truncamento`. Rodar só na "
            "máquina autorizada (`host_siafe.exigir_autorizacao`), uma sessão por IP."),
        medido_em="2026-08-04",
    ),
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
            "A API **congela a paginação na página 10.000**: dali em diante devolve HTTP 200 com a "
            "MESMA fatia de 50, para sempre. Numa varredura global isso limita a 500.000 dos "
            "909.916 registros da competência (55%) — e a falha se disfarça de sucesso. "
            "**CONTORNADO EM PARTE em 01/08/2026**: o teto era do PARÂMETRO, não da fonte. "
            "`orgao`, `orgaoId`, `vinculo`, `funcaoCargo`, `cargo`, `lotacao` e `folhaRef` são "
            "ignorados (o total não muda), mas **`codCargo` filtra** — `codCargo=403` → 17.000 "
            "registros em 340 páginas, abaixo da janela. Somando os 1.136 códigos: **681.876 de "
            "909.916 = 74,9%**. O que sobra **não tem cargo**: são PENSIONISTAS (`funcaoCargo` "
            "nulo, vínculo PENSÃO, RIOPREVIDÊNCIA PENSÕES) e não há balde de cargo nulo "
            "(`codCargo=0` → total 0). Eles só existem na listagem global, onde a janela de 10.000 "
            "páginas volta a valer: medido por amostra, ~42% deles (≈96.750) caberiam numa passada "
            "global complementar; **~131 mil (14,4% do universo) ficam fora dos dois eixos**. "
            "Permanece: `size` ≤ 50 (>50 → HTTP 400) e `nome` só com o nome completo exato."),
        caminho_alternativo=(
            "Implementado para quem TEM cargo: `collectors/folha_estado.py` varre cargo a cargo "
            "com `codCargo` (1.136 códigos de `/remuneracoes/cargos`). Para os pensionistas, falta "
            "uma passada global complementar (páginas 0–9.999, guardando só os sem cargo) — "
            "recupera ~42% deles; o restante exige LAI à SEPLAG/RIOPREVIDÊNCIA."),
        medido_em="2026-08-01",
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
        fonte="TCE-RJ — valor_homologacao dos licitantes",
        tipo="limite_de_dado",
        o_que_acontece=(
            "O campo `valor_homologacao` de `tcerj_licitante` carrega outliers impossíveis: o "
            "máximo é **R$ 990 bilhões**, e uma compra de gaze em Macaé traz R$ 2,21 bi "
            "homologados contra R$ 2,95 mi estimados (750×). Medido em 2026-08-09: **1,10% das "
            "125.060 linhas** com os dois campos passam de 10× o estimado e carregam **87,4% da "
            "soma** (R$ 2,43 tri brutos → R$ 306 bi podados). Somar o campo cru publica número "
            "~8× inflado; calcular desconto com ele dá −75.000%."),
        caminho_alternativo=(
            "Usar `MAX_HOMOLOGADO_SOBRE_ESTIMADO` de `collectors/tcerj_licitantes` — acima do "
            "múltiplo o valor é INDISPONÍVEL, nunca zero nem número impossível. O certame "
            "continua contando; só o valor sai."),
        medido_em="2026-08-09",
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
