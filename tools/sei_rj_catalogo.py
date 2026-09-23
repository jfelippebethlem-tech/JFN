# -*- coding: utf-8 -*-
"""Catálogo dos processos do SEI do ESTADO (sei.rj.gov.br) pela pesquisa pública — sem login.

Como funciona (medido 23/09/2026; formato lido do fonte do módulo, github.com/anatelgovbr/mod-sei-pesquisa):
  1. GET do formulário + captcha (ddddocr) + POST do formulário abre a sessão;
  2. a lista vem SÓ pelo AJAX `md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar`,
     que honra o filtro Solr `partialfields` (`sta_prot:P AND id_tipo_proc:N`) e devolve {itens, html};
  3. o servidor fixa 50 linhas por página (rowsSolr maior é ignorado), ordena por dta_ger desc e
     aceita qualquer `inicio` (paginação profunda funciona);
  4. alguns registros do índice estão "envenenados": qualquer janela de 50 que os contenha responde
     XML `Atributo [StaProtocolo] não recebeu valor`. Como o `inicio` é livre, acha-se a posição do
     registro por busca binária e as janelas vizinhas cobrem o resto — o que não der para cobrir é
     CONTADO como perdido, nunca silenciado.
  Número do processo no filtro vai só com dígitos: `prot_pesq:*0800020028862024*` (controle positivo).
  Datas absolutas com ':' quebram a consulta; `dta_ger:[NOW-2DAYS TO NOW-1DAY]` funciona.
  A VM-2 não completa TLS com sei.rj.gov.br — roda na VM-1.

Escopo: tipos de processo de contratação/controle (regex TIPOS_ALVO sobre os 1.525 tipos do formulário:
82 tipos, 64.326 processos em 23/09/2026) — não os 9,3 milhões (a maioria é Detran).

    python -m tools.sei_rj_catalogo                 # varre todos os tipos-alvo (incremental)
    python -m tools.sei_rj_catalogo --completo      # re-varre tudo
    python -m tools.sei_rj_catalogo --tipos         # só lista tipos-alvo e contagens
"""
from __future__ import annotations

import argparse
import base64
import html as H
import json
import logging
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

log = logging.getLogger("sei_rj_catalogo")

DB = Path(__file__).resolve().parents[1] / "data" / "sei_rj_catalogo.db"
BASE = "https://sei.rj.gov.br/sei/modulos/pesquisa/"
FORM = BASE + ("md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar"
               "&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6")
AJAX = BASE + ("md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar"
               "&id_orgao_acesso_externo=6&isPaginacao=true&inicio={inicio}&rowsSolr=50")
PAGINA = 50
PAUSA = 0.6
TIPOS_ALVO = re.compile(r"^Contrata|Termo de Ajuste de Contas|Obras|Conv[eê]nio|Controle Interno|"
                        r"Reconhecimento de D[íi]vida|Emerg", re.I)
_UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"

DDL = """CREATE TABLE IF NOT EXISTS sei_rj_processo (
    numero TEXT PRIMARY KEY, tipo TEXT, id_tipo TEXT, unidade_sigla TEXT, unidade_nome TEXT,
    orgao TEXT, data TEXT, coletado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_sei_rj_processo_tipo ON sei_rj_processo(id_tipo);
CREATE INDEX IF NOT EXISTS ix_sei_rj_processo_orgao ON sei_rj_processo(orgao);
CREATE TABLE IF NOT EXISTS sei_rj_varredura (
    id_tipo TEXT PRIMARY KEY, tipo TEXT, itens INTEGER, coletados INTEGER, envenenados INTEGER,
    perdidos INTEGER, varrido_em TEXT);"""


class Envenenada(Exception):
    """Janela de 50 contém registro que o servidor não consegue renderizar."""


class SessaoCaiu(Exception):
    pass


