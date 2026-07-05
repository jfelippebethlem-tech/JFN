# -*- coding: utf-8 -*-
"""Panorama AGREGADO das Organizações Sociais (OS) de saúde da Prefeitura do Rio.

Os RDP (Relatórios de Despesa de Pessoal) da CODESP são AGREGADOS — não publicam nomes
de empregados (ver memória `pcrj-modulo-cruzamento`), logo NÃO permitem cruzamento nominal.
Este módulo extrai o que a fonte oferece: por OS/unidade/competência, a despesa de pessoal
(soma por cargo), o headcount (soma das contagens por cargo) e o nº de cargos distintos.

Fonte: PDFs em controladoria.prefeitura.rio (padrão SMS-<OS>-RDP-<unidade>-<Mes><Ano>.pdf).
Banco DEDICADO `data/pcrj_os.db` (não toca a pcrj.db — zero contenção com outros sweeps).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import fitz
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DB = Path(__file__).resolve().parents[2] / "data" / "pcrj_os.db"
_MESES = {m: i for i, m in enumerate(
    ["Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho", "Julho", "Agosto",
     "Setembro", "Outubro", "Novembro", "Dezembro"], 1)}
_RE_CARGO = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú ./,()\-]{4,60}\([A-Z]{2,8}\))\s*\n\s*(\d{1,4})\s*\n\s*"
    r"([\d.]+,\d{2})\s*\n\s*([\d.]+,\d{2})")

# Semente de RDP (enumerados via busca; o índice do site é dinâmico). Extensível.
URLS_SEED = [
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/09/SMS-VIVARIO-RDP-SERV-PGCEE-HMPIEDADE-Agosto2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/04/SMS-VIVARIO-RDP-ATENCAO-PRIMARIA-PRISIONAL-Fevereiro2026.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/03/SMS-SPDM-RDP-HOSPITAL-PEDRO-II-Janeiro2026.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/03/SMS-SPDM-RDP-CAP-1.0-Janeiro2026.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/03/SMS-SPDM-RDP-CAP-4.0-Dezembro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/06/SPDM-Relatorio-de-Despesa-de-Pessoal-HOSPITAL-CARDOSO-FONTES-Maio2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/10/SMS-CEJAM-RDP-HOSPITAL-PAULINO-WERNECK-Setembro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/12/SMS-CEJAM-RDP-HOSPITAL-EVANDRO-FREIRE-Outubro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/01/SMS-IGEDES-RDP-SERV-INFECTO-PNEUMO-HMRPS-Novembro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/10/SMS-GNOSIS-RDP-CAP-5.1-Setembro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2025/09/SMS-VIVARIO-RDP-RAPS-APs-1.0-e-3.1-Agosto2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/01/SMS-FAS-RDP-Servicos-de-Cirurg.-Ortop.-Anest.-e-Neurocirurgia-do-HMSF-Novembro2025.pdf",
    "https://controladoria.prefeitura.rio/wp-content/uploads/sites/29/2026/05/SMEL-IRF-RDP-Marco2026.pdf",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS os_rdp (
    os          TEXT, unidade TEXT, competencia TEXT, ano INTEGER, mes INTEGER,
    headcount   INTEGER, n_cargos INTEGER, despesa_pessoal REAL,
    url TEXT PRIMARY KEY, coletado_em TEXT
);
"""


def _conectar() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB), timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _parse_nome(url: str) -> tuple[str, str, str, int, int]:
    """(os, unidade, competencia_str, ano, mes) a partir do nome do arquivo."""
    nome = url.rsplit("/", 1)[-1].replace(".pdf", "")
    m_comp = re.search(r"([A-Z][a-z]+)(\d{4})$", nome)
    mes_nome, ano = (m_comp.group(1), int(m_comp.group(2))) if m_comp else ("", 0)
    mes = _MESES.get(mes_nome, 0)
    corpo = re.sub(r"-?[A-Z][a-z]+\d{4}$", "", nome)
    corpo = re.sub(r"^SMS-", "", corpo)
    m_os = re.match(r"([A-Z]+)[-]", corpo)
    os_ = m_os.group(1) if m_os else corpo.split("-")[0]
    unidade = re.sub(r"^" + re.escape(os_) + r"[-]?(RDP|Relatorio-de-Despesa-de-Pessoal)?[-]?", "",
                     corpo).replace("-", " ").strip() or "(geral)"
    return os_, unidade, f"{mes_nome}/{ano}" if ano else nome, ano, mes


def _parse_pdf(dados: bytes) -> tuple[int, int, float]:
    """(headcount, n_cargos, despesa_pessoal) — soma das linhas por-cargo."""
    with fitz.open(stream=dados, filetype="pdf") as d:
        t = "\n".join(p.get_text() for p in d)
    rows = _RE_CARGO.findall(t)
    head = sum(int(r[1]) for r in rows)
    desp = sum(float(r[2].replace(".", "").replace(",", ".")) for r in rows)
    return head, len(rows), round(desp, 2)


