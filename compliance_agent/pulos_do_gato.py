# -*- coding: utf-8 -*-
"""Detectores dos "pulos do gato" do orçamento estadual — Comissão de Orçamento da ALERJ (13/11/2026).

Cada detector transforma um padrão do manual (`~/vault/notas/manual-orcamento-publico-rj.md`, capítulo 11) em regra
que roda sobre o que a casa JÁ tem: SIAFE (`ne_siafe`, `nl_siafe`, `ob_orcamentaria_siafe`), DOERJ
(`publicacoes_doerj`), SICONFI (`siconfi_rreo`, `siconfi_rgf`) e Portal de Transparência/CGE
(`cge_execucao_despesa`). Nenhum abre sessão em sistema externo.

Contrato de TODO detector (dict):
  id, pulo, titulo, regra (explícita), dispositivo (legal), fonte (tabelas), prevalencia {unidade, base, acionados,
  taxa, acende_sozinho}, explicacao_inocente [..], limites [..] (o que a base NÃO vê), achados [..].
Contrato de TODO achado: ano, mes (None = anual), titulo, detalhe, valor, estagio (o que o valor É: dotação,
  empenhado, liquidado, pago por OB…), estado, por_que_estado, proveniencia.

ESTADO fala do NÚMERO, nunca da irregularidade:
  VERIFICADO   registro primário individualizado (documento SIAFE numerado, decreto publicado) com a cobertura da
               coleta declarada completa, ou duas fontes independentes que concordam;
  PENDENTE     fonte única agregada ou autodeclarada (SICONFI), cobertura parcial, pareamento por heurística ou
               dependência de documento ainda não lido;
  INDISPONÍVEL a fonte não tem o dado (≠ zero).
Em qualquer estado o achado é INDÍCIO: ato administrativo tem presunção de legitimidade.

Prevalência (memória `parentesco-prevalencia-decide-o-eixo`): medida na base a cada rodada; eixo que acende em 10% ou
mais da base não acende sozinho (`acende_sozinho = taxa < 10%`) — vira contexto. Empenho nunca é chamado de pago.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR", RAIZ / "data"))
DB = DATA / "compliance.db"
DB_ABERTOS = DATA / "dadosabertos_rj.db"
SAIDA = DATA / "pulos_do_gato.json"
MANUAL = Path(os.environ.get("JFN_MANUAL_ORCAMENTO", Path.home() / "vault" / "notas" / "manual-orcamento-publico-rj.md"))

VERIFICADO, PENDENTE, INDISPONIVEL = "VERIFICADO", "PENDENTE", "INDISPONÍVEL"
TETO_PREVALENCIA = 0.10

# data_emissao do SIAFE é TEXTO DD/MM/AAAA (memória data-emissao-siafe-e-texto)
_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
_MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
          "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}


def brl(x) -> str:
    return "R$ " + f"{float(x or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, casas: int = 2) -> str:
    return f"{100 * float(x or 0):.{casas}f}%".replace(".", ",")


def _ro(caminho: Path) -> sqlite3.Connection | None:
    if not Path(caminho).is_file():
        return None
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=30)


def _tem(c: sqlite3.Connection | None, tabela: str) -> bool:
    return bool(c is not None and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                            (tabela,)).fetchone())


def _prev(unidade: str, base: int, acionados: int) -> dict:
    taxa = (acionados / base) if base else None
    return {"unidade": unidade, "base": base, "acionados": acionados, "taxa": taxa,
            "acende_sozinho": bool(taxa is not None and taxa < TETO_PREVALENCIA)}


def _det(id_: str, pulo: int, titulo: str, regra: str, dispositivo: str, fonte: str, prevalencia: dict,
         inocente: list[str], limites: list[str], achados: list[dict]) -> dict:
    return {"id": id_, "pulo": pulo, "titulo": titulo, "regra": regra, "dispositivo": dispositivo, "fonte": fonte,
            "prevalencia": prevalencia, "explicacao_inocente": inocente, "limites": limites, "achados": achados}


def _ach(ano, mes, titulo: str, detalhe: str, valor, estagio: str, estado: str, por_que: str, proveniencia: str,
         **extra) -> dict:
    return {"ano": ano, "mes": mes, "titulo": titulo, "detalhe": detalhe, "valor": valor, "estagio": estagio,
            "estado": estado, "por_que_estado": por_que, "proveniencia": proveniencia, **extra}


def _sem_fonte(id_: str, pulo: int, titulo: str, regra: str, dispositivo: str, fonte: str) -> dict:
    """Fonte ausente na base: o detector declara INDISPONÍVEL em vez de devolver lista vazia (ausência ≠ zero)."""
    return _det(id_, pulo, titulo, regra, dispositivo, fonte, _prev("—", 0, 0), [], [f"Tabela ausente: {fonte}."],
                [_ach(None, None, "Fonte indisponível", f"A base não tem {fonte}; o detector não rodou.", None, "—",
                      INDISPONIVEL, "tabela ausente", fonte)])


# ══════════════════════════ PG01 · suplementação por decreto × teto da LOA (Pulo 1) ══════════════════════════

# Limite de remanejamento por decreto, por exercício: (lei, artigo, fração do total da despesa). Conferido no texto
# da LOA 2026 (Lei 11.098/2026, art. 6º, I) — manual, seção 6.3. Exercício sem entrada = limite INDISPONÍVEL.
LIMITE_LOA = {2026: ("Lei 11.098/2026", "art. 6º, I", 0.20)}
# Itens do §2º do art. 120 da Lei estadual 287/1979 (origem do recurso do crédito). Só o item de ANULAÇÃO consome o
# teto do art. 6º, I. Preenchido da leitura do texto da lei (ver manual, seção 6.2); item ausente = "não lido".
ITENS_ART_120: dict[str, str] = {}
ITEM_ANULACAO = "3"

_RE_DECRETO = re.compile(
    r"DECRETO\s+N[ºo°]\s*(?P<num>\d{2}\.\d{3})\s+DE\s+(?P<dia>\d{1,2})[ºo°]?\s+DE\s+(?P<mes>[A-ZÇ]+)\s+DE\s+"
    r"(?P<ano>20\d\d)\s*\n(?P<ementa>(?:.*\n){0,14}?)(?=O\s+GOVERNADOR|A\s+GOVERNADORA|O\s+VICE-GOVERNADOR)", re.I)
_RE_ITENS = re.compile(r"§\s*2º,\s*ite(?:m|ns)\s+([\d, e]+?),?\s*do\s+art\.\s*120", re.I)
_RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d\d)")
_RE_ANEXO = re.compile(r"(?P<pt>\b\d{5}\.\d{2}\.\d{3}\.\d{4}\.\d{4}\b)|(?P<nat>\b\d{4}\.\d{2}\b)"
                       r"|(?P<fr>\b\d\.\d{3}\.\d{3}\b)|(?P<val>\b\d{1,3}(?:,\d{3})*\.\d{2}\b)")


def _junta(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"-\n", "", s)).strip()


def _num_br(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def itens_do_anexo(texto: str) -> list[dict]:
    """Linhas do anexo de um decreto de crédito: programa de trabalho, natureza, valor e fonte (FR), na ordem em que
    aparecem. O texto do DOERJ perde a coluna (suplementado × cancelado): a direção NÃO é recuperável daqui."""
    itens, cur = [], {}
    for m in _RE_ANEXO.finditer(texto):
        k = m.lastgroup
        if k == "pt":
            cur = {"pt": m.group()}
        elif k == "nat" and "pt" in cur and "nat" not in cur:
            cur["nat"] = m.group()
        elif k == "val" and "nat" in cur and "val" not in cur:
            cur["valor"] = float(m.group().replace(",", ""))
            cur["val"] = m.group()
        elif k == "fr" and "val" in cur:
            cur["fr"] = m.group()
            itens.append(cur)
            cur = {}
    return itens


def decretos_de_credito(textos) -> list[dict]:
    """Extrai os decretos de crédito adicional de (id, data_publicacao, texto, url). Um decreto por número (a mesma
    página do DOERJ aparece em mais de uma linha da tabela). Tudo que sai daqui tem citação literal no texto."""
    out: dict[str, dict] = {}
    for pid, data_pub, texto, url in textos:
        cabecas = list(_RE_DECRETO.finditer(texto or ""))
        for i, m in enumerate(cabecas):
            ementa = _junta(m.group("ementa"))
            tipo = next((t for t in ("SUPLEMENTAR", "ESPECIAL", "EXTRAORDINÁRIO") if f"CRÉDITO {t}" in ementa.upper()),
                        None)
            if not tipo or not ementa.upper().startswith("ABRE"):
                continue
            fim = cabecas[i + 1].start() if i + 1 < len(cabecas) else len(texto)
            corpo = texto[m.end():fim]
            art = corpo.find("Rio de Janeiro,")
            dispositivo = _junta(corpo[:art if art > 0 else 4000])
            v = _RE_VALOR.search(ementa)
            it = _RE_ITENS.search(dispositivo)
            itens = sorted(set(re.findall(r"\d", it.group(1)))) if it else []
            loa = re.search(r"art\.\s*(\d+)º?[^;]{0,60}?Lei Estadual nº\s*([\d.]+),\s*de\s*\d{1,2}[ºo°]?\s*de\s*\w+\s*de\s*"
                            r"(20\d\d),\s*que\s*estima", dispositivo, re.I)
            d = {"numero": m.group("num"), "data": f"{m.group('ano')}-{_MESES.get(m.group('mes').upper(), 0):02d}-"
                 f"{int(m.group('dia')):02d}", "publicado_em": str(data_pub)[:10], "tipo": tipo.lower(),
                 "ementa": ementa[:300], "valor": _num_br(v.group(1)) if v else None, "itens_art_120": itens,
                 "citacao_itens": it.group(0) if it else None,
                 "loa_artigo": loa.group(1) if loa else None, "loa_lei": loa.group(2) if loa else None,
                 "exercicio": int(loa.group(3)) if loa else None,
                 "itens_anexo": itens_do_anexo(corpo), "url": url, "id_publicacao": pid}
            ant = out.get(d["numero"])
            if ant is None or (d["valor"] is not None and len(d["itens_anexo"]) > len(ant["itens_anexo"])):
                out[d["numero"]] = d
    return sorted(out.values(), key=lambda d: d["data"])


def _despesa_fixada(ca, exercicio: int) -> float | None:
    """Total da despesa na dotação INICIAL (RREO, Anexo 01, 'TOTAL DAS DESPESAS (XII)') — base do percentual."""
    if not _tem(ca, "siconfi_rreo"):
        return None
    r = ca.execute("SELECT valor FROM siconfi_rreo WHERE anexo='RREO-Anexo 01' AND exercicio=? AND conta LIKE "
                   "'TOTAL DAS DESPESAS (XII)%' AND coluna LIKE 'DOTAÇÃO INICIAL%' ORDER BY periodo DESC LIMIT 1",
                   (exercicio,)).fetchone()
    return float(r[0]) if r and r[0] else None


def _textos_decreto(c):
    return c.execute("SELECT id, data_publicacao, texto, url_fonte FROM publicacoes_doerj WHERE secao='I' AND "
                     "(texto LIKE '%CRÉDITO SUPLEMENTAR%' OR texto LIKE '%CRÉDITO ESPECIAL%' "
                     "OR texto LIKE '%CRÉDITO EXTRAORDINÁRIO%')")


def suplementacao_por_decreto(c, ca, decs: list[dict] | None = None) -> dict:
    meta = ("PG01", 1, "Suplementação por decreto contra o teto da LOA",
            "Somar os decretos de crédito suplementar do exercício publicados no DOERJ e separar pela origem do "
            "recurso declarada no art. 2º do decreto (itens do §2º do art. 120 da Lei 287/1979). PISO de anulação = "
            f"decretos compensados SÓ pelo item {ITEM_ANULACAO} (anulação de dotação); TETO = todos os que citam o item "
            f"{ITEM_ANULACAO}. Comparar com o limite da LOA sobre a despesa fixada. Se nem o TETO alcança o limite, o "
            "limite não foi excedido mesmo sem descontar as exceções do §2º; se o PISO o ultrapassa, só as exceções "
            "(pessoal, dívida, precatórios, DEA, vinculadas, emendas) explicam.",
            "CE-RJ, arts. 209, §8º, e 211, V a VII; CF, art. 167, V a VII; Lei 4.320/1964, arts. 42 e 43; LOA 2026 "
            "(Lei 11.098/2026), arts. 6º e 16, V; Lei estadual 287/1979, art. 120, §2º",
            "publicacoes_doerj (Parte I) + siconfi_rreo (RREO, Anexo 01)")
    if not _tem(c, "publicacoes_doerj"):
        return _sem_fonte(*meta)
    decs = decs if decs is not None else decretos_de_credito(_textos_decreto(c))
    edicoes = c.execute("SELECT COUNT(DISTINCT data_publicacao), MIN(data_publicacao), MAX(data_publicacao) "
                        "FROM publicacoes_doerj WHERE secao='I'").fetchone()
    cobertura = f"{edicoes[0]} edições da Parte I do DOERJ na base, de {edicoes[1]} a {edicoes[2]}"
    achados, por_ano = [], defaultdict(list)
    for d in decs:
        ex = d["exercicio"] or int(d["data"][:4])
        por_ano[ex].append(d)
        origem = ", ".join(f"item {i}" + (f" ({ITENS_ART_120[i]})" if i in ITENS_ART_120 else "")
                           for i in d["itens_art_120"]) or "origem não localizada no texto"
        achados.append(_ach(
            int(d["publicado_em"][:4]), int(d["publicado_em"][5:7]),
            f"Decreto {d['numero']}, de {d['data'][8:]}/{d['data'][5:7]}/{d['data'][:4]} — crédito {d['tipo']}",
            f"{d['ementa']} Compensação: {origem}." + (f" Citação: “{d['citacao_itens']}”." if d["citacao_itens"] else "")
            + (f" Invoca o art. {d['loa_artigo']}º da Lei {d['loa_lei']}." if d["loa_artigo"] else
               " Artigo da LOA invocado não localizado no texto.") + f" Exercício do crédito: {ex}.",
            d["valor"], "crédito aberto (dotação; não é empenho nem pagamento)",
            VERIFICADO if d["valor"] is not None and d["itens_art_120"] else PENDENTE,
            "valor e origem lidos no texto do decreto publicado" if d["valor"] is not None and d["itens_art_120"]
            else "valor ou origem do recurso não localizados no texto extraído — ler o decreto",
            f"DOERJ, Parte I, edição de {d['publicado_em']} (publicacoes_doerj id {d['id_publicacao']})",
            url=d["url"], tipo="evidencia", exercicio=ex))
    acionados = 0
    for ex, lista in sorted(por_ano.items()):
        sup = [d for d in lista if d["tipo"] == "suplementar" and d["valor"] is not None]
        total = sum(d["valor"] for d in sup)
        piso = sum(d["valor"] for d in sup if d["itens_art_120"] == [ITEM_ANULACAO])
        # pior cenário: decreto cuja origem não foi localizada no texto conta INTEIRO como anulação
        teto = sum(d["valor"] for d in sup if ITEM_ANULACAO in d["itens_art_120"] or not d["itens_art_120"])
        sem_origem = [d["numero"] for d in sup if not d["itens_art_120"]]
        sem_valor = [d["numero"] for d in lista if d["tipo"] == "suplementar" and d["valor"] is None]
        fix, lim = _despesa_fixada(ca, ex), LIMITE_LOA.get(ex)
        if not (fix and lim):
            achados.append(_ach(ex, None, f"Créditos suplementares de {ex}: limite não calculável",
                                f"{len(sup)} decreto(s), {brl(total)} em créditos. "
                                + ("Despesa fixada ausente no RREO da base. " if not fix else "")
                                + ("Limite da LOA deste exercício não cadastrado (ler a lei). " if not lim else ""),
                                total, "crédito aberto (dotação)", INDISPONIVEL,
                                "falta a despesa fixada ou o artigo da LOA do exercício", f"{cobertura}"))
            continue
        limite = fix * lim[2]
        if teto < limite:
            veredito, est, pq = (f"abaixo do limite no cenário mais desfavorável, com margem de {brl(limite - teto)} "
                                 "(sem descontar exceções e contando como anulação os decretos de origem não localizada)",
                                 PENDENTE, "a conta vale para os decretos que estão na base; não há prova de que a base "
                                 "tem TODOS os decretos do exercício (edições extras) — pedir a relação à SEPLAG")
        elif piso > limite:
            veredito, est, pq = ("o PISO de anulação já supera o limite: só as exceções do §2º explicam", PENDENTE,
                                 "falta a decomposição por exceção (pessoal, dívida, DEA, vinculadas, emendas), que o "
                                 "texto do decreto não dá — requisitar à SEPLAG")
            acionados += 1
        else:
            veredito, est, pq = ("indeterminado: o limite está entre o piso e o teto de anulação", PENDENTE,
                                 "os decretos mistos não dizem quanto de cada origem — requisitar a decomposição")
            acionados += 1
        achados.append(_ach(
            ex, None, f"Créditos suplementares de {ex} contra o limite de {pct(lim[2], 0)} ({lim[0]}, {lim[1]})",
            f"{len(sup)} decreto(s) somam {brl(total)}. Anulação de dotação: PISO {brl(piso)} "
            f"({pct(piso / fix)} da despesa fixada) e TETO {brl(teto)} ({pct(teto / fix)}). Limite: {brl(limite)} "
            f"({pct(lim[2], 0)} de {brl(fix)}). Resultado: {veredito}."
            + (f" Origem não localizada no texto (contados no teto): {', '.join(sem_origem)}." if sem_origem else "")
            + (f" Valor não localizado no texto (FORA da soma): {', '.join(sem_valor)}." if sem_valor else ""),
            teto, "crédito aberto por anulação (dotação) — teto", est, pq,
            f"{cobertura}; despesa fixada: RREO Anexo 01, dotação inicial (SICONFI, autodeclarado)", tipo="veredito",
            piso=piso, teto=teto, limite=limite, n_decretos=len(sup)))
    return _det(*meta, _prev("exercício com decretos na base", len(por_ano), acionados),
                ["O §2º do art. 6º da LOA exclui do teto reforço de pessoal, inativos, dívida, precatórios, DEA, "
                 "despesas com receita vinculada e emendas impositivas.",
                 "Crédito por superávit financeiro, excesso de arrecadação ou operação de crédito não consome o teto.",
                 "O art. 16, V, da LOA 2026 autoriza movimentação de saldos fora do limite do art. 6º, I."],
                ["O texto extraído do DOERJ perde as colunas do anexo: não dá para saber, linha a linha, o que foi "
                 "suplementado e o que foi cancelado.", "Decreto misto (várias origens) não informa quanto de cada.",
                 "Só entram decretos cuja edição está na base (cobertura declarada em cada achado)."], achados)


# ══════════════════════════ PG03 · DEA recorrente para o mesmo credor (Pulo 3) ══════════════════════════

DEA_MESES_MIN = 3  # empenhos de DEA ao mesmo credor em 3+ meses distintos do exercício, na mesma UG


def dea_recorrente(c) -> dict:
    meta = ("PG03", 3, "DEA recorrente para o mesmo credor (despesa sem empenho paga no ano seguinte)",
            f"Na mesma UG e exercício, credor pessoa jurídica com notas de empenho CONTABILIZADAS no elemento 92 "
            f"(Despesas de Exercícios Anteriores, aplicação direta: naturezas 339092/449092) em {DEA_MESES_MIN} ou mais "
            "meses distintos. Folha, pessoa física e transferência a outro ente ficam fora. O valor é EMPENHADO; o pago "
            "sai das OB contabilizadas ligadas pela cadeia NE→NL→OB, quando a liquidação foi coletada.",
            "Lei 4.320/1964, arts. 37 e 60; LRF, arts. 15, 16 e 42; Lei 14.133/2021, art. 149; CP, art. 359-D",
            "ne_siafe + nl_siafe + ob_orcamentaria_siafe + siafe_documento_cobertura")
    if not _tem(c, "ne_siafe"):
        return _sem_fonte(*meta)
    cob = {}
    if _tem(c, "siafe_documento_cobertura"):
        cob = {(t, ug, int(ex)): bool(comp) for t, ug, ex, comp in c.execute(
            "SELECT tipo, ug_emitente, exercicio, completo FROM siafe_documento_cobertura")}
    base = c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM ne_siafe WHERE status='Contabilizado' AND length(credor)=14 "
                     "GROUP BY ug_emitente, exercicio, credor)").fetchone()[0]
    com_dea = c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM ne_siafe WHERE status='Contabilizado' AND length(credor)=14 "
                        "AND substr(natureza,5,2)='92' GROUP BY ug_emitente, exercicio, credor)").fetchone()[0]
    linhas = c.execute(f"""
        SELECT ug_emitente, exercicio, credor, MAX(nome_credor), COUNT(*), COUNT(DISTINCT substr(data_emissao,4,2)),
               SUM(valor), SUM(tipo_reconhecimento_passivo='Passivo reconhecido previamente'),
               MIN({_ISO}), MAX({_ISO}), GROUP_CONCAT(numero)
        FROM ne_siafe WHERE status='Contabilizado' AND length(credor)=14 AND substr(natureza,3,2)='90'
          AND substr(natureza,5,2)='92'
        GROUP BY ug_emitente, exercicio, credor HAVING COUNT(DISTINCT substr(data_emissao,4,2)) >= ?
        ORDER BY SUM(valor) DESC""", (DEA_MESES_MIN,)).fetchall()
    tem_cadeia = _tem(c, "nl_siafe") and _tem(c, "ob_orcamentaria_siafe")
    achados = []
    for ug, ex, cnpj, nome, n, meses, valor, previos, d0, d1, nes in linhas:
        ex = int(ex)
        pago, n_ob = None, 0
        if tem_cadeia:
            lista = nes.split(",")
            marc = ",".join("?" * len(lista))
            r = c.execute(f"""SELECT COALESCE(SUM(o.valor),0), COUNT(*) FROM ob_orcamentaria_siafe o
                WHERE o.credor=? AND o.ug_emitente=? AND o.status='Contabilizado' AND o.nl IN
                  (SELECT numero FROM nl_siafe WHERE ug_emitente=? AND status='Contabilizado' AND ne IN ({marc}))""",
                          (cnpj, ug, ug, *lista)).fetchone()
            pago, n_ob = float(r[0] or 0), int(r[1] or 0)
        completo = cob.get(("NE", ug, ex), False)
        nl_completa = cob.get(("NL", ug, ex), False)
        achados.append(_ach(
            ex, None, f"{nome} — UG {ug}: DEA em {meses} meses de {ex}",
            f"{n} nota(s) de empenho no elemento 92, de {d0} a {d1}; {previos or 0} com “Passivo reconhecido "
            f"previamente”. Empenhado: {brl(valor)}. "
            + (f"Pago por OB contabilizada ligada às liquidações coletadas: {brl(pago)} em {n_ob} OB"
               + ("." if nl_completa else " (PISO: liquidações desta UG com coleta parcial).") if tem_cadeia
               else "Pago: INDISPONÍVEL (cadeia NE→NL→OB ausente na base).")
            + " Perguntar: competência do serviço, contrato vigente na época e por que não houve empenho.",
            valor, "empenhado (NE contabilizada) — não é pagamento", VERIFICADO if completo else PENDENTE,
            "notas de empenho individualizadas do SIAFE-Rio, com a coleta de NE desta UG/exercício marcada completa"
            if completo else "coleta de NE desta UG/exercício não está marcada como completa — valor é piso",
            f"SIAFE-Rio, Nota de Empenho, UG {ug}, exercício {ex}: {', '.join(nes.split(',')[:6])}"
            + ("…" if n > 6 else ""), cnpj=cnpj, ug=ug, pago_ob=pago, n_empenhos=n, meses=meses))
    d = _det(*meta, _prev("par UG × credor (CNPJ) com empenho no exercício", base, len(achados)),
             ["Hipótese legal do art. 37: a despesa tinha dotação e não foi processada na época por atraso do "
              "credor em apresentar a cobrança, ou o compromisso só foi reconhecido após o encerramento.",
              "Reajuste, repactuação ou reequilíbrio retroativo de contrato vigente gera DEA sem serviço descoberto.",
              "Decisão judicial ou acordo homologado.", "Repasse a outro ente (modalidades 30/40) — excluído pela regra."],
             ["NE coletada só para as UGs e exercícios listados em siafe_documento_cobertura; UG fora dali não "
              "é 'sem DEA', é INDISPONÍVEL.", "A base não tem a competência do serviço nem o documento de "
              "reconhecimento da dívida: sem eles não se distingue serviço sem cobertura de reajuste retroativo.",
              "Recorrência entre EXERCÍCIOS exige NE de mais de um ano (hoje a coleta cobre um)."], achados)
    d["prevalencia"]["contexto"] = (f"{com_dea} de {base} pares UG × credor têm ALGUM empenho de DEA "
                                    f"({pct(com_dea / base) if base else '—'}): ter DEA, sozinho, não é sinal.")
    return d


# ══════════════════════════ PG04 · restos a pagar: inscrição e cancelamento (Pulo 4) ══════════════════════════

RP_CANCELAMENTO_MIN = 0.10  # RP não processados cancelados ≥ 10% do estoque inscrito


def _rreo(ca, anexo: str, ex: int, per: int, conta_like: str) -> dict[str, float]:
    return {col: float(v or 0) for col, v in ca.execute(
        "SELECT coluna, valor FROM siconfi_rreo WHERE anexo=? AND exercicio=? AND periodo=? AND conta LIKE ?",
        (anexo, ex, per, conta_like))}


def _col(d: dict, *trechos: str) -> float:
    for k, v in d.items():
        if all(t.lower() in k.lower() for t in trechos):
            return v
    return 0.0


def restos_a_pagar(ca) -> dict:
    meta = ("PG04", 4, "Restos a pagar: o que foi inscrito e depois cancelado",
            "RREO, Anexo 07 (total do ente), último bimestre disponível de cada exercício: restos a pagar NÃO "
            f"processados cancelados ÷ estoque inscrito (exercícios anteriores + 31/12 anterior). Acende quando ≥ "
            f"{pct(RP_CANCELAMENTO_MIN, 0)}: empenho que contou como despesa do ano anterior e não virou despesa.",
            "Lei 4.320/1964, arts. 36 e 92; LRF, arts. 42 e 55, III, “b”; CP, arts. 359-B e 359-F; LC 141/2012, art. 24",
            "siconfi_rreo (RREO, Anexo 07)")
    if not _tem(ca, "siconfi_rreo"):
        return _sem_fonte(*meta)
    pares = ca.execute("SELECT exercicio, MAX(periodo) FROM siconfi_rreo WHERE anexo='RREO-Anexo 07' "
                       "GROUP BY exercicio ORDER BY exercicio").fetchall()
    if not pares:
        return _sem_fonte(*meta)
    achados, acionados = [], 0
    for ex, per in pares:
        t = _rreo(ca, "RREO-Anexo 07", ex, per, "TOTAL (III)%")
        np_ant, np_dez = _col(t, "Anteriores (f)"), _col(t, "dezembro", "(g)")
        np_canc, p_canc = _col(t, "Cancelados (j)"), _col(t, "Cancelados (d)")
        p_insc = _col(t, "Anteriores (a)") + _col(t, "dezembro", "(b)")
        saldo = _col(t, "Saldo Total")
        estoque = np_ant + np_dez
        taxa = np_canc / estoque if estoque else 0.0
        fechado = per == 6
        if taxa >= RP_CANCELAMENTO_MIN:
            acionados += 1
        achados.append(_ach(
            ex, per * 2, f"RP não processados cancelados em {ex}: {pct(taxa)} do estoque"
            + ("" if fechado else f" (parcial, até o {per}º bimestre)"),
            f"Não processados inscritos: {brl(estoque)} ({brl(np_dez)} em 31/12/{ex - 1}); cancelados: {brl(np_canc)}. "
            f"Processados inscritos: {brl(p_insc)}; cancelados: {brl(p_canc)} — cancelar RP PROCESSADO é cancelar "
            f"dívida já reconhecida (liquidada). Saldo total a pagar: {brl(saldo)}. "
            + ("Acima do limiar da regra." if taxa >= RP_CANCELAMENTO_MIN else "Abaixo do limiar da regra."),
            np_canc, "restos a pagar não processados CANCELADOS (empenho desfeito — não é pagamento)", PENDENTE,
            "valor autodeclarado pelo Executivo ao SICONFI; conferir com o RREO publicado no DOERJ antes de usar em peça",
            f"SICONFI/Tesouro, RREO Anexo 07, RJ, {ex}, {per}º bimestre, linha TOTAL (III)", acende=taxa >= RP_CANCELAMENTO_MIN))
    return _det(*meta, _prev("exercício (2021 em diante)", len(pares), acionados),
                ["Cancelamento por prescrição quinquenal ou por saneamento de RP antigo é o que a boa prática manda.",
                 "Contrato rescindido, obra não executada ou entrega recusada: o empenho deixa de ter objeto.",
                 "Empenho estimativo maior que o consumo real (água, luz, telefonia)."],
                ["O Anexo 07 do SICONFI vem por Poder, não por órgão, fonte ou credor: não diz QUAL empenho foi cancelado.",
                 "Não diz se o empenho cancelado tinha entrado no mínimo de saúde ou educação (ver PG15).",
                 f"Base pequena ({len(pares)} exercícios): a prevalência orienta, não prova."], achados)


# ══════════════════════════ PG05 · art. 42 da LRF: caixa por fonte depois dos RP (Pulo 5) ══════════════════════════

ULTIMO_ANO_DE_MANDATO = {2018, 2022, 2026, 2030}
_COL_LIQ = "DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS%"
_COL_NAO_INSCRITO = "EMPENHOS NÃO LIQUIDADOS CANCELADOS%"


def caixa_art_42(ca, hoje: date | None = None) -> dict:
    meta = ("PG05", 5, "Art. 42 da LRF: obrigação sem caixa no fim do exercício",
            "RGF, Anexo 05 do 3º quadrimestre (Poder Executivo): fonte de recursos com DISPONIBILIDADE DE CAIXA LÍQUIDA "
            "NEGATIVA depois da inscrição dos restos a pagar não processados, e o total de empenhos não liquidados "
            "cancelados por insuficiência financeira. Em último ano de mandato a insuficiência é o próprio fato do "
            "art. 42; nos demais anos é desequilíbrio a explicar (LRF, art. 1º, §1º).",
            "LRF, arts. 1º, §1º, 42, 50, I, e 55, III; CP, art. 359-C; Lei 10.028/2000",
            "siconfi_rgf (RGF, Anexo 05, co_poder E)")
    if not _tem(ca, "siconfi_rgf"):
        return _sem_fonte(*meta)
    hoje = hoje or date.today()
    linhas = ca.execute(
        "SELECT exercicio, conta, valor FROM siconfi_rgf WHERE anexo='RGF-Anexo 05' AND co_poder='E' AND periodo=3 "
        "AND coluna LIKE ? AND valor IS NOT NULL", (_COL_LIQ,)).fetchall()
    base = [x for x in linhas if not x[1].upper().startswith("TOTAL")]
    achados = []
    for ex, conta, v in sorted(base):
        if v >= 0:
            continue
        final = ex in ULTIMO_ANO_DE_MANDATO
        achados.append(_ach(
            ex, 12, f"{conta}: caixa líquido negativo em 31/12/{ex}" + (" (último ano de mandato)" if final else ""),
            f"Disponibilidade de caixa líquida após a inscrição em restos a pagar não processados: {brl(v)}. "
            + ("Exercício de fim de mandato: é a hipótese do art. 42 da LRF, a confirmar com a data em que cada "
               "obrigação foi contraída (a partir de 1º/05)." if final else
               "Não é fim de mandato: o art. 42 não incide; a insuficiência por fonte indica despesa maior que o caixa "
               "do vínculo (LRF, arts. 1º, §1º, e 50, I)."),
            v, "disponibilidade de caixa líquida (saldo, não é despesa)", PENDENTE,
            "autodeclarado ao SICONFI; conferir com o RGF publicado e com o parecer prévio do TCE-RJ do exercício",
            f"SICONFI/Tesouro, RGF Anexo 05, RJ, Poder Executivo, {ex}, 3º quadrimestre", fim_de_mandato=final))
    for ex, v in ca.execute(
            "SELECT exercicio, valor FROM siconfi_rgf WHERE anexo='RGF-Anexo 05' AND co_poder='E' AND periodo=3 AND "
            "conta LIKE 'TOTAL (IV)%' AND coluna LIKE ? AND valor > 0 ORDER BY exercicio", (_COL_NAO_INSCRITO,)):
        achados.append(_ach(
            ex, 12, f"Empenhos cancelados por falta de caixa em {ex}: {brl(v)}",
            "Empenhos não liquidados cancelados, não inscritos em restos a pagar por insuficiência financeira (total do "
            "Executivo). É despesa que foi empenhada no exercício e desfeita no fechamento: se o serviço foi prestado, "
            "reaparece como DEA no ano seguinte (ver PG03).",
            v, "empenho CANCELADO (não é pagamento)", PENDENTE,
            "autodeclarado ao SICONFI; conferir com o RGF publicado",
            f"SICONFI/Tesouro, RGF Anexo 05, RJ, Poder Executivo, {ex}, 3º quadrimestre, linha TOTAL (IV)", tipo="contexto"))
    feitos = {x[0] for x in linhas}
    for ex in sorted(ULTIMO_ANO_DE_MANDATO):
        if ex <= hoje.year and ex >= 2021 and ex not in feitos:
            achados.append(_ach(
                ex, 12, f"RGF do 3º quadrimestre de {ex}: ainda não disponível",
                f"O demonstrativo que mede o art. 42 em {ex} (último ano de mandato) só é publicado até 30/01/{ex + 1} "
                "(LRF, art. 55, §2º). Até lá o detector não tem o que medir.", None, "—", INDISPONIVEL,
                "demonstrativo ainda não publicado", "SICONFI/Tesouro, RGF Anexo 05", fim_de_mandato=True))
    n_neg = sum(1 for x in base if x[2] < 0)
    return _det(*meta, _prev("linha de fonte × exercício (RGF Anexo 05, 3º quadr.)", len(base), n_neg),
                ["Fonte com caixa negativo coberta por outra fonte livre do mesmo ente dentro do exercício.",
                 "Recursos extraorçamentários negativos refletem depósitos e consignações, não despesa sem caixa.",
                 "Erro de classificação da fonte no demonstrativo (retificado depois no SICONFI)."],
                ["O Anexo 05 não informa a DATA em que a obrigação foi contraída: o art. 42 só alcança as assumidas "
                 "nos dois últimos quadrimestres do mandato.", "A linha é agregada por grupo de fonte, não por órgão.",
                 "Prevalência alta (a linha negativa é comum): o achado é ponto de pergunta, não conclusão."], achados)


# ══════════════════════════ PG06 · troca de fonte e uso de fonte vinculada (Pulo 6) ══════════════════════════

FONTE_FECP_RJ = "122"            # detalhamento estadual ↔ STN 761 (conferido em cge_execucao_despesa.fonte_rj/fonte_stn)
_STN_LIVRES = ("500", "501", "502")  # Portaria STN 710/2021: recursos não vinculados
FUNDO_EXECUCAO_MIN = 0.50        # fonte "Recursos Vinculados a Fundos" com menos de 50% da dotação empenhada


def troca_de_fonte(c, ca, decs: list[dict] | None = None) -> dict:
    meta = ("PG06", 6, "Troca de fonte e dinheiro carimbado fora do carimbo",
            "(a) Decreto de crédito em que duas linhas consecutivas do anexo têm o MESMO programa de trabalho, a MESMA "
            "natureza e o MESMO valor, mudando só a fonte de recursos (FR). (b) Fonte do FECP (detalhamento estadual "
            f"{FONTE_FECP_RJ}, STN 761) empenhada em pessoal e encargos (grupo 1). (c) Fonte “Recursos Vinculados a "
            f"Fundos” (STN 759) com menos de {pct(FUNDO_EXECUCAO_MIN, 0)} da dotação inicial empenhada em exercício "
            "encerrado: receita carimbada que não foi aplicada no objeto.",
            "LRF, arts. 8º, parágrafo único, e 50, I; CE-RJ, art. 211, IV; ADCT, arts. 79 a 82; EC 132/2023; "
            "Portaria STN 710/2021; LDO 2026, art. 13; LOA 2026, art. 4º, §§2º e 3º",
            "publicacoes_doerj (anexos dos decretos) + cge_execucao_despesa (fonte_rj, fonte_stn)")
    if not (_tem(c, "publicacoes_doerj") or _tem(ca, "cge_execucao_despesa")):
        return _sem_fonte(*meta)
    achados, base, acionados, limites = [], 0, 0, []
    if _tem(c, "publicacoes_doerj"):
        for d in (decs if decs is not None else decretos_de_credito(_textos_decreto(c))):
            it = d["itens_anexo"]
            for x, y in zip(it, it[1:]):
                base += 1
                if x["pt"] == y["pt"] and x["nat"] == y["nat"] and x["val"] == y["val"] and x["fr"] != y["fr"]:
                    acionados += 1
                    livres = [f.split(".")[1] in _STN_LIVRES for f in (x["fr"], y["fr"])]
                    natureza = ("entre duas fontes livres" if all(livres) else "entre duas fontes vinculadas"
                                if not any(livres) else "entre fonte VINCULADA e fonte livre")
                    achados.append(_ach(
                        int(d["publicado_em"][:4]), int(d["publicado_em"][5:7]),
                        f"Decreto {d['numero']}: mesma dotação, troca {natureza} ({x['fr']} ↔ {y['fr']})",
                        f"Programa de trabalho {x['pt']}, natureza {x['nat']}, valor {brl(x['valor'])} nas duas linhas; "
                        f"só a fonte muda ({x['fr']} e {y['fr']}). O texto não diz qual é a suplementada e qual a "
                        "cancelada: ler o anexo no DOERJ.", x["valor"], "crédito aberto (dotação)", PENDENTE,
                        "pareamento por linhas consecutivas no texto extraído (as colunas se perdem) — conferir no PDF",
                        f"DOERJ, Parte I, edição de {d['publicado_em']} (publicacoes_doerj id {d['id_publicacao']})",
                        url=d["url"], eixo="troca_em_decreto", vinculada=not all(livres)))
    else:
        limites.append("publicacoes_doerj ausente: eixo (a) INDISPONÍVEL.")
    if _tem(ca, "cge_execucao_despesa"):
        for ano, emp, pago in ca.execute(
                "SELECT ano, SUM(despesas_empenhadas), SUM(despesas_orcamentarias_pagas) FROM cge_execucao_despesa "
                "WHERE fonte_rj LIKE ? AND grupo_de_despesa LIKE '1 %' GROUP BY ano HAVING SUM(despesas_empenhadas) > 0 "
                "ORDER BY ano", (FONTE_FECP_RJ + " %",)):
            tot = ca.execute("SELECT SUM(despesas_empenhadas) FROM cge_execucao_despesa WHERE fonte_rj LIKE ? AND ano=?",
                             (FONTE_FECP_RJ + " %", ano)).fetchone()[0] or 0
            achados.append(_ach(
                int(ano), None, f"FECP custeando pessoal em {ano}: {brl(emp)} empenhados",
                f"Fonte {FONTE_FECP_RJ} (Fundo de Combate e Erradicação da Pobreza, STN 761), grupo 1 – Pessoal e Encargos "
                f"Sociais: empenhado {brl(emp)} ({pct(emp / tot) if tot else '—'} do empenhado na fonte), pago {brl(pago)}. "
                "Perguntar a base legal para pagar pessoal com o fundo e em quais ações.",
                emp, "empenhado (não é pagamento)", PENDENTE,
                "agregado do Portal de Transparência (CGE), fonte única; a legalidade depende da lei do fundo",
                f"CGE-RJ, despesa orçamentária, exercício {ano}, fonte_rj {FONTE_FECP_RJ}, grupo 1", eixo="fecp_pessoal",
                pago=pago, tipo="contexto"))
        ano_fechado = (ca.execute("SELECT MAX(ano) FROM cge_execucao_despesa WHERE mes=12").fetchone()[0] or 0)
        fontes = ca.execute(
            "SELECT ano, fonte_rj, SUM(dotacao_inicial), SUM(despesas_empenhadas), SUM(despesas_orcamentarias_pagas) "
            "FROM cge_execucao_despesa WHERE fonte_stn LIKE '759 %' AND ano <= ? GROUP BY ano, fonte_rj "
            "HAVING SUM(dotacao_inicial) >= 1e6", (ano_fechado,)).fetchall()
        for ano, fonte, dot, emp, pago in fontes:
            base += 1
            if emp / dot < FUNDO_EXECUCAO_MIN:
                acionados += 1
                achados.append(_ach(
                    int(ano), None, f"Fonte de fundo {fonte.split(' - ')[0]} em {ano}: {pct(emp / dot)} da dotação empenhada",
                    f"{fonte}: dotação inicial {brl(dot)}, empenhado {brl(emp)}, pago {brl(pago)}. Receita vinculada a "
                    "fundo que ficou sem aplicação no exercício: perguntar o saldo financeiro da fonte em 31/12 e se "
                    "houve desvinculação ou uso como superávit para outra despesa.",
                    dot - emp, "dotação inicial não empenhada (não é despesa nem pagamento)", PENDENTE,
                    "agregado do Portal de Transparência (CGE), fonte única; o detalhamento estadual da fonte reúne "
                    "mais de um fundo", f"CGE-RJ, despesa orçamentária, exercício {ano}, fonte_rj {fonte.split(' - ')[0]}",
                    eixo="fundo_sem_execucao", pago=pago))
    else:
        limites.append("cge_execucao_despesa ausente: eixos (b) e (c) INDISPONÍVEIS.")
    return _det(*meta, _prev("par de linhas de anexo de decreto + fonte de fundo × exercício", base, acionados),
                ["Desvinculação autorizada (EC 132/2023; LDO 2026, art. 13; LOA 2026, art. 4º, §§2º e 3º).",
                 "Correção de classificação: a despesa foi orçada na fonte errada e o decreto só acerta o registro.",
                 "Fundo cuja receita não se realizou: a dotação não empenhada reflete falta de receita, não desvio.",
                 "A lei do FECP admite despesas de pessoal em ações finalísticas específicas (conferir a lei)."],
                limites + ["O código de detalhamento estadual da fonte agrupa vários fundos (FECAM, FEHIS, FISED não têm "
                           "código próprio identificado na base): o achado é por fonte, não por fundo.",
                           "Receita realizada por fonte não está na base de 2026: não dá para medir arrecadado × aplicado.",
                           "O anexo do decreto perde as colunas no texto extraído."], achados)


# ══════════════════════════ PG07 · reserva de contingência usada como caixa (Pulo 7) ══════════════════════════

def reserva_de_contingencia(c, ca) -> dict:
    meta = ("PG07", 7, "Reserva de contingência: composição e consumo",
            "(a) Composição da reserva na dotação inicial, por unidade gestora e fonte (grupo 9). (b) Redução da "
            "reserva no ano: dotação atualizada menor que a inicial no RREO, Anexo 01 — a diferença foi usada como "
            "fonte de crédito por decreto. Acende quando há redução.",
            "LRF, art. 5º, III, “b”; LDO 2026, art. 8º; LOA 2026, arts. 6º, V, e 31; Lei 4.320/1964, art. 43",
            "cge_execucao_despesa (grupo 9) + siconfi_rreo (RREO, Anexo 01, linha Reserva de Contingência)")
    if not (_tem(ca, "siconfi_rreo") or _tem(ca, "cge_execucao_despesa")):
        return _sem_fonte(*meta)
    achados, base, acionados = [], 0, 0
    comp = defaultdict(list)
    if _tem(ca, "cge_execucao_despesa"):
        for ano, ug, fonte, v in ca.execute(
                "SELECT ano, unidade_gestora, fonte_rj, SUM(dotacao_inicial) FROM cge_execucao_despesa "
                "WHERE grupo_de_despesa LIKE '9 %' GROUP BY 1,2,3 HAVING SUM(dotacao_inicial) > 0 ORDER BY 1, 4 DESC"):
            comp[int(ano)].append((ug, fonte, float(v)))
    if _tem(ca, "siconfi_rreo"):
        for ex, per in ca.execute("SELECT exercicio, MAX(periodo) FROM siconfi_rreo WHERE anexo='RREO-Anexo 01' "
                                  "GROUP BY exercicio ORDER BY exercicio").fetchall():
            r = _rreo(ca, "RREO-Anexo 01", ex, per, "RESERVA DE CONTINGÊNCIA")
            if not r:
                continue
            base += 1
            ini, atu = _col(r, "DOTAÇÃO INICIAL"), _col(r, "DOTAÇÃO ATUALIZADA")
            partes = comp.get(ex, [])
            soma = sum(v for *_, v in partes)
            bate = bool(partes) and abs(soma - ini) < 1.0
            txt = "; ".join(f"{ug}: {brl(v)} ({pct(v / soma)}), fonte {f}" for ug, f, v in partes)
            if ini > atu:
                acionados += 1
            achados.append(_ach(
                ex, per * 2, f"Reserva de contingência de {ex}: {brl(ini)} na LOA"
                + (f", reduzida em {brl(ini - atu)}" if ini > atu else ", sem redução"),
                f"Dotação inicial {brl(ini)}; atualizada {brl(atu)} até o {per}º bimestre. "
                + (f"Composição por UG e fonte (soma {brl(soma)}): {txt}. " if partes else
                   "Composição por UG: INDISPONÍVEL na base. ")
                + ("A parcela que não é fundo previdenciário é a única que funciona como reserva para riscos fiscais. "
                   if partes else "") + ("Redução = uso como fonte de crédito: pedir os decretos e a finalidade."
                                         if ini > atu else ""),
                ini - atu if ini > atu else ini, "dotação (reserva; não é despesa nem pagamento)",
                VERIFICADO if bate else PENDENTE,
                "duas fontes independentes concordam no total da dotação inicial: RREO/SICONFI e Portal de "
                "Transparência (CGE)" if bate else "só o RREO autodeclarado, ou as duas fontes divergem no total",
                f"SICONFI/Tesouro, RREO Anexo 01, RJ, {ex}, {per}º bimestre; CGE-RJ, despesa orçamentária, grupo 9",
                acende=ini > atu, composicao=[{"ug": ug, "fonte": f, "valor": v} for ug, f, v in partes]))
    return _det(*meta, _prev("exercício (RREO Anexo 01)", base, acionados),
                ["A LDO exclui do teto da reserva os fundos previdenciário e soberano, o FEF e o fundo do Propag: "
                 "reserva alta nessas unidades é técnica orçamentária (saldo do fundo sem despesa programada).",
                 "Usar a reserva para passivo contingente materializado ou evento fiscal imprevisto é a função dela."],
                ["O RREO não diz para qual dotação a reserva foi transferida: é preciso o decreto (ver PG01).",
                 "A composição vem do portal da CGE (dotação inicial); a atualizada por UG não está na base."], achados)


# ══════════════════════════ PG09 · empenho concentrado em dezembro (Pulo 9) ══════════════════════════

DEZEMBRO_MIN, DEZEMBRO_PISO = 0.25, 10_000_000.0


def empenho_em_dezembro(c, ca) -> dict:
    meta = ("PG09", 9, "Empenho concentrado em dezembro",
            f"Por unidade gestora e exercício encerrado, nos grupos 3, 4 e 5 (custeio, investimento e inversões — "
            f"pessoal e dívida ficam fora): empenhado em dezembro ÷ empenhado no ano ≥ {pct(DEZEMBRO_MIN, 0)} e ≥ "
            f"{brl(DEZEMBRO_PISO)}. O esperado de um mês é 8,3%. Onde há nota de empenho coletada, o achado traz o que "
            "foi emitido de 15 a 31/12.",
            "Lei 4.320/1964, arts. 58 a 60; LRF, arts. 9º e 42; LC 141/2012, art. 24; LOA 2026, art. 27",
            "cge_execucao_despesa (mensal por UG) + ne_siafe")
    if not _tem(ca, "cge_execucao_despesa"):
        return _sem_fonte(*meta)
    linhas = ca.execute("""
        SELECT ano, ug, MAX(unidade_gestora), SUM(CASE WHEN mes=12 THEN despesas_empenhadas ELSE 0 END),
               SUM(despesas_empenhadas), SUM(CASE WHEN mes=12 THEN despesas_orcamentarias_pagas ELSE 0 END)
        FROM cge_execucao_despesa WHERE substr(grupo_de_despesa,1,1) IN ('3','4','5')
          AND ano IN (SELECT ano FROM cge_execucao_despesa WHERE mes=12)
        GROUP BY ano, ug HAVING SUM(despesas_empenhadas) >= 1e6""").fetchall()
    achados = []
    for ano, ug, nome, dez, tot, pago_dez in sorted(linhas, key=lambda x: -x[3]):
        if dez < DEZEMBRO_PISO or dez / tot < DEZEMBRO_MIN:
            continue
        extra = ""
        if _tem(c, "ne_siafe"):
            r = c.execute(f"SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ne_siafe WHERE ug_emitente=? AND exercicio=? "
                          f"AND status='Contabilizado' AND {_ISO} BETWEEN ? AND ?",
                          (ug, ano, f"{ano}-12-15", f"{ano}-12-31")).fetchone()
            extra = (f" No SIAFE, de 15 a 31/12: {r[0]} nota(s) de empenho, {brl(r[1])}." if r[0] else
                     " Notas de empenho desta UG: não coletadas (INDISPONÍVEL).")
        achados.append(_ach(
            int(ano), 12, f"{nome}: {pct(dez / tot)} do empenho do ano em dezembro de {ano}",
            f"Empenhado em dezembro: {brl(dez)} de {brl(tot)} no ano (grupos 3, 4 e 5). Pago em dezembro: "
            f"{brl(pago_dez)}.{extra} Seguir no ano seguinte: quanto virou resto a pagar não processado e quanto foi "
            "cancelado.", dez, "empenhado (não é pagamento)", PENDENTE,
            "agregado mensal do Portal de Transparência (CGE), fonte única; não distingue empenho estimativo/global de "
            "ordinário", f"CGE-RJ, despesa orçamentária, exercício {ano}, UG {ug}, mês 12", ug=ug))
    return _det(*meta, _prev("UG × exercício encerrado com ≥ R$ 1 milhão empenhado", len(linhas), len(achados)),
                ["Crédito suplementar ou descentralização recebidos em dezembro: só então havia dotação para empenhar.",
                 "Licitação homologada no fim do ano; convênio ou transferência federal creditado em dezembro.",
                 "Reforço de empenho estimativo de contrato contínuo para cobrir a competência de dezembro."],
                ["A base agregada não tem o TIPO do empenho (ordinário, estimativo, global).",
                 "Não liga o empenho de dezembro ao resto a pagar cancelado no ano seguinte (ver PG04)."], achados)


# ══════════════════════════ PG10 · quebra da ordem cronológica de pagamento (Pulo 10) ══════════════════════════

ORDEM_DIAS, ORDEM_POSTERIORES, ORDEM_TOP = 30, 10, 150
# vinculações de pagamento que NÃO são contrato de fornecimento/serviço/obra (folha, tributos, judiciais, dívida)
_VINC_FORA = ("1 -", "84 -", "87 -", "88 -", "93 -")
# credor que é ente ou órgão público: repasse (fundo a fundo, convênio, tributo), não contrato do art. 141
_ENTE_PUBLICO = re.compile(r"\b(FUNDO|PREFEITURA|MUNIC[IÍ]PIO|SECRETARIA|MINIST[EÉ]RIO|TRIBUNAL|INSS|INSTITUTO NACIONAL|"
                           r"RECEITA FEDERAL|FAZENDA|TESOURO|ESTADO D[OE]|UNI[AÃ]O|C[AÂ]MARA|ASSEMBL[EÉ]IA|DEFENSORIA|"
                           r"PROCURADORIA|AUTARQUIA|RIOPREVID[EÊ]NCIA|CAIXA ECON[OÔ]MICA|BANCO DO BRASIL)\b", re.I)


def ordem_cronologica(c) -> dict:
    meta = ("PG10", 10, "Quebra da ordem cronológica de pagamento",
            f"Por UG, exercício e vinculação de pagamento (aproximação da fonte), entre credores pessoa jurídica que não "
            f"são ente ou órgão público (repasse não é contrato): "
            f"liquidação (NL) cujo PRIMEIRO pagamento por OB contabilizada saiu depois de {ORDEM_POSTERIORES} ou mais "
            f"liquidações de numeração POSTERIOR terem sido pagas com pelo menos {ORDEM_DIAS} dias de antecedência. A "
            "numeração da NL é sequencial na UG: número maior = liquidada depois.",
            "Lei 14.133/2021, art. 141, §§1º a 3º; Decreto RJ 49.134/2024, arts. 9º, 10 e 21 a 24; Lei 4.320/1964, art. 63",
            "ob_orcamentaria_siafe (campo nl)")
    if not _tem(c, "ob_orcamentaria_siafe"):
        return _sem_fonte(*meta)
    linhas = c.execute(f"""
        SELECT ug_emitente, exercicio, vinculacao_pagamento, nl, MIN({_ISO}), SUM(valor), MAX(credor), MAX(nome_credor),
               MIN(numero_ob), MAX(processo)
        FROM ob_orcamentaria_siafe
        WHERE status='Contabilizado' AND tipo_ob='Orçamentária' AND length(credor)=14
          AND nl LIKE (CAST(exercicio AS TEXT) || 'NL%')
        GROUP BY ug_emitente, exercicio, vinculacao_pagamento, nl""").fetchall()
    grupos = defaultdict(list)
    for ug, ex, vinc, nl, d, v, cnpj, nome, ob, proc in linhas:
        if (vinc or "").startswith(_VINC_FORA) or _ENTE_PUBLICO.search(nome or ""):
            continue
        try:
            grupos[(ug, int(ex), vinc)].append((int(nl[6:]), date.fromisoformat(d).toordinal(), v, cnpj, nome, nl, ob,
                                                proc, d))
        except (ValueError, TypeError):
            continue
    base, cand = 0, []
    for (ug, ex, vinc), lst in grupos.items():
        lst.sort(reverse=True)                      # da NL mais nova para a mais antiga
        pagas: list[tuple[int, float]] = []         # (dia do pagamento, valor) das NL posteriores
        dias: list[int] = []
        for seq, dia, v, cnpj, nome, nl, ob, proc, d in lst:
            base += 1
            n = bisect.bisect_right(dias, dia - ORDEM_DIAS)
            if n >= ORDEM_POSTERIORES:
                cand.append((v, ug, ex, vinc, nome, cnpj, nl, ob, proc, d, n,
                             sum(x[1] for x in pagas if x[0] <= dia - ORDEM_DIAS)))
            i = bisect.bisect_left(dias, dia)
            dias.insert(i, dia)
            pagas.insert(i, (dia, v))
    cand.sort(reverse=True)
    achados = [_ach(
        ex, int(d[5:7]), f"{nome} — UG {ug}: {nl} paga depois de {n} liquidações posteriores",
        f"Primeira OB ({ob}) em {d[8:]}/{d[5:7]}/{d[:4]}, {brl(v)}. Antes dela, com {ORDEM_DIAS} dias ou mais de "
        f"antecedência, foram pagas {n} liquidações de número posterior ({brl(vp)}) na mesma vinculação “{vinc}”."
        + (f" Processo {proc}." if proc else "") + " Pedir a justificativa prévia publicada (art. 141, §1º) ou a "
        "pendência que reteve o pagamento.", v, "pago por OB contabilizada (valor da liquidação preterida)", PENDENTE,
        "a ordem de liquidação foi inferida do número da NL e a fonte, da vinculação de pagamento; falta a data da "
        "liquidação, a categoria do contrato e a justificativa — conferir no SIAFE e no processo",
        f"SIAFE-Rio, OB Orçamentária, UG {ug}, exercício {ex}: {ob} (liquidação {nl})", cnpj=cnpj, ug=ug,
        posteriores=n, valor_posteriores=vp) for v, ug, ex, vinc, nome, cnpj, nl, ob, proc, d, n, vp in cand[:ORDEM_TOP]]
    det = _det(*meta, _prev("liquidação (NL) paga a pessoa jurídica", base, len(cand)),
               ["A ordem do art. 141 é por FONTE e por CATEGORIA de contrato (fornecimento, locação, serviço, obra): "
                "liquidações de categorias diferentes não concorrem entre si.",
                "Pendência do próprio credor (certidão vencida, conta bancária, nota fiscal devolvida, retenção).",
                "Hipóteses do §1º do art. 141 com justificativa prévia: calamidade, microempresa em risco, serviço "
                "essencial, falência ou recuperação judicial.", "Ordem judicial; pagamento em parcelas."],
               ["A vinculação de pagamento é aproximação da fonte de recursos, não a fonte.",
                "A data da liquidação só existe para as UGs com NL coletada; a regra usa o número da NL.",
                "Total do SIAFE na base é PISO (cobertura parcial): liquidação posterior não coletada não entra na conta."],
               achados)
    det["total_acionados"] = len(cand)
    det["valor_acionados"] = sum(x[0] for x in cand)
    return det


# ══════════════════════════ PG15 · mínimos de saúde e educação fechados com RP (Pulo 15) ══════════════════════════

_FUNCOES = {"Saúde": ("Despesas com Ações e Serviços Públicos de Saúde%", "Saúde (ASPS)"),
            "Educação": ("Mínimo Anual de <18%", "Educação (MDE)")}


def minimos_com_restos_a_pagar(ca) -> dict:
    meta = ("PG15", 15, "Mínimos de saúde e educação fechados com restos a pagar",
            "No 6º bimestre: FOLGA do índice (percentual aplicado − mínimo, convertida em R$ pela proporção do valor "
            "apurado) contra os restos a pagar NÃO processados inscritos na função (RREO, Anexo 02). Acende quando os RP "
            "não processados da função são maiores que a folga: o mínimo só fecha se esses empenhos virarem despesa. "
            "Índice declarado abaixo do mínimo também acende.",
            "CF, arts. 198, §2º, 212 e 212-A; LC 141/2012, arts. 6º e 24, §§1º e 2º; Lei 14.113/2020",
            "siconfi_rreo (RREO, Anexos 02, 07 e 14)")
    if not _tem(ca, "siconfi_rreo"):
        return _sem_fonte(*meta)
    anos = [r[0] for r in ca.execute("SELECT DISTINCT exercicio FROM siconfi_rreo WHERE anexo='RREO-Anexo 14' "
                                     "AND periodo=6 ORDER BY 1")]
    if not anos:
        return _sem_fonte(*meta)
    achados, base, acionados = [], 0, 0
    for ex in anos:
        canc = ca.execute("SELECT valor FROM siconfi_rreo WHERE anexo='RREO-Anexo 07' AND exercicio=? AND conta LIKE "
                          "'TOTAL (III)%' AND coluna LIKE 'Cancelados (j)' ORDER BY periodo DESC LIMIT 1",
                          (ex + 1,)).fetchone()
        for funcao, (conta14, rotulo) in _FUNCOES.items():
            ind = _rreo(ca, "RREO-Anexo 14", ex, 6, conta14)
            fn = {col: v for col, v in ca.execute(
                "SELECT coluna, valor FROM siconfi_rreo WHERE anexo='RREO-Anexo 02' AND exercicio=? AND periodo=6 AND "
                "conta=? AND cod_conta='RREO2TotalDespesas'", (ex, funcao))}
            if not ind or not fn:
                continue
            base += 1
            apurado, minimo, aplicado = (_col(ind, "Valor Apurado"), _col(ind, "% Mínimo"), _col(ind, "% Aplicado"))
            rpnp, emp = _col(fn, "INSCRITAS EM RESTOS"), _col(fn, "EMPENHADAS ATÉ")
            folga = apurado * (aplicado - minimo) / aplicado if aplicado else 0.0
            abaixo, depende = aplicado < minimo, 0 <= folga < rpnp
            if abaixo or depende:
                acionados += 1
            achados.append(_ach(
                ex, 12, f"{rotulo} em {ex}: {str(aplicado).replace('.', ',')}% aplicados, mínimo "
                f"{str(minimo).replace('.', ',')}%" + (" — ABAIXO do mínimo declarado" if abaixo else
                                                       " — folga menor que os RP não processados" if depende else ""),
                f"Valor apurado no índice: {brl(apurado)}; folga sobre o mínimo: {brl(folga)}. Função {funcao} (toda a "
                f"função, não só o que entra no índice): empenhado {brl(emp)}, dos quais {brl(rpnp)} inscritos em RP não "
                f"processados ({pct(rpnp / emp) if emp else '—'}). "
                + (f"Em {ex + 1} o Estado cancelou {brl(canc[0])} de RP não processados no total (todas as funções)."
                   if canc and canc[0] else f"Cancelamento de RP em {ex + 1}: INDISPONÍVEL."),
                rpnp, "inscrito em restos a pagar não processados (empenhado e não liquidado)", PENDENTE,
                "autodeclarado ao SICONFI; o RJ não entrega os Anexos 08 e 12 do RREO — a composição do índice está no "
                "SIOPE/SIOPS e no parecer prévio do TCE-RJ", f"SICONFI/Tesouro, RREO Anexos 14 e 02, RJ, {ex}, 6º bimestre",
                acende=abaixo or depende, folga=folga, aplicado=aplicado, minimo=minimo))
    return _det(*meta, _prev("índice (saúde ou educação) × exercício encerrado", base, acionados),
                ["RP não processado de dezembro liquidado e pago normalmente no início do ano seguinte.",
                 "A LC 141/2012 admite RP no cômputo da saúde até o limite da disponibilidade de caixa vinculada.",
                 "Índice abaixo do mínimo no SICONFI por diferença de metodologia com o TCE-RJ (base de cálculo)."],
                ["O RP da FUNÇÃO inclui despesa que não entra no índice (fontes federais, inativos): é teto, não medida.",
                 "O cancelamento do ano seguinte é do Estado todo; não há cancelamento por função na base.",
                 "Os Anexos 08 (MDE) e 12 (saúde) do RREO do RJ não existem no SICONFI (conferido na API em 13/11/2026)."],
                achados)


# ══════════════════════════ manual ao lado de cada achado ══════════════════════════

def trechos_do_manual(caminho: Path | None = None) -> dict[int, dict]:
    """{nº do pulo: {titulo, campos: {rótulo: texto}}} lido do manual do vault (capítulo 11). Manual ausente = {}."""
    caminho = Path(caminho or MANUAL)
    if not caminho.is_file():
        return {}
    out: dict[int, dict] = {}
    for bloco in re.split(r"^### PULO ", caminho.read_text(encoding="utf-8"), flags=re.M)[1:]:
        m = re.match(r"(\d+)\.\s*(.+)", bloco)
        if not m:
            continue
        campos = {}
        for rot, txt in re.findall(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", bloco, re.M):
            campos[rot] = txt
        out[int(m.group(1))] = {"titulo": m.group(2).strip(), "campos": campos}
    return out


# ══════════════════════════ orquestração ══════════════════════════

def _decs(c, memo: dict) -> list[dict] | None:
    """Os decretos são lidos uma vez por rodada (a varredura do texto do DOERJ é a parte cara)."""
    if "decs" not in memo:
        memo["decs"] = decretos_de_credito(_textos_decreto(c)) if _tem(c, "publicacoes_doerj") else None
    return memo["decs"]


DETECTORES = (
    ("PG01", lambda c, ca, m: suplementacao_por_decreto(c, ca, _decs(c, m))),
    ("PG03", lambda c, ca, m: dea_recorrente(c)),
    ("PG04", lambda c, ca, m: restos_a_pagar(ca)),
    ("PG05", lambda c, ca, m: caixa_art_42(ca)),
    ("PG06", lambda c, ca, m: troca_de_fonte(c, ca, _decs(c, m))),
    ("PG07", lambda c, ca, m: reserva_de_contingencia(c, ca)),
    ("PG09", lambda c, ca, m: empenho_em_dezembro(c, ca)),
    ("PG10", lambda c, ca, m: ordem_cronologica(c)),
    ("PG15", lambda c, ca, m: minimos_com_restos_a_pagar(ca)),
)

RESSALVA = ("Indício não é acusação: cada item descreve um padrão que pode ser regular. VERIFICADO e PENDENTE falam do "
            "NÚMERO (se foi conferido), não da irregularidade. Empenho, dotação e restos a pagar nunca são “pago”: só "
            "a OB contabilizada é pagamento. Totais do SIAFE na base são piso.")


def rodar(db: Path | None = None, db_abertos: Path | None = None, manual: Path | None = None) -> dict:
    """Roda todos os detectores (somente leitura) e devolve o painel. Detector que quebra não derruba os outros:
    aparece com o erro, em estado INDISPONÍVEL."""
    c, ca = _ro(db or DB), _ro(db_abertos or DB_ABERTOS)
    dets, memo = [], {}
    try:
        for id_, fn in DETECTORES:
            try:
                dets.append(fn(c, ca, memo))
            except sqlite3.Error as exc:
                dets.append(_det(id_, 0, f"{id_}: falhou", "", "", "", _prev("—", 0, 0), [], [],
                                 [_ach(None, None, "Detector falhou", f"{type(exc).__name__}: {exc}", None, "—",
                                       INDISPONIVEL, "erro de banco", id_)]))
    finally:
        for con in (c, ca):
            if con is not None:
                con.close()
    man = trechos_do_manual(manual)
    for d in dets:
        d["manual"] = man.get(d["pulo"])
        d["estados"] = dict(Counter(a["estado"] for a in d["achados"]))
    anos = sorted({a["ano"] for d in dets for a in d["achados"] if a["ano"]}, reverse=True)
    return {"ok": True, "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"), "detectores": dets, "anos": anos,
            "ressalva": RESSALVA, "manual_lido": bool(man)}


def gravar(painel: dict, saida: Path | None = None) -> Path:
    saida = Path(saida or SAIDA)
    tmp = saida.with_suffix(".tmp")
    tmp.write_text(json.dumps(painel, ensure_ascii=False), encoding="utf-8")
    tmp.replace(saida)
    return saida


def ler(saida: Path | None = None) -> dict | None:
    saida = Path(saida or SAIDA)
    if not saida.is_file():
        return None
    return json.loads(saida.read_text(encoding="utf-8"))


def filtrar(painel: dict, ano: int | None = None, mes: int | None = None) -> dict:
    """Recorte por ano e mês. Achado anual (mes None) aparece em qualquer mês do seu ano."""
    out = {**painel, "filtro": {"ano": ano, "mes": mes}, "detectores": []}
    for d in painel.get("detectores", []):
        ach = [a for a in d["achados"] if (not ano or a["ano"] == ano or a["ano"] is None)
               and (not mes or a["mes"] in (None, mes))]
        out["detectores"].append({**d, "achados": ach, "n_total": len(d["achados"])})
    return out
