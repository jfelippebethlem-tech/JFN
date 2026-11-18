# -*- coding: utf-8 -*-
"""citacoes — vault, cérebro e documentos CITAM o fato pelo id; este verificador acusa quem diverge.

Duas formas de um texto carregar um número de fato:

  1. CITAÇÃO (âncora): o número seguido de `<!--fato:ID-->` (comentário HTML: invisível na leitura do Obsidian,
     indexado pelo cérebro junto com o texto). Ex.: `R$ 2.437.189,45<!--fato:iss_nao_retido:00801512000157:180100:valor-->`.
     O verificador compara o número escrito com a versão vigente do fato; `sincronizar` reescreve o número (só o
     número, só com JFN_CERTEZA_SINCRONIZAR=1) — é o que faz nota e painel mudarem JUNTOS quando a fonte muda.
  2. MENÇÃO LIVRE: texto sem âncora. O registro guarda todas as versões do fato; um texto que repete o valor de
     uma versão SUPERADA está desatualizado — acusado com arquivo e linha (regras em `mencoes_superadas`).
     Valor monetário casa ao centavo; contagem só casa como "<número> <medida>" no parágrafo que também cita o
     fornecedor/objeto (apelido) e o assunto (termo) do fato. Parágrafo com `<!--fato-historico-->` é narrativa
     de histórico e fica fora.

Cérebro: o registro local de memórias (`propagacao.db › cerebro`) é varrido como texto; o índice remoto é consultado
pelo valor superado (teto de consultas por ciclo) — trecho antigo que o índice ainda serve é divergência do ÍNDICE.
Divergências têm ciclo de vida: aberta → curada → REINCIDIU (mesmo desenho da fila de automelhoria).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

from . import config, fatos, portoes

RE_ANCORA = re.compile(r"(?P<num>R\$\s?-?[\d.]+,\d{2}|-?\d{1,3}(?:\.\d{3})+(?:,\d+)?%?|-?\d+(?:,\d+)?%?)(?P<meio>[*_`]{0,3}\s?)"
                       r"<!--\s*fato:(?P<id>[A-Za-z0-9_.:\-]+)\s*-->")
HISTORICO = "<!--fato-historico-->"
_GENERICOS = {"INSTITUTO", "CONSTRUTORA", "FUNDACAO", "ASSOCIACAO", "EMPRESA", "CENTRO", "COMPANHIA", "SOCIEDADE",
              "SERVICOS", "COMERCIO", "CONSORCIO", "GRUPO", "BANCO", "FUNDO", "LTDA", "COOPERATIVA"}
DDL = """
CREATE TABLE IF NOT EXISTS divergencia(chave TEXT PRIMARY KEY, tipo TEXT, fato_id TEXT, superficie TEXT, local TEXT,
  encontrado TEXT, esperado TEXT, aberta_em REAL, vista_em REAL, fechada_em REAL, reincidencias INTEGER DEFAULT 0);
