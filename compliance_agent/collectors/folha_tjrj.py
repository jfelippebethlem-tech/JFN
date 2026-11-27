# -*- coding: utf-8 -*-
"""folha_tjrj — coletor da FOLHA do Tribunal de Justiça do RJ (Anexo VIII CNJ).

Fluxo (ASP.NET WebForms, reverse-engineering 2026-07-17):
  1. GET  https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx  → __VIEWSTATE etc.
  2. POST (grConsulta=rbDetalhada + ddlMes + ddlAno + btnPesqGeral) → resposta traz
     <a id="ctl00_ConteudoPrincipal_lnkFile" href="…/GEDCacheWeb/…?GEDID=…"> (o ZIP do mês).
  3. GET do GEDID → ZIP com 1 HTML (Excel export) — tabela Anexo VIII: Nome | Lotação | Cargo | valores.

Sem CPF (o TJ não publica no Anexo VIII) — o cruzamento nomeados×candidatos é por NOME.
Grava direto em `registros_folha` (mesmo DB), órgão TJRJ. Certificado TLS incompleto → verify=False
(dado público, só-leitura; nenhuma credencial trafega).
"""
from __future__ import annotations

import io
import re
import warnings
import zipfile
from datetime import date

import httpx

from compliance_agent.collectors.arquivos import abrir_banco
from compliance_agent.collectors.formato import valor_br

warnings.filterwarnings("ignore")
_URL = "https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx"
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_FONTE = "tjrj_anexo8"
_ORGAO = ("TJRJ", "Tribunal de Justiça do Estado do RJ")


def _field(html: str, nome: str) -> str:
    m = re.search(rf'name="{re.escape(nome)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _cells(row: str) -> list[str]:
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).strip()
            for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def baixar_mes(ano: int, mes: int, cli: httpx.Client) -> list[dict]:
    """Baixa e parseia a folha (Anexo VIII) de um mês. [] se o mês não tem arquivo."""
    h = cli.get(_URL).text
    data = {
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": _field(h, "__VIEWSTATE"), "__VIEWSTATEGENERATOR": _field(h, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _field(h, "__EVENTVALIDATION"),
        "ctl00$ConteudoPrincipal$grConsulta": "rbDetalhada",
        "ctl00$ConteudoPrincipal$ddlMes": str(mes), "ctl00$ConteudoPrincipal$ddlAno": str(ano),
        "ctl00$ConteudoPrincipal$btnPesqGeral": "Pesquisar",
    }
    h2 = cli.post(_URL, data=data).text
    m = re.search(r'id="ctl00_ConteudoPrincipal_lnkFile"[^>]*href="([^"]+)"', h2) \
        or re.search(r'href="([^"]+GEDID=[^"]+)"', h2)
    if not m:
        return []
    return parsear(_texto_do_arquivo(cli.get(m.group(1)).content), f"{ano}-{mes:02d}")


def _texto_do_arquivo(blob: bytes) -> str:
    """O GED entregava um ZIP com 1 HTML; desde 2026 entrega o HTML direto (37 MB). 27/11/2026: o coletor só aceitava
    ZIP, descartava o HTML e concluía «sem publicação» — 06 e 08/2026 existiam e nunca entraram. Outro formato = ''."""
    if blob[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(blob))
        return zf.read(zf.namelist()[0]).decode("latin-1", errors="replace")
    if blob.lstrip()[:1] == b"<":
        return blob.decode("latin-1", errors="replace")
    return ""


