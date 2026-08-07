#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quem, entre os agentes públicos que conhecemos, aparece no quadro societário do país.

A PERGUNTA DO DONO, em 2026-08-06: *relações de políticos, comissionados e familiares com empresas,
ONGs e associações — de forma ampla*. O insumo já existia e estava sendo usado ao contrário:
`socios_reverso` é semeado pelos sócios dos NOSSOS FORNECEDORES, ou seja, parte da empresa e chega
à pessoa. Aqui a semente é a PESSOA COM PODER — folha do Estado, ALERJ, comissionados — e a
travessia é dela para todas as sociedades dela no Brasil.

A FONTE É O CADASTRO INTEIRO. `data/receita_dump/socios_full.csv.zst`, 27.650.926 linhas, o QSA de
todo o Brasil, atualizado mensalmente. Não é amostra: `socios_receita` (59.506 linhas) é a fatia
curada dos nossos fornecedores e responderia 0,7% desta pergunta.

O QUE ISTO **NÃO** FAZ, e precisa estar escrito antes do primeiro número:

  · **Não prova identidade.** A folha não traz CPF utilizável e o dump traz o CPF MASCARADO
    (`***NNNNNN**`). O casamento é por NOME NORMALIZADO — indício, nunca prova. Medido nesta base:
    dos nomes de servidor que casam no QSA, **4,7%** casam com MAIS DE UM CPF mascarado distinto,
    isto é, são homônimos comprovados; os outros podem sê-lo sem que a base o mostre. Nome com
    menos de três termos não entra.
  · **Não estabelece parentesco.** Sobrenome compartilhado NÃO é sinal: 16,9% das empresas com dois
    ou mais sócios PF têm sobrenome de família em comum — empresa familiar é a norma no Brasil.
    O eixo de parentesco vive em `osint/parentesco`, com prevalência medida, e só corrobora.
  · **Não afirma irregularidade.** Servidor pode ser sócio; o que a lei restringe é o exercício de
    comércio por certas carreiras, o conflito de interesses e a contratação pelo próprio órgão. O
    achado aqui é *há o que conferir*, e o campo `diligencia` diz o quê.

O QUE ELE PESA. Três marcadores objetivos, todos verificáveis na base, e nenhum deles opinativo:
`comissionado` (cargo em comissão / livre nomeação — quem entra sem concurso), `terceiro_setor` (a
entidade é associação, fundação ou organização religiosa — natureza 3xx, a modalidade do caso das
ONGs) e `recebeu_do_estado` (a entidade tem Ordem Bancária contabilizada no SIAFE — dinheiro que
saiu de fato, nunca empenho).

    python -m tools.agente_publico_reverso            # constrói e resume
    python -m tools.agente_publico_reverso --so-resumo
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ZST = _REPO / "data" / "receita_dump" / "socios_full.csv.zst"
_ESTAB = _REPO / "data" / "receita_estab.db"
_MIN_TERMOS = 3           # "JOSE SILVA" casa com meio estado; três termos é o mínimo defensável

_SQL = """
CREATE TABLE IF NOT EXISTS agente_publico_societario (
    nome_norm       TEXT NOT NULL,
    nome_socio      TEXT NOT NULL,
    doc_socio       TEXT,
    cnpj_basico     TEXT NOT NULL,
    qualif_cod      TEXT,
    origem          TEXT NOT NULL,   -- folha_estado | alerj
    cargo           TEXT,
    vinculo         TEXT,
    orgao           TEXT,
    comissionado    INTEGER NOT NULL DEFAULT 0,
    construido_em   TEXT NOT NULL,
    PRIMARY KEY (nome_norm, cnpj_basico, doc_socio)
)"""
_INDICES = (
    "CREATE INDEX IF NOT EXISTS ix_aps_cnpj ON agente_publico_societario(cnpj_basico)",
    "CREATE INDEX IF NOT EXISTS ix_aps_comis ON agente_publico_societario(comissionado)",
)

# Livre nomeação e exoneração é o que interessa: quem entra sem concurso e sai por vontade de quem
# nomeou. Os rótulos vêm da própria base (`vinculo` e `cargo` de `registros_folha`).
_RX_COMISSAO = re.compile(r"COMISS|LIVRE\s+NOMEA|EM\s+COMISSAO|ASSESSOR|GABINETE|SECRETARI", re.I)


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z ]", " ", s)).strip().upper()