def parse_linhas(html: str) -> list[dict]:
    """Linhas do HTML do AJAX: número, tipo, unidade (sigla e nome), data ISO."""
    saida = []
    for bloco in html.split('class="pesquisaTituloRegistro"')[1:]:
        m = re.search(r'data-prot="([^"]+)"', bloco)
        if not m:
            continue
        tipo = re.search(r'class="arvore" /></a>([^<]*?)\s*n(?:º|°|o|&ordm;)\s*<a', bloco)
        uni = re.search(r'<b>Unidade:</b>\s*<a[^>]*title="([^"]*)"[^>]*>([^<]*)</a>', bloco)
        dt = re.search(r"<b>Data:</b>\s*(\d{2})/(\d{2})/(\d{4})", bloco)
        sigla = H.unescape(uni.group(2)).strip() if uni else None
        saida.append({"numero": m.group(1).strip(), "tipo": H.unescape(tipo.group(1)).strip() if tipo else None,
                      "unidade_sigla": sigla, "unidade_nome": H.unescape(uni.group(1)).strip() if uni else None,
                      "orgao": sigla.split("/")[0] if sigla else None,
                      "data": f"{dt.group(3)}-{dt.group(2)}-{dt.group(1)}" if dt else None})
    return saida


def varrer_janelas(buscar, total: int, pagina: int = PAGINA) -> tuple[dict[int, dict], list[int], int]:
    """Cobre as posições [0, total) com janelas de `pagina` a partir de `inicio` livre.

    buscar(inicio) -> list[linha] ou levanta Envenenada. Devolve ({posição: linha}, envenenados, perdidos).
    Uma janela que falha tem ao menos um registro envenenado b em [i, i+pagina). O 1º início bom depois
    de i é b+1 (busca binária); o maior início bom antes de i, a partir do último envenenado, cobre até b-1.
    """
    linhas: dict[int, dict] = {}
    envenenados: list[int] = []
    cache: dict[int, list | None] = {}

    def tenta(s):
        if s not in cache:
            try:
                cache[s] = buscar(s)
            except Envenenada:
                cache[s] = None
        return cache[s]

    def guarda(s, rows):
        for k, r in enumerate(rows):
            if s + k < total:
                linhas.setdefault(s + k, r)

    i, piso = 0, 0          # piso = 1ª posição depois do último envenenado
    while i < total:
        rows = tenta(i)
        if rows is not None:
            guarda(i, rows)
            if not rows:
                break
            i += pagina
            continue
        # 1º início bom em (i, i+pagina] — ou nenhum (mais de um envenenado na faixa)
        lo, hi = i + 1, min(i + pagina, total)
        if hi < lo or tenta(hi) is None:
            depois = None
        else:
            while lo < hi:
                m = (lo + hi) // 2
                if tenta(m) is not None:
                    hi = m
                else:
                    lo = m + 1
            depois = lo
        b = (depois - 1) if depois is not None else min(i + pagina, total) - 1
        envenenados.append(b)
        # maior início bom em [piso, i) — cobre as posições até b-1 (inícios ≤ i-pagina nada acrescentam)
        lo, hi = max(piso, i - pagina + 1), i - 1
        melhor = None
        while lo <= hi:
            m = (lo + hi) // 2
            if tenta(m) is not None:
                melhor, lo = m, m + 1
            else:
                hi = m - 1
        if melhor is not None:
            guarda(melhor, tenta(melhor))
        if depois is not None:
            guarda(depois, tenta(depois))
            i = depois + pagina
        else:
            i = b + 1
        piso = b + 1
    faixa = range(0, total)
    perdidos = sum(1 for p in faixa if p not in linhas and p not in envenenados)
    return linhas, envenenados, perdidos


DIAS_MAX = 12_000        # ~1993; o registro mais antigo visto é de 2003


def faixa_dias(a: int, b: int) -> str:
    """Filtro Solr para 'gerado entre b e a dias atrás' ([b, a) em dias; a=-1 inclui hoje). Só aritmética
    de data — data absoluta com ':' quebra a consulta no servidor."""
    return f"dta_ger:[NOW/DAY{-b:+d}DAYS TO NOW/DAY{-a:+d}DAYS}}"


