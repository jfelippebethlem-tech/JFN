# -*- coding: utf-8 -*-
"""Rotas `/api/intel/*` de pessoas, sócios e endereços (família, nepotismo, porta giratória, sócio oculto,
fênix, fantasmas, ninho de sala, hub físico) + `/api/laranjas` e a revisão humana de fachada (`/api/fachada/*`).

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rotas.investigacao import RAIZ, _cache_calc, _cache_get, _cache_put, _ro

router = APIRouter()


@router.get("/api/fachada/revisar")
def api_fachada_revisar(limite: int = 50):
    """Lista fachadas FLAGRADAS ainda sem veredito humano, p/ o validador do painel (revisão 1-a-1).
    Maior valor primeiro. Inclui motivo do flag, endereço e coordenada (link Street View no front)."""
    try:
        con = _ro(linhas=True)
        vetados = {r[0] for r in con.execute("SELECT cnpj FROM fachada_veredito WHERE status IN ('real','pular','fachada','indicio')")}
        rows = con.execute(
            "SELECT cnpj, razao, endereco, municipio, uf, total_recebido, nivel, evidencia, geo_lat, geo_lon, "
            "places_status, visual_classe FROM verificacao_sede "
            "WHERE nivel IN ('SEM_GOOGLE','FECHADO_GOOGLE','REVISAR_FACHADA') "
            "ORDER BY total_recebido DESC LIMIT ?", (max(1, min(int(limite), 500)),)).fetchall()
        con.close()
        out = [dict(r) for r in rows if r["cnpj"] not in vetados]
        return JSONResponse(content={"ok": True, "total": len(out), "fachadas": out})
    except Exception as e:
        return JSONResponse(content={"ok": False, "erro": str(e)})


@router.post("/api/fachada/veredito")
def api_fachada_veredito(payload: Optional[dict] = None):
    """Salva o veredito HUMANO do validador. Body: {cnpj, veredito: suspeito|ok|mais_info, nota?}.
    suspeito→fachada (mantém INDICIO); ok→real (volta AFASTADO); mais_info→pular (fica pendente)."""
    import datetime as _dt
    p = payload or {}
    cnpj = str(p.get("cnpj") or "").strip()
    ver = str(p.get("veredito") or "").strip().lower()
    nota = str(p.get("nota") or "")[:480]
    mapa = {"suspeito": ("fachada", "INDICIO"), "ok": ("real", "AFASTADO"), "mais_info": ("pular", None)}
    if not cnpj or ver not in mapa:
        return JSONResponse(content={"ok": False, "erro": "cnpj e veredito (suspeito|ok|mais_info) obrigatórios"})
    status_vd, novo_status = mapa[ver]
    try:
        con = sqlite3.connect(RAIZ / "data" / "compliance.db", timeout=30); con.execute("PRAGMA busy_timeout=30000")
        row = con.execute("SELECT razao, endereco, total_recebido FROM verificacao_sede WHERE cnpj=?", (cnpj,)).fetchone()
        razao, endereco, tr = (row or ("", "", 0))
        con.execute(
            "INSERT INTO fachada_veredito (cnpj, razao, endereco, total_recebido, status, veredito_raw, veredito_em) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(cnpj) DO UPDATE SET status=excluded.status, "
            "veredito_raw=excluded.veredito_raw, veredito_em=excluded.veredito_em",
            (cnpj, razao, endereco, tr, status_vd, nota, _dt.datetime.now().isoformat(timespec="seconds")))
        if novo_status:
            con.execute("UPDATE verificacao_sede SET status=? WHERE cnpj=?", (novo_status, cnpj))
        con.commit(); con.close()
        return JSONResponse(content={"ok": True, "cnpj": cnpj, "veredito": status_vd})
    except Exception as e:
        return JSONResponse(content={"ok": False, "erro": str(e)})


@router.get("/api/laranjas")
def api_laranjas(limite: int = 100):
    """Sócios de fornecedores do Estado que RECEBEM benefício social de subsistência (bolsa família etc.)
    — indício clássico de LARANJA/interposição (art. 337-F CP): quem figura como dono de empresa que
    recebe do Estado não deveria depender de auxílio. Só os confirmados (recebe_beneficio=1)."""
    try:
        con = _ro(linhas=True)
        rows = con.execute(
            "SELECT socio_nome_norm, cpf_resolvido, beneficios_json, motivo, confianca "
            "FROM socio_beneficio WHERE recebe_beneficio=1 ORDER BY confianca DESC LIMIT ?",
            (max(10, min(int(limite or 100), 500)),)).fetchall()
        con.close()
        itens = []
        for r in rows:
            try:
                bens = json.loads(r["beneficios_json"] or "[]")
            except (ValueError, TypeError):
                bens = []
            cpf = re.sub(r"\D", "", r["cpf_resolvido"] or "")
            # fail-CLOSED: valor não-canônico (≠11 dígitos) vira "***" — nunca ecoar o bruto
            cpf_masc = f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else ("***" if cpf else "")
            itens.append({"socio": r["socio_nome_norm"], "cpf": cpf_masc,  # LGPD: nunca CPF completo
                          "beneficios": bens if isinstance(bens, list) else [str(bens)],
                          "motivo": r["motivo"], "confianca": r["confianca"]})
        out = {"ok": True, "total": len(itens), "itens": itens,
               "aviso": "Indício de laranja/interposição (art. 337-F CP) a verificar — receber benefício "
                        "não é ilícito; o sinal é ser SÓCIO de empresa que recebe do Estado E depender de auxílio."}
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/grafo_familias")
def api_intel_grafo_familias():
    """Grafo D3 (nodes/links) das famílias que ocupam cargo de confiança E fornecem ao Estado —
    consumido pelo graph.html em /graph?fonte=familias."""
    try:
        from compliance_agent.cruzamentos_intel import grafo_familias
        d = _cache_calc("intel:grafofam", 600, lambda: grafo_familias(db_path=str(RAIZ / "data" / "compliance.db")))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"nodes": [], "links": [], "erro": str(exc)}, status_code=500)


@router.get("/api/intel/comunidades_grafo")
def api_intel_comunidades_grafo():
    """Grafo D3 (nodes/links) das comunidades Louvain — consumido pelo graph.html em
    /graph?fonte=comunidades. Sai do cache do intel (construir o grafo não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("comunidades") or {}
        return JSONResponse(d.get("d3") or {"nodes": [], "links": []})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"nodes": [], "links": [], "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fenix")