def semente(con: sqlite3.Connection) -> dict[str, dict]:
    """Agentes públicos conhecidos, por nome normalizado. Cargo mais 'forte' vence o empate."""
    alvo: dict[str, dict] = {}
    for nome, cargo, vinc, org in con.execute(
            "SELECT DISTINCT nome, cargo, vinculo, orgao_nome FROM registros_folha"):
        n = norm(nome)
        if len(n.split()) < _MIN_TERMOS:
            continue
        com = bool(_RX_COMISSAO.search(f"{cargo} {vinc}"))
        atual = alvo.get(n)
        if atual is None or (com and not atual["comissionado"]):
            alvo[n] = {"nome": nome, "cargo": cargo, "vinculo": vinc, "orgao": org,
                       "origem": "folha_estado", "comissionado": int(com)}
    for nome, cargo in con.execute("SELECT DISTINCT nome, cargo FROM alerj_folha"):
        n = norm(nome)
        if len(n.split()) < _MIN_TERMOS:
            continue
        # A ALERJ prevalece sobre a folha do Estado: mandato e gabinete são o poder que interessa.
        alvo[n] = {"nome": nome, "cargo": cargo, "vinculo": "ALERJ", "orgao": "ALERJ",
                   "origem": "alerj", "comissionado": 1}
    return alvo


def varrer(alvo: dict[str, dict], zst: Path = _ZST):
    """Uma passada de streaming pelo cadastro nacional. Nada é carregado em memória."""
    if not zst.exists():
        raise SystemExit(f"cadastro nacional ausente: {zst} — rode tools/socios_dump_refresh.sh")
    proc = subprocess.Popen(["zstd", "-dcq", str(zst)], stdout=subprocess.PIPE,
                            preexec_fn=lambda: os.nice(10))
    lidas = 0
    try:
        for bruto in proc.stdout:
            lidas += 1
            p = bruto.decode("utf-8", "replace").rstrip("\n").split(";")
            if len(p) < 5 or p[1].strip('"') != "2":     # só pessoa física
                continue
            nome = p[2].strip('"')
            n = norm(nome)
            meta = alvo.get(n)
            if meta is None:
                continue
            yield n, nome, p[3].strip('"'), p[0].strip('"'), p[4].strip('"'), meta
    finally:
        proc.stdout.close()
        proc.wait()
    varrer.lidas = lidas


def construir(db: str = "") -> dict:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(db or _DB, timeout=120)
    con.execute(_SQL)
    for ix in _INDICES:
        con.execute(ix)
    alvo = semente(con)
    t0 = time.time()
    con.execute("DELETE FROM agente_publico_societario")
    n = 0
    for nome_norm, nome, doc, raiz, qualif, meta in varrer(alvo):
        con.execute(
            "INSERT OR REPLACE INTO agente_publico_societario (nome_norm, nome_socio, doc_socio, "
            "cnpj_basico, qualif_cod, origem, cargo, vinculo, orgao, comissionado, construido_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,date('now'))",
            (nome_norm, nome, doc, raiz, qualif, meta["origem"], meta["cargo"], meta["vinculo"],
             meta["orgao"], meta["comissionado"]))
        n += 1
        if n % 500 == 0:
            con.commit()
    con.commit()
    out = {"agentes_semeados": len(alvo), "linhas_gravadas": n,
           "linhas_lidas": getattr(varrer, "lidas", 0), "segundos": round(time.time() - t0, 1)}
    con.close()
    return out


# AS EXPLICAÇÕES QUE SÃO O DESENHO DO PROGRAMA, NÃO O ACHADO. Medidas em 2026-08-06 sobre os 296
# pares defensáveis: `apoio_a_escola` sozinha responde por **35,1%** deles. Associação de Apoio à
# Escola é a entidade que a própria rede estadual usa para descentralizar recurso à unidade, e o
# dirigente é, por desenho, um professor daquela escola. Idem fundação de apoio universitária
# (Lei 8.958/1994), associação de classe (a Mútua dos Magistrados tem magistrado na direção por
# definição) e cooperativa. Vetar isso não é benevolência: é a diferença entre uma fila de trabalho
# e uma lista que acusa um terço do magistério de improbidade.
_INSTITUCIONAL = {
    "apoio_a_escola": re.compile(r"APOIO\s+[AÀ]\s+ESCOLA|APOIO\s+ESCOLA|CIEP|CAIC", re.I),
    "fundacao_de_apoio_universitaria": re.compile(
        r"FUNDA[CÇ][AÃ]O.*(APOIO|PESQUISA|ENSINO|DESENVOLVIMENTO|UNIVERSIT)", re.I),
    "associacao_de_classe": re.compile(
        r"M[UÚ]TUA|SINDICATO|ASSOCIA[CÇ][AÃ]O\s+DOS?\s+(MAGISTR|SERVIDOR|PROFESSOR|M[EÉ]DICO"
        r"|DELEGADO|OFICIA)", re.I),
    "cooperativa": re.compile(r"COOPERATIVA|UNIMED", re.I),
}


