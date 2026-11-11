#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PERÍCIA EM MASSA — aplica o motor auditar_contrato (T01-T22) a CADA fornecedor×órgão com OBs no SIAFE.
Determinístico (sem LLM no volume): cada "contrato contínuo" (fornecedor×UG) sai periciado e gravado em
`pericia_fornecedor`. É a perícia que o /relatorio e o /orgao consomem, e que o sweep diário mantém.

Inteligência progressiva: as regras de método aprendidas (memória `metodo`, auto_melhoria) e o enriquecimento
por contrato (serie_reajustes, retenções, bruto_nf das íntegras) entram via `enriquecer()` — cada perícia nova
melhora a base p/ os próximos casos.

Uso:
  python -m compliance_agent.pericia_sweep --min-obs 6 [--limit N]   # roda o sweep
  python -m compliance_agent.pericia_sweep --cnpj 19088605000104 --ug 133100  # uma perícia
"""
from __future__ import annotations
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"

_DDL = """CREATE TABLE IF NOT EXISTS pericia_fornecedor (
  cnpj TEXT, ug TEXT, favorecido TEXT, n_obs INTEGER, total_pago REAL,
  grau TEXT, score INTEGER, n_confirmados INTEGER, n_indicios INTEGER, n_indisponivel INTEGER,
  resumo TEXT, achados_json TEXT, atualizado_em TEXT,
  PRIMARY KEY (cnpj, ug))"""


def _conn():
    # TIMEOUT NA ESCRITA (11/11/2026): com o padrão do sqlite (5 s) o sweep perdia par para qualquer outro
    # escritor — 5.377 "database is locked" no log do cron e 28.414 numa passada concorrente. A casa espera 120 s.
    c = sqlite3.connect(DB, timeout=120); c.row_factory = sqlite3.Row
    c.execute(_DDL); return c


def _obs_de(c, cnpj: str, ug: str) -> list[dict]:
    # `data_emissao` e TEXTO DD/MM/AAAA: um ORDER BY cru ordena por DIA DO MES (01/10/2024
    # vinha antes de 16/12/2022). A ordem errada nao quebra nada — sai calada no parecer,
    # e daqui a cadeia vai ate lex_render.render_pdf, o PDF que vai para fora. Mesmo idioma
    # ISO que retro_auditoria.py e cruzamentos_intel.py ja usavam (`_OB_ISO`).
    iso = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
    cur = c.execute(f"""SELECT numero_ob,status,COALESCE(nl,'') nl,COALESCE(re,'') re,COALESCE(pd,'') pd,
        valor,competencia,data_emissao,COALESCE(processo,'') processo,nome_credor
        FROM ob_orcamentaria_siafe WHERE credor=? AND ug_emitente=? ORDER BY {iso},numero_ob""", (cnpj, ug))
    return [dict(r) for r in cur.fetchall()]


def enriquecer(dados: dict, c) -> dict:
    """Hook de inteligência progressiva: anexa dados por-contrato já conhecidos (reajustes, bruto_nf etc.)
    extraídos das íntegras/sweep. Hoje: série de reajustes do ITERJ×MGS (caso-âncora, provado). Cresce a
    cada perícia (próximo passo: ler das íntegras em data/sei_cache/INTEGRA_*.txt automaticamente)."""
    if dados.get("favorecido", "").upper().startswith("MGS") or dados.get("_cnpj") == "19088605000104":
        dados["serie_reajustes"] = [90419.34, 98276.62, 103988.53, 109687.73, 118441.47]
        dados["cct_percentuais"] = {2022: 9.91, 2023: 6.01, 2024: 6.20, 2025: 7.50}
        dados["cct_data_base"] = 3
        if str(dados.get("orgao")) == "133100":
            # só o par ITERJ×MGS tem contrato lido (005/2021, limpeza com faturamento mensal): é o único em que o
            # T08 sabe que deveria haver OB todo mês e pode citar o contrato. Nos demais pares o T08 é INDISPONÍVEL.
            dados["contrato_ref"] = "005/2021"
            dados["servico_continuo"] = True
            dados["periodicidade_meses"] = 1
    # T07 fechado pela NF (tools/resolver_duplicidade_nf.py): o veredito por competência que o resolvedor gravou.
    # Tabela ausente (banco que nunca rodou o resolvedor) = nenhuma resolução, o T07 segue como antes.
    if c is None:
        return dados
    try:
        dados["resolucao_duplicidade"] = {
            r[0]: {"veredito": r[1], "motivo": r[2], "citacao": r[3], "camada": r[4], "obs": json.loads(r[5] or "[]")}
            for r in c.execute("SELECT competencia, veredito, motivo, citacao, camada, obs_json FROM resolucao_duplicidade"
                               " WHERE cnpj=? AND ug=?", (dados.get("_cnpj") or "", str(dados.get("orgao") or "")))}
    except sqlite3.OperationalError:
        dados["resolucao_duplicidade"] = {}
    return dados


def periciar(cnpj: str, ug: str, c=None) -> dict:
    from compliance_agent.auditoria_contrato import auditar_contrato
    own = c is None
    c = c or _conn()
    try:
        obs = _obs_de(c, cnpj, ug)
        fav = obs[0]["nome_credor"] if obs else ""
        dados = enriquecer({"obs": obs, "favorecido": fav, "orgao": ug, "contrato": f"{fav}×UG{ug}", "_cnpj": cnpj}, c)
        res = auditar_contrato(dados)
        res["cnpj"] = cnpj; res["ug"] = ug; res["favorecido"] = fav
        # REGRA DE OURO: só OB Contabilizado é "pago". Somar tudo inflava o par (62162335000163/370200:
        # R$ 1,04 bi contabilizado + R$ 1,03 bi Excluído saía como ~R$ 2,07 bi "pago").
        res["n_obs"] = len(obs)
        res["total_pago"] = sum(o["valor"] or 0 for o in obs
                                if str(o.get("status") or "").strip().lower().startswith("contabiliz"))
        return res
    finally:
        if own:
            c.close()


def _gravar(c, res: dict):
    c.execute("""INSERT OR REPLACE INTO pericia_fornecedor
        (cnpj,ug,favorecido,n_obs,total_pago,grau,score,n_confirmados,n_indicios,n_indisponivel,resumo,achados_json,atualizado_em)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (res["cnpj"], res["ug"], res["favorecido"], res["n_obs"], res["total_pago"], res["grau"], res["score"],
         res["n_confirmados"], res["n_indicios"], res["n_indisponivel"], res["resumo"],
         json.dumps(res["achados"], ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())))