def parsear(txt: str, comp: str) -> list[dict]:
    """Linhas de servidor da tabela Anexo VIII (puro, sem rede)."""
    out: list[dict] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cs = _cells(row)
        # linha de servidor: nome (letras maiúsculas) + lotação + cargo + valores
        if len(cs) < 4 or not re.search(r"[A-ZÀ-Ú]{3,}", cs[0]) or "nome" in cs[0].lower():
            continue
        nome, lotacao, cargo = cs[0], cs[1], cs[2]
        if not nome or nome.lower() in ("nome", "total", "totais") or len(nome) < 4:
            continue
        # total de créditos = maior valor monetário da linha (proxy robusto do bruto)
        bruto = max(((valor_br(x) or 0.0) for x in cs[3:] if "," in x), default=0.0)
        if not cargo and not lotacao and not bruto:      # título de seção da planilha («ANEXO VIII», «MAGISTRADOS»…)
            continue
        out.append({"nome": nome, "lotacao": lotacao, "cargo": cargo, "competencia": comp,
                    "bruto": bruto})
    return out


def ingerir(regs: list[dict]) -> int:
    """Dedup em memória (1 leitura) + INSERT em lote (executemany) — evita 21k queries sob lock."""
    if not regs:
        return 0
    con = abrir_banco()
    con.execute("PRAGMA busy_timeout=60000")
    try:
        # 27/11/2026: a chave NÃO tinha o mês — quem já aparecera nunca era gravado nos meses seguintes (só os novos
        # entravam, com o mês da 1ª aparição). Agora é foto por competência.
        existentes = {(n, c, k) for n, c, k in con.execute(
            "SELECT nome, cargo, competencia FROM registros_folha WHERE fonte=?", (_FONTE,))}
        novos = [r for r in regs if (r["nome"], r["cargo"], r["competencia"]) not in existentes]
        # dedup interno do lote (o Anexo VIII repete nome em várias faixas)
        vistos: set = set()
        linhas = []
        for r in novos:
            k = (r["nome"], r["cargo"], r["competencia"])
            if k in vistos:
                continue
            vistos.add(k)
            linhas.append(("", r["nome"], _ORGAO[0], _ORGAO[1], r["cargo"], r["lotacao"],
                           r["competencia"], r["bruto"], _FONTE))
        con.executemany(
            "INSERT INTO registros_folha (cpf,nome,orgao_codigo,orgao_nome,cargo,vinculo,competencia,"
            "remuneracao_bruta,remuneracao_liquida,abonos,descontos,fonte,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,0,0,?,datetime('now'))", linhas)
        con.commit()
        return len(linhas)
    finally:
        con.close()


ANO_INICIAL = 2023          # o seletor do portal começa em 2023: antes disso a fonte não publica (INDISPONÍVEL)


def coletar(max_meses: int = 6) -> dict:
    """Folha por competência desde 2023-01 até o mês corrente (dono 27/11/2026: «desde 2020» — o TJRJ só publica a
    partir de 2023). Coleta os meses que FALTAM no banco, do mais recente para trás, no máximo `max_meses` com
    arquivo por execução (cada um ~37 MB). Mês sem publicação («Não existem dados») é declarado, nunca zero."""
    hoje = date.today()
    con = abrir_banco()
    try:
        tem = {c for (c,) in con.execute("SELECT DISTINCT competencia FROM registros_folha WHERE fonte=?", (_FONTE,))}
    finally:
        con.close()
    alvo, y, m = [], hoje.year, hoje.month
    while (y, m) >= (ANO_INICIAL, 1):
        if f"{y}-{m:02d}" not in tem:
            alvo.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    res = {"ok": True, "coletadas": [], "sem_publicacao": [], "faltam": 0}
    with httpx.Client(verify=False, timeout=180, headers=_H, follow_redirects=True) as cli:
        for (y, m) in alvo:
            if len(res["coletadas"]) >= max_meses:
                break
            regs = baixar_mes(y, m, cli)
            if regs:
                res["coletadas"].append(f"{y}-{m:02d}:{ingerir(regs)}")
            else:
                res["sem_publicacao"].append(f"{y}-{m:02d}")
    res["faltam"] = len(alvo) - len(res["coletadas"]) - len(res["sem_publicacao"])
    return res


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False))