# ENTE PÚBLICO NÃO TEM SÓCIO — TEM DIRIGENTE NOMEADO. O primeiro item da fila renderizada no
# painel era `EMPRESA PUBLICA DE SAUDE DO RIO DE JANEIRO S/A - RIOSAÚDE` com dois Capitães BM no
# "quadro societário": é a diretoria da estatal, indicada pelo governo, exatamente como manda a lei
# das estatais. Servidor na direção de empresa pública é o desenho, não o achado.
#
# O corte é por NATUREZA JURÍDICA, não por nome: `1xxx` (administração pública direta, autarquia,
# fundação), `2011` (empresa pública) e `2038` (sociedade de economia mista). E PARA AÍ: `2054` é
# S/A fechada e pegaria CONDOR S/A INDÚSTRIA QUÍMICA e CABERJ INTEGRAL SAÚDE, que são privadas —
# vetar demais é tão ruim quanto vetar de menos. Medido: 15 dos 538 pares.
def e_estatal(natureza_cod: str) -> bool:
    n = str(natureza_cod or "")
    return n.startswith("1") or n in ("2011", "2038")


def explicacao_institucional(razao_social: str, natureza_cod: str = "") -> str:
    """Nome da explicação inocente conhecida, ou vazio. Vazio NÃO significa que não haja uma."""
    if e_estatal(natureza_cod):
        return "ente_publico_ou_estatal"
    for nome, rx in _INSTITUCIONAL.items():
        if rx.search(str(razao_social or "")):
            return nome
    return ""


# AS QUATRO TORNEIRAS, e por que uma só não bastava. A fila nasceu olhando apenas o SIAFE estadual
# e por isso enxergava 296 pares e 18 comissionados. O caso que motivou o módulo — assessor de
# gabinete no quadro de instituto que recebe EMENDA PARLAMENTAR — não passa por OB estadual: entra
# por emenda federal e por contrato municipal. Medido em 2026-08-06: `pcrj_contratos` acrescenta
# 127 pares novos (27 comissionados) e `emenda_favorecidos` outros 35 (8 comissionados, 18 deles em
# terceiro setor). Fila unificada: **458 pares, 53 comissionados, 186 em terceiro setor**.
#
# TODAS SÃO FASE DE PAGAMENTO, sem exceção: OB `Contabilizado` no SIAFE, `pago` (não `empenhado`)
# na despesa municipal e `fase='Pagamento'` na emenda. Empenho ≠ liquidação ≠ pagamento, e a única
# das quatro que NÃO é pagamento é `pcrj_contratos` — contrato assinado é obrigação, não desembolso,
# e por isso ele entra rotulado como tal, nunca somado a dinheiro.
_TORNEIRAS = (
    # `credor` INTEIRO, não `substr(...,1,8)`: quem reduz à raiz é o normalizador abaixo, e a
    # consulta que já entregava 8 dígitos era descartada por ele em silêncio — a fonte SIAFE
    # inteira sumia da fila sem erro nenhum. Um teste de mesa pegou; a fila não teria acusado.
    ("siafe_ob", "SELECT credor, SUM(valor) FROM ob_orcamentaria_siafe "
                 "WHERE status='Contabilizado' AND length(credor)=14 GROUP BY 1", True),
    ("pcrj_despesa", "SELECT credor_documento, SUM(pago) FROM pcrj_despesa "
                     "WHERE pago > 0 GROUP BY 1", True),
    ("emenda_favorecidos", "SELECT documento_favorecido, SUM(valor) FROM emenda_favorecidos "
                           "WHERE fase='Pagamento' GROUP BY 1", True),
    ("pcrj_contratos", "SELECT fornecedor_documento, SUM(COALESCE(valor_global, valor_inicial)) "
                       "FROM pcrj_contratos GROUP BY 1", False),
)