def coletar_por_data(pagina, base_pf: str, a: int = -1, b: int = DIAS_MAX, limite: int = PAGINA,
                     orgaos: list[str] | None = None) -> dict:
    """Bisseção por data e, dentro de um dia, por órgão gerador, até cada fatia caber numa página limpa.

    pagina(pf, inicio) -> (itens, linhas) ou levanta Envenenada. Só quando um único órgão num único dia
    ainda não abre usa janelas deslocadas. Devolve {linhas: {numero: linha}, envenenados, perdidos,
    fatias_perdidas} — fatia em que nenhuma janela abre entra em fatias_perdidas (quantidade
    desconhecida: INDISPONÍVEL, não zero)."""
    out = {"linhas": {}, "envenenados": 0, "perdidos": 0, "fatias_perdidas": []}
    pilha = [(a, b, None)]
    while pilha:
        a_, b_, orgs = pilha.pop()
        pf = f"{base_pf} AND {faixa_dias(a_, b_)}"
        if orgs:
            pf += " AND (" + " OR ".join(f"id_org_ger:{o}" for o in orgs) + ")"
        try:
            n, rows = pagina(pf, 0)
        except Envenenada:
            n, rows = None, None
        if rows is not None and n <= limite:
            out["linhas"].update((x["numero"], x) for x in rows)
            continue
        if b_ - a_ > 1:
            m = (a_ + b_) // 2
            pilha += [(m, b_, orgs), (a_, m, orgs)]
            continue
        lista = orgs if orgs is not None else (orgaos or [])
        if len(lista) > 1:
            m = len(lista) // 2
            pilha += [(a_, b_, lista[m:]), (a_, b_, lista[:m])]
            continue
        # um órgão num dia, ainda lotado ou envenenado: janelas deslocadas
        if n is None:
            for s in range(1, limite + 1):
                try:
                    n_s, rows_s = pagina(pf, s)
                except Envenenada:
                    continue
                n = n_s if rows_s else s          # janela vazia logo após envenenada: o total é s
                break
            if n is None:
                out["fatias_perdidas"].append((a_, lista[0] if lista else None))
                continue

        def buscar(ini, pf=pf):
            return pagina(pf, ini)[1]
        linhas, env, perd = varrer_janelas(buscar, n, limite)
        out["linhas"].update((x["numero"], x) for x in linhas.values())
        out["envenenados"] += len(env)
        out["perdidos"] += perd
    return out


class Sessao:
    def __init__(self, cliente=None):
        import httpx
        self.c = cliente or httpx.Client(headers={"User-Agent": _UA}, timeout=90, follow_redirects=True)
        self.form_html = ""
        self.orgaos: list[str] = []
        self._ocr = None

    def _captcha(self, h: str) -> str | None:
        """None quando a página veio sem a imagem (resposta transitória) — quem chama tenta de novo."""
        m = re.search(r'<img[^>]*id="imgCaptcha"[^>]*>', h)
        b64 = re.search(r'src="data:image/png;base64,([^"]+)"', m.group(0)) if m else None
        if not b64:
            return None
        if self._ocr is None:
            import ddddocr
            self._ocr = ddddocr.DdddOcr(show_ad=False)
        return re.sub(r"[^A-Za-z0-9]", "", self._ocr.classification(base64.b64decode(b64.group(1))))

    def abrir(self, tentativas: int = 8) -> None:
        for n in range(tentativas):
            h = self.c.get(FORM).text
            cap = self._captcha(h)
            if cap is None:
                log.info("formulário sem captcha (tentativa %d) — %d bytes", n + 1, len(h))
                time.sleep(5)
                continue
            ini = h.find('id="selOrgaoPesquisa"')
            orgs = re.findall(r'<option value="(\d+)"', h[ini:h.find("</select>", ini)])
            dados = [("txtProtocoloPesquisa", ""), ("q", "*"), ("chkSinProcessos", "P"), ("txtDataInicio", ""),
                     ("txtDataFim", ""), ("txtInfraCaptcha", cap), ("hdnInfraCaptcha", "1"),
                     ("sbmPesquisar", "Pesquisar"), ("partialfields", "sta_prot:P"), ("hdnFlagPesquisa", "1"),
                     ("hdnInfraPrefixoCookie", "ERJ_SEI_")] + [("selOrgaoPesquisa[]", o) for o in orgs]
            r = self.c.post(FORM, content=urllib.parse.urlencode(dados, encoding="iso-8859-1"),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
            if re.search(r"confirma[çc][ãa]o\s+(?:inv[áa]lid|incorret|n[ãa]o\s+confere)", r.text.lower()):
                log.info("captcha rejeitado (tentativa %d)", n + 1)
                continue
            self.form_html = r.text
            self.orgaos = orgs
            return
        raise SessaoCaiu("captcha rejeitado em todas as tentativas")

    def pagina(self, partialfields: str, inicio: int) -> tuple[int, list[dict]]:
        dados = [("q", "*"), ("partialfields", partialfields), ("chkSinProcessos", "P"), ("hdnFlagPesquisa", "1")]
        r = self.c.post(AJAX.format(inicio=inicio), content=urllib.parse.urlencode(dados),
                        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                 "X-Requested-With": "XMLHttpRequest", "Referer": FORM})
        time.sleep(PAUSA)
        try:
            j = r.json()
        except ValueError:
            if "StaProtocolo" in r.text:
                raise Envenenada(inicio)
            raise SessaoCaiu(r.text[:200])
        return int(j.get("itens") or 0), parse_linhas(j.get("html") or "")

    def tipos(self) -> list[tuple[str, str]]:
        h = self.form_html
        i = h.find('id="selTipoProcedimentoPesquisa"')
        ops = [(v, H.unescape(n).strip()) for v, n in re.findall(r'<option value="(\d+)"[^>]*>([^<]*)', h[i:h.find("</select>", i)])]
        return [o for o in ops if TIPOS_ALVO.search(o[1])]