def api_intel_fenix(limite: int = 120):
    """Empresa fênix: BAIXADA/INAPTA que recebeu, ou aberta ≤12m antes do 1º pagamento."""
    try:
        from compliance_agent.cruzamentos_intel import empresa_fenix
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:fenix:{lim}", 3600, lambda: empresa_fenix(limite=lim))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/fenix", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_sancionada")
def api_intel_socio_sancionada():
    """Contratada cujo sócio é sócio de empresa sancionada (vedação que alcança o RJ), com OB SIAFE paga na
    janela em que as duas sociedades e a sanção coexistem. Força = critérios do TCU (Ac. 1831/2014-P)."""
    try:
        from compliance_agent.socio_de_sancionada import socio_de_sancionada
        return JSONResponse(_cache_calc("intel:socio_sancionada", 3600, socio_de_sancionada))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/porta_giratoria")
def api_intel_porta_giratoria(limite: int = 120):
    """Porta giratória: ex-servidor (inativo/exonerado) que virou sócio de fornecedor do Estado."""
    try:
        from compliance_agent.cruzamentos_intel import porta_giratoria
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:porta:{lim}", 3600, lambda: porta_giratoria(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/nepotismo_cruzado")
def api_intel_nepotismo_cruzado(limite: int = 60):
    """Nepotismo cruzado: colocação recíproca de parentes entre dois órgãos (dribla a SV13)."""
    try:
        from compliance_agent.cruzamentos_intel import nepotismo_cruzado
        lim = max(1, min(int(limite or 60), 200))
        d = _cache_calc(f"intel:nepcruz:{lim}", 3600, lambda: nepotismo_cruzado(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/nepotismo")
def api_intel_nepotismo(limite: int = 120):
    """Nepotismo (SV13 STF): ≥2 pessoas de nomes distintos, mesmo sobrenome de família raro, ambas
    em cargo de confiança no mesmo órgão. Fragmento de CPF corrobora pessoas distintas."""
    try:
        from compliance_agent.cruzamentos_intel import nepotismo
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:nep:{lim}", 3600, lambda: nepotismo(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_oculto")
def api_intel_socio_oculto(limite: int = 120):
    """Pessoa/holding sócia de ≥3 empresas fornecedoras do Estado (empresário oculto / grupo familiar)."""
    try:
        from compliance_agent.cruzamentos_intel import socio_oculto
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:ocult:{lim}", 600, lambda: socio_oculto(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/socio_servidor")
def api_intel_socio_servidor(limite: int = 1000):
    """Sócio na folha: servidor público que é sócio-dono de fornecedor pago pelo Estado — uma linha por
    PESSOA, identidade desambiguada em camadas (`identidade_pessoa`: CPF na janela de cada folha,
    prevalência do nome, faixa etária). Lista principal = VERIFICADO + PROVÁVEL; indeterminados e
    homônimos vêm à parte. Chave `socserv2`: o formato mudou em 19/11/2026 (cache antigo não serve)."""
    try:
        from compliance_agent.cruzamentos_intel import socio_servidor
        lim = max(1, min(int(limite or 1000), 2000))
        d = _cache_calc(f"intel:socserv2:{lim}", 6 * 3600, lambda: socio_servidor(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fantasmas")
def api_intel_fantasmas(limite: int = 50):
    """Ranking de risco de empresa-fantasma (8 sinais determinísticos do /fantasma) no conjunto-alvo
    (capturas, rodízios, perdedoras contumazes, sancionadas, top favorecidos)."""
    try:
        from compliance_agent.cruzamentos_intel import ranking_fantasmas
        lim = max(1, min(int(limite or 50), 200))
        d = _cache_calc(f"intel:fant:{lim}", 3600, lambda: ranking_fantasmas(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/ninho_sala")
def api_intel_ninho_sala(limite: int = 120):
    """Ninho pela SALA (endereço + complemento) e por CONJUNTO de fatores.

    Dividir o PRÉDIO não diz nada — 'Rua da Assembleia 10' tem 318 CNPJs e é edifício
    comercial. Dividir a SALA, com dois ou mais recebendo dinheiro público, é a assinatura
    de interposição. O grau vem do acúmulo de fatores, nunca de um sinal só.
    """
    try:
        # cache primeiro (o cálculo a frio leva ~16 s e o painel corta em 30 s); sem cache,
        # calcula ao vivo e diz que veio ao vivo — nunca fica mudo.
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        from compliance_agent.proveniencia_manchetes import anexar
        c = ler_cache_intel("ninho_sala")
        if c and c.get("ok"):
            c["do_cache"] = True
            c["grupos"] = (c.get("grupos") or [])[:limite]
            return JSONResponse(anexar("/api/intel/ninho_sala", c))
        from compliance_agent.ninho_sala import ninhos_por_sala
        d = ninhos_por_sala(limite=limite)
        d["do_cache"] = False
        return JSONResponse(anexar("/api/intel/ninho_sala", d))
    except Exception as exc:  # noqa: BLE001 — degrada honesto, nunca lista vazia
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/hub_compartilhado")
def api_intel_hub_compartilhado(chave: str = "endereco", min: int = 5):
    """Hub compartilhado: 1 âncora física (endereço/telefone/e-mail) usada por N CNPJs — assinatura
    de 'ninho de fantasmas'. Guarda anti-FP rebaixa massa legítima (contador, galeria, coworking)."""
    from datetime import datetime as _dt
    try:
        from compliance_agent.cruzamentos_intel import hub_compartilhado, ler_cache_intel
        ch = chave if chave in ("endereco", "telefone", "email") else "endereco"
        mn = int(min or 5)
        mn = 2 if mn < 2 else (100 if mn > 100 else mn)
        d = _cache_get(f"intel:hub:{ch}:{mn}", 600)
        # O cálculo ao vivo cruza o dump da Receita (6,1 mi de estabelecimentos) com as OB:
        # medido, NÃO responde em 90 s enquanto o sweep escreve no compliance.db — e era por
        # isso que o card "ninhos de fachada" ficava eternamente em "—". O cache em disco
        # gerado por `gerar_cache_intel` já existe e usa EXATAMENTE estes parâmetros
        # (endereco/5); a rota só não o lia. Fora desses parâmetros não há cache: aí sim
        # calcula ao vivo, mas isso é caminho de exceção, não o do painel.
        if d is None and ch == "endereco" and mn == 5:
            if (c := ler_cache_intel("hub_compartilhado")) and c.get("grupos"):
                c["do_cache"] = True
                d = _cache_put(f"intel:hub:{ch}:{mn}", c)
        if d is None:
            d = _cache_put(f"intel:hub:{ch}:{mn}", hub_compartilhado(chave=ch, min_cnpjs=mn))
        return JSONResponse({"ok": d.get("ok", True), "grupos": d.get("grupos", []),
                             "erro": d.get("erro"), "explicacao": d.get("explicacao"),
                             "ressalva": d.get("ressalva"),
                             # honestidade de frescor: dado de cache não se apresenta como de agora
                             "do_cache": bool(d.get("do_cache")),
                             "gerado_em": d.get("gerado_em") or _dt.now().strftime("%Y-%m-%d %H:%M")})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