def dinheiro_publico(con: sqlite3.Connection) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """`({raiz: {fonte: valor}}, {raiz: [fontes]})` — POR FONTE, nunca somado às cegas.

    Somar um total único esconderia que as fontes não são a mesma coisa. `siafe_ob` é Ordem
    Bancária do sistema do Estado; `pcrj_despesa` é o campo `pago` do arquivo de empenhos do portal
    do município (conferido: diverge de `empenhado` em 8.404 das 78.595 linhas e, onde diverge,
    acompanha o liquidado — é pagamento, não cópia do empenho), e cobre só **2019 a 2023**;
    `emenda_favorecidos` traz a OB federal no próprio campo de referência. Quem lê precisa saber
    qual torneira produziu o número antes de citá-lo.
    """
    valor: dict[str, dict] = {}
    de_onde: dict[str, list[str]] = {}
    for nome, sql, e_pagamento in _TORNEIRAS:
        try:
            linhas = con.execute(sql).fetchall()
        except sqlite3.Error:
            continue
        for doc, v in linhas:
            d = re.sub(r"\D", "", str(doc or ""))
            if len(d) != 14:
                continue
            r = d[:8]
            de_onde.setdefault(r, []).append(nome)
            d_r = valor.setdefault(r, {})
            if e_pagamento:
                d_r[nome] = d_r.get(nome, 0.0) + float(v or 0.0)
    return valor, de_onde


# QUEM PAGOU É O PRÓPRIO ÓRGÃO DO AGENTE? É o discriminador que separa o comum do grave. Médico
# servidor sócio de PJ médica que vende ao Estado é frequente e tem explicação banal — 25,9% dos
# pares sem explicação são PJ médica. O que não tem explicação banal é o servidor ser sócio de
# empresa que a SUA PRÓPRIA unidade paga: art. 9º, III da Lei 8.429/1992 e o dever de impedimento
# do art. 20 da Lei 9.784/1999.
#
# Medido em 2026-08-06 sobre os 413 pares sem explicação: **5**. Poucos, e é isso que os torna
# úteis — dois engenheiros da Fundação DER sócios de construtoras que o DER paga, um Major PM sócio
# de casa de saúde paga pelo Fundo Especial da PM, um 3º Sargento PM sócio de oficina paga pela
# SEPM, e uma especialista em educação sócia de entidade paga pela Fundação onde ela serve.
_PARADAS_ORGAO = frozenset({
    "DE", "DO", "DA", "DOS", "DAS", "E", "ESTADO", "SECRETARIA", "MUNICIPAL", "RIO", "JANEIRO",
    "GERAL", "COORDENADORIA", "SUBSECRETARIA", "FUNDACAO", "EMPRESA",
})


def _nucleo_orgao(nome: str) -> frozenset:
    """As palavras que DISTINGUEM o órgão, sem o vocabulário administrativo que todos compartilham.

    Sem tirar `SECRETARIA`, `ESTADO` e `FUNDAÇÃO`, dois órgãos quaisquer casariam por essas
    palavras e o eixo acusaria a folha inteira. Exigir DUAS palavras distintivas em comum é o que
    faz `SECRETARIA DE ESTADO DE POLICIA MILITAR` casar com `Fundo Especial da Polícia Militar` —
    que é, de fato, o fundo da própria corporação — sem casar com qualquer outra secretaria.
    """
    return frozenset(p for p in norm(nome).split()
                     if p not in _PARADAS_ORGAO and len(p) > 3)


def pagadores_por_raiz(con: sqlite3.Connection) -> dict[str, set[str]]:
    """Nome da unidade que pagou cada raiz, nas duas fontes que NOMEIAM o pagador."""
    out: dict[str, set[str]] = {}
    ug_nome = dict(con.execute("SELECT DISTINCT ug_codigo, ug_nome FROM ordens_bancarias "
                               "WHERE ug_nome IS NOT NULL"))
    for raiz, ug in con.execute(
            "SELECT substr(credor,1,8), ug_emitente FROM ob_orcamentaria_siafe "
            "WHERE status='Contabilizado' AND length(credor)=14 GROUP BY 1,2"):
        out.setdefault(raiz, set()).add(ug_nome.get(str(ug or ""), str(ug or "")))
    for doc, org in con.execute(
            "SELECT credor_documento, orgao FROM pcrj_despesa WHERE pago > 0 GROUP BY 1,2"):
        d = re.sub(r"\D", "", str(doc or ""))
        if len(d) == 14:
            out.setdefault(d[:8], set()).add(str(org or ""))
    return out


def conflito_de_orgao(orgao_do_agente: str, pagadores: set[str]) -> str:
    """Nome da unidade pagadora que É o órgão do agente, ou vazio.

    A REGRA DE IDENTIDADE VEM ANTES DA DE SEMELHANÇA, e a falta dela fazia o eixo perder o caso
    mais óbvio de todos: `FUNDAÇÃO SAÚDE DO ESTADO DO RIO DE JANEIRO` comparada COM ELA MESMA não
    casava, porque o núcleo distintivo — depois de tirar FUNDAÇÃO, ESTADO, RIO e JANEIRO — é só
    `{SAUDE}`, uma palavra, e o cotejo por semelhança exige duas. Descoberto ao ligar os processos:
    cinco autos de indenização por serviços médicos correndo NA PRÓPRIA Fundação Saúde, com três
    Diretores-Gerais dela no quadro societário da contratada, e o eixo mudo.

    Nome idêntico é o mesmo órgão, ponto. A exigência de duas palavras continua valendo para os
    nomes DIFERENTES, que é onde ela existe para evitar que duas secretarias quaisquer casem pelo
    vocabulário administrativo comum.
    """
    alvo = norm(orgao_do_agente)
    if not alvo:
        return ""
    ka = _nucleo_orgao(orgao_do_agente)
    for p in pagadores or ():
        if norm(p) == alvo:
            return p
    if not ka:
        return ""
    for p in pagadores or ():
        if len(ka & _nucleo_orgao(p)) >= 2:
            return p
    return ""