def conectar(db=DB) -> sqlite3.Connection:
    con = sqlite3.connect(db, timeout=30)
    con.executescript(DDL)
    return con


def varrer_tipo(s: Sessao, con, id_tipo: str, tipo: str, incremental: bool) -> dict:
    """Um tipo de processo. Incremental: só os últimos 45 dias (processo novo entra por data de geração)."""
    pf = f"sta_prot:P AND id_tipo_proc:{id_tipo}"
    try:
        total = s.pagina(pf, 0)[0]
    except Envenenada:
        total = None
    tem = con.execute("SELECT 1 FROM sei_rj_varredura WHERE id_tipo=?", (id_tipo,)).fetchone()
    out = coletar_por_data(s.pagina, pf, b=45 if (incremental and tem) else DIAS_MAX, orgaos=s.orgaos)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con.executemany("INSERT OR REPLACE INTO sei_rj_processo VALUES (?,?,?,?,?,?,?,?)",
                    [(x["numero"], x["tipo"] or tipo, id_tipo, x["unidade_sigla"], x["unidade_nome"], x["orgao"], x["data"], agora)
                     for x in out["linhas"].values()])
    no_banco = con.execute("SELECT count(*) FROM sei_rj_processo WHERE id_tipo=?", (id_tipo,)).fetchone()[0]
    con.execute("INSERT OR REPLACE INTO sei_rj_varredura VALUES (?,?,?,?,?,?,?)",
                (id_tipo, tipo, total, no_banco, out["envenenados"], out["perdidos"] + len(out["fatias_perdidas"]), agora))
    con.commit()
    return {"id_tipo": id_tipo, "tipo": tipo, "itens": total, "coletados": len(out["linhas"]), "no_banco": no_banco,
            "envenenados": out["envenenados"], "perdidos": out["perdidos"], "fatias_perdidas": len(out["fatias_perdidas"])}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--tipos", action="store_true")
    ap.add_argument("--so", help="id_tipo único")
    a = ap.parse_args()
    s = Sessao()
    s.abrir()
    alvo = s.tipos()
    if a.so:
        alvo = [t for t in alvo if t[0] == a.so] or [(a.so, a.so)]
    if a.tipos:
        for v, n in alvo:
            print(v, s.pagina(f"sta_prot:P AND id_tipo_proc:{v}", 0)[0], n)
        return
    con = conectar()
    resumo = []
    for v, n in alvo:
        for tentativa in range(3):
            try:
                r = varrer_tipo(s, con, v, n, incremental=not a.completo)
                break
            except SessaoCaiu as e:
                log.warning("sessão caiu em %s (%s) — reabrindo", v, e)
                s = Sessao()
                s.abrir()
        else:
            r = {"id_tipo": v, "tipo": n, "erro": "sessão caiu 3×"}
        log.info("%s", r)
        resumo.append(r)
    con.close()
    print(json.dumps({"tipos": len(resumo), "coletados": sum(r.get("coletados", 0) for r in resumo),
                      "envenenados": sum(r.get("envenenados", 0) for r in resumo),
                      "perdidos": sum(r.get("perdidos", 0) for r in resumo)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