def coletar(urls: list[str] | None = None) -> dict:
    urls = urls or URLS_SEED
    con = _conectar()
    agora = datetime.now(timezone.utc).isoformat()
    ok = 0
    try:
        for url in urls:
            try:
                r = requests.get(url, verify=False, timeout=90)
                r.raise_for_status()
                head, ncar, desp = _parse_pdf(r.content)
            except Exception as exc:  # noqa: BLE001
                print(f"  [erro] {url.rsplit('/',1)[-1]}: {str(exc)[:60]}", flush=True)
                continue
            os_, uni, comp, ano, mes = _parse_nome(url)
            con.execute("INSERT OR REPLACE INTO os_rdp VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (os_, uni, comp, ano, mes, head, ncar, desp, url, agora))
            ok += 1
            print(f"  {os_:8} {uni[:34]:34} {comp:16} head={head:4} R$ {desp:,.2f}", flush=True)
        con.commit()
        tot = con.execute("SELECT COUNT(*) n, SUM(headcount) h, SUM(despesa_pessoal) d, "
                          "COUNT(DISTINCT os) o FROM os_rdp").fetchone()
    finally:
        con.close()
    return {"relatorios": ok, "os_distintas": tot["o"], "headcount_total": tot["h"],
            "despesa_total": tot["d"]}


def _reais(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_ctx() -> dict:
    import html
    con = _conectar()
    try:
        por_os = con.execute(
            "SELECT os, COUNT(*) n, SUM(headcount) h, SUM(despesa_pessoal) d "
            "FROM os_rdp GROUP BY os ORDER BY d DESC").fetchall()
        det = con.execute(
            "SELECT os, unidade, competencia, headcount, n_cargos, despesa_pessoal "
            "FROM os_rdp ORDER BY despesa_pessoal DESC").fetchall()
        tot = con.execute("SELECT COUNT(*) n, COUNT(DISTINCT os) o, SUM(headcount) h, "
                          "SUM(despesa_pessoal) d FROM os_rdp").fetchone()
    finally:
        con.close()
    e = html.escape
    sumario = (f"<table><tr><td>Organizações Sociais no panorama</td>"
               f"<td style='text-align:right'><b>{tot['o']}</b></td></tr>"
               f"<tr><td>Relatórios (OS × unidade × competência)</td>"
               f"<td style='text-align:right'>{tot['n']}</td></tr>"
               f"<tr><td>Headcount somado (nas competências amostradas)</td>"
               f"<td style='text-align:right'><b>{tot['h'] or 0:,}</b></td></tr>"
               f"<tr><td>Despesa de pessoal somada</td>"
               f"<td style='text-align:right'><b>{_reais(tot['d'])}</b></td></tr></table>"
               .replace(",", "."))
    t_os = ("<table><tr><th>Organização Social</th><th>Relatórios</th><th>Headcount</th>"
            "<th>Despesa de pessoal</th></tr>"
            + "".join(f"<tr><td>{e(r['os'])}</td><td style='text-align:right'>{r['n']}</td>"
                      f"<td style='text-align:right'>{r['h'] or 0}</td>"
                      f"<td style='text-align:right'>{_reais(r['d'])}</td></tr>" for r in por_os)
            + "</table>")
    t_det = ("<table><tr><th>OS</th><th>Unidade</th><th>Competência</th><th>Headcount</th>"
             "<th>Cargos</th><th>Despesa de pessoal</th></tr>"
             + "".join(f"<tr><td>{e(r['os'])}</td><td>{e(r['unidade'])}</td>"
                       f"<td>{e(r['competencia'])}</td><td style='text-align:right'>{r['headcount']}</td>"
                       f"<td style='text-align:right'>{r['n_cargos']}</td>"
                       f"<td style='text-align:right'>{_reais(r['despesa_pessoal'])}</td></tr>"
                       for r in det) + "</table>")
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Panorama agregado — Organizações Sociais de saúde (Prefeitura do Rio)",
        "subtitulo": "Despesa de pessoal e headcount por OS/unidade — Módulo PCRJ",
        "metodologia": "Extração dos RDP agregados da CODESP (sem nomes de empregados)",
        "score": tot["o"] or 0, "faixa": "MÉDIO",
        "top_flags": [f"{tot['o']} OSs", f"{tot['h'] or 0} pessoas", _reais(tot['d'])],
        "secoes": [
            {"titulo": "1. Sumário", "html": sumario},
            {"titulo": "2. Por Organização Social", "html": t_os},
            {"titulo": "3. Detalhe por unidade/competência", "html": t_det},
            {"titulo": "4. Método e limitações (honestidade)", "html":
             "<p>Os RDP da CODESP são <b>AGREGADOS</b> — não publicam nomes de empregados das "
             "OSs, logo <b>não permitem cruzamento nominal</b> com Câmara/candidatos (só a "
             "comissão do CODESP é nominal). Headcount e despesa são a <b>soma das linhas por "
             "cargo</b> de cada relatório; a amostra cobre as OSs/unidades enumeráveis (o índice "
             "do site é dinâmico), não é exaustiva; relatórios em formato divergente podem sair "
             "com headcount 0 (marcado). Valores por competência (mês), não anuais.</p>"}],
        "proveniencia": [{"dado": "RDP das OSs", "estado": "REAL",
                          "fonte": "controladoria.prefeitura.rio (CODESP)",
                          "data": datetime.now().strftime("%d/%m/%Y")}],
        "ressalva": "Panorama de gasto agregado (sem nomes). Amostra não exaustiva.",
    }


async def gerar() -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx()
    html_s = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_os_panorama_{datetime.now().date()}.pdf")
    await html_to_pdf(html_s, pdf)
    return {"pdf": pdf}


if __name__ == "__main__":
    print(coletar())