def fila(db: str = "", *, so_comissionados: bool = False) -> list[dict]:
    """Pares agente × entidade que recebeu dinheiro público, do maior valor para o menor.

    Três cortes, todos objetivos: a entidade aparece em ao menos uma das quatro torneiras (SIAFE,
    despesa municipal paga, emenda na fase de PAGAMENTO, contrato municipal — este último entra na
    procedência e nunca no valor); o nome do agente tem UM único CPF mascarado no índice (homônimo
    comprovado sai — os que ficam podem ser homônimos sem que a base o mostre); e a explicação
    institucional conhecida vai marcada, nunca escondida. `fontes` diz de onde veio cada par.
    """
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    pago, fontes = dinheiro_publico(con)
    # A RAZÃO SOCIAL VEM DA BASE MAIS LARGA PRIMEIRO. `empresas_min`/`empresas_cadastro` são as
    # tabelas curadas dos nossos fornecedores (141.560 e 36.192 raízes) e reconheciam 3.861
    # entidades de terceiro setor; `receita_estab.empresas` tem 5.859.921 raízes e 158.728 do
    # terceiro setor. Entidade sem razão social não é entidade sem nome — é entidade que a tabela
    # estreita não alcançava, e era assim que um par ficava sem poder ser classificado.
    razao: dict[str, tuple[str, str]] = {}
    for tab in ("empresas_min", "empresas_cadastro"):
        try:
            for r in con.execute(f"SELECT cnpj_basico, razao_social, natureza_cod FROM {tab}"):
                razao[r[0]] = (str(r[1] or ""), str(r[2] or ""))
        except sqlite3.Error:
            continue
    # SEM `except: pass` AQUI. Se a base larga existe, ela tem de ser legível — engolir o erro faria
    # a fila voltar silenciosamente à cobertura estreita e ninguém saberia por quê. Ausência do
    # arquivo é lacuna conhecida e degrada; erro de leitura é defeito e sobe.
    # PERGUNTAR ANTES, EM VEZ DE ENGOLIR DEPOIS. A tentação era `try/except: pass` — e um except
    # mudo aqui faria a fila voltar à cobertura estreita em silêncio, sem que ninguém soubesse por
    # quê. A catraca de dívida muda pegou exatamente isso. `sqlite_master` responde a pergunta certa
    # (a tabela já foi construída?) e qualquer OUTRO erro de leitura sobe, como deve.
    if _ESTAB.exists():
        est = sqlite3.connect(f"file:{_ESTAB}?mode=ro", uri=True)
        try:
            tem = est.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                              ).fetchone()
            if tem:
                for r in est.execute(
                        "SELECT cnpj_basico, razao_social, natureza_cod FROM empresas"):
                    razao[r[0]] = (str(r[1] or ""), str(r[2] or ""))
        finally:
            est.close()
    pagadores = pagadores_por_raiz(con)
    ndocs = dict(con.execute("SELECT nome_norm, COUNT(DISTINCT doc_socio) "
                             "FROM agente_publico_societario GROUP BY 1"))
    linhas = list(con.execute(
        "SELECT nome_norm, nome_socio, cnpj_basico, cargo, orgao, comissionado, origem "
        "FROM agente_publico_societario"))
    con.close()

    quantos = {}
    for x in linhas:
        if x[2] in pago and ndocs.get(x[0]) == 1:
            quantos[x[2]] = quantos.get(x[2], 0) + 1

    out = []
    for nome_norm, nome, raiz, cargo, orgao, com, origem in linhas:
        if raiz not in pago or ndocs.get(nome_norm) != 1:
            continue
        rz, nat = razao.get(raiz, ("", ""))
        out.append({
            "agente": nome, "cargo": cargo, "orgao": orgao, "origem": origem,
            "comissionado": bool(com), "cnpj_basico": raiz,
            "entidade": rz or f"(raiz {raiz} — razão social não capturada)",
            "terceiro_setor": nat.startswith("3"),
            "valor_por_fonte": pago[raiz],
            "valor_recebido": sum(pago[raiz].values()),
            "fontes": sorted(set(fontes.get(raiz, []))),
            "explicacao_institucional": explicacao_institucional(rz, nat),
            "servidores_no_qsa": quantos.get(raiz, 1),
            "orgao_pagador_e_o_proprio": conflito_de_orgao(orgao, pagadores.get(raiz, set())),
            "diligencia": ("confirmar identidade por CPF na ficha funcional e no QSA integral da "
                           "JUCERJA; verificar se a sociedade é anterior ou posterior à posse, e "
                           "se o órgão do agente é o contratante"),
        })
    if so_comissionados:
        out = [x for x in out if x["comissionado"]]
    # A ORDEM É A DA FILA DE TRABALHO, não a do dinheiro. Ordenar só por valor punha a RIOSAÚDE
    # (empresa pública, dirigente nomeado) no topo, à frente de todo par que de fato precisa de
    # diligência — e quem abre a tela lê o primeiro item como o mais grave. Par COM explicação
    # institucional vai para o fim; comissionado vem antes; empate, o maior valor.
    # A ORDEM É A DA GRAVIDADE, e o primeiro critério é o único quase-objetivo: a unidade que pagou
    # é a unidade onde o agente serve. Depois vem o QSA tomado por servidores (o QSA da MEDVIVA é
    # inteiro de servidores: 10 de 10), e só então o cargo comissionado e o valor.
    # `servidores_no_qsa` NÃO entra na ordem: medido, ele ordena por tamanho da empresa (MEDVIVA,
    # 10 de 125 sócios) e não por concentração. Sobram o conflito de órgão, que é quase-objetivo, o
    # cargo comissionado e o valor como desempate.
    return sorted(out, key=lambda x: (bool(x["explicacao_institucional"]),
                                      not x["orgao_pagador_e_o_proprio"],
                                      not x["comissionado"],
                                      -x["valor_recebido"]))