# Credores NÃO-contratuais (repasse intra-governo / folha / previdência / precatório / órgão público): NÃO
# recebem a bateria T01-T25 (são transferência, não contrato de fornecimento). Comparação SEM acento.
_NAO_CONTRATUAL = ("FOLHA DE PAGAMENTO", "RIOPREV", "INATIVO", "PENSIONISTA", "INSS", "TESOURO DO ESTADO",
                   "FUNDO UNICO DE PREV", "PREVIDENCI", "PRECATORI", "AUXILIO ALIMENTA", "PECUNIA",
                   "ESTADO DO RIO DE JANEIRO", "INSTITUTO NACIONAL DO SEGURO SOCIAL",
                   # órgão público / ente (repasse, convênio, fundo a fundo) — medido 11/11: 629 pares de
                   # prefeitura, 164 de fundo municipal, 165 de ministério, 42 de tribunal na perícia
                   "PREFEITURA", "MUNICIPIO D", "FUNDO MUNICIPAL", "FUNDO ESTADUAL", "FUNDO NACIONAL",
                   "SECRETARIA DE", "MINISTERIO D", "TRIBUNAL", "CAMARA MUNICIPAL", "ASSEMBLEIA LEGISLATIVA",
                   "DEFENSORIA PUBLICA", "PROCURADORIA", "GOVERNO DO ESTADO",
                   # abreviações do nome no SIAFE (conferência dos 308 🟡, 11/11): "Fundo Mun. De Saude…", IPALERJ
                   "FUNDO MUN.", "FUNDO MUN ", "FUNDO EST.", "FUNDO EST ", "IPALERJ")

# Código de credor que não é fornecedor identificável (medido 11/11 em pericia_fornecedor): 518 pares com
# código de UG (6 dígitos = repasse intragoverno), CG (inscrição genérica: folha, auxílios, multas — 1.213),
# RP/RF/PR/PP (precatório/RPV/processo judicial — 576), BJ (bloqueio judicial — 53), PO (tributo — 1).
# CS (consórcio) e CNPJ/CPF seguem na bateria.
_CODIGO_NAO_FORNECEDOR = re.compile(r"^(\d{6}|(CG|RP|RF|PR|PP|BJ|PO)\w*)$")


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode()


