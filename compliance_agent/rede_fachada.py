# -*- coding: utf-8 -*-
"""
Pacote de inteligência de FACHADA/LARANJA — monta o dict de sinais determinísticos (1-4) para um CNPJ,
reusando o que já existe (sem duplicar). É o INPUT do raciocínio LLM (gemini/cerebras) na §II-E do Lex.

Sinais (pedido do dono — codificar o caso IDESI como padrão):
  1. TAC/indenização     → reporting.detector_tac.red_flag_tac (o achado central, determinístico)
  2. Sede/fachada        → verificacao_sede (status, places_achou=0, visual_classe, evidencia)
  3. Cadastro (situação) → situação cadastral se disponível; senão INDISPONÍVEL honesto (não fabrica)
  4. Rede                → socios_receita (QSA real, incl. Presidente/Diretor de associação) +
                           rede_socios_fornecedores (pessoas ligando ≥2 fornecedores nossos)

Tudo é READ-ONLY e degrada honesto (tabela ausente → o sinal vira INDISPONÍVEL, nunca quebra).
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolver_db(db_path=None) -> Path:
    if db_path:
        return Path(db_path)
    env = os.environ.get("JFN_DB")
    if env:
        return Path(env)
    data = Path(os.environ.get("JFN_DATA_DIR", _root() / "data"))
    return data / "compliance.db"


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _ro(db: Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        return con
    except Exception:  # noqa: BLE001
        return None


def _data_br(s) -> str:
    """YYYYMMDD → dd/mm/aaaa (formato do dump da Receita); passa adiante o que não casar."""
    d = _digitos(s)
    if len(d) == 8:
        return f"{d[6:8]}/{d[4:6]}/{d[0:4]}"
    return str(s or "")


# ───────────────────────── 2. sede / fachada ─────────────────────────

def sinal_sede(cnpj: str, *, db_path=None) -> dict:
    """Lê `verificacao_sede` (Google + visão) p/ o CNPJ. Honesto: ausente → INDISPONÍVEL."""
    db = _resolver_db(db_path)
    con = _ro(db)
    if not con:
        return {"cobertura": "INDISPONIVEL (base ausente)"}
    try:
        try:
            r = con.execute(
                "SELECT status, nivel, geo_tipo, addr_residencial, places_achou, places_bate_nome, "
                "evidencia, visual_classe, visual_conf, visual_fonte, municipio, uf, total_recebido "
                "FROM verificacao_sede WHERE cnpj=?", (_digitos(cnpj),)).fetchone()
        except sqlite3.OperationalError:
            r = None
    finally:
        con.close()
    if not r:
        return {"cobertura": "INDISPONIVEL (sede ainda não verificada)"}
    d = dict(r)
    d["cobertura"] = f"verificado ({d.get('status', '')}/{d.get('nivel', '')})"
    # leitura honesta dos sinais visuais e de operação
    d["sem_negocio_google"] = (d.get("places_achou") == 0)
    d["residencial"] = (d.get("addr_residencial") == 1)
    vc = (d.get("visual_classe") or "")
    d["visual_suspeito"] = bool(vc) and vc.lower() in (
        "terreno_baldio", "area_aberta_rural", "area_aberta", "area_rural", "vegetacao", "obra")
    return d


# ───────────────────────── 3. cadastro (situação) ─────────────────────────

def sinal_cadastro(cnpj: str, *, cadastral: dict | None = None) -> dict:
    """Situação cadastral (INAPTA/'inexistência de fato'/BAIXADA…) se disponível; senão INDISPONÍVEL.

    Não fabrica: usa o que vier em `cadastral` (do enriquecimento do produto) ou, se None, tenta o
    registry best-effort. Sem dado → cobertura INDISPONIVEL (≠ regular)."""
    cad = cadastral
    if cad is None and len(_digitos(cnpj)) == 14:
        try:
            from compliance_agent.providers import lookup
            r = lookup("registry", cnpj=_digitos(cnpj))
            cad = r.dados if (getattr(r, "ok", False) and isinstance(r.dados, dict)) else None
        except Exception:  # noqa: BLE001
            cad = None
    if not cad:
        return {"cobertura": "INDISPONIVEL (cadastro não disponível nesta varredura)"}
    sit = str(cad.get("situacao") or "").upper()
    motivo = str(cad.get("situacao_motivo") or cad.get("motivo_situacao") or "")
    irregular = any(t in sit for t in ("BAIXAD", "INAPT", "SUSPENS", "NULA"))
    return {
        "cobertura": "verificado" if sit else "INDISPONIVEL (sem campo de situação)",
        "situacao": cad.get("situacao") or "", "motivo": motivo, "irregular": irregular,
        "abertura": cad.get("abertura") or cad.get("data_abertura") or "",
        "natureza": cad.get("natureza_juridica") or cad.get("natureza") or "",
    }


# ───────────────────────── 4. rede (QSA real + pessoas que ligam fornecedores) ─────────────────────────

def sinal_rede(cnpj: str, *, db_path=None) -> dict:
    """QSA REAL do CNPJ (socios_receita: Presidente/Diretor/Administrador) + os OUTROS fornecedores do
    Estado que compartilham as MESMAS pessoas (rede_socios_fornecedores).

    Retorna {cobertura, qsa:[…], administradores:[…], compartilhados:[…]} — tudo só do que está no DB
    (dump CNPJ ingerido). Honesto: sem tabela → INDISPONÍVEL; CPF dos sócios mascarado (LGPD)."""
    db = _resolver_db(db_path)
    con = _ro(db)
    if not con:
        return {"cobertura": "INDISPONIVEL (base de rede ausente)", "qsa": [], "compartilhados": []}
    raiz = _digitos(cnpj)[:8]
    qsa: list[dict] = []
    compartilhados: list[dict] = []
    try:
        try:
            for r in con.execute(
                "SELECT nome_socio, doc_socio, qualificacao_txt, data_entrada FROM socios_receita "
                "WHERE cnpj_basico=? ORDER BY qualificacao_cod", (raiz,)):
                qsa.append({"nome": r["nome_socio"], "doc": r["doc_socio"],
                            "qualificacao": r["qualificacao_txt"],
                            "entrada": _data_br(r["data_entrada"])})
        except sqlite3.OperationalError:
            return {"cobertura": "INDISPONIVEL (socios_receita ausente — rode o dump da Receita)",
                    "qsa": [], "compartilhados": []}
        # pessoas do QSA que aparecem em ≥2 fornecedores nossos (rede_socios_fornecedores)
        docs = {q["doc"] for q in qsa if q.get("doc")}
        nomes = {(q["nome"] or "").upper() for q in qsa if q.get("nome")}
        try:
            for r in con.execute(
                "SELECT nome_socio, doc_socio, n_fornecedores, cnpjs_basicos, qualificacoes, "
                "total_recebido FROM rede_socios_fornecedores WHERE n_fornecedores >= 2"):
                if r["doc_socio"] in docs or (r["nome_socio"] or "").upper() in nomes:
                    outros = [c for c in (r["cnpjs_basicos"] or "").split(",") if c and c != raiz]
                    compartilhados.append({
                        "pessoa": r["nome_socio"], "doc": r["doc_socio"],
                        "n_fornecedores": r["n_fornecedores"],
                        "outros_cnpjs": outros, "qualificacoes": r["qualificacoes"],
                        "total_recebido": float(r["total_recebido"] or 0.0)})
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    administradores = [q for q in qsa if any(
        t in (q.get("qualificacao") or "").upper()
        for t in ("PRESIDENTE", "DIRETOR", "ADMINISTRADOR", "SOCIO-ADM"))]
    # OUTROS VEÍCULOS dos administradores (socios_reverso: todos os CNPJs do Brasil onde a pessoa figura,
    # não só fornecedores nossos). É como o presidente do IDESI aparece em SIGNAL RIO (veículo externo).
    outros_veiculos = _outros_veiculos(administradores or qsa, raiz, db_path=db)
    if not qsa:
        cob = "INDISPONIVEL (sem QSA no dump para esta raiz)"
    else:
        cob = (f"verificado ({len(qsa)} no QSA; {len(compartilhados)} pessoa(s) ligando outros fornecedores; "
               f"{len(outros_veiculos)} outro(s) veículo(s) dos administradores)")
    return {"cobertura": cob, "qsa": qsa, "administradores": administradores,
            "compartilhados": compartilhados, "outros_veiculos": outros_veiculos}


_QUALIF = {  # principais códigos de qualificação de sócio (Receita) → rótulo legível
    "16": "Presidente", "10": "Diretor", "05": "Administrador", "49": "Sócio-Administrador",
    "22": "Sócio", "65": "Titular", "08": "Conselheiro de Administração",
}


def _outros_veiculos(pessoas: list[dict], raiz_alvo: str, *, db_path=None) -> list[dict]:
    """Para cada administrador/sócio, lista os OUTROS CNPJs onde figura (socios_reverso, todo o Brasil),
    marcando se é fornecedor nosso. Surfacia veículos externos (ex.: presidente IDESI → SIGNAL RIO).

    Honesto/bounded: só lê a tabela pré-computada (instantâneo, sem ZIP); ausente → []. Dedup por pessoa.
    """
    db = _resolver_db(db_path)
    con = _ro(db)
    if not con:
        return []
    nossas: set[str] = set()
    achados: list[dict] = []
    try:
        # raízes dos nossos fornecedores (p/ marcar veículo interno vs externo) — barato
        try:
            nossas = {r[0] for r in con.execute(
                "SELECT DISTINCT substr(favorecido_cpf,1,8) FROM ordens_bancarias "
                "WHERE length(favorecido_cpf)=14")}
        except sqlite3.OperationalError:
            nossas = set()
        vistos: set[str] = set()
        for p in pessoas:
            doc, nome = p.get("doc"), (p.get("nome") or "")
            if not doc or doc in vistos:
                continue
            vistos.add(doc)
            try:
                rows = con.execute(
                    "SELECT cnpj_basico, qualif_cod FROM socios_reverso WHERE doc_socio=? AND nome_norm=?",
                    (doc, nome.upper())).fetchall()
            except sqlite3.OperationalError:
                return []  # tabela ausente → sinal indisponível, não quebra
            outros = []
            for cnpj_b, qcod in rows:
                if cnpj_b == raiz_alvo:
                    continue
                razao = ""
                try:
                    rr = con.execute(
                        "SELECT razao_social FROM empresas_min WHERE cnpj_basico=?", (cnpj_b,)).fetchone()
                    razao = (rr[0] if rr else "") or ""
                except sqlite3.OperationalError:
                    razao = ""
                outros.append({"cnpj_basico": cnpj_b, "razao": razao,
                               "qualificacao": _QUALIF.get(str(qcod), f"cód {qcod}"),
                               "fornecedor_nosso": cnpj_b in nossas})
            if outros:
                achados.append({"pessoa": nome, "doc": doc,
                                "qualif_no_alvo": p.get("qualificacao"), "veiculos": outros})
    finally:
        con.close()
    return achados


# ───────────────────────── pacote completo (1-4) ─────────────────────────

def pacote_sinais(cnpj: str, *, total_pago: float = 0.0, cadastral: dict | None = None,
                  db_path=None) -> dict:
    """Monta o dict de sinais 1-4 p/ um CNPJ — INPUT do raciocínio LLM da §II-E do Lex.

    Reusa o que já existe: detector_tac (1), verificacao_sede (2), registry/enriquecimento (3),
    socios_receita + rede_socios_fornecedores (4). Tudo degrada honesto.
    """
    cnpj = _digitos(cnpj)
    db = _resolver_db(db_path)
    pac: dict = {"cnpj": cnpj, "total_pago": total_pago}
    # 1. TAC
    try:
        from compliance_agent.reporting.detector_tac import red_flag_tac, tac_por_cnpj
        rf = red_flag_tac(cnpj, db_path=db)
        pac["tac"] = rf if rf else {"red_flag": None, "metricas": tac_por_cnpj(cnpj, db_path=db)}
    except Exception as e:  # noqa: BLE001
        pac["tac"] = {"cobertura": f"INDISPONIVEL ({str(e)[:40]})"}
    # 2. sede / fachada
    try:
        pac["sede"] = sinal_sede(cnpj, db_path=db)
    except Exception as e:  # noqa: BLE001
        pac["sede"] = {"cobertura": f"INDISPONIVEL ({str(e)[:40]})"}
    # 3. cadastro
    try:
        pac["cadastro"] = sinal_cadastro(cnpj, cadastral=cadastral)
    except Exception as e:  # noqa: BLE001
        pac["cadastro"] = {"cobertura": f"INDISPONIVEL ({str(e)[:40]})"}
    # 4. rede
    try:
        pac["rede"] = sinal_rede(cnpj, db_path=db)
    except Exception as e:  # noqa: BLE001
        pac["rede"] = {"cobertura": f"INDISPONIVEL ({str(e)[:40]})"}
    return pac


# ───────────────────────── render markdown da rede (p/ o relatório/Lex) ─────────────────────────

def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def render_rede_md(rede: dict) -> list[str]:
    """Linhas markdown da REDE (administradores reais + outros veículos compartilhados). [] se INDISPONÍVEL."""
    if not rede or not rede.get("qsa"):
        return []
    linhas: list[str] = []
    adms = rede.get("administradores") or []
    if adms:
        quem = "; ".join(
            f"**{a['nome']}** ({a.get('qualificacao', '—')}, desde {a.get('entrada', '—')})" for a in adms[:6])
        linhas.append(f"- **Quadro de comando (QSA real, Receita):** {quem}.")
    comp = rede.get("compartilhados") or []
    if comp:
        for c in comp[:5]:
            outros = ", ".join(c.get("outros_cnpjs") or []) or "—"
            linhas.append(
                f"- **{c['pessoa']}** liga **{c['n_fornecedores']}** fornecedores do Estado "
                f"(outras raízes: {outros}; total recebido pela rede: {_moeda(c.get('total_recebido', 0))}) — "
                "diretores/sócios compartilhados entre fornecedores é red flag de rede de fachada/laranja.")
    # outros veículos dos administradores (todo o Brasil, via socios_reverso) — externos e internos
    veic = rede.get("outros_veiculos") or []
    for v in veic[:5]:
        itens = []
        for o in (v.get("veiculos") or [])[:6]:
            tag = "fornecedor do Estado" if o.get("fornecedor_nosso") else "veículo externo"
            nome = f" {o['razao']}" if o.get("razao") else ""
            itens.append(f"CNPJ {o['cnpj_basico']}…{nome} ({o.get('qualificacao', '—')}, {tag})")
        if itens:
            linhas.append(
                f"- O administrador **{v['pessoa']}** ({v.get('qualif_no_alvo', '—')}) figura também em: "
                + "; ".join(itens) + ". Administrador com outros veículos societários é vetor a apurar "
                "(interposição/dispersão de contratos, sucessão de empresa inapta).")
    return linhas


# ───────────────────────── raciocínio LLM (gemini/cerebras) sobre o pacote ─────────────────────────

_SYS_FACHADA = (
    "Voce e auditor de controle externo (TCE-RJ) avaliando se um fornecedor do Estado e EMPRESA DE FACHADA / "
    "interposicao de pessoas (laranja). Receba os SINAIS DETERMINISTICOS ja apurados (pagamento fora de "
    "contrato via TAC/indenizacao; realidade da sede; situacao cadastral; rede de socios/veiculos). Pese-os em "
    "conjunto e de um veredito HONESTO. Regras: indicio NUNCA e acusacao; INDISPONIVEL nao conta como prova nem "
    "como 'limpo'; nao invente fato fora dos sinais; cite a BASE LEGAL. Responda SOMENTE JSON: "
    '{"veredito":"FACHADA_PROVAVEL|INDICIOS|INSUFICIENTE","confianca":"ALTA|MEDIA|BAIXA",'
    '"fundamentacao":"3 a 6 frases conectando os sinais e o mecanismo","base_legal":"artigos"}.'
)


def _resumo_pacote_p_llm(pac: dict) -> str:
    """Serializa o pacote em texto curto p/ o prompt (só o que importa; sem dump cru)."""
    L = []
    tac = pac.get("tac") or {}
    if tac.get("pct") is not None and tac.get("pct"):
        L.append(f"- TAC/indenizacao: {tac.get('pct')}% de {_moeda(tac.get('total', 0))} pagos FORA de "
                 f"contrato regular ({_moeda(tac.get('total_tac', 0))}); severidade {tac.get('grau', '')}.")
        for u in (tac.get("ugs") or [])[:2]:
            L.append(f"  - UG pagadora {u.get('ug_nome') or u.get('ug_codigo')}: {u.get('pct')}% sistemico.")
    else:
        L.append(f"- TAC: {(tac.get('cobertura') or 'sem TAC relevante')}.")
    sede = pac.get("sede") or {}
    if sede.get("cobertura", "").startswith("verificado"):
        L.append(f"- Sede ({sede.get('status')}/{sede.get('nivel')}): "
                 f"{'SEM negocio no Google; ' if sede.get('sem_negocio_google') else ''}"
                 f"{'endereco residencial; ' if sede.get('residencial') else ''}"
                 f"{('imagem ' + str(sede.get('visual_classe')) + '; ') if sede.get('visual_suspeito') else ''}"
                 f"{(sede.get('evidencia') or '')[:160]}")
    else:
        L.append(f"- Sede: {sede.get('cobertura', 'INDISPONIVEL')}.")
    cad = pac.get("cadastro") or {}
    if cad.get("situacao"):
        L.append(f"- Situacao cadastral: {cad.get('situacao')}"
                 f"{' (' + cad['motivo'] + ')' if cad.get('motivo') else ''}"
                 f"{' — IRREGULAR' if cad.get('irregular') else ''}; aberta {cad.get('abertura', '?')}.")
    else:
        L.append(f"- Cadastro: {cad.get('cobertura', 'INDISPONIVEL')}.")
    rede = pac.get("rede") or {}
    adms = rede.get("administradores") or []
    if adms:
        L.append("- Comando (QSA real): " + "; ".join(
            f"{a['nome']} ({a.get('qualificacao', '')})" for a in adms[:4]) + ".")
    for v in (rede.get("outros_veiculos") or [])[:3]:
        nomes = ", ".join((o.get("razao") or o.get("cnpj_basico"))
                          + ("[forn. Estado]" if o.get("fornecedor_nosso") else "[externo]")
                          for o in (v.get("veiculos") or [])[:4])
        L.append(f"- Administrador {v['pessoa']} tem outros veiculos: {nomes}.")
    if not adms and not (rede.get("outros_veiculos")):
        L.append(f"- Rede: {rede.get('cobertura', 'INDISPONIVEL')}.")
    return "\n".join(L)


def veredito_llm(pac: dict, *, gerar=None, timeout: float = 45.0) -> dict:
    """Raciocínio gemini/cerebras sobre o pacote → veredito fachada/laranja. Async-safe via gerar_sync.

    Bounded(timeout) + degrada honesto: LLM caído/sem JSON → {disponivel:False, motivo:…}. `gerar` injetável p/ teste.
    """
    import json
    resumo = _resumo_pacote_p_llm(pac)
    prompt = ("Sinais deterministicos ja apurados sobre o fornecedor CNPJ "
              f"{pac.get('cnpj', '')} (recebeu {_moeda(pac.get('total_pago', 0))} do Estado):\n\n"
              + resumo + "\n\nDe o veredito conforme as regras (SOMENTE JSON).")
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync
            gerar = lambda p, s="": gerar_sync(p, s, timeout=timeout)  # noqa: E731
        except Exception:  # noqa: BLE001
            return {"disponivel": False, "motivo": "LLM indisponível (import)"}
    try:
        bruto = gerar(prompt, _SYS_FACHADA)
    except Exception as e:  # noqa: BLE001
        return {"disponivel": False, "motivo": f"LLM indisponível ({str(e)[:50]})"}
    t = (bruto or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(t)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", t, re.DOTALL)
        try:
            d = json.loads(m.group(0)) if m else None
        except Exception:  # noqa: BLE001
            d = None
    if not isinstance(d, dict):
        return {"disponivel": False, "motivo": "LLM respondeu sem JSON válido"}
    return {"disponivel": True, "veredito": str(d.get("veredito", ""))[:40],
            "confianca": str(d.get("confianca", ""))[:20],
            "fundamentacao": str(d.get("fundamentacao", "")).strip(),
            "base_legal": str(d.get("base_legal", "")).strip()}


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Pacote de sinais de fachada/laranja (1-4) p/ um CNPJ")
    ap.add_argument("cnpj")
    ap.add_argument("--total", type=float, default=0.0)
    a = ap.parse_args()
    print(json.dumps(pacote_sinais(a.cnpj, total_pago=a.total), ensure_ascii=False, indent=2, default=str))