def resumo(db: str = "") -> dict:
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    q = con.execute
    tot = q("SELECT COUNT(DISTINCT nome_norm), COUNT(*) FROM agente_publico_societario").fetchone()
    # HOMÔNIMO COMPROVADO: o mesmo nome com dois CPFs mascarados distintos. Não é estimativa.
    homon = q("SELECT COUNT(*) FROM (SELECT nome_norm FROM agente_publico_societario "
              "GROUP BY nome_norm HAVING COUNT(DISTINCT doc_socio) > 1)").fetchone()[0]
    ter = q("SELECT COUNT(*) FROM agente_publico_societario a JOIN empresas_min e "
            "ON e.cnpj_basico=a.cnpj_basico WHERE substr(e.natureza_cod,1,1)='3'").fetchone()[0]
    din = q("SELECT COUNT(DISTINCT a.nome_norm || a.cnpj_basico) FROM agente_publico_societario a "
            "JOIN ob_orcamentaria_siafe o ON substr(o.credor,1,8)=a.cnpj_basico "
            "WHERE o.status='Contabilizado'").fetchone()[0]
    con.close()
    return {"pessoas": tot[0], "vinculos_societarios": tot[1],
            "nomes_com_mais_de_um_cpf": homon, "entidades_terceiro_setor": ter,
            "pares_pessoa_entidade_que_recebeu_do_estado": din}


_FILA_JSON = _REPO / "data" / "agente_publico_fila.json"


_FILA_MD = _REPO / "data" / "osint_fila_agente.md"
_SQL_VISTO = """
CREATE TABLE IF NOT EXISTS agente_publico_visto (
    chave     TEXT PRIMARY KEY,
    visto_em  TEXT NOT NULL
)"""


def marcar_novidades(itens: list[dict], db: str = "") -> int:
    """Marca `novo=True` no que nunca apareceu antes e devolve quantos são.

    A FILA SE REGENERA TODO DIA E NINGUÉM ERA AVISADO. Um par que surge às 3 da manhã — porque a
    folha ganhou competência nova ou o dump da Receita mudou — ficava indistinguível dos 538 que já
    estavam lá; só apareceria se alguém relesse a lista inteira. É exatamente a pergunta que a
    persistência do grafo foi construída para responder: *o que mudou desde a última vez?*

    A chave é (nome do agente + raiz da entidade), não a posição na lista: reordenar a fila não
    pode inventar novidade.
    """
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(db or _DB, timeout=60)
    con.execute(_SQL_VISTO)
    ja = {r[0] for r in con.execute("SELECT chave FROM agente_publico_visto")}
    hoje = time.strftime("%Y-%m-%d")
    novos = 0
    for x in itens:
        chave = f"{x['agente']}|{x['cnpj_basico']}"
        x["novo"] = chave not in ja
        if x["novo"]:
            novos += 1
            con.execute("INSERT OR REPLACE INTO agente_publico_visto VALUES (?,?)", (chave, hoje))
        # PRIMEIRA RODADA NÃO É NOVIDADE. Com a tabela vazia, os 538 seriam "novos" e o aviso
        # nasceria gritando — o fiscal aprenderia a ignorá-lo na primeira vez que o visse.
    if not ja:
        for x in itens:
            x["novo"] = False
        novos = 0
    con.commit()
    con.close()
    return novos


