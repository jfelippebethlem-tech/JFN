# -*- coding: utf-8 -*-
"""ACERVO — uma busca e uma ficha para TODO processo (SEI do Estado e da Prefeitura), com OBs, contratos,
documentos, agentes, achados, perícias e pedidos LAI, vindos de todas as tabelas que a casa já tem.

Por que: o dado existe espalhado por 12 tabelas em 3 bancos (sei_arvore, sei_ficha, processo_avaliacao,
achado_detector, agente_processo, ob_orcamentaria_siafe, sei_arquivo/, pcrj_processo, pcrj_sei_arvore,
pcrj_processo_doc, contasrio_contrato, pcrj_emergencia_sinal, lai.db) e ninguém consegue "ver tudo de um
processo" sem SQL. Aqui a chave é o NÚMERO NORMALIZADO; cada fonte diz o que tem e o que não tem.

Só leitura. Honestidade: fonte ausente vem como lista vazia com `cobertura` explicando; nada é fabricado.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
DB_COMPLIANCE = _RAIZ / "data" / "compliance.db"
DB_ACHADOS = _RAIZ / "data" / "achados.db"
DB_PCRJ = _RAIZ / "data" / "pcrj.db"
DB_LAI = _RAIZ / "data" / "lai.db"
DB_SEI_RJ = _RAIZ / "data" / "sei_rj_catalogo.db"      # catálogo da pesquisa pública do SEI estadual
# Consulta SOB DEMANDA do SEI da Prefeitura: a VM-1 escreve pedidos/, a VM-2 (deploy/vm2/sei_pcrj_consulta.py,
# timer de 2 min) consulta a pesquisa pública do SEI.RIO e escreve respostas/ — Syncthing, um escritor por pasta.
CONSULTA_PCRJ = Path.home() / "shared-brain" / "sei_pcrj_consulta"
ARQUIVO_SEI = _RAIZ / "data" / "sei_arquivo"

_RX_ESTADO = re.compile(r"(\d{6})\D{0,3}(\d{6})\D{0,3}(20\d{2})")
_RX_PCRJ = re.compile(r"^\d{6}\.\d{6}/20\d{2}-\d{2}$")
_RX_LEGADO = re.compile(r"^[A-Z]{2,5}-[A-Z]{3}-20\d{2}/\d{5}(?:\.\d+)?$", re.I)


def norm(numero: str | None) -> tuple[str, str] | None:
    """→ (esfera, canônico). Estado: qualquer 6/6/4 dígitos vira 'SEI-DDDDDD/DDDDDD/AAAA' (é como a
    sei_arvore e o SIAFE escrevem; a avaliação omite o 'SEI-' e o arquivo usa '_'). Prefeitura: SEI
    municipal (000700.007924/2026-97) ou Processo.rio (SME-PRO-2025/38233), como estão."""
    s = (numero or "").strip()
    if not s:
        return None
    if _RX_PCRJ.match(s):
        return "prefeitura", s
    if _RX_LEGADO.match(s):
        return "prefeitura", s.upper()
    m = _RX_ESTADO.search(s)
    if m:
        return "estado", f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return None


def _variantes_estado(canon: str) -> list[str]:
    a, b, c = canon[4:].split("/")
    return [canon, f"{a}/{b}/{c}", f"{a}_{b}_{c}", f"SEI-{a}/{b}/{c}".replace("SEI-", "SEI "), f"{a}{b}{c}"]


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _tem(con, tabela: str) -> bool:
    return bool(con and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone())


def _js(s):
    try:
        return json.loads(s) if s else None
    except (TypeError, ValueError):
        return None


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ───────────────────────────── FICHA ─────────────────────────────

def _ficha_estado(canon: str) -> dict:
    con, ach, lai = _ro(DB_COMPLIANCE), _ro(DB_ACHADOS), _ro(DB_LAI)
    f: dict = {"esfera": "estado", "numero": canon, "cobertura": {}, "identidade": {}, "documentos": [], "obs": {},
               "contratos": [], "agentes": [], "achados": [], "pericias": {}, "avaliacao_360": None, "lai": [], "acoes": [],
               "tac": []}
    vars_ = _variantes_estado(canon)
    q = ",".join("?" * len(vars_))
    try:
        if _tem(con, "sei_arvore"):
            r = con.execute(f"SELECT * FROM sei_arvore WHERE numero_sei IN ({q})", vars_).fetchone()
            if r:
                f["identidade"].update({"objeto": r["objeto"], "nivel_risco": r["nivel_risco"], "n_docs_arvore": r["n_docs"],
                                        "n_obs": r["n_obs"], "total_pago": r["total_pago"], "situacao": r["situacao"],
                                        "lifecycle": r["lifecycle"], "ultima_ob": r["ultima_ob"], "atualizado_em": r["atualizado_em"]})
                f["contratos"] = [{"fonte": "sei_arvore.fornecedores", **x} for x in (_js(r["fornecedores"]) or []) if isinstance(x, dict)]
            f["cobertura"]["sei_arvore"] = "lida" if r else "ausente"
        if _tem(con, "sei_ficha"):
            r = con.execute(f"SELECT * FROM sei_ficha WHERE numero_sei IN ({q})", vars_).fetchone()
            if r:
                f["identidade"].setdefault("objeto", r["objeto"])
                f["identidade"].update({"modalidade": r["modalidade"], "fundamento_legal": r["fundamento_legal"], "resumo": r["resumo"],
                                        "cnpjs": _js(r["cnpjs"]) or [], "partes": _js(r["partes"]) or r["partes"], "valores": _js(r["valores"]) or r["valores"]})
                f["pericias"] = {"red_flags": _js(r["red_flags"]) or r["red_flags"], "contabil": _js(r["pericia_contabil"]) or r["pericia_contabil"],
                                 "juridica": _js(r["pericia_juridica"]) or r["pericia_juridica"], "analise": r["analise"], "nivel_risco": r["nivel_risco"],
                                 "fonte_modelo": r["fonte_modelo"], "atualizado_em": r["atualizado_em"]}
            f["cobertura"]["sei_ficha"] = "lida" if r else "ausente"
        if _tem(con, "processo_avaliacao"):
            r = con.execute(f"SELECT * FROM processo_avaliacao WHERE numero_sei IN ({q})", vars_).fetchone()
            if r:
                f["avaliacao_360"] = {"score100": r["score100"], "grau": r["grau"], "faixa": r["faixa"], "cnpj_vencedor": r["cnpj_vencedor"],
                                      "confianca": r["confianca"], "avaliado_em": r["avaliado_em"], "achados": _js(r["achados_json"]) or [],
                                      "lacunas": _js(r["lacunas_json"]) or [], "docs_chave": _js(r["docs_chave_json"]) or [],
                                      "sintese": _js(r["sintese_json"]), "cobertura": _js(r["cobertura_json"])}
                for a in f["avaliacao_360"]["achados"]:
                    if isinstance(a, dict):
                        f["achados"].append({"fonte": "avaliacao_360", "codigo": a.get("codigo"), "grau": a.get("grau"), "diz": a.get("diz"), "apoio": a.get("apoio")})
            f["cobertura"]["avaliacao_360"] = "lida" if r else "não avaliado (POST /api/processo/avaliar)"
        if _tem(con, "agente_processo"):
            f["agentes"] = [dict(x) for x in con.execute(f"SELECT nome, papel, cargo, origem, documento, contexto FROM agente_processo "
                                                          f"WHERE processo IN ({q})", vars_)]
        if _tem(con, "ob_orcamentaria_siafe"):
            # PAGO = só OB `Contabilizado`. Anulada/Excluída/Não contabilizada somavam R$ 6,58 bi em 5.726 processos
            # e inflavam o total da ficha (medido 24/09/2026); aparecem à parte, na lista, com o status.
            rows = con.execute(f"SELECT credor, nome_credor, count(*) n, round(sum(valor),2) total, min(data_emissao) primeira, max(data_emissao) ultima, "
                               f"group_concat(DISTINCT ug_emitente) ugs FROM ob_orcamentaria_siafe WHERE processo IN ({q}) AND status='Contabilizado' "
                               f"GROUP BY credor ORDER BY total DESC LIMIT 30", vars_).fetchall()
            lista = [dict(x) for x in con.execute(
                f"SELECT numero_ob, data_emissao, ug_emitente, credor, nome_credor, valor, status FROM ob_orcamentaria_siafe "
                f"WHERE processo IN ({q}) ORDER BY substr(data_emissao,7,4)||substr(data_emissao,4,2)||substr(data_emissao,1,2) DESC LIMIT 400", vars_)]
            nao_pagas = [x for x in lista if x["status"] != "Contabilizado"]
            f["obs"] = {"fonte": "SIAFE (ob_orcamentaria_siafe.processo, só OB Contabilizado no total)", "n": sum(x["n"] for x in rows),
                        "total": round(sum(x["total"] or 0 for x in rows), 2), "por_credor": [dict(x) for x in rows], "lista": lista,
                        "n_nao_pagas": len(nao_pagas), "valor_nao_pago": round(sum(x["valor"] or 0 for x in nao_pagas), 2)}
            f["cobertura"]["obs_siafe"] = (f"{f['obs']['n']} OB(s) contabilizada(s) com este nº de processo"
                                           + (f"; {len(nao_pagas)} anulada(s)/excluída(s) fora do total" if nao_pagas else "")) if lista \
                else "nenhuma OB do SIAFE cita este processo"
        if _tem(con, "doerj_tac"):
            f["tac"] = [dict(x) for x in con.execute(
                f"SELECT data_doe, numero_tac, orgao, fornecedor, cnpj, valor, objeto, data_assinatura, id_publicacao "
                f"FROM doerj_tac WHERE processo IN ({q}) ORDER BY data_doe", vars_)]
            f["cobertura"]["doerj_tac"] = (f"{len(f['tac'])} extrato(s) de TAC no DOERJ citam este processo" if f["tac"]
                                           else "nenhum extrato de TAC no DOERJ cita este processo (DOERJ lido desde 02/01/2026)")
        if _tem(con, "sei_fila_captura"):
            r = con.execute(f"SELECT * FROM sei_fila_captura WHERE numero_sei IN ({q}) OR processo IN ({q})", vars_ + vars_).fetchone() \
                if "processo" in [c[1] for c in con.execute("PRAGMA table_info(sei_fila_captura)")] else None
            if r:
                f["identidade"]["fila_captura"] = {k: r[k] for k in r.keys()}
    finally:
        for c in (con,):
            if c:
                c.close()
    cat = _ro(DB_SEI_RJ)
    try:
        if _tem(cat, "sei_rj_processo"):
            r = cat.execute(f"SELECT tipo, unidade_sigla, unidade_nome, orgao, data FROM sei_rj_processo WHERE numero IN ({q})", vars_).fetchone()
            if r:
                f["identidade"].update({"tipo": r["tipo"], "unidade": r["unidade_sigla"], "unidade_nome": r["unidade_nome"],
                                        "orgao_gerador": r["orgao"], "gerado_em": r["data"]})
            f["cobertura"]["catalogo_publico"] = "lido" if r else "fora do catálogo (só tipos de contratação/controle são catalogados)"
    finally:
        if cat:
            cat.close()
    # arquivo compacto (documentos com texto)
    pasta = ARQUIVO_SEI / vars_[2]
    man = pasta / "manifest.json"
    if man.exists():
        m = _js(man.read_text(encoding="utf-8", errors="ignore")) or {}
        docs = m.get("docs") or []
        f["documentos"] = [{"seq": d.get("i"), "titulo": d.get("titulo"), "tipo": d.get("tipo"), "fase": d.get("fase"), "chars": int(d.get("chars") or 0),
                            "ocr": str(d.get("ocr")) == "True", "texto_path": str(pasta / d["texto"]) if d.get("texto") else None} for d in docs if isinstance(d, dict)]
        f["identidade"]["arquivo"] = {"docs": len(docs), "docs_na_arvore": m.get("docs_na_arvore"), "lacunas": m.get("lacunas"), "gerado_em": m.get("gerado_em"),
                                      "qualidade_cache": m.get("qualidade_cache"),
                                      "linha_do_tempo": (m.get("linha_do_tempo")[:40] if isinstance(m.get("linha_do_tempo"), list) else m.get("linha_do_tempo"))}
        f["cobertura"]["arquivo"] = f"{len(docs)} documento(s) com texto"
    else:
        f["cobertura"]["arquivo"] = "não capturado (data/sei_arquivo) — enfileirar em sei_fila_captura"
    try:
        if _tem(ach, "achado_detector"):
            for x in ach.execute(f"SELECT ug, detector, processo, score, status, motivo, explicacao_inocente, valores, evidencia, gerado_em "
                                 f"FROM achado_detector WHERE processo IN ({q})", vars_):
                f["achados"].append({"fonte": "achado_detector", "codigo": x["detector"], "grau": x["status"], "score": x["score"], "diz": x["motivo"],
                                     "apoio": x["evidencia"], "explicacao_inocente": x["explicacao_inocente"], "ug": x["ug"]})
    finally:
        if ach:
            ach.close()
    f["lai"] = _lai_do(lai, [canon] + vars_)
    f["acoes"] = [{"id": "avaliar_360", "rotulo": "Avaliar 360", "metodo": "POST", "rota": "/api/processo/avaliar", "body": {"numero": canon}},
                  {"id": "lai", "rotulo": "Gerar requerimento LAI", "metodo": "POST", "rota": "/api/lai/gerar", "body": {"alvo": canon, "esfera": "estado"}}]
    return f


def _slug(numero: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", numero.strip()).strip("_")


def pedir_consulta_pcrj(numero: str) -> dict:
    """Pede à VM-2 a consulta ao vivo de um processo da Prefeitura na pesquisa pública do SEI.RIO."""
    n = norm(numero)
    if not n or n[0] != "prefeitura":
        return {"ok": False, "erro": f"não é nº de processo da Prefeitura: {numero!r}"}
    ped = CONSULTA_PCRJ / "pedidos"
    ped.mkdir(parents=True, exist_ok=True)
    tmp = ped / (_slug(n[1]) + ".req.tmp")
    tmp.write_text(n[1], encoding="utf-8")
    tmp.replace(ped / (_slug(n[1]) + ".req"))
    return {"ok": True, "numero": n[1], "pedido": True,
            "mensagem": "Pedido enviado à VM-2: a consulta à pesquisa pública do SEI.RIO sai em até ~3 min; reabra a ficha."}


def ler_consulta_pcrj(numero: str) -> dict | None:
    """Resposta da consulta ao vivo (ou {'pendente': True}); None se nunca foi pedida."""
    s = _slug(numero)
    resp, ped = CONSULTA_PCRJ / "respostas" / f"{s}.json", CONSULTA_PCRJ / "pedidos" / f"{s}.req"
    if resp.exists() and (not ped.exists() or resp.stat().st_mtime >= ped.stat().st_mtime):
        return _js(resp.read_text(encoding="utf-8", errors="ignore"))
    return {"pendente": True} if ped.exists() else None


def _ficha_prefeitura(numero: str) -> dict:
    con, lai = _ro(DB_PCRJ), _ro(DB_LAI)
    f: dict = {"esfera": "prefeitura", "numero": numero, "cobertura": {}, "identidade": {}, "documentos": [], "obs": {}, "contratos": [],
               "agentes": [], "achados": [], "pericias": {}, "avaliacao_360": None, "lai": [], "acoes": []}
    try:
        if _tem(con, "pcrj_processo"):
            r = con.execute("SELECT * FROM pcrj_processo WHERE upper(numero_processo)=upper(?)", (numero,)).fetchone()
            if r:
                f["identidade"].update({"sistema": r["sistema"], "tipo": r["assunto"], "unidade": r["orgao"], "disponivel_na_pesquisa_publica": r["disponivel"],
                                        "coletado_em": r["coletado_em"]})
            f["cobertura"]["catalogo"] = "no catálogo" if r else "fora do catálogo público do SEI municipal"
        if _tem(con, "pcrj_sei_arvore"):
            arv = con.execute("SELECT doc, tipo, data, inclusao, unidade FROM pcrj_sei_arvore WHERE upper(numero)=upper(?) ORDER BY data", (numero,)).fetchall()
            f["documentos"] = [{"seq": x["doc"], "titulo": x["tipo"], "tipo": x["tipo"], "data": x["data"], "unidade": x["unidade"], "texto_path": None} for x in arv]
            f["cobertura"]["arvore"] = f"{len(arv)} documento(s) listados (sem conteúdo público)" if arv else "árvore não capturada"
        if _tem(con, "pcrj_processo_doc"):
            obt = con.execute("SELECT seq, tipo, titulo, length(texto) chars, url FROM pcrj_processo_doc WHERE upper(numero_processo)=upper(?) ORDER BY seq", (numero,)).fetchall()
            vistos = {str(d["seq"]) for d in f["documentos"]}
            for x in obt:
                d = {"seq": str(x["seq"]), "titulo": x["titulo"], "tipo": x["tipo"], "chars": x["chars"], "url": x["url"], "com_texto": True}
                if str(x["seq"]) in vistos:
                    for dd in f["documentos"]:
                        if dd["seq"] == str(x["seq"]):
                            dd.update(d)
                else:
                    f["documentos"].append(d)
            f["cobertura"]["integras"] = f"{len(obt)} documento(s) com texto (CCON/conferência)" if obt else "nenhuma íntegra obtida"
        if _tem(con, "pcrj_doc_campos"):
            campos: dict[str, list] = {}
            for x in con.execute("SELECT campo, valor, seq FROM pcrj_doc_campos WHERE upper(numero_processo)=upper(?) ORDER BY campo", (numero,)):
                campos.setdefault(x["campo"], []).append({"valor": x["valor"], "seq": x["seq"]})
            f["pericias"]["leitura_estruturada"] = campos
        if _tem(con, "pcrj_sei_assinatura"):
            tem_nome = _tem(con, "pcrj_sei_assinante")
            sql = ("SELECT a.matricula, count(*) n, min(a.quando) primeira, max(a.quando) ultima" + (", s.nome, s.orgao, s.sigla_ua" if tem_nome else ", NULL nome, NULL orgao, NULL sigla_ua")
                   + " FROM pcrj_sei_assinatura a" + (" LEFT JOIN pcrj_sei_assinante s ON s.matricula=a.matricula" if tem_nome else "")
                   + " WHERE upper(a.numero)=upper(?) GROUP BY a.matricula ORDER BY n DESC")
            f["agentes"] = [{"nome": x["nome"] or f"matrícula {x['matricula']}", "papel": "assinante", "cargo": x["sigla_ua"] or x["orgao"], "matricula": x["matricula"],
                             "n_assinaturas": x["n"], "primeira": x["primeira"], "ultima": x["ultima"]} for x in con.execute(sql, (numero,))]
        if _tem(con, "pcrj_sei_andamento"):
            f["identidade"]["andamentos"] = [dict(x) for x in con.execute("SELECT quando, unidade, descricao FROM pcrj_sei_andamento WHERE upper(numero)=upper(?) "
                                                                            "ORDER BY quando DESC LIMIT 40", (numero,))]
        if _tem(con, "contasrio_contrato"):
            f["contratos"] = [{"fonte": "ContasRio", **dict(x)} for x in con.execute(
                "SELECT contrato, favorecido_doc cnpj, favorecido_nome nome, orgao, ano, forma_contratacao, objeto, valor_atualizado valor, total_pago, "
                "vigencia_ini, vigencia_fim, url_ccon FROM contasrio_contrato WHERE upper(processo)=upper(?)", (numero,))]
            if _tem(con, "contasrio_fiscal") and f["contratos"]:
                ids = [c["contrato"] for c in f["contratos"]]
                for x in con.execute(f"SELECT contrato, fiscal_nome, fiscal_doc FROM contasrio_fiscal WHERE contrato IN ({','.join('?' * len(ids))})", ids):
                    f["agentes"].append({"nome": x["fiscal_nome"], "papel": "fiscal do contrato", "cargo": x["fiscal_doc"], "contrato": x["contrato"]})
            f["obs"] = {"fonte": "ContasRio (pago pelo Município, não OB do SIAFE)", "n": len(f["contratos"]),
                        "total": round(sum(c.get("total_pago") or 0 for c in f["contratos"]), 2), "por_credor": []}
        if _tem(con, "pcrj_emergencia_sinal"):
            for x in con.execute("SELECT * FROM pcrj_emergencia_sinal WHERE upper(processo)=upper(?)", (numero,)):
                f["achados"].append({"fonte": "emergencia_incumbente", "codigo": "EMERGENCIA-INCUMBENTE", "grau": x["grau"], "diz": x["detalhe"],
                                     "apoio": f"fundamento: {x['fundamento']}; motivo: {x['motivo']}", "explicacao_inocente": "desastre declarado / vão entre certames"})
        if _tem(con, "pcrj_ocp_sinal"):
            for x in con.execute("SELECT * FROM pcrj_ocp_sinal WHERE upper(processo_2)=upper(?) OR upper(processo_1)=upper(?)", (numero, numero)):
                f["achados"].append({"fonte": "ocp_redflags", "codigo": f"OCP-{x['indicador']}", "grau": x["grau"], "diz": x["detalhe"],
                                     "apoio": f"contratos {x['contrato_1']} → {x['contrato_2']} ({x['favorecido_nome']})",
                                     "explicacao_inocente": "expansão legítima do serviço; 1º contrato foi piloto ou emergência real"})
        if _tem(con, "pcrj_sei_busca"):
            f["identidade"]["termos_que_acharam"] = [x[0] for x in con.execute("SELECT DISTINCT termo FROM pcrj_sei_busca WHERE upper(processo)=upper(?) LIMIT 20", (numero,))]
    finally:
        if con:
            con.close()
    f["lai"] = _lai_do(lai, [numero])
    f["consulta_ao_vivo"] = ler_consulta_pcrj(numero)
    cv = f["consulta_ao_vivo"] or {}
    f["cobertura"]["consulta_ao_vivo"] = ("pedida — aguardando a VM-2" if cv.get("pendente") else
                                          f"SEI.RIO consultado em {cv.get('consultado_em')}: {len(cv.get('documentos') or [])} documento(s) na árvore"
                                          if cv else "nunca consultado ao vivo")
    f["acoes"] = [{"id": "consultar_pcrj", "rotulo": "Consultar agora no SEI.RIO", "metodo": "POST", "rota": "/api/pcrj/consultar", "body": {"numero": numero}},
                  {"id": "lai", "rotulo": "Gerar requerimento LAI", "metodo": "POST", "rota": "/api/lai/gerar", "body": {"alvo": numero, "esfera": "prefeitura"}}]
    for c in f["contratos"]:
        if c.get("cnpj"):
            f["acoes"].append({"id": f"dossie_{c['cnpj']}", "rotulo": f"Dossiê do fornecedor {c.get('nome', '')[:30]}", "metodo": "dossie", "cnpj": c["cnpj"], "nome": c.get("nome")})
            break
    return f


def _lai_do(lai, numeros: list[str]) -> list[dict]:
    if not _tem(lai, "lai_requerimento"):
        if lai:
            lai.close()
        return []
    try:
        saida = []
        for r in lai.execute("SELECT id, alvo, esfera, status, protocolo, prazo_resposta, criado_em, processos FROM lai_requerimento ORDER BY id DESC LIMIT 300"):
            procs = _js(r["processos"]) or []
            if r["alvo"] in numeros or any(p in numeros for p in procs):
                saida.append(dict(r))
        return saida
    finally:
        lai.close()


def ficha(numero: str) -> dict:
    n = norm(numero)
    if not n:
        return {"ok": False, "erro": f"número não reconhecido: {numero!r} (Estado: 6/6/4 dígitos; Prefeitura: 000700.007924/2026-97 ou SME-PRO-2025/38233)"}
    esfera, canon = n
    f = _ficha_estado(canon) if esfera == "estado" else _ficha_prefeitura(canon)
    f["ok"] = True
    f["n_achados"] = len(f["achados"])
    f["existe"] = bool(f["identidade"] or f["documentos"] or f["contratos"] or (f["obs"] or {}).get("n") or f.get("tac")
                       or (f.get("consulta_ao_vivo") or {}).get("documentos"))
    return f


def texto_documento(numero: str, seq: str, limite: int = 200_000) -> dict:
    """Texto de um documento: Estado = arquivo compacto (data/sei_arquivo); Prefeitura = pcrj_processo_doc."""
    n = norm(numero)
    if not n:
        return {"ok": False, "erro": "número não reconhecido"}
    esfera, canon = n
    if esfera == "estado":
        pasta = ARQUIVO_SEI / _variantes_estado(canon)[2]
        m = _js((pasta / "manifest.json").read_text(encoding="utf-8", errors="ignore")) if (pasta / "manifest.json").exists() else None
        for d in (m or {}).get("docs") or []:
            if str(d.get("i")) == str(seq) and d.get("texto"):
                p = pasta / d["texto"]
                if p.exists():
                    return {"ok": True, "titulo": d.get("titulo"), "texto": p.read_text(encoding="utf-8", errors="ignore")[:limite]}
        return {"ok": False, "erro": "documento sem texto no arquivo compacto"}
    con = _ro(DB_PCRJ)
    try:
        if not _tem(con, "pcrj_processo_doc"):
            return {"ok": False, "erro": "sem íntegras municipais"}
        r = con.execute("SELECT titulo, texto FROM pcrj_processo_doc WHERE upper(numero_processo)=upper(?) AND seq=?", (canon, int(_digits(seq) or 0))).fetchone()
        if not r:
            return {"ok": False, "erro": "documento sem íntegra obtida (a árvore lista, o SEI não abre)"}
        return {"ok": True, "titulo": r["titulo"], "texto": (r["texto"] or "")[:limite]}
    finally:
        if con:
            con.close()


# ───────────────────────────── BUSCA ─────────────────────────────

def _hit(esfera, numero, objeto=None, orgao=None, grau=None, total=None, n_docs=None, fonte=None, data=None, extra=None) -> dict:
    return {"esfera": esfera, "numero": numero, "objeto": (objeto or "")[:200], "orgao": (orgao or "")[:80], "grau": grau, "total_pago": total,
            "n_docs": n_docs, "fonte": fonte, "data": data, **(extra or {})}


def buscar(q: str, esfera: str = "todos", limite: int = 60) -> dict:
    """Busca única: nº de processo → ficha direta; CNPJ (14 dígitos) → processos do fornecedor (SIAFE, sei_arvore,
    ContasRio); texto → objeto/tipo/assunto/título nas duas esferas. Devolve hits deduplicados por (esfera, nº)."""
    q = (q or "").strip()
    if not q:
        return {"ok": False, "erro": "informe o que procurar"}
    hits: dict[tuple, dict] = {}

    def add(h):
        k = (h["esfera"], h["numero"])
        if k in hits:
            for kk, v in h.items():
                if v and not hits[k].get(kk):
                    hits[k][kk] = v
            hits[k]["fonte"] = ",".join(sorted(set((hits[k].get("fonte") or "").split(",")) | set((h.get("fonte") or "").split(","))))
        else:
            hits[k] = h

    n = norm(q)
    if n and (esfera in ("todos", n[0])):
        f = ficha(q)
        if f.get("existe"):
            idt = f["identidade"]
            add(_hit(f["esfera"], f["numero"], idt.get("objeto") or idt.get("tipo"), idt.get("unidade") or "", (f.get("avaliacao_360") or {}).get("grau") or idt.get("nivel_risco"),
                     (f.get("obs") or {}).get("total"), len(f["documentos"]), "ficha", extra={"n_achados": f["n_achados"]}))
        return {"ok": True, "q": q, "tipo": "numero", "hits": list(hits.values()), "n": len(hits)}

    dig = _digits(q)
    e_cnpj = len(dig) == 14
    like = f"%{q.upper()}%"
    lim = max(10, min(int(limite or 60), 300))
    con = _ro(DB_COMPLIANCE)
    if con and esfera in ("todos", "estado"):
        try:
            if _tem(con, "sei_arvore"):
                sql = "SELECT numero_sei, objeto, nivel_risco, n_docs, total_pago, fornecedores, atualizado_em FROM sei_arvore WHERE "
                rows = con.execute(sql + "fornecedores LIKE ? ORDER BY total_pago DESC LIMIT ?", (f"%{dig}%", lim)).fetchall() if e_cnpj else \
                    con.execute(sql + "upper(objeto) LIKE ? ORDER BY total_pago DESC LIMIT ?", (like, lim)).fetchall()
                for r in rows:
                    forn = _js(r["fornecedores"]) or []
                    add(_hit("estado", norm(r["numero_sei"])[1], r["objeto"], (forn[0].get("nome") if forn and isinstance(forn[0], dict) else ""), r["nivel_risco"],
                             r["total_pago"], r["n_docs"], "sei_arvore", r["atualizado_em"]))
            if _tem(con, "processo_avaliacao"):
                sql = "SELECT numero_sei, score100, grau, faixa, cnpj_vencedor, avaliado_em FROM processo_avaliacao WHERE "
                rows = con.execute(sql + "cnpj_vencedor=? ORDER BY score100 DESC LIMIT ?", (dig, lim)).fetchall() if e_cnpj else []
                for r in rows:
                    nn = norm(r["numero_sei"])
                    if nn:
                        add(_hit("estado", nn[1], None, None, r["grau"], None, None, "avaliacao_360", r["avaliado_em"], {"score100": r["score100"], "faixa": r["faixa"]}))
            if _tem(con, "sei_ficha") and not e_cnpj:
                for r in con.execute("SELECT numero_sei, objeto, nivel_risco, n_docs, atualizado_em FROM sei_ficha WHERE upper(objeto) LIKE ? OR upper(resumo) LIKE ? LIMIT ?",
                                     (like, like, lim)):
                    nn = norm(r["numero_sei"])
                    if nn:
                        add(_hit("estado", nn[1], r["objeto"], None, r["nivel_risco"], None, r["n_docs"], "sei_ficha", r["atualizado_em"]))
            if _tem(con, "doerj_tac") and (e_cnpj or len(q) >= 4):
                cond, arg = ("replace(replace(replace(cnpj,'.',''),'/',''),'-','')=?", dig) if e_cnpj else ("upper(fornecedor) LIKE ?", like)
                for r in con.execute(f"SELECT processo, max(fornecedor) forn, max(orgao) org, count(*) n, round(sum(valor),2) soma, max(data_doe) ult, "
                                     f"max(objeto) obj FROM doerj_tac WHERE processo IS NOT NULL AND {cond} GROUP BY processo "
                                     f"ORDER BY soma DESC LIMIT ?", (arg, lim)):
                    nn = norm(r["processo"])
                    if nn:
                        add(_hit("estado", nn[1], f"TAC: {r['obj'] or ''}", r["org"], None, None, None, "doerj_tac", r["ult"],
                                 {"fornecedor": r["forn"], "n_tac": r["n"], "soma_tac_publicada": r["soma"]}))
            if _tem(con, "ob_orcamentaria_siafe") and e_cnpj:
                for r in con.execute("SELECT processo, nome_credor, count(*) n, round(sum(valor),2) total, max(data_emissao) ultima FROM ob_orcamentaria_siafe "
                                     "WHERE credor LIKE ? AND processo LIKE 'SEI-%' AND status='Contabilizado' GROUP BY processo ORDER BY total DESC LIMIT ?", (f"%{dig[:8]}%", lim)):
                    nn = norm(r["processo"])
                    if nn:
                        add(_hit("estado", nn[1], None, r["nome_credor"], None, r["total"], None, "siafe_ob", r["ultima"], {"n_obs": r["n"]}))
        finally:
            con.close()
    cat = _ro(DB_SEI_RJ)
    if cat and esfera in ("todos", "estado") and not e_cnpj and len(q) >= 3:
        try:
            if _tem(cat, "sei_rj_processo"):
                for r in cat.execute("SELECT numero, tipo, unidade_sigla, unidade_nome, data FROM sei_rj_processo WHERE upper(tipo) LIKE ? "
                                     "OR upper(unidade_sigla) LIKE ? OR upper(unidade_nome) LIKE ? ORDER BY data DESC LIMIT ?", (like, like, like, lim)):
                    add(_hit("estado", r["numero"], r["tipo"], r["unidade_sigla"], None, None, None, "catalogo_publico", r["data"],
                             {"unidade_nome": r["unidade_nome"]}))
        finally:
            cat.close()
    pc = _ro(DB_PCRJ)
    if pc and esfera in ("todos", "prefeitura"):
        try:
            if _tem(pc, "contasrio_contrato"):
                sql = ("SELECT processo, favorecido_nome, orgao, objeto, forma_contratacao, total_pago, ano FROM contasrio_contrato WHERE processo<>'' AND ")
                rows = pc.execute(sql + "favorecido_doc=? ORDER BY coalesce(total_pago,0) DESC LIMIT ?", (dig, lim)).fetchall() if e_cnpj else \
                    pc.execute(sql + "(upper(objeto) LIKE ? OR upper(favorecido_nome) LIKE ? OR upper(orgao) LIKE ?) ORDER BY coalesce(total_pago,0) DESC LIMIT ?",
                               (like, like, like, lim)).fetchall()
                for r in rows:
                    add(_hit("prefeitura", r["processo"], f"{r['forma_contratacao']}: {r['objeto']}", r["orgao"], None, r["total_pago"], None, "contasrio", str(r["ano"]),
                             {"fornecedor": r["favorecido_nome"]}))
            if _tem(pc, "pcrj_emergencia_sinal"):
                rows = pc.execute("SELECT processo, favorecido_nome, orgao, grau, total_pago, detalhe FROM pcrj_emergencia_sinal WHERE favorecido_doc=? OR upper(favorecido_nome) LIKE ? "
                                  "OR upper(orgao) LIKE ? LIMIT ?", (dig if e_cnpj else "-", like, like, lim)).fetchall()
                for r in rows:
                    add(_hit("prefeitura", r["processo"], r["detalhe"], r["orgao"], r["grau"], r["total_pago"], None, "emergencia", None, {"fornecedor": r["favorecido_nome"]}))
            if _tem(pc, "pcrj_ocp_sinal"):
                for r in pc.execute("SELECT processo_2, favorecido_nome, orgao, grau, valor_2, detalhe FROM pcrj_ocp_sinal WHERE favorecido_doc=? OR upper(favorecido_nome) LIKE ? "
                                    "OR upper(orgao) LIKE ? LIMIT ?", (dig if e_cnpj else "-", like, like, lim)):
                    if r["processo_2"]:
                        add(_hit("prefeitura", r["processo_2"], r["detalhe"], r["orgao"], r["grau"], None, None, "ocp_r052", None, {"fornecedor": r["favorecido_nome"]}))
            if _tem(pc, "pcrj_processo") and not e_cnpj and len(q) >= 4:
                for r in pc.execute("SELECT numero_processo, assunto, orgao, disponivel FROM pcrj_processo WHERE sistema='SEI.RIO' AND (upper(assunto) LIKE ? OR upper(orgao) LIKE ?) "
                                    "ORDER BY coletado_em DESC LIMIT ?", (like, like, lim)):
                    add(_hit("prefeitura", r["numero_processo"], r["assunto"], r["orgao"], None, None, None, "catalogo", None, {"disponivel": r["disponivel"]}))
            if _tem(pc, "pcrj_sei_busca") and not e_cnpj:
                for r in pc.execute("SELECT DISTINCT processo, titulo, unidade, data FROM pcrj_sei_busca WHERE processo IS NOT NULL AND (upper(termo) LIKE ? OR upper(titulo) LIKE ?) LIMIT ?",
                                    (like, like, lim)):
                    add(_hit("prefeitura", r["processo"], r["titulo"], r["unidade"], None, None, None, "busca_livre", r["data"]))
        finally:
            pc.close()
    itens = sorted(hits.values(), key=lambda h: (-(h.get("total_pago") or 0), h["numero"]))[:lim]
    return {"ok": True, "q": q, "tipo": "cnpj" if e_cnpj else "texto", "hits": itens, "n": len(itens), "esferas": {e: sum(1 for h in itens if h["esfera"] == e) for e in ("estado", "prefeitura")}}


def estatisticas() -> dict:
    """Números do acervo para o cabeçalho da aba — cada um com a tabela de origem."""
    out = {}
    con = _ro(DB_COMPLIANCE)
    if con:
        try:
            for k, sql in (("estado_arvores", "SELECT count(*) FROM sei_arvore"), ("estado_fichas", "SELECT count(*) FROM sei_ficha"),
                           ("estado_avaliados_360", "SELECT count(*) FROM processo_avaliacao"),
                           ("estado_obs_com_processo", "SELECT count(DISTINCT processo) FROM ob_orcamentaria_siafe WHERE processo LIKE 'SEI-%'")):
                try:
                    out[k] = con.execute(sql).fetchone()[0]
                except sqlite3.Error:
                    out[k] = None
        finally:
            con.close()
    cat = _ro(DB_SEI_RJ)
    if cat:
        try:
            out["estado_catalogo"] = cat.execute("SELECT count(*) FROM sei_rj_processo").fetchone()[0] if _tem(cat, "sei_rj_processo") else None
        finally:
            cat.close()
    out["estado_arquivos"] = sum(1 for p in ARQUIVO_SEI.iterdir() if (p / "manifest.json").exists()) if ARQUIVO_SEI.exists() else 0
    pc = _ro(DB_PCRJ)
    if pc:
        try:
            for k, sql in (("pcrj_catalogo", "SELECT count(*) FROM pcrj_processo WHERE sistema='SEI.RIO'"), ("pcrj_com_arvore", "SELECT count(DISTINCT numero) FROM pcrj_sei_arvore"),
                           ("pcrj_com_integra", "SELECT count(DISTINCT numero_processo) FROM pcrj_processo_doc"), ("pcrj_contratos", "SELECT count(*) FROM contasrio_contrato"),
                           ("pcrj_emergencias", "SELECT count(*) FROM pcrj_emergencia_sinal"),
                           ("pcrj_ocp_r052", "SELECT count(*) FROM pcrj_ocp_sinal")):
                try:
                    out[k] = pc.execute(sql).fetchone()[0]
                except sqlite3.Error:
                    out[k] = None
        finally:
            pc.close()
    return out