def _eh_nao_contratual(nome: str) -> bool:
    n = _sem_acento(nome)
    return any(p in n for p in _NAO_CONTRATUAL)


def _fora_da_bateria(credor: str, nome: str) -> bool:
    """O par não é contrato de fornecimento → fora da perícia. Antes o sweep passava o CÓDIGO do credor a
    `_eh_nao_contratual` (nunca casava): 246 pares 🟡 de folha/RIOPREV/precatório, R$ 233 bi."""
    return bool(_CODIGO_NAO_FORNECEDOR.match((credor or "").strip().upper())) or _eh_nao_contratual(nome)


def _podar(c, elegiveis: set, completo: bool) -> int:
    """Remove de `pericia_fornecedor` o par que não deveria existir. O sweep só fazia INSERT OR REPLACE e
    NUNCA removia (36 pares parados desde jul–ago; folha/precatório de antes do filtro). Sempre sai o par
    fora da bateria; numa passada COMPLETA (sem --limit/--ugs) sai também o que deixou de ser elegível."""
    rm = [(r[0], r[1]) for r in c.execute("SELECT cnpj, ug, favorecido FROM pericia_fornecedor")
          if _fora_da_bateria(r[0], r[2]) or (completo and (r[0], r[1]) not in elegiveis)]
    c.executemany("DELETE FROM pericia_fornecedor WHERE cnpj=? AND ug=?", rm)
    return len(rm)


def sweep(min_obs: int = 6, limit: int | None = None, ugs: list[str] | None = None) -> dict:
    c = _conn()
    filtro_ug = ""
    params: list = []
    if ugs:
        filtro_ug = f" AND ug_emitente IN ({','.join('?' * len(ugs))})"
        params = list(ugs)
    # só OB efetivamente paga (status contabilizado) — exclui anulada/excluída/não-contab que inflavam o ranking
    pares = c.execute(f"""SELECT credor,ug_emitente,COUNT(*) n,MAX(nome_credor) nome FROM ob_orcamentaria_siafe
        WHERE credor IS NOT NULL AND credor!='' AND lower(status) LIKE 'contabiliz%'{filtro_ug}
        GROUP BY credor,ug_emitente HAVING n>=? ORDER BY SUM(valor) DESC""", (*params, min_obs)).fetchall()
    pares = [r for r in pares if not _fora_da_bateria(r["credor"], r["nome"])]  # repasse/folha/precatório fora
    removidos = _podar(c, {(r["credor"], r["ug_emitente"]) for r in pares}, completo=not (limit or ugs))
    if limit:
        pares = pares[:limit]
    n = 0; graus = {"🔴": 0, "🟡": 0, "🟢": 0, "⚪": 0}
    for r in pares:
        try:
            res = periciar(r["credor"], r["ug_emitente"], c)
            _gravar(c, res); graus[res["grau"]] = graus.get(res["grau"], 0) + 1; n += 1
            if n % 200 == 0:
                c.commit(); print(f"  {n}/{len(pares)} periciados…", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  erro {r['credor']}/{r['ug_emitente']}: {str(e)[:60]}", flush=True)
    c.commit(); c.close()
    return {"periciados": n, "de": len(pares), "graus": graus, "removidos": removidos}


if __name__ == "__main__":
    import sys
    a = sys.argv
    if "--cnpj" in a:
        cnpj = a[a.index("--cnpj") + 1]; ug = a[a.index("--ug") + 1]
        res = periciar(cnpj, ug)
        print(json.dumps({k: res[k] for k in ("favorecido", "ug", "n_obs", "total_pago", "grau", "score",
              "n_confirmados", "n_indicios", "n_indisponivel", "resumo")}, ensure_ascii=False, indent=1))
    else:
        mo = int(a[a.index("--min-obs") + 1]) if "--min-obs" in a else 6
        lim = int(a[a.index("--limit") + 1]) if "--limit" in a else None
        ugs = a[a.index("--ugs") + 1].split(",") if "--ugs" in a else None
        print(json.dumps(sweep(mo, lim, ugs), ensure_ascii=False))
