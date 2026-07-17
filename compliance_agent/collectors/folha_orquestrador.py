# -*- coding: utf-8 -*-
"""
folha_orquestrador — coleta autônoma das FOLHAS dos órgãos do RJ.

Problema real: as fontes ficam intermitentemente fora do ar (rj.gov.br/SEPLAG=503,
backend MPRJ=404). Em vez de coletar à mão quando voltam, este orquestrador:
  1. checa a disponibilidade de cada fonte;
  2. roda o coletor de cada fonte que estiver NO AR;
  3. é idempotente (re-rodar não duplica) e agendável no cron → as folhas vão sendo
     coletadas automaticamente conforme as fontes retornam.

Coletores registrados: DPRJ (arquivos diretos), MPRJ (API CNMP115). Outros (TJRJ/TCE/
UERJ/UENF) entram aqui quando seus coletores forem construídos.
Uso: python -m compliance_agent.collectors.folha_orquestrador
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_LOG = _REPO / "data" / "folha_orquestrador.log"


def _no_ar(url: str, timeout: int = 12) -> bool:
    """Fonte responde (status < 500)? 503/timeout/erro = fora do ar."""
    try:
        r = httpx.get(url, verify=False, timeout=timeout, follow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def _coletor_dprj() -> dict:
    from compliance_agent.collectors import folha_dprj
    return folha_dprj.coletar()


def _coletor_mprj() -> dict:
    from compliance_agent.collectors import folha_mprj
    return folha_mprj.coletar()


def _coletor_tjrj() -> dict:
    """TJRJ — folha do mês mais recente (Anexo VIII CNJ, ZIP). Grava direto em registros_folha."""
    from compliance_agent.collectors import folha_tjrj
    return folha_tjrj.coletar()


def _coletor_camara() -> dict:
    """Câmara Municipal do RJ (dados abertos, CSV por ano de ingresso). Refresh dos anos recentes
    (servidores que podem ter sido candidatos) + ponte p/ registros_folha. Full histórico (1990+) é
    manual: `python -m compliance_agent.pcrj.camara_servidores --ano-min 1990`."""
    import datetime as _dt

    from compliance_agent.pcrj import camara_servidores as C
    ano = _dt.date.today().year
    col = C.coletar(ano_min=ano - 8, ano_max=ano, pausa=0.4)
    br = C.bridge_para_folha()
    return {**col, **br}


# (órgão, URL de health-check, função de coleta)
_FONTES = [
    ("DPRJ", "https://transparencia.rj.def.br/gastos-com-pessoal/relatorio-mensal-de-remuneracao", _coletor_dprj),
    ("MPRJ", "https://api-transparencia.mprj.mp.br:8280/cnmp115/1.0.0/anos", _coletor_mprj),
    ("CAMARA_RJ", "https://transparencia.camara.rj.gov.br/", _coletor_camara),
    ("TJRJ", "https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx", _coletor_tjrj),
]

# ── MAPA DE FONTES RECONHECIDAS (2026-07-16) — coletores a construir (entram em _FONTES) ──
# Reconhecimento (health-check ao vivo + pedido do dono). Cada um é um coletor próprio:
_FONTES_MAPEADAS = {
    # Estado — executivo (GESPERJ): SPA JS; achar o backend XHR (dev-tools) que serve a consulta.
    "EXEC_ESTADO": {"url": "https://www.rj.gov.br/remuneracao/", "acesso": "SPA/GESPERJ (XHR backend)", "status": "200"},
    # TJRJ: ASPX com ViewState — POST no PortalCorpDetalheFolha.aspx (form + __VIEWSTATE).
    "TJRJ": {"url": "https://www3.tjrj.jus.br/portalservidor/PortalCorpDetalheFolha.aspx", "acesso": "ASPX ViewState", "status": "200"},
    # MPRJ: API WSO2 CNMP115 (coletor existe em folha_mprj) — backend voltou a 401 (auth), reendpoint de dados instável.
    "MPRJ_API": {"url": "https://api-transparencia.mprj.mp.br:8280/cnmp115/1.0.0", "acesso": "OAuth client_credentials", "status": "401"},
    # TCE-RJ: portal da transparência (consulta remuneração de conselheiros/servidores).
    "TCE_RJ": {"url": "https://www.tcerj.tc.br/portalnovo/pagina/portal-da-transparencia-tce-rj", "acesso": "portal (verificar export)", "status": "200"},
    # Câmara Municipal do RJ: portal transparência (memória: CSV por ANOINGRESSO no módulo PCRJ).
    "CAMARA_RJ": {"url": "https://transparencia.camara.rj.gov.br/", "acesso": "CSV/portal", "status": "200"},
    # Prefeitura do RJ (PCRJ): contracheque JSF (não é REST) — usar contrachequedoc/ArquivoTC já mapeado no módulo PCRJ.
    "PCRJ": {"url": "https://contrachequeapi.rio.gov.br/contrachequeapi/transparencia", "acesso": "JSF (viewstate) / ArquivoTC", "status": "200"},
    # TCM-RJ: Tribunal de Contas do Município (buscar portal de transparência específico).
    "TCM_RJ": {"url": "https://www.tcmrj.tc.br/", "acesso": "portal (a mapear)", "status": "?"},
}


def _total_por_orgao() -> dict:
    if not _DB.exists():
        return {}
    con = sqlite3.connect(str(_DB))
    try:
        return {o: n for o, n in con.execute(
            "SELECT orgao_codigo, COUNT(*) FROM registros_folha GROUP BY orgao_codigo")}
    finally:
        con.close()


def rodar() -> dict:
    res = {}
    for orgao, health, run in _FONTES:
        if not _no_ar(health):
            res[orgao] = {"no_ar": False, "acao": "pulado (fonte fora do ar)"}
            continue
        try:
            res[orgao] = {"no_ar": True, **(run() or {})}
        except Exception as e:  # noqa: BLE001
            res[orgao] = {"no_ar": True, "erro": f"{type(e).__name__}: {str(e)[:100]}"}
    out = {"ok": True, "fontes": res, "totais_na_base": _total_por_orgao()}
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{int(time.time())}] {json.dumps(out, ensure_ascii=False)}\n")
    except Exception:
        pass
    return out


if __name__ == "__main__":
    print(json.dumps(rodar(), ensure_ascii=False, indent=1))