def escrever_fila_md(itens: list[dict], novos: int, caminho: Path = _FILA_MD) -> str:
    """A fila em markdown, no mesmo idioma de `data/fila_fiscal_360.md` — um arquivo para abrir.

    Ordem já é a da gravidade; aqui só se declara, na cabeça do arquivo, o que o leitor precisa
    saber ANTES do primeiro nome: que isto é indício por casamento de NOME, que servidor pode ser
    sócio, e o que fecha a questão.
    """
    trabalho = [x for x in itens if not x["explicacao_institucional"]]
    conflito = [x for x in trabalho if x["orgao_pagador_e_o_proprio"]]
    linhas = [
        "# Fila OSINT — agente público no quadro societário",
        "",
        f"Gerada em {time.strftime('%Y-%m-%d %H:%M')} · **{len(itens)}** pares · "
        f"**{len(trabalho)}** sem explicação institucional · **{len(conflito)}** com o pagamento "
        f"vindo do PRÓPRIO órgão do agente · **{novos}** novos desde a última rodada.",
        "",
        "> **Indício, nunca prova.** O casamento é por NOME NORMALIZADO: a folha não traz CPF "
        "utilizável e a Receita entrega o CPF do sócio mascarado. Nomes com mais de um CPF no "
        "índice já foram excluídos, mas os que ficam podem ser homônimos sem que a base o mostre. "
        "**Servidor pode ser sócio** — o que se afirma é que há o que conferir: ficha funcional com "
        "CPF, QSA integral na JUCERJA, e se a sociedade antecede ou sucede a posse.",
        "",
    ]
    # NOVIDADE NÃO PODE CAIR NO CORTE. A seção 2 mostra 80 pares; um par novo que caia fora dela
    # ficaria invisível — e um aviso que não avisa é pior que nenhum. Verificado ao vivo: o primeiro
    # novo simulado (ADILSON DE SOUZA DUBOIS) não aparecia em lugar nenhum do arquivo. Todo novo
    # entra AQUI, inteiro, antes de qualquer corte.
    if novos:
        linhas += [f"## 0. NOVOS desde a última rodada ({novos})", "",
                   "| Agente | Cargo | Órgão | Entidade | Situação |", "|---|---|---|---|---|"]
        for x in [y for y in itens if y.get("novo")]:
            sit = (x["orgao_pagador_e_o_proprio"] and "⚠ pago pelo próprio órgão") or \
                  x["explicacao_institucional"] or ("comissionado" if x["comissionado"] else "—")
            linhas.append(f"| {x['agente']} | {x['cargo']} | {x['orgao']} | {x['entidade']} "
                          f"| {sit} |")
        linhas.append("")
    linhas += [
        "## 1. Pagamento vindo do próprio órgão do agente (art. 9º, III da Lei 8.429/1992)",
        "",
        "| # | Agente | Cargo | Órgão | Entidade | Quem pagou | Valor |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, x in enumerate(conflito, 1):
        v = " · ".join(f"{k} {n:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
                       for k, n in x["valor_por_fonte"].items()) or "só contrato"
        linhas.append(f"| {i}{' 🆕' if x.get('novo') else ''} | {x['agente']} | {x['cargo']} | "
                      f"{x['orgao']} | {x['entidade']} | {x['orgao_pagador_e_o_proprio']} | {v} |")
    linhas += ["", "## 2. Demais pares sem explicação institucional, por valor", "",
               "| # | Agente | Cargo | Órgão | Entidade | 3ºsetor | Valor | Sócios |",
               "|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate([y for y in trabalho if not y["orgao_pagador_e_o_proprio"]][:80], 1):
        v = " · ".join(f"{k} {n:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
                       for k, n in x["valor_por_fonte"].items()) or "só contrato"
        linhas.append(f"| {i}{' 🆕' if x.get('novo') else ''} | {x['agente']} | {x['cargo']} | "
                      f"{x['orgao']} | {x['entidade']} | {'sim' if x['terceiro_setor'] else ''} | "
                      f"{v} | {x['servidores_no_qsa']} de {x.get('socios_no_qsa', 0)} |")
    linhas += ["", f"## 3. Com explicação institucional declarada "
                   f"({sum(1 for x in itens if x['explicacao_institucional'])})", "",
               "Associação de apoio à escola, fundação de apoio universitária, associação de "
               "classe, cooperativa e ente público/estatal — o servidor na direção é o DESENHO do "
               "programa, não o achado. Ficam fora da fila de trabalho e contados aqui para que "
               "ninguém os confunda com ausência de verificação.", ""]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return str(caminho)


def contar_qsa(raizes: set[str], zst: Path = _ZST) -> dict[str, int]:
    """Tamanho REAL do QSA de cada raiz — o denominador sem o qual a contagem engana.

    "10 servidores no QSA" parecia o sinal mais forte da fila e era o mais enganoso: a MEDVIVA tem
    **125 sócios**, e 10 servidores são 8%; a B&B MED tem 203 e 7 servidores são 3%. A contagem
    crua ordenava por TAMANHO DA EMPRESA, não por concentração — o mesmo defeito dos dois
    detectores anti-preditivos que esta casa já removeu.

    E a fração também não salva: exigindo denominador defensável (≥5 sócios e maioria de
    servidores) sobram 5 entidades, das quais 4 já têm explicação institucional (duas estatais e
    duas associações de apoio à escola). O eixo NÃO discrimina, em nenhuma das duas formas — por
    isso ele não ordena mais nada. Fica exibido, com o denominador ao lado, para quem lê julgar.
    """
    total: dict[str, int] = {}
    proc = subprocess.Popen(["zstd", "-dcq", str(zst)], stdout=subprocess.PIPE,
                            preexec_fn=lambda: os.nice(10))
    try:
        for bruto in proc.stdout:
            raiz = bruto[1:9].decode("ascii", "replace")
            if raiz in raizes:
                total[raiz] = total.get(raiz, 0) + 1
    finally:
        proc.stdout.close()
        proc.wait()
    return total


def gravar_fila(caminho: Path = _FILA_JSON) -> dict:
    """Materializa a fila em JSON — o CÁLCULO NÃO PODE CAIR DENTRO DO REQUEST.

    Medido: a rota levava 22,3 s porque `fila()` remonta o dicionário de 5,86 milhões de razões
    sociais a cada chamada. É a mesma regra que já governa `/api/tac/ranking`, que só LÊ o arquivo
    que o sweep escreveu. Painel que espera 22 s é painel que o usuário conclui estar quebrado.
    """
    import json

    itens = fila()
    qsa = contar_qsa({x["cnpj_basico"] for x in itens})
    for x in itens:
        x["socios_no_qsa"] = qsa.get(x["cnpj_basico"], 0)
    novos = marcar_novidades(itens)
    md = escrever_fila_md(itens, novos)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    corpo = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M"),
        "total": len(itens),
        "comissionados": sum(1 for x in itens if x["comissionado"]),
        "terceiro_setor": sum(1 for x in itens if x["terceiro_setor"]),
        "com_explicacao_institucional": sum(1 for x in itens if x["explicacao_institucional"]),
        "novos": novos,
        "fila_md": md,
        "itens": itens,
    }
    caminho.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in corpo.items() if k != "itens"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--so-resumo", action="store_true", help="não reconstrói, só mede")
    ap.add_argument("--fila", type=int, default=0, help="imprime os N primeiros da fila")
    ap.add_argument("--so-comissionados", action="store_true")
    a = ap.parse_args()
    if not a.so_resumo and not a.fila:
        for k, v in construir().items():
            print(f"{k:34s} {v}")
    if not a.so_resumo:
        for k, v in gravar_fila().items():
            print(f"{k:34s} {v}")
    if a.fila:
        f = fila(so_comissionados=a.so_comissionados)
        print(f"fila: {len(f)} pares (portador único, entidade com OB contabilizada)")
        for x in f[:a.fila]:
            marca = "★" if x["comissionado"] else " "
            expl = f"  ⟨{x['explicacao_institucional']}⟩" if x["explicacao_institucional"] else ""
            print(f"{marca}{x['agente'][:34]:34s} | {str(x['cargo'])[:24]:24s} | "
                  f"{str(x['orgao'])[:24]:24s} | {x['entidade'][:32]:32s} "
                  f"R$ {x['valor_recebido']:>14,.2f}{expl}")
        return
    print("── resumo ──")
    for k, v in resumo().items():
        print(f"{k:44s} {v}")


if __name__ == "__main__":
    main()
