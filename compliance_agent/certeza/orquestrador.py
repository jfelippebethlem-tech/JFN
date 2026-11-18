# -*- coding: utf-8 -*-
"""orquestrador — o CICLO da certeza e o painel em dados (data/certeza/estado.json, relatorio.md).

Chamado pelo despachante de propagação (derivado `certeza`, folha do grafo) sempre que um derivado que publica
fato, o vault ou a perícia mudam. Um ciclo: extrai os fatos declarados no mapa → portão → registro; audita os
contratos das tabelas de achado e fotografa o nível de prova; audita o grafo; confere citações e menções no
vault, nos documentos, na memória e no cérebro; concilia as divergências; grava o painel. Não chama LLM, não grava
no compliance.db, não se reagenda. Tudo o que não pôde ser medido sai em `indisponiveis` — nunca como zero.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import citacoes, config, fatos, grafo, portoes


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)


def laudos(ro: sqlite3.Connection) -> dict:
    """Certeza dos laudos de execução: por nível de prova, quantos são risco alto e quantos se espera confirmar na
    fonte (taxa calibrada do autoaprimoramento). 🔴/🟡 só com prova primária — conta o que escaparia da regra."""
    from compliance_agent.autoaprimoramento import calibracao
    from compliance_agent.autoaprimoramento import config as acfg
    from compliance_agent.autoaprimoramento import ledger
    from compliance_agent.correlacao_sei import estado_do_laudo
    cal = calibracao.carregar()
    por: dict[int, dict] = {}
    escapou = []
    for ns, modelo, nota in ro.execute("SELECT numero_sei, modelo, nota_risco FROM lex_execucao"):
        _motor, nivel = ledger.motor_e_nivel(modelo)
        alto = nota is not None and nota >= acfg.ALTO
        g = por.setdefault(nivel, {"laudos": 0, "risco_alto": 0, "esperados_confirmar": 0.0, "sem_taxa": 0})
        g["laudos"] += 1
        if not alto:
            continue
        g["risco_alto"] += 1
        c = calibracao.confianca(modelo, nota, cal)
        if nivel == acfg.NIVEL_FONTE:
            g["esperados_confirmar"] += 1
        elif c.get("p_confirma") is None:
            g["sem_taxa"] += 1
        else:
            g["esperados_confirmar"] += c["p_confirma"]
        if estado_do_laudo(modelo, nota)[0] == "VERIFICADO" and nivel != acfg.NIVEL_FONTE:
            escapou.append(ns)
    nomes = {-1: "regra determinística (sem laudo de modelo)", 0: "modelo de volume", 1: "Opus sobre o resumo", 2: "fonte primária"}
    return {"calibracao": "carregada" if cal else "INDISPONIVEL",
            "por_nivel": [{"nivel_prova": n, "quem": nomes.get(n, str(n)), **{k: (round(v, 1) if isinstance(v, float) else v)
                           for k, v in g.items()}} for n, g in sorted(por.items())],
            "risco_alto_verificado_sem_prova_primaria": escapou}


def _sem_drenar(cz: sqlite3.Connection, medidas: dict, agora: float) -> list[str]:
    """Fila de re-perícia de um externo que não DIMINUIU em 24 h (falha 5: fonte nova que não refaz o derivado).
    Compara com a medida mais recente de pelo menos 24 h atrás; sem história ainda, não acusa (e não dá por são)."""
    out = []
    for eid, n in medidas.items():
        ant = cz.execute("SELECT valor, em FROM medida WHERE nome=? AND em <= ? ORDER BY em DESC LIMIT 1",
                         (f"atraso:{eid}", agora - 86400)).fetchone()
        if ant and n > 0 and n >= ant[0]:
            out.append(f"{eid}: {n} item(ns) à espera de re-perícia; eram {int(ant[0])} há {(agora - ant[1]) / 3600:.0f} h — a fila não diminui")
        cz.execute("INSERT INTO medida VALUES (?,?,?)", (f"atraso:{eid}", agora, n))
    return out


def _publicar_cerebro(cz: sqlite3.Connection, mudados: list[str]) -> dict:
    """Fato novo/alterado → fila do segundo cérebro, com o id (chave `fato:<id>`; texto novo substitui o anterior).
    Só com JFN_CERTEZA_CEREBRO=1; teto por ciclo; quem envia é o despachante (`enviar_pendentes`)."""
    if not config.ligado("CEREBRO"):
        return {"estado": "desligado (JFN_CERTEZA_CEREBRO)", "n": 0}
    from compliance_agent import cerebro_compartilhado as cer
    n, res = 0, {}
    for fid in mudados[:config.TETO_CEREBRO_CICLO]:
        f = fatos.vigente(cz, fid)
        if not f or f["valor"] is None:
            continue
        txt = (f"JFN — fato {fid}: {f['rotulo']} = {fatos.formatar(f['valor'], f['unidade'])} "
               f"[{f['estado']}, nível de prova {f['nivel_prova']}; fonte: {f['fonte']}; referência {f['data_ref']}]. "
               f"Cite pelo id; o valor vigente está em /api/sistema/certeza.")
        r = cer.registrar(f"fato:{fid}", txt, "semantica", f"fato {fid.split(':')[0]}")
        res[r.split(":")[0]] = res.get(r.split(":")[0], 0) + 1
        n += 1
    return {"estado": "ligado", "n": n, **res}


def ciclo(cfg: dict | None = None, compliance_db: Path | None = None, cz: sqlite3.Connection | None = None,
          estado_prop: dict | None = None, raiz: Path | None = None, buscar="cerebro", cron: str | None = "",
          gravar: bool = True, agora: float | None = None) -> dict:
    from compliance_agent import propagacao
    agora = agora or time.time()
    raiz = raiz or config.REPO
    cfg = cfg or propagacao.carregar()
    proprio = cz is None
    cz = cz or fatos.conectar()
    indis: list[str] = []
    ro = None
    try:
        ro = _ro(compliance_db or raiz / "data" / "compliance.db")
        ro.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except sqlite3.Error as e:
        indis.append(f"compliance.db: {type(e).__name__}: {e}")
        ro = None
    try:
        # 1. fatos
        props, erros = fatos.extrair(cfg, ro, raiz, cz, agora)
        recon = []
        for p in props:
            rc = p.pop("_reconcilia", None)
            if rc and p["valor"] is not None and abs(float(rc["esperado"]) - float(p["valor"])) > (0.05 if p["unidade"] == "BRL" else 0):
                recon.append({"tipo": "agregado_nao_bate_com_o_detalhe", "fato_id": p["fato_id"], "superficie": "derivado",
                              "local": rc["caminho"], "linha": 0, "encontrado": fatos.formatar(p["valor"], p["unidade"]),
                              "esperado": fatos.formatar(rc["esperado"], p["unidade"])})
        lote = fatos.registrar_lote(cz, props, agora)
        # 2. contratos
        contratos = cfg.get("contratos") or {}
        if ro is not None:
            violacoes = portoes.auditar(ro, contratos)
            foto = portoes.fotografar(ro, cz, contratos, agora)
        else:
            violacoes, foto = None, None
        # 3. grafo
        if estado_prop is None:
            try:
                estado_prop = propagacao.estado(cfg)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
                indis.append(f"estado da propagação: {type(e).__name__}: {e}")
        g = grafo.auditar(cfg, estado_prop, raiz, cron, ro, agora)
        indis += g["indisponiveis"]
        g["achados"]["externo_sem_drenar"] = _sem_drenar(cz, g["atraso_dos_externos"], agora)
        g["resumo"]["achados"]["externo_sem_drenar"] = len(g["achados"]["externo_sem_drenar"])
        g["resumo"]["graves"] += len(g["achados"]["externo_sem_drenar"])
        # 4. citações e menções
        if buscar == "cerebro":
            from compliance_agent import cerebro_compartilhado as cer
            buscar = cer.buscar
        v = citacoes.varrer(cz, (cfg.get("certeza") or {}).get("superficies") or {}, raiz, aplicar=True, buscar=buscar)
        indis += v["indisponiveis"]
        conc = citacoes.conciliar(cz, v["divergencias"] + recon, v["superficies_lidas"] + ["derivado"], agora)
        # 5. laudos
        try:
            ld = laudos(ro) if ro is not None else None
        except (sqlite3.Error, ImportError, OSError, ValueError, KeyError) as e:
            ld = None
            indis.append(f"certeza dos laudos: {type(e).__name__}: {e}")
        cer_pub = _publicar_cerebro(cz, [m["fato_id"] for m in lote["mudancas"]] + lote["novos"])
        est = painel(cz, g, agora)
        est.update({
            "ciclo": {"extracao": {"propostos": len(props), **{k: lote[k] for k in ("novo", "atualizado", "igual", "recusado")},
                                   "mudancas": lote["mudancas"][:50], "recusas": lote["recusas"][:50], "erros": erros},
                      "texto": {k: v[k] for k in ("lidos", "citacoes", "sincronizados", "fatos_com_valor_superado", "superficies_lidas")},
                      "divergencias": conc, "cerebro": cer_pub},
            "contratos": {"estado": "INDISPONIVEL" if violacoes is None else "ok", "violacoes": violacoes or [], "fotografia": foto or {}},
            "laudos": ld, "indisponiveis": indis})
        r = est["resumo"]
        r["violacoes_de_contrato"] = None if violacoes is None else len(violacoes)
        r["regressoes_de_prova_abertas"] = None if foto is None else sum(x.get("regressoes_abertas", 0) for x in foto.values())
        r["erros_de_extracao"] = len(erros)
        r["recusas_no_ciclo"] = lote["recusado"]
        r["risco_alto_verificado_sem_prova_primaria"] = None if ld is None else len(ld["risco_alto_verificado_sem_prova_primaria"])
        r["indisponiveis"] = len(indis)
        if gravar:
            _gravar(est)
        return est
    finally:
        if ro is not None:
            ro.close()
        if proprio:
            cz.close()


def painel(cz: sqlite3.Connection, g: dict | None = None, agora: float | None = None) -> dict:
    """O painel de certeza: por fato — valor, estado, nível de prova, confiança, proveniência, frescor, divergências."""
    agora = agora or time.time()
    nos = {n["id"]: n for n in (g or {}).get("nos", [])}
    div = citacoes.abertas(cz)
    por_fato: dict[str, int] = {}
    for d in div:
        por_fato[d["fato_id"]] = por_fato.get(d["fato_id"], 0) + 1
    ext = {(no, b): (em, n, erro) for no, b, em, n, erro in cz.execute("SELECT no, bloco, em, n, erro FROM extracao")}
    ult_no: dict[str, float] = {}
    for (no, _b), (em, _n, _e) in ext.items():
        ult_no[no] = max(ult_no.get(no, 0), em or 0)
    nver = dict(cz.execute("SELECT fato_id, COUNT(*) FROM fato_versao GROUP BY 1"))
    lista = []
    for f in fatos.vigentes(cz):
        no = nos.get(f["no"]) or {}
        orfao = f["confirmado_em"] < ult_no.get(f["no"], 0) - 1
        fresc = "a fonte não produz mais este fato" if orfao else \
            {"fresco": "fresco", "observada": "fresco", "agendado": "fresco"}.get(no.get("estado"), no.get("estado") or "INDISPONIVEL")
        lista.append({
            "id": f["fato_id"], "rotulo": f["rotulo"], "valor": f["valor"], "valor_fmt": fatos.formatar(f["valor"], f["unidade"]),
            "unidade": f["unidade"], "estado": f["estado"], "nivel_prova": f["nivel_prova"], "natureza": f["natureza"],
            "base": f["base"], "confianca": f["confianca"],
            "confianca_texto": f["confianca_texto"] or ("determinístico: consulta reproduzível sobre a fonte (hash da fonte registrado)"),
            "proveniencia": {"fonte": f["fonte"], "consulta": f["consulta"], "data_ref": f["data_ref"],
                             "hash_fonte": f["hash_fonte_confirmado"] or f["hash_fonte"], "produtor": f["produtor"]},
            "no": f["no"], "frescor": {"estado": fresc, "confirmado_ha_s": round(agora - f["confirmado_em"]),
                                       "valor_desde": datetime.fromtimestamp(f["registrado_em"]).strftime("%Y-%m-%dT%H:%M:%S")},
            "versoes": nver.get(f["fato_id"], 1), "divergencias_abertas": por_fato.get(f["fato_id"], 0),
            "citar": citacoes.citar(f) if f["valor"] is not None else None})
    conta = lambda k: {str(x): sum(1 for i in lista if i[k] == x) for x in sorted({i[k] for i in lista}, key=str)}  # noqa: E731
    return {"ok": True, "estado": "ok", "gerado_em": agora, "gerado_em_iso": datetime.fromtimestamp(agora).strftime("%Y-%m-%dT%H:%M:%S"),
            "resumo": {"fatos": len(lista), "por_estado": conta("estado"), "por_nivel_prova": conta("nivel_prova"),
                       "fatos_aguardando_recalculo": sum(1 for i in lista if i["frescor"]["estado"] == "sujo"),
                       "fatos_nao_frescos": sum(1 for i in lista if i["frescor"]["estado"] not in ("fresco", "sujo")),
                       "divergencias_abertas": len(div),
                       "divergencias_reincidentes": sum(1 for d in div if d["reincidencias"]),
                       "grafo_achados_graves": (g or {}).get("resumo", {}).get("graves"),
                       "recusas_24h": cz.execute("SELECT COUNT(*) FROM recusa WHERE em > ?", (agora - 86400,)).fetchone()[0]},
            "fatos": lista, "divergencias": div,
            "grafo": {"resumo": (g or {}).get("resumo"), "achados": (g or {}).get("achados"),
                      "nos": (g or {}).get("nos")} if g else {"estado": "INDISPONIVEL"},
            "proveniencia": {"fonte": "data/certeza/certeza.db (registro de fatos) + config/propagacao.yaml + data/propagacao.db",
                             "data_ref": datetime.fromtimestamp(agora).strftime("%Y-%m-%dT%H:%M:%S"),
                             "cobertura": "só os fatos DECLARADOS em `fatos:` no mapa; número sem declaração não é coberto"}}


def _gravar(est: dict) -> None:
    d = config.dados()
    for nome, txt in (("estado.json", json.dumps(est, ensure_ascii=False, indent=1, default=str)), ("relatorio.md", relatorio(est))):
        tmp = d / (nome + ".tmp")
        tmp.write_text(txt, encoding="utf-8")
        os.replace(tmp, d / nome)


def ler_estado() -> dict:
    """Para a rota e o sensor: a última fotografia. Ausente = INDISPONÍVEL (o ciclo nunca rodou), nunca 'tudo certo'."""
    try:
        return json.loads((config.dados() / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "estado": "INDISPONIVEL", "motivo": f"o ciclo da certeza ainda não gravou estado — {type(e).__name__}"}


def relatorio(est: dict) -> str:
    r, L = est["resumo"], []
    ind = lambda v: "INDISPONÍVEL" if v is None else str(v)  # noqa: E731
    L += ["# JFN — Painel de Certeza", "", f"Gerado em {est['gerado_em_iso']} · fonte: `data/certeza/certeza.db` · "
          "detalhe em `docs/ARQUITETURA-DE-CERTEZA.md`", "", "## 1. Resumo", "", "| Medida | Valor |", "|---|---:|",
          f"| Fatos registrados (vigentes) | {r['fatos']} |",
          f"| Por estado | {', '.join(f'{k}: {v}' for k, v in r['por_estado'].items())} |",
          f"| Por nível de prova | {', '.join(f'nível {k}: {v}' for k, v in r['por_nivel_prova'].items())} |",
          f"| Fatos aguardando recálculo do nó (dentro do prazo) | {r['fatos_aguardando_recalculo']} |",
          f"| Fatos NÃO frescos (nó atrasado, falhando, ou a fonte deixou de produzir) | {r['fatos_nao_frescos']} |",
          f"| Divergências abertas (reincidentes) | {r['divergencias_abertas']} ({r['divergencias_reincidentes']}) |",
          f"| Violações de contrato de dados | {ind(r.get('violacoes_de_contrato'))} |",
          f"| Regressões de nível de prova abertas | {ind(r.get('regressoes_de_prova_abertas'))} |",
          f"| Risco alto VERIFICADO sem prova primária | {ind(r.get('risco_alto_verificado_sem_prova_primaria'))} |",
          f"| Achados graves do grafo | {ind(r.get('grafo_achados_graves'))} |",
          f"| Escritas recusadas pelo portão (24 h) | {r['recusas_24h']} |",
          f"| Medidas indisponíveis neste ciclo | {ind(r.get('indisponiveis'))} |", ""]
    L += ["## 2. Divergências abertas", ""]
    if est["divergencias"]:
        L += ["| Tipo | Fato | Onde | Encontrado | Vigente |", "|---|---|---|---:|---:|"]
        L += [f"| {d['tipo']} | `{d['fato_id']}` | {d['superficie']}: {d['local']} | {d['encontrado']} | {d['esperado']} |"
              for d in est["divergencias"]]
    else:
        L += ["Nenhuma nas superfícies lidas."]
    L += ["", "## 3. Contratos de dados", ""]
    for v in (est.get("contratos") or {}).get("violacoes", []):
        L.append(f"- **{v['contrato']}** · {v['regra']} · {ind(v.get('n'))} de {ind(v.get('de'))} — {v['detalhe']}"
                 + (f" · ex.: {'; '.join(map(str, v['exemplos'][:3]))}" if v.get("exemplos") else ""))
    for cid, f in ((est.get("contratos") or {}).get("fotografia") or {}).items():
        L.append(f"- fotografia **{cid}**: " + (f.get("erro") or f"{f['linhas']} linhas, por nível {f['por_nivel']}, "
                                                 f"regressões abertas {f['regressoes_abertas']}"))
    L += ["", "## 4. Grafo de dependências", ""]
    for k, v in ((est.get("grafo") or {}).get("achados") or {}).items():
        if v:
            L.append(f"- **{k.replace('_', ' ')}** ({len(v)}): " + "; ".join(map(str, v[:8])) + (" …" if len(v) > 8 else ""))
    for n in ((est.get("grafo") or {}).get("nos") or []):
        if n.get("tipo") == "externo":
            L.append(f"- externo **{n['id']}** ({n['estado']}) → publica `{n.get('publica')}`"
                     + (f"; {n['atraso']} item(ns) com a fonte mais nova que o derivado" if n.get("atraso") is not None else ""))
    if est.get("laudos"):
        L += ["", "## 5. Laudos de execução — certeza por nível de prova", "",
              "| Nível | Quem | Laudos | Risco alto | Esperados confirmar na fonte | Sem taxa medida |", "|---:|---|---:|---:|---:|---:|"]
        L += [f"| {x['nivel_prova']} | {x['quem']} | {x['laudos']} | {x['risco_alto']} | {x['esperados_confirmar']} | {x['sem_taxa']} |"
              for x in est["laudos"]["por_nivel"]]
    L += ["", "## 6. Fatos", "", "| Fato | Valor | Estado | Prova | Frescor | Referência |", "|---|---:|---|---:|---|---|"]
    L += [f"| `{f['id']}` — {f['rotulo'][:70]} | {f['valor_fmt']} | {f['estado']} | {f['nivel_prova']} | {f['frescor']['estado']} | "
          f"{f['proveniencia']['data_ref']} |" for f in est["fatos"]]
    if est.get("indisponiveis"):
        L += ["", "## 7. Não medido neste ciclo (INDISPONÍVEL ≠ 0)", ""] + [f"- {x}" for x in est["indisponiveis"]]
    return "\n".join(L) + "\n"