"""


def numero(txt: str) -> float | None:
    s = txt.replace("R$", "").replace("%", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _igual(a: float, b: float, unidade: str) -> bool:
    return abs(a - b) < (0.005 if unidade == "BRL" else 0.05 if unidade == "percentual" else 0.5)


def ancoras(texto: str):
    """(match, id do fato, número escrito) de cada citação."""
    for m in RE_ANCORA.finditer(texto):
        yield m, m.group("id"), numero(m.group("num"))


def conferir_citacoes(texto: str, vig: dict[str, dict]) -> list[dict]:
    out = []
    for m, fid, n in ancoras(texto):
        f = vig.get(fid)
        linha = texto.count("\n", 0, m.start()) + 1
        if f is None:
            out.append({"tipo": "citacao_de_fato_inexistente", "fato_id": fid, "linha": linha,
                        "encontrado": m.group("num"), "esperado": "fato registrado"})
        elif f["valor"] is None or n is None or not _igual(n, f["valor"], f["unidade"]):
            out.append({"tipo": "citacao_divergente", "fato_id": fid, "linha": linha, "encontrado": m.group("num"),
                        "esperado": fatos.formatar(f["valor"], f["unidade"])})
    return out


def sincronizar(texto: str, vig: dict[str, dict]) -> tuple[str, int]:
    """Reescreve o número de cada citação divergente pelo valor vigente (só o número; o resto do texto fica)."""
    n = 0

    def troca(m: re.Match) -> str:
        nonlocal n
        f = vig.get(m.group("id"))
        v = numero(m.group("num"))
        if f is None or f["valor"] is None or (v is not None and _igual(v, f["valor"], f["unidade"])):
            return m.group(0)
        n += 1
        return fatos.formatar(f["valor"], f["unidade"]) + m.group("meio") + f"<!--fato:{m.group('id')}-->"
    return RE_ANCORA.sub(troca, texto), n


def citar(fato: dict) -> str:
    """O texto pronto para colar numa nota: número vigente + âncora."""
    return f"{fatos.formatar(fato['valor'], fato['unidade'])}<!--fato:{fato['fato_id']}-->"


# ───────────────────────────── menção livre a valor superado ─────────────────────────────
def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def alvos(con: sqlite3.Connection) -> list[dict]:
    """Um alvo por fato com valor superado: {fato_id, unidade, vigente, superados, apelidos, termos}."""
    out = []
    for f in fatos.vigentes(con):
        if f["valor"] is None:
            continue
        meta = json.loads(f["meta"] or "{}")
        antigos = {round(float(h["valor"]), 2) for h in fatos.historico(con, f["fato_id"]) if h["valor"] is not None}
        antigos |= {round(float(x), 2) for x in meta.get("superados", [])}
        antigos = {a for a in antigos if not _igual(a, f["valor"], f["unidade"])}
        if not antigos:
            continue
        ap = set()
        for a in meta.get("apelidos", []):
            a = _sem_acento(str(a))
            ap.add(a)
            prim = re.split(r"[^A-Z0-9]+", a)[0]
            if len(prim) >= 4 and prim not in _GENERICOS:
                ap.add(prim)
        out.append({"fato_id": f["fato_id"], "unidade": f["unidade"], "vigente": f["valor"], "superados": sorted(antigos),
                    "medida": meta.get("medida") or f["fato_id"].rsplit(":", 1)[-1],
                    "apelidos": sorted(ap), "termos": [_sem_acento(t) for t in meta.get("termos", [])]})
    return out


def _rx_num(v: float, unidade: str) -> re.Pattern:
    s = fatos.formatar(v, unidade).replace("R$ ", "")
    return re.compile(r"(?<![\d.,/])" + re.escape(s) + r"(?![\d/]|[.,]\d)")


def _tem(texto_maiusculo: str, palavras: list[str]) -> bool:
    """Alguma das palavras aparece em INÍCIO de palavra ("ISS" casa "ISSQN", não "COMISSÃO")."""
    return any(re.search(r"(?<![A-Z0-9])" + re.escape(p), texto_maiusculo) for p in palavras if p)


def mencoes_superadas(texto: str, alvos_: list[dict]) -> list[dict]:
    """Menção livre a valor superado. A unidade de contexto é o PARÁGRAFO (linhas seguidas sem linha em branco —
    nota com quebra dura de linha parte a frase no meio; medido na nota da AGILE em 18/11/2026: "Em 35\nprocessos").
      · BRL: o valor antigo, ao centavo, num parágrafo que NÃO traz o valor vigente;
      · contagem: "<antigo> <medida>" (ex.: "35 processos") num parágrafo que cita o apelido e o termo do fato.
    Parágrafo com `<!--fato-historico-->` é narrativa de histórico e fica fora."""
    candidatos = []
    for a in alvos_:
        for antigo in a["superados"]:
            if a["unidade"] == "BRL":
                if abs(antigo) >= 1000:                      # valor pequeno casa por acaso: fora
                    candidatos.append((a, antigo, _rx_num(antigo, "BRL")))
            elif a["apelidos"] and a["termos"] and re.fullmatch(r"[a-zà-ú]+", a["medida"] or ""):
                n = re.escape(fatos.formatar(antigo, a["unidade"]))
                candidatos.append((a, antigo, re.compile(r"(?<![\d.,/])" + n + r"\s+" + re.escape(a["medida"]) + r"\b", re.I)))
    candidatos = [c for c in candidatos if c[2].search(texto)]
    if not candidatos:
        return []
    out = []
    for m in re.finditer(r"(?:[^\n]*\S[^\n]*(?:\n|$))+", texto):       # parágrafos
        par = m.group(0)
        if HISTORICO in par:
            continue
        for a, antigo, rx in candidatos:
            for achado in rx.finditer(par):
                if par[achado.end():].lstrip("*_` ").startswith("<!--fato:" + a["fato_id"]):
                    continue                                   # é uma citação: quem julga é `conferir_citacoes`
                if a["unidade"] == "BRL":
                    if _rx_num(a["vigente"], "BRL").search(par):
                        continue
                else:
                    up = _sem_acento(par)
                    if not (_tem(up, a["apelidos"]) and _tem(up, a["termos"])):
                        continue
                out.append({"tipo": "mencao_a_valor_superado", "fato_id": a["fato_id"],
                            "linha": texto.count("\n", 0, m.start() + achado.start()) + 1,
                            "encontrado": fatos.formatar(antigo, a["unidade"]),
                            "esperado": fatos.formatar(a["vigente"], a["unidade"])})
    return out


# ───────────────────────────── superfícies ─────────────────────────────
def arquivos(sup: dict, raiz: Path | None = None):
    pasta = Path(os.path.expanduser(str(sup["pasta"])))
    pasta = pasta if pasta.is_absolute() else (raiz or config.REPO) / pasta
    ign = [str(x) for x in sup.get("ignorar", [])]
    for arq in sorted(pasta.glob(sup.get("glob", "**/*.md"))):
        rel = str(arq.relative_to(pasta))
        if arq.is_file() and not any(rel.startswith(i) or f"/{i}" in "/" + rel for i in ign):
            yield arq, rel


def varrer(con: sqlite3.Connection, superficies: dict, raiz: Path | None = None, aplicar: bool = False,
           prop_db: Path | None = None, buscar=None) -> dict:
    """Confere todas as superfícies. Devolve {divergencias, lidos, citacoes, sincronizados, indisponiveis}.
    `aplicar` reescreve citações divergentes (exige a chave SINCRONIZAR). `buscar` = função de busca do cérebro."""
    vig = {f["fato_id"]: f for f in fatos.vigentes(con)}
    alv = alvos(con)
    aplicar = aplicar and config.ligado("SINCRONIZAR")
    div, lidos, ncit, sinc, indis, lidas = [], 0, 0, 0, [], set()
    for nome, sup in (superficies or {}).items():
        if "pasta" not in sup:
            continue
        lidas.add(nome)
        for arq, rel in arquivos(sup, raiz):
            if lidos >= config.TETO_ARQUIVOS_TEXTO:
                indis.append(f"{nome}: teto de {config.TETO_ARQUIVOS_TEXTO} arquivos atingido — o resto não foi lido")
                lidas.discard(nome)
                break
            try:
                if arq.stat().st_size > 2_000_000:
                    continue
                txt = arq.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                indis.append(f"{nome}/{rel}: {type(e).__name__}")
                continue
            lidos += 1
            ncit += sum(1 for _ in ancoras(txt)) if "<!--fato:" in txt else 0
            achados = (conferir_citacoes(txt, vig) if "<!--fato:" in txt else []) + mencoes_superadas(txt, alv)
            if aplicar and sup.get("sincronizar") and any(a["tipo"] == "citacao_divergente" for a in achados):
                novo, n = sincronizar(txt, vig)
                if n:
                    arq.write_text(novo, encoding="utf-8")
                    sinc += n
                    achados = [a for a in achados if a["tipo"] != "citacao_divergente"]
            for a in achados:
                div.append({**a, "superficie": nome, "local": f"{rel}:{a['linha']}"})
    cer = (superficies or {}).get("cerebro") or {}
    if cer.get("registro"):
        try:
            ro = sqlite3.connect(f"file:{prop_db or config.REPO / 'data' / 'propagacao.db'}?mode=ro", uri=True, timeout=10)
            try:
                for chave, conteudo in ro.execute("SELECT chave, conteudo FROM cerebro WHERE conteudo IS NOT NULL"):
                    for a in conferir_citacoes(conteudo, vig) + mencoes_superadas(conteudo, alv):
                        div.append({**a, "superficie": "cerebro_registro", "local": f"memória {chave}"})
                lidas.add("cerebro_registro")
            finally:
                ro.close()
        except sqlite3.Error as e:
            indis.append(f"registro local do cérebro: {type(e).__name__}: {e}")
    if cer.get("busca") and buscar:
        feitas, inteira = 0, True
        for a in alv:
            if a["unidade"] != "BRL":
                continue
            for antigo in a["superados"]:
                if feitas >= config.TETO_BUSCAS_CEREBRO:
                    inteira = False
                    break
                feitas += 1
                s_ant = fatos.formatar(antigo, "BRL").replace("R$ ", "")
                try:
                    achou = buscar(s_ant, 8)
                except (OSError, ValueError, RuntimeError) as e:
                    indis.append(f"busca no cérebro: {type(e).__name__}: {str(e)[:120]}")
                    inteira = False
                    break
                rx, rx_vig = _rx_num(antigo, "BRL"), _rx_num(a["vigente"], "BRL")
                for h in achou or []:
                    trecho = str(h.get("snippet") or h.get("content") or h.get("text") or "")
                    if rx.search(trecho) and not rx_vig.search(trecho) and HISTORICO not in trecho:
                        div.append({"tipo": "indice_do_cerebro_serve_valor_superado", "fato_id": a["fato_id"],
                                    "superficie": "cerebro_indice", "linha": 0,
                                    "local": f"{h.get('source', '?')}:{h.get('path', h.get('id', '?'))} › {str(h.get('heading') or '')[:80]}",
                                    "encontrado": fatos.formatar(antigo, "BRL"), "esperado": fatos.formatar(a["vigente"], "BRL")})
        if inteira:
            lidas.add("cerebro_indice")
    return {"divergencias": div, "lidos": lidos, "citacoes": ncit, "sincronizados": sinc, "indisponiveis": indis,
            "fatos_com_valor_superado": len(alv), "superficies_lidas": sorted(lidas)}


def conciliar(con: sqlite3.Connection, divergencias: list[dict], lidas: list[str] | None = None,
              agora: float | None = None) -> dict:
    """aberta → curada → REINCIDIU. A chave é (tipo, fato, superfície, local sem número de linha, valor encontrado):
    a nota que ganha uma linha acima não vira divergência nova. Só se dá por CURADA a divergência de superfície que
    foi lida inteira neste ciclo (`lidas`; None = todas) — superfície que não respondeu não cura nada."""
    agora = agora or time.time()
    con.executescript(DDL)
    vistas = set()
    novas = reinc = 0
    for d in divergencias:
        local = re.sub(r":\d+$", "", d["local"])
        chave = portoes.versao({"t": d["tipo"], "f": d["fato_id"], "s": d["superficie"], "l": local, "e": d["encontrado"]})
        if chave in vistas:
            continue
        vistas.add(chave)
        ant = con.execute("SELECT fechada_em FROM divergencia WHERE chave=?", (chave,)).fetchone()
        if ant is None:
            con.execute("INSERT INTO divergencia VALUES (?,?,?,?,?,?,?,?,?,NULL,0)",
                        (chave, d["tipo"], d["fato_id"], d["superficie"], d["local"], d["encontrado"], d["esperado"], agora, agora))
            novas += 1
        elif ant[0] is not None:
            con.execute("UPDATE divergencia SET fechada_em=NULL, vista_em=?, local=?, esperado=?, reincidencias=reincidencias+1 "
                        "WHERE chave=?", (agora, d["local"], d["esperado"], chave))
            reinc += 1
        else:
            con.execute("UPDATE divergencia SET vista_em=?, local=?, esperado=? WHERE chave=?", (agora, d["local"], d["esperado"], chave))
    curadas = 0
    for chave, sup in con.execute("SELECT chave, superficie FROM divergencia WHERE fechada_em IS NULL").fetchall():
        if chave not in vistas and (lidas is None or sup in lidas):
            con.execute("UPDATE divergencia SET fechada_em=? WHERE chave=?", (agora, chave))
            curadas += 1
    return {"novas": novas, "reincidiram": reinc, "curadas": curadas,
            "abertas": con.execute("SELECT COUNT(*) FROM divergencia WHERE fechada_em IS NULL").fetchone()[0]}


def abertas(con: sqlite3.Connection) -> list[dict]:
    con.executescript(DDL)
    cur = con.execute("SELECT tipo, fato_id, superficie, local, encontrado, esperado, aberta_em, reincidencias FROM divergencia "
                      "WHERE fechada_em IS NULL ORDER BY aberta_em")
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
