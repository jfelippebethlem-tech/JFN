# -*- coding: utf-8 -*-
"""Render Markdown do relatório (11 seções) + sede/fachada/benefícios/rodízio — extraído de inteligencia.py (split 2026-07-06).
Comportamento idêntico; rede de segurança: tools/inteligencia_snapshot_check.py + tests/test_inteligencia_snapshot.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from collections import OrderedDict, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from compliance_agent.reporting.intel_base import _DATA, _DB, _REPORTS, fmt_cnpj, moeda, so_digitos, cabecalho_frescor
from compliance_agent.reporting.intel_analise import (
    _FEAT_ANOM, _NOTA_CARDINALIDADE, _anomalias_fornecedor, _beneficios_socios, _fatores_risco,
    _frase_cardinalidade, _red_flags, _resumo_executivo, _termos_significativos,
    parecer_fornecedor, troca_controle_societaria,
)
from compliance_agent.reporting.intel_base import _num_brl
from compliance_agent import fachada_remotes as _fr

_FB2_TIMEOUT = float(os.environ.get("JFN_FACHADA_B2_TIMEOUT", "20"))

_SEDE_ONDEMAND_DIAS = int(os.environ.get("JFN_RELATORIO_SEDE_ONDEMAND_DIAS", "30"))


def _render_cruzamento(ctx: dict) -> str:
    """Seção 1-B: cruzamento sócio × OB (SIAFE) × processo SEI × endereço."""
    cz = ctx.get("cruzamento") or {}
    L: list[str] = []
    add = L.append
    add("## 1-B. REDE SOCIETÁRIA — CRUZAMENTO SÓCIO × OB × SEI × ENDEREÇO")
    add("")
    add("> Cruza o **quadro societário** (QSA/Receita) com **as OBs do SIAFE**, os **processos SEI** de origem dos "
        "pagamentos e o **endereço (sede)** das empresas. Empresas que compartilham sócio — e sobretudo as que "
        "compartilham a mesma sede — recebendo recursos do mesmo Estado são indício de grupo econômico/empresas-"
        "irmãs a verificar (art. 337-F CP; art. 11 Lei 8.429/92). **Indício, nunca acusação.**")
    add("")

    if cz.get("_erro"):
        add(f"> ⚠️ Cruzamento indisponível nesta execução ({cz['_erro']}). As demais seções não dependem dele.")
        add("")
        return "\n".join(L)

    osi = cz.get("obs_sei") or {}
    add(f"**Pegada do alvo no SIAFE:** {osi.get('n_obs', 0)} OBs · R$ {moeda(osi.get('total_pago', 0))} pagos · "
        f"{osi.get('n_sei', 0)} processo(s) SEI vinculado(s).")
    if cz.get("cidade"):
        add(f"**Cidade-sede do alvo:** {cz['cidade']}.")
    add("")
    seis = osi.get("sei_processos") or []
    if seis:
        amostra = ", ".join(seis[:12]) + (f" (+{len(seis)-12})" if len(seis) > 12 else "")
        add(f"**Processos SEI do alvo (origem das OBs/contratos):** {amostra}")
        add("")

    # Fornecedores na MESMA sede (independe de sócio em comum) — red flag de fachada/laranja
    coend = cz.get("coendereco") or []
    if coend:
        n_pagos = sum(1 for c in coend if c.get("total_pago", 0) > 0)
        add(f"### 🔴 Fornecedores no MESMO endereço ({len(coend)}; {n_pagos} também recebem OBs)")
        add("")
        add("> Empresas com **sede idêntica** ao alvo — mesmo sem sócio declarado em comum. Compartilhar imóvel "
            "entre fornecedores do Estado é indício de empresa de fachada/laranja ou direcionamento "
            "(art. 337-F CP; art. 11 Lei 8.429/92). **Indício a verificar, não acusação.**")
        add("")
        add("| Empresa (CNPJ) | OBs | Pago (R$) | SEI |")
        add("|---|---:|---:|---:|")
        for c in coend[:25]:
            add(f"| {(c.get('razao') or '—')[:48]} ({fmt_cnpj(c['cnpj'])}) | {c.get('n_obs',0)} | "
                f"{moeda(c.get('total_pago',0))} | {c.get('n_sei',0)} |")
        add("")

    if not cz.get("tem_rede"):
        msg = cz.get("_nota") or "Sem rede societária ingerida para este CNPJ."
        if not cz.get("socios"):  # QSA ainda não ingerido → ofereça o comando
            msg += (" Para habilitar o cruzamento por sócio: "
                    "`python -m compliance_agent.rede_societaria --ingerir " + (cz.get("cnpj") or "") + "`.")
        add(f"> {msg}")
        add("")
        return "\n".join(L)

    socios = cz.get("socios") or []
    if socios:
        add(f"**Sócios do alvo (QSA):** {', '.join(socios[:15])}"
            + (f" (+{len(socios)-15})" if len(socios) > 15 else "") + ".")
        add("")

    rel = cz.get("relacionados") or []
    add(f"**Empresas com sócio em comum ({len(rel)}):** ordenadas por sede compartilhada e valor pago.")
    add("")
    add("| Empresa (CNPJ) | Sócio(s) em comum | Cidade-sede | OBs | Pago (R$) | SEI | Mesma sede? |")
    add("|---|---|---|---:|---:|---:|:---:|")
    for r in rel[:25]:
        razao = (r.get("razao") or "—")[:38]
        comuns = (r.get("socios_comuns") or "—")
        comuns = (comuns[:40] + "…") if len(comuns) > 40 else comuns
        cidade = r.get("cidade") or "—"
        if r.get("mesmo_endereco"):
            flag = "🔴 SIM"
        elif r.get("mesma_cidade"):
            flag = "🟡 cidade"
        else:
            flag = "—"
        add(f"| {razao} ({fmt_cnpj(r['cnpj'])}) | {comuns} | {cidade} | {r.get('n_obs',0)} | "
            f"{moeda(r.get('total_pago',0))} | {r.get('n_sei',0)} | {flag} |")
    add("")

    for ind in (cz.get("indicios") or []):
        add(f"> 🟡 **Indício:** {ind}")
        add("")
    _add_rede_fachada(add, ctx.get("cnpj") or cz.get("cnpj") or "")
    return "\n".join(L)


def _add_rede_fachada(add, cnpj: str) -> None:
    """Acrescenta o bloco de REDE (QSA REAL via dump Receita + outros veículos dos administradores —
    socios_reverso). Surfacia o quadro de comando real (Presidente/Diretor) e veículos externos do
    administrador (ex.: presidente IDESI → SIGNAL RIO). Degrada honesto (tabela ausente → nada)."""
    if not so_digitos(cnpj):
        return
    try:
        from compliance_agent.rede_fachada import render_rede_md, sinal_rede
        rede = sinal_rede(cnpj)
        linhas = render_rede_md(rede)
    except Exception:  # noqa: BLE001
        return
    if not linhas:
        return
    add("### Rede de comando e veículos do administrador (QSA real — dump Receita)")
    add("")
    add("> Quadro societário REAL da Receita (inclui Presidente/Diretor de associação) e os OUTROS veículos "
        "societários dos administradores no Brasil. Administrador que controla empresa inapta e mantém outros "
        "CNPJs é vetor a apurar (interposição/sucessão). **Indício, nunca acusação.**")
    add("")
    for ln in linhas:
        add(ln)
    add("")


def _sede_velho(verificado_em: Optional[str]) -> bool:
    """True se a verificação de sede é mais antiga que _SEDE_ONDEMAND_DIAS (re-verificar on-demand).
    Sem data legível → trata como velho (re-verifica) só se o on-demand está ligado."""
    if _SEDE_ONDEMAND_DIAS <= 0:
        return False
    if not verificado_em:
        return True
    try:
        from datetime import datetime
        dtv = datetime.fromisoformat(str(verificado_em)[:19])
        return (datetime.now() - dtv).days > _SEDE_ONDEMAND_DIAS
    except Exception:  # noqa: BLE001
        return True


def _sede_total_pago(cnpj: str) -> float:
    """Total pago (OBs) a TODA a raiz do fornecedor — usado p/ calibrar o veredito de sede (Places só nos
    relevantes; INDÍCIO ALTO exige magnitude). Best-effort: 0.0 se a base não responde."""
    if not _DB.exists():
        return 0.0
    raiz = so_digitos(cnpj)[:8]
    try:
        con = sqlite3.connect(str(_DB))
        try:
            r = con.execute("SELECT SUM(valor) FROM ordens_bancarias WHERE favorecido_cpf LIKE ?",
                            (f"{raiz}%",)).fetchone()
            return float((r[0] if r else 0) or 0.0)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return 0.0


def _verificar_sede_ondemand(cnpj: str) -> Optional[tuple]:
    """Verifica a sede do fornecedor NA HORA via Google (Geocoding+AddrVal+Places) e CACHEIA em
    `verificacao_sede`, p/ todo relatório ter veredito fresco mesmo que o sweep ainda não tenha varrido o CNPJ.

    BOUNDED e seguro (degrada honesto p/ o caminho atual — OSM/INDISPONÍVEL — em vez de crashar/atrasar):
      • sem endereço em `endereco_fornecedor` → None;
      • cota Google esgotada (geocoding/addressvalidation) → None (o sweep cuida quando a cota voltar);
      • qualquer erro/timeout (timeouts já embutidos no sede_google) → None.
    Quando consegue, grava com `INSERT OR REPLACE` (mesmas colunas/lógica do sweep `tools.sweep_sede_google`,
    reusadas via `grava_verificacao`, sem duplicar a thesaurus de colunas) usando busy_timeout=30000
    (concorrência com o sweep que também escreve), e devolve (status, nivel, evidencia)."""
    if _SEDE_ONDEMAND_DIAS <= 0:
        return None
    cnpj = so_digitos(cnpj or "")
    if not cnpj or not _DB.exists():
        return None
    try:
        from compliance_agent import sede_google as sg
    except Exception:  # noqa: BLE001
        return None
    # endereço do fornecedor (mesma fonte que o sweep usa: endereco_fornecedor por cnpj)
    end = None
    try:
        con = sqlite3.connect(str(_DB))
        con.row_factory = sqlite3.Row
        try:
            end = con.execute(
                "SELECT cnpj,razao,endereco,municipio,uf,cep FROM endereco_fornecedor WHERE cnpj=?",
                (cnpj,)).fetchone()
        except sqlite3.OperationalError:
            end = None
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None
    if not end or not (end["endereco"] or "").strip():
        return None  # sem endereço → degrada p/ o caminho atual (OSM/fallback)
    # cota: precisa de Geocoding + Address Validation; se estourou, não verifica agora (sweep retoma depois)
    try:
        if sg.cota_restante("geocoding") <= 0 or sg.cota_restante("addressvalidation") <= 0:
            return None
    except Exception:  # noqa: BLE001
        return None
    total_pago = _sede_total_pago(cnpj)
    try:
        # com_places=True só faz uma chamada Places (já quota-guarded internamente; no-op se sem cota)
        sinais = sg.coletar_sinais(end["razao"], end["endereco"], end["municipio"], end["uf"], end["cep"],
                                   com_validacao=True, com_places=True)
        vd = sg.verdict_de_sinais(sinais, total_pago)
    except Exception:  # noqa: BLE001
        return None  # qualquer falha de coleta → degrada honesto (nunca derruba o relatório)
    try:
        from tools.sweep_sede_google import grava_verificacao as _grava
        _grava(str(_DB), dict(end), total_pago, sinais, vd)
    except Exception:  # noqa: BLE001
        # falha ao cachear NÃO invalida o veredito — usamos o resultado fresco mesmo sem persistir
        pass
    return (vd.get("status"), vd.get("nivel"), vd.get("evidencia"))


def _realidade_sede_texto(cnpj: str) -> str:
    """Veredito (texto puro) de realidade da sede — responde 'a empresa é real?'. PREFERE a verificação
    autoritativa do Google (`verificacao_sede`: Geocoding+Address Validation+Places); se o CNPJ NÃO está lá
    (ou está VELHO, > _SEDE_ONDEMAND_DIAS dias) verifica NA HORA (quota-guarded) e cacheia, p/ relatório de
    fornecedor GRANDE não cair no fallback só porque o sweep ainda não o varreu. Fallback final p/ o OSM antigo
    (`endereco_verificacao`, deprecado). Honesto: AFASTADO = sede real; INDÍCIO = apurar; INDISPONÍVEL/ausente
    = sem conclusão (≠ inexistência)."""
    cnpj = so_digitos(cnpj or "")
    if not cnpj or not _DB.exists():
        return ""
    vs = row = None
    vs_velho = False
    try:
        con = sqlite3.connect(str(_DB))
        try:
            try:
                vs = con.execute("SELECT status,nivel,evidencia,verificado_em FROM verificacao_sede WHERE cnpj=?",
                                 (cnpj,)).fetchone()
            except sqlite3.OperationalError:
                vs = None
            try:
                row = con.execute("SELECT status,nivel,evidencia FROM endereco_verificacao WHERE cnpj=?",
                                  (cnpj,)).fetchone()
            except sqlite3.OperationalError:
                row = None
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return ""
    if vs and _SEDE_ONDEMAND_DIAS > 0:
        vs_velho = _sede_velho(vs[3] if len(vs) > 3 else None)
    # ON-DEMAND: ausente OU velho → verifica na hora (quota-guarded; degrada p/ o que houver se não der)
    if (not vs or vs_velho):
        fresco = _verificar_sede_ondemand(cnpj)
        if fresco is not None:
            vs = fresco
    fonte, google = (vs, True) if vs else (row, False)
    if not fonte:
        return "ainda não verificada (sweep de endereços em andamento) — INDISPONÍVEL não é prova de inexistência."
    st, nivel, evid = (fonte[0] or "").upper(), fonte[1] or "—", (fonte[2] or "")[:200]
    selo = " [Google: Geocoding+Address Validation+Places]" if google else ""
    if st == "AFASTADO":
        return f"endereço real — afastada a hipótese de fachada{selo}. {evid}".rstrip()
    if st == "INDICIO":
        return (f"🟡 indício ({nivel}) sobre a realidade da sede — apurar{selo}. {evid}").rstrip()
    return ("sem conclusão" + (selo or " pela base cartográfica aberta (cobertura incompleta)") +
            " — INDISPONÍVEL ≠ inexistência (Street View/in loco conclui).")


def _realidade_sede(cnpj: str) -> str:
    """Versão Markdown (bullet) do veredito de realidade da sede."""
    t = _realidade_sede_texto(cnpj)
    return f"- **Realidade da sede:** {t}" if t else ""


def _sede_status_cacheado(cnpj: str) -> str:
    """Status JÁ gravado em `verificacao_sede` (AFASTADO/INDICIO/INDISPONIVEL/'') — leitura local barata,
    SEM acionar Google on-demand (a §4.1 manda nunca disparar API paga no caminho de score). Usado p/
    o score cruzar 'sede = indício de fachada' com 'doador eleitoral' (convergência, backlog #16). Honesto:
    '' = sem linha = INDISPONÍVEL ≠ inexistência."""
    cnpj = so_digitos(cnpj or "")
    if not cnpj or not _DB.exists():
        return ""
    try:
        con = sqlite3.connect(str(_DB))
        try:
            vs = con.execute("SELECT status FROM verificacao_sede WHERE cnpj=?", (cnpj,)).fetchone()
        except sqlite3.OperationalError:
            return ""
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return ""
    return ((vs[0] or "").upper() if vs else "")


_RCLONE_BIN = _fr.rclone_bin()


def _foto_fachada_b2(cnpj: str) -> Optional[dict]:
    """Busca, p/ um CNPJ FLAGUEADO com `visual_img_b2`, a foto da fachada guardada na nuvem e devolve
    {bytes, classe, fonte, objeto}. Lê do `remote:bucket/objeto` EXATO gravado em `visual_img_b2` (R2 ou
    B2 — cada foto vive em UM bucket só). Bounded e degrada HONESTO: se a coluna estiver vazia/legada
    (sem remote:), ou o rclone falhar, devolve None (o relatório nota INDISPONÍVEL, não quebra). A imagem
    NÃO é mantida na VM — é lida via `rclone cat` p/ memória e descartada após embutir."""
    cnpj = so_digitos(cnpj or "")
    if not cnpj or not _DB.exists() or not Path(_RCLONE_BIN).exists():
        return None
    loc = classe = fonte = None
    try:
        con = sqlite3.connect(str(_DB))
        try:
            row = con.execute(
                "SELECT visual_img_b2, visual_classe, visual_fonte FROM verificacao_sede WHERE cnpj=?",
                (cnpj,)).fetchone()
        finally:
            con.close()
        if not row or not (row[0] or "").strip():
            return None
        loc, classe, fonte = row[0].strip(), (row[1] or ""), (row[2] or "")
    except Exception:  # noqa: BLE001
        return None
    parsed = _fr.parse_localizacao(loc)  # ('remote','bucket','objeto') ou None p/ legado 'fachadas/x.jpg'
    if not parsed:
        return None  # localização incompleta/legada → degrada honesto (INDISPONÍVEL, não inventa)
    remote, bucket, objeto = parsed
    destino = f"{remote}:{bucket}/{objeto}"
    import subprocess  # local: só quando há foto a buscar
    try:
        r = subprocess.run([_RCLONE_BIN, "cat", destino], capture_output=True,
                           timeout=_FB2_TIMEOUT)
        if r.returncode != 0 or not r.stdout:
            return None
        return {"bytes": r.stdout, "classe": classe, "fonte": fonte, "objeto": objeto}
    except Exception:  # noqa: BLE001
        return None


def _fachada_b2_html(cnpj: str) -> str:
    """HTML (figure com a foto em data-URI) da fachada guardada no B2, p/ embutir no relatório HTML→PDF.
    Legenda HONESTA: classe visual + fonte da imagem de rua. Se não houver foto/falhar → '' (sem ruído;
    o veredito textual de 'Realidade da sede' já cobre o caso)."""
    import base64
    import html as _h
    d = _foto_fachada_b2(cnpj)
    if not d:
        return ""
    img = d["bytes"]
    mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
    b64 = base64.b64encode(img).decode("ascii")
    classe = (d["classe"] or "").replace("_", " ") or "—"
    fonte = d["fonte"] or "imagem de rua"
    legenda = _h.escape(f"Classe visual: {classe} · imagem de rua, fonte {fonte}. "
                        "Indício a confirmar in loco — não é prova de fachada.")
    return (f'<figure style="margin:8px 0;text-align:center">'
            f'<img src="data:{mime};base64,{b64}" '
            f'style="max-width:48%;max-height:320px;border:1px solid #ccc;border-radius:4px"/>'
            f'<figcaption class="nota" style="margin-top:4px">{legenda}</figcaption></figure>')




def _render_beneficios_socios(ctx: dict) -> str:
    """Seção 1-C — benefícios de subsistência dos sócios/administradores deste fornecedor (indício de laranja).
    Cruzamento INTELIGENTE: dado completo + leitura raciocinada + conclusão honesta (indício, nunca acusação)."""
    from compliance_agent.reporting import beneficios_view as bv
    b = ctx.get("beneficios_socios")
    if b is None:
        b = _beneficios_socios(ctx.get("cnpj", ""))
    L: list[str] = []
    add = L.append
    add("## 1-C. BENEFÍCIOS SOCIAIS DOS SÓCIOS/ADMINISTRADORES (INDÍCIO DE LARANJA)")
    add("")
    add("> Cruza o **CPF dos sócios/administradores** do QSA com os **benefícios de subsistência** por CPF "
        "(Bolsa Família, BPC, Auxílio Emergencial, PETI, Garantia-Safra, Seguro-Defeso — Portal da "
        "Transparência/CGU). Ser **dono/gestor** de empresa que recebe recursos públicos **e** receber benefício "
        "de subsistência é **indício clássico de testa-de-ferro (laranja)** — interposição de pessoas (art. 337-F "
        "CP; art. 11 Lei 8.429/92). CPF mascarado (LGPD); resolvido por fontes oficiais (favorecidos PF + TSE). "
        "**INDISPONÍVEL ≠ ausência de benefício.**")
    add("")
    if not b or not b.get("total_qsa"):
        add("_Sem sócios/administradores com CPF mascarado no QSA deste fornecedor (ou QSA público não ingerido) "
            "— **INDISPONÍVEL** (não equivale a ausência de benefício)._")
        return "\n".join(L)
    add(bv.leitura(b, escopo="deste fornecedor"))
    add("")
    add(f"- Sócios/administradores no QSA (mascarados): **{b['total_qsa']}** · já varridos: **{b['n_varridos']}** · "
        f"CPF resolvido: **{b['n_resolvidos']}** · verificados: **{b['n_verificados']}** ({b['cobertura']}%) · "
        f"**INDISPONÍVEL:** {b['n_indisponivel']}")
    itens = b.get("itens") or []
    if itens:
        add("")
        add("| Sócio/Administrador | Papel | Benefício | Fonte do CPF |")
        add("|---|---|---|---|")
        _f = {"favorecidos_pf": "favorecidos PF", "tse_doadores": "doadores TSE"}
        for it in itens:
            tipos = ", ".join(it.get("tipos") or []) or "(tipo não detalhado)"
            add(f"| {it.get('nome', '')} | {it.get('papel', '')} | {tipos} | "
                f"{_f.get(it.get('fonte', ''), it.get('fonte', '') or '—')} |")
        add("")
        add("> 🟡 **Indício a confirmar:** sócio/gestor que recebe benefício de subsistência sugere **interposição "
            "de pessoas (laranja)** — confirmar no contrato social, na procuração e no processo SEI. **Indício, não "
            "prova.** CPF de uso interno (LGPD).")
    add("")
    return "\n".join(L)


def _render_doacoes_tse(ctx: dict) -> str:
    """Seção 1-D — doações eleitorais (TSE) × contratos: conflito doador↔contrato. Cruzamento inteligente
    (paridade com o PDF): dado completo (cadeia doador→fornecedor→candidato→UG→SEI) + leitura + conclusão."""
    rede = ctx.get("conflito_rede")
    if rede is None:
        try:
            from compliance_agent.lex_conflito import conflito
            rede = conflito(cnpj=so_digitos(ctx.get("cnpj", "")), limite=30).get("rede", [])
        except Exception:  # noqa: BLE001
            rede = []
    if isinstance(rede, dict):
        rede = rede.get("rede", [])
    L: list[str] = []
    add = L.append
    add("## 1-D. DOAÇÕES ELEITORAIS — CONFLITO DOADOR ↔ CONTRATO (TSE)")
    add("")
    add("> Cruza as **doações eleitorais** (TSE) da empresa **e de seus sócios** com os contratos/pagamentos do "
        "Estado, fechando a cadeia **doador → fornecedor → candidato → UG pagadora → processo SEI**. Doar a "
        "campanha e contratar com o poder público é **indício de relação política / conflito de interesse** a "
        "verificar (Lei 9.504/97; Lei 14.133 art. 14) — presunção de legitimidade, **nunca acusação**.")
    add("")
    if not rede:
        add("_Nenhuma doação eleitoral (TSE) localizada para a empresa ou seus sócios na base — **INDISPONÍVEL / "
            "sem registro** (não equivale a inexistência de doação fora do período/base ingerida)._")
        add("")
        return "\n".join(L)
    add(f"**{len(rede)}** vínculo(s) doação↔contrato localizado(s) — o doador pode ser a empresa OU um sócio (coluna *Via*):")
    add("")
    add("| Doador | Via | Candidato | Partido | Ano | Valor doado (R$) | Órgão (UG) pagador | Processos SEI |")
    add("|---|---|---|---|---:|---:|---|---|")
    for r in rede[:20]:
        ugs = r.get("ugs") or []
        ug_cell = ("; ".join(f"{u.get('nome')} (R$ {moeda(u.get('total'))})" for u in ugs[:2])
                   + (f" (+{len(ugs) - 2} UG)" if len(ugs) > 2 else "")) if ugs else "—"
        seis = r.get("seis") or []
        sei_cell = (", ".join(str(s) for s in seis[:5]) + (f" (+{len(seis) - 5})" if len(seis) > 5 else "")) if seis else "—"
        add(f"| {r.get('doador', '')} | {r.get('via', '')} | {r.get('candidato', '')} | {r.get('partido', '')} "
            f"| {r.get('ano', '')} | {moeda(r.get('valor_doacao'))} | {ug_cell} | {sei_cell} |")
    add("")
    add("> 🟡 **Indício a verificar:** doação eleitoral de fornecedor (ou de seu sócio) a candidato, combinada com "
        "recebimento de recursos públicos no Estado, é indício de **relação política / conflito de interesse** — "
        "confirmar a cadeia (doação→contrato→UG→SEI) e a regularidade do certame. **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _rodizio_fornecedor(cnpj: str, max_ugs: int = 3) -> dict:
    """A4 — o fornecedor é 'campeão' de algum anel de rodízio (bid rotation/cartel) nas UGs que mais o pagam?
    Bounded (top `max_ugs` por valor); reusa `rodizio_temporal.rodizio_orgao` (DuckDB). Degrada honesto."""
    cnpj = so_digitos(cnpj)
    out = {"ok": False, "ugs_avaliadas": 0, "aneis": []}
    if len(cnpj) != 14:
        return out
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            ugs = [str(r[0]) for r in con.execute(
                "SELECT ug_codigo FROM ordens_bancarias WHERE favorecido_cpf=? AND ug_codigo IS NOT NULL "
                "GROUP BY ug_codigo ORDER BY SUM(valor) DESC LIMIT ?", (cnpj, max_ugs)).fetchall()]
        finally:
            con.close()
        if not ugs:
            return out
        from compliance_agent import rodizio_temporal as rt
        for ug in ugs:
            try:
                r = rt.rodizio_orgao(ug)
            except Exception:  # noqa: BLE001
                continue
            out["ugs_avaliadas"] += 1
            if r.get("indicio"):
                camp = next((c for c in r.get("campeoes", []) if so_digitos(c.get("cnpj", "")) == cnpj), None)
                if camp:
                    out["aneis"].append({"ug": ug, "score": r.get("score"), "n_campeoes": r.get("n_campeoes"),
                                         "share_ring": r.get("share_ring"), "n_vitorias": camp.get("n_vitorias"),
                                         "anos": camp.get("anos", [])})
        out["ok"] = out["ugs_avaliadas"] > 0
        return out
    except Exception as exc:  # noqa: BLE001
        out["_nota"] = str(exc)[:160]
        return out


def _render_execucao(ctx: dict) -> str:
    """Seção 1-G — execução contratual (prova de entrega): cruza OB paga × perícia SEI (lex_execucao).
    Surfacing dos contratos pagos sem execução comprovada nos autos. Indício, não prova; INDISPONÍVEL ≠ irregular."""
    def _brl(v):
        return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    L: list[str] = []
    add = L.append
    add("## 1-G. EXECUÇÃO CONTRATUAL — PROVA DE ENTREGA (OB PAGA × PERÍCIA SEI)")
    add("")
    add("> Cruza os **processos pagos** (Ordem Bancária) deste fornecedor com a **perícia de execução** "
        "(lex_execucao): há prova de entrega/fiscalização nos autos? Pagar sem execução comprovada é *red flag* "
        "(Lei 4.320/64 art. 63 — a liquidação exige a comprovação; Lei 14.133/2021 arts. 117/140). "
        "**Indício, não prova** — INDISPONÍVEL ≠ irregular (pode faltar só no recorte coletado).")
    add("")
    try:
        from compliance_agent import correlacao_sei
        itens = correlacao_sei.execucao_de_fornecedor(ctx.get("cnpj", ""))
    except Exception as e:  # noqa: BLE001
        add(f"_Cruzamento de execução indisponível nesta execução ({str(e)[:60]}) — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    suspeitos = [x for x in itens if (x.get("exec") in ("nao", "parcial", "indeterminado")) and (x.get("total") or 0) > 0]
    periciados = [x for x in itens if x.get("exec")]
    if not suspeitos:
        if periciados:
            add(f"Dos **{len(periciados)}** processo(s) pago(s) com perícia de execução disponível, **nenhum** com "
                "execução não-comprovada — execução **aparentemente regular** nos autos periciados (demais: INDISPONÍVEL).")
        else:
            add("_Nenhum processo SEI deste fornecedor foi periciado quanto à execução ainda — **INDISPONÍVEL** "
                "(a perícia documental SEI roda por sweep; este fornecedor pode não ter sido alcançado)._")
        add("")
        return "\n".join(L)
    tot = sum(x.get("total") or 0 for x in suspeitos)
    add(f"🟡 **Indício:** **{len(suspeitos)}** processo(s) pago(s) — **R$ {_brl(tot)}** — sem execução comprovada nos autos:")
    add("")
    add("| Processo SEI | OBs | Pago (R$) | Execução | Nota | Resumo da perícia |")
    add("|---|---:|---:|:--:|:--:|---|")
    for x in sorted(suspeitos, key=lambda x: -(x.get("total") or 0))[:20]:
        res = (x.get("resumo") or "")[:90].replace("|", "/")
        add(f"| {x.get('numero_sei')} | {x.get('n_obs')} | {_brl(x.get('total'))} | {x.get('exec')} | {x.get('nota')}/10 | {res} |")
    add("")
    add("> 🟡 **Indício a apurar:** exigir do gestor a prova de entrega/fiscalização (atesto, NF, medição, relatório "
        "fotográfico) dos processos acima antes de novo pagamento. **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _render_rodizio_fornecedor(ctx: dict) -> str:
    """Seção 1-E — rodízio de vencedores (bid rotation/cartel) do fornecedor. Dado + leitura + conclusão honesta."""
    rod = ctx.get("rodizio_forn")
    if rod is None:
        rod = _rodizio_fornecedor(ctx.get("cnpj", ""))
    L: list[str] = []
    add = L.append
    add("## 1-E. RODÍZIO DE VENCEDORES / CARTEL (BID ROTATION)")
    add("")
    add("> Verifica se este fornecedor é um dos **'campeões' que se revezam no topo** das UGs que mais o pagam — "
        "padrão de **bid rotation** (rodízio de vencedores), *red flag* de cartel/conluio (OCDE *Guidelines*; Lei "
        "12.529/11 art. 36; Lei 8.666 art. 90). A OB expõe o **vencedor**, não os licitantes — corroborar no "
        "SEI/PNCP. **Indício, não prova.**")
    add("")
    if not rod.get("ok"):
        add("_Sem UGs suficientes para avaliar rodízio, ou avaliação indisponível nesta execução — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    aneis = rod.get("aneis") or []
    if not aneis:
        add(f"Avaliadas as **{rod['ugs_avaliadas']}** UG(s) que mais pagam este fornecedor: **nenhum anel de "
            "rodízio** com este fornecedor como campeão (indício de cartel **afastado** para essas UGs; as demais "
            "UGs do fornecedor não foram avaliadas — INDISPONÍVEL).")
        add("")
        return "\n".join(L)
    add(f"🟡 **Indício:** este fornecedor figura como **campeão de rodízio** em **{len(aneis)}** UG(s):")
    add("")
    add("| UG | Score do anel | Nº campeões | Vitórias do fornecedor | Anos no topo | Dominância do anel |")
    add("|---|---:|---:|---:|---|---:|")
    for a in aneis:
        anos = ", ".join(str(y) for y in (a.get("anos") or []))
        add(f"| {a['ug']} | {a.get('score')} | {a.get('n_campeoes')} | {a.get('n_vitorias')}× | {anos} "
            f"| {a.get('share_ring')} |")
    add("")
    add("> 🟡 **Indício a corroborar:** revezamento sistemático no topo sugere **bid rotation / cartel** — "
        "confirmar a lista de licitantes (SEI/PNCP) e sócios em comum entre os campeões. **Indício, não prova.**")
    add("")
    return "\n".join(L)




def _capital_recebido_md(emp: dict | None, pagamentos: dict) -> str:
    """A8 — leitura inteligente capital social × recebido (subcapitalização típica de fachada). Indício honesto.
    Limiar espelha o H-CAPITAL do motor DD: recebido ≥ 50× capital e > R$ 500 mil = indício (ALTO se ≥ 200×)."""
    if not emp:
        return ""
    cap = _num_brl(emp.get("capital_social"))
    total = (pagamentos or {}).get("total_geral") or 0
    if cap is None or total <= 0:
        return ""
    if cap <= 0:
        return ("- **Capital × recebido:** capital social declarado **nulo/não informado** frente a "
                f"R$ {moeda(total)} recebidos do Estado — **atenção** (capital irrisório/ausente é indício de "
                "subcapitalização a verificar; INDISPONÍVEL não equivale a regular).")
    razao = total / cap
    if total >= 50 * cap and total > 500_000:
        nivel = "🔴 ALTO" if razao >= 200 else "🟡 MÉDIO"
        return (f"- **Capital × recebido ({nivel}):** capital social de **R$ {moeda(cap)}** contra "
                f"**R$ {moeda(total)}** recebidos (**{razao:,.0f}× o capital**) — **indício** de subcapitalização "
                "típica de empresa de fachada; verificar a capacidade econômico-financeira (art. 11 Lei 8.429/92; "
                "Lei 14.133/21 art. 69). **Indício, não prova.**")
    return (f"- **Capital × recebido:** capital social de R$ {moeda(cap)} frente a R$ {moeda(total)} recebidos "
            f"({razao:,.1f}× o capital) — proporção **sem indício relevante** de subcapitalização.")


def _render_conflito_pessoal(ctx: dict) -> str:
    """Seção 1-F — sócio/admin (CPF resolvido) na folha do Estado = conflito de pessoal. Dado + leitura + conclusão."""
    from compliance_agent.reporting import conflito_pessoal_view as cp
    agg = ctx.get("conflito_pessoal")
    if agg is None:
        agg = cp.por_fornecedor(so_digitos(ctx.get("cnpj", "")))
    L: list[str] = []
    add = L.append
    add("## 1-F. CONFLITO DE PESSOAL — SÓCIO/ADMINISTRADOR NA FOLHA DO ESTADO")
    add("")
    add("> Cruza os sócios/administradores do QSA com a **folha do Estado** (servidores/terceirizados/bolsistas — "
        "`registros_folha`) por **nome + 5 dígitos do CPF** (a sobreposição entre a máscara do QSA e a da folha) — "
        "cobre **todos** os sócios mascarados, sem depender de resolver o CPF. Ser sócio/gestor de empresa "
        "contratada pelo poder público **e** integrar sua folha é indício de **conflito de interesse / "
        "incompatibilidade** (CF art. 37; Lei 8.429/92 art. 11; Lei 14.133/21 art. 9º). **INDISPONÍVEL ≠ ausência**. "
        "Indício, **nunca acusação**.")
    add("")
    add(cp.leitura(agg))
    itens = agg.get("itens") or []
    if itens:
        add("")
        add("| Sócio/Administrador | Papel (QSA) | Órgão (folha) | Cargo | Vínculo | Competência |")
        add("|---|---|---|---|---|---|")
        for it in itens[:20]:
            add(f"| {it['nome']} | {it['papel']} | {it['orgao']} | {it['cargo']} | {it['vinculo']} | {it['competencia']} |")
        add("")
        add("> 🟡 **Indício a confirmar:** confirmar a identidade (nome + 5 díg admite homonímia rara) e a natureza "
            "do vínculo (acumulação lícita de cargos? impedimento de contratar? art. 9º Lei 14.133). **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _render_anomalias(ctx: dict) -> str:
    """Seção 8-C — anomalias nas OBs do fornecedor (modelo de detecção). Dado + leitura + conclusão honesta."""
    import json as _json
    a = ctx.get("anomalias")
    if a is None:
        a = _anomalias_fornecedor(so_digitos(ctx.get("cnpj", "")))
    L: list[str] = []
    add = L.append
    add("## 8-C. ANOMALIAS NAS ORDENS BANCÁRIAS (MODELO DE DETECÇÃO)")
    add("")
    add("> Um modelo de detecção de anomalias (ensemble não supervisionado) pontua cada OB de **0 a 1** por quanto "
        "ela destoa do padrão (valor, frequência do fornecedor, dia/mês, UG). Score alto é **indício** de pagamento "
        "atípico a inspecionar — **nunca prova** (pode ser contrato grande legítimo, sazonalidade, parcela única).")
    add("")
    if not a.get("ok"):
        add("_Sem OBs pontuadas pelo modelo para este fornecedor — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    add(f"Das **{a['n_obs']}** OBs do fornecedor pontuadas pelo modelo, **{a['n_anomalas']}** têm **score alto "
        f"(≥ 0,70)** de anomalia.")
    add("")
    itens = a.get("itens") or []
    if not itens:
        add("> ✅ Nenhuma OB com score alto — **sem anomalia destacada** pelo modelo (não afasta outras irregularidades).")
        add("")
        return "\n".join(L)
    add("| Score | OB | Valor (R$) | Data | Fatores que mais pesaram |")
    add("|---:|---|---:|---|---|")
    for it in itens:
        try:
            feats = ", ".join(_FEAT_ANOM.get(f, f) for f in _json.loads(it.get("feats") or "[]"))
        except Exception:  # noqa: BLE001
            feats = "—"
        add(f"| {it['score']:.3f} | {it.get('ob', '—')} | {moeda(it.get('valor'))} | {it.get('data', '—')} | {feats} |")
    add("")
    add("> 🟡 **Indício a inspecionar:** as OBs acima destoam do padrão do fornecedor segundo o modelo — verificar "
        "o lastro (contrato, medição, aderência do objeto) das de maior score. **Indício estatístico, não prova.**")
    add("")
    return "\n".join(L)


def _render_benford(ctx: dict) -> str:
    """Seção 8-B — Lei de Benford sobre os valores de OB (triagem estatística de fracionamento/fabricação)."""
    p = ctx.get("pagamentos") or {}
    L: list[str] = []
    add = L.append
    add("## 8-B. ANÁLISE ESTATÍSTICA DOS VALORES (LEI DE BENFORD)")
    add("")
    add("> A Lei de Benford prevê a frequência do **1º dígito** em populações de valores naturais (pagamentos). "
        "Um desvio relevante (MAD de Nigrini) é **indício** estatístico de fracionamento, valores fabricados ou "
        "direcionamento — **nunca prova**; amostras pequenas (n<50) são pouco confiáveis. Triagem, a confirmar nos documentos.")
    add("")
    if not p.get("tem_dados"):
        add("_Sem Ordens Bancárias na base para este fornecedor — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    try:
        from compliance_agent.analysis.benford import benford
        vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", [])
                if (ln.get("valor") or 0) > 0]
        bf = benford(vals)
    except Exception:  # noqa: BLE001
        add("_Análise de Benford indisponível nesta execução._")
        add("")
        return "\n".join(L)
    d1 = bf.get("primeiro_digito") or {}
    faixa = d1.get("faixa_nigrini", "—")
    conforme = "CONFORM" in faixa.upper() and "NÃO" not in faixa.upper()
    add(f"**1º dígito** (n={d1.get('n', 0)} OBs): **MAD de Nigrini = {d1.get('mad', '—')}** → **{faixa}**.")
    if not bf.get("suficiente"):
        add(f"> ⚠️ Amostra pequena (n={d1.get('n', 0)} < 50) — resultado **pouco confiável**, informativo apenas.")
    add("")
    obs = d1.get("obs") or {}
    esp = d1.get("esp") or {}
    add("| Dígito | Esperado (Benford) | Observado | Δ (pp) |")
    add("|---:|---:|---:|---:|")
    for dig in range(1, 10):
        e = float(esp.get(str(dig), 0) or 0)
        o = float(obs.get(str(dig), 0) or 0)
        add(f"| {dig} | {e * 100:.1f}% | {o * 100:.1f}% | {(o - e) * 100:+.1f} |")
    add("")
    if conforme:
        add("> ✅ **Conforme** — a distribuição dos 1ºs dígitos é compatível com Benford; **sem indício** estatístico "
            "de fracionamento/fabricação de valores (não afasta outras irregularidades).")
    else:
        add("> 🟡 **Não conformidade** — a distribuição se afasta do esperado; **indício** estatístico a verificar "
            "(fracionamento, valores fabricados, direcionamento). Confirmar nos contratos/OBs — Benford é triagem, não prova.")
    add("")
    return "\n".join(L)


def render_md(ctx: dict) -> str:
    p = ctx["pagamentos"]
    L: list[str] = []
    add = L.append

    add("# RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR")
    add(f"### {ctx['nome']}")
    add("")
    add("*Due Diligence de Integridade · Exposição Financeira · Risco & Compliance*")
    add("")
    add(f"**CNPJ:** {ctx['cnpj_fmt']}  |  **Data:** {ctx['data']}  |  **Analista:** Controle Externo (automatizado)")
    add("**Metodologia:** due diligence de integridade (padrão Kroll/Deloitte) · matriz de risco TCU P×I · OB = pagamento (fonte de verdade)")
    add(f"**Classificação de fonte:** OBs/Contratos = **REAL** (SIAFE/TFE) · Perfil/Sanções/Rede = **{ctx['fonte_enriq']}**")
    add("")
    add("---")
    add("")
    _fr = cabecalho_frescor()  # honestidade: cobertura/frescor da base no topo
    if _fr:
        add(_fr)
        add("")

    # 1. Sumário executivo
    add("## SUMÁRIO EXECUTIVO")
    add("")
    add(_resumo_executivo(ctx))
    add("")
    if p["tem_dados"]:
        add("### Exposição financeira — pagamentos por exercício")
        add("")
        add("| Exercício | Nº de OBs | Valor pago (R$) |")
        add("|---|---:|---:|")
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"| {a} | {b['n']} | {moeda(b['total'])} |")
        add(f"| **Total** | **{p['n_geral']}** | **{moeda(p['total_geral'])}** |")
        add("")

    # 2. Perfil cadastral
    add("## 1. PERFIL CADASTRAL")
    add("")
    emp = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx["enriq"].get("ok") else None
    if emp:
        # Município/UF: o enrich às vezes vem sem esses campos separados; o cruzamento já os
        # extrai do endereço (mesma fonte que alimenta "Cidade-sede" na Seção 1-B) — fallback honesto.
        _endcz = (ctx.get("cruzamento") or {}).get("endereco") or {}
        _mun = emp.get("municipio") or _endcz.get("municipio") or "—"
        _uf = emp.get("uf") or _endcz.get("uf") or "—"
        campos = [
            ("Razão social", emp.get("razao_social")), ("Situação", emp.get("situacao")),
            ("Data de abertura", emp.get("data_abertura")), ("Porte", emp.get("porte")),
            ("Natureza jurídica", emp.get("natureza_juridica")), ("Capital social", f"R$ {moeda(emp.get('capital_social'))}"),
            ("CNAE principal", emp.get("cnae_principal")), ("Município/UF", f"{_mun}/{_uf}"),
            ("Endereço (sede)", emp.get("endereco")),
        ]
        for k, v in campos:
            add(f"- **{k}:** {v or '—'}")
        socios = emp.get("socios") or []
        if socios:
            add("")
            add("**Quadro societário:**")
            for s in socios[:15]:
                add(f"- {s.get('nome','—')} — {s.get('qualificacao','—')} (entrada: {s.get('data_entrada','—')})")
    else:
        add(f"> ⚠️ Perfil cadastral **{ctx['fonte_enriq']}** "
            f"({ctx['enriq'].get('_motivo','enriquecimento não disponível')}). "
            f"Os dados financeiros abaixo (OBs/contratos) são REAIS e independem desta seção.")
        # endereço da sede via cruzamento (BrasilAPI direto), mesmo sem o enriquecimento completo
        _end = (ctx.get("cruzamento") or {}).get("endereco") or {}
        if _end.get("endereco"):
            add("")
            add(f"- **Endereço (sede):** {_end['endereco']}")
    # realidade da sede (a empresa é real?) — cruza a verificação de endereço do próprio CNPJ
    _rs = _realidade_sede(ctx.get("cnpj", ""))
    if _rs:
        add(_rs)
    # A8 — capital social × recebido (subcapitalização típica de fachada)
    _cr = _capital_recebido_md(emp, p)
    if _cr:
        add(_cr)
    # Natureza SEM FINS LUCRATIVOS ('3xxx') ANCORADA NO DUMP LOCAL (`empresas_min`) — surge mesmo com o
    # enriquecimento RFB INDISPONÍVEL (o dump é local). Indício ≠ acusação; ressalva p/ ensino/pesquisa/estágio.
    _nsf = ctx.get("natureza_sem_fins") or {}
    if _nsf.get("sem_fins"):
        _nat = _nsf.get("natureza_txt") or "sem fins lucrativos"
        add("")
        if _nsf.get("ressalva"):
            add(f"- **Natureza jurídica (dump RF):** {_nat} (cód. {_nsf.get('natureza_cod','—')}) — entidade de "
                "ensino/pesquisa/estágio; recebimento provavelmente **legítimo** (ressalva).")
        else:
            add(f"- 🟡 **Natureza jurídica (dump RF):** {_nat} (cód. {_nsf.get('natureza_cod','—')}) — "
                "**organização social/associação/fundação recebendo como fornecedor comum** (Lei 9.637/98; "
                "Lei 13.019/2014 — MROSC). Confirmar objeto, credenciamento e prestação de contas. "
                "**Indício ≠ acusação.**")
    add("")

    # 1-B. Cruzamento sócio × OB (SIAFE) × processo SEI × endereço
    add(_render_cruzamento(ctx))

    # 1-C. Cruzamento de benefícios sociais dos sócios/administradores (laranja/testa-de-ferro)
    add(_render_beneficios_socios(ctx))

    # 1-D. Doações eleitorais (TSE) × contratos — conflito doador↔contrato (paridade com o PDF)
    add(_render_doacoes_tse(ctx))

    # 1-E. Rodízio de vencedores / cartel (bid rotation) — o fornecedor é campeão de algum anel?
    if "rodizio_forn" not in ctx:
        ctx["rodizio_forn"] = _rodizio_fornecedor(ctx.get("cnpj", ""))
    add(_render_rodizio_fornecedor(ctx))

    # 1-F. Conflito de pessoal — sócio/administrador (CPF resolvido) na folha do Estado
    add(_render_conflito_pessoal(ctx))

    # 1-G. Execução contratual (prova de entrega) — OB paga × perícia SEI (lex_execucao). Surfacing de pago-sem-execução.
    add(_render_execucao(ctx))

    # 3. Pagamentos (OBs) por ano — TABELA POR ANO (requisito do Mestre Jorge)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Fonte: SIAFE/TFE-RJ (Ordem Bancária = dado **definitivo de pagamento**). Por exercício, as **maiores "
        "OBs** (materiais); a **lista completa** de cada pagamento está na **planilha XLSX** deste relatório. "
        "OBs de R$ 0,00 são estornos/regularizações (entram na contagem, não somam ao total).")
    add("")
    add(f"> {_NOTA_CARDINALIDADE}")
    card = ctx.get("cardinalidade") or {}
    if card.get("n_obs"):
        add("")
        add(f"> {_frase_cardinalidade(card)}")
    add("")
    if p["tem_dados"]:
        TOP_OB_ANO = 12  # padrão de due diligence: destacar o material; o detalhe completo vai na planilha
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"### Exercício {a} — {b['n']} OBs — Total pago: R$ {moeda(b['total'])}")
            add("")
            maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:TOP_OB_ANO]
            add("| # | Nº OB | Data pagamento | Órgão (UG) | Valor (R$) |")
            add("|---:|---|---|---|---:|")
            for i, ln in enumerate(maiores, 1):
                add(f"| {i} | {ln['numero_ob']} | {ln['data']} | {ln['orgao']} | {moeda(ln['valor'])} |")
            add(f"| | | | **Total {a} ({b['n']} OBs)** | **{moeda(b['total'])}** |")
            if b["n"] > len(maiores):
                add("")
                add(f"> _{len(maiores)} maiores de {b['n']} OBs do exercício — lista completa na planilha XLSX._")
            add("")
    else:
        add("_Sem OBs registradas na base local para este CNPJ._")
        add("")

    # 4. Concentração por órgão + HHI
    add("## 3. CONCENTRAÇÃO POR ÓRGÃO CONTRATANTE (HHI)")
    add("")
    if p["tem_dados"]:
        add(f"**HHI:** {p['hhi'].get('indice')} — concentração **{p['hhi'].get('nivel')}** "
            f"(maior órgão = {p['hhi'].get('top_share')}% do valor pago).")
        add("")
        add("| Órgão (UG) | Valor pago (R$) | % do total |")
        add("|---|---:|---:|")
        tot = p["total_geral"] or 1
        for org, val in list(p["por_orgao_geral"].items()):
            add(f"| {org} | {moeda(val)} | {val/tot*100:.1f}% |")
        add("")
        if p["hhi"].get("top_share", 0) >= 60:
            add("> 🔴 **Red flag (ACFE):** concentração ≥60% em um único órgão sem justificativa técnica "
                "merece verificação (isonomia/impessoalidade — Art. 37 CF/88).")
            add("")
    else:
        add("_Indisponível sem OBs._")
        add("")

    # 5. Carteira de contratos
    add("## 4. CARTEIRA DE CONTRATOS (SIAFE)")
    add("")
    c = ctx["contratos"]
    if c["n"]:
        add(f"**{c['n']} contratos** — valor total declarado: R$ {moeda(c['total'])}.")
        add("")
        add("| Nº | Objeto | Órgão | Valor (R$) | Assinatura | Situação |")
        add("|---|---|---|---:|---|---|")
        for ln in c["linhas"]:
            obj = (ln["objeto"] or "—")[:60]
            add(f"| {ln['numero']} | {obj} | {ln['orgao']} | {moeda(ln['valor'])} | {ln['assinatura']} | {ln['status']} |")
        add("")
    else:
        add("_Nenhum contrato oficial vinculado na base local._")
        add("")

    # 4-B. Contratos e compras diretas no TCE-RJ (Dados Abertos — independe do SEI/WAF)
    add("## 4-B. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)")
    add("")
    try:
        from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
        _itens = contratos_de_fornecedor(ctx["cnpj"], limite=100)
    except Exception:
        _itens = []
    _ctr = [i for i in _itens if i.get("_tipo") == "contrato"]
    _cmp = [i for i in _itens if i.get("_tipo") == "compra_direta"]
    if _ctr or _cmp:
        _soma_ctr = sum(i.get("valor_contrato") or 0 for i in _ctr)
        _soma_cmp = sum(i.get("valor") or 0 for i in _cmp)
        _dispensa = [i for i in _cmp if any(k in ((i.get("afastamento") or "") + " " +
                     (i.get("enquadramento_legal") or "")).lower() for k in ["dispensa", "inexigibil"])]
        add(f"O controle externo (TCE-RJ) registra **{len(_ctr)} contrato(s)** (R$ {moeda(_soma_ctr)}) e "
            f"**{len(_cmp)} compra(s) direta(s)** (R$ {moeda(_soma_cmp)}; {len(_dispensa)} por dispensa/"
            "inexigibilidade). Fonte oficial, independe do SEI.")
        add("")
        # contratado (TCE-RJ) vs pago (OBs) — leitura de execução
        _pago = (ctx.get("pagamentos") or {}).get("total_geral") or 0
        if _soma_ctr and _pago:
            _r = _pago / _soma_ctr * 100
            add(f"> **Contratado vs. pago:** R$ {moeda(_soma_ctr)} contratados (TCE-RJ) × R$ {moeda(_pago)} pagos "
                f"em OBs (SIAFE/TFE) = **{_r:.0f}%** de execução financeira sobre o valor contratado registrado. "
                "(Pago superior ao contratado pode indicar aditivos/contratos não listados — verificar.)")
            add("")
        if _ctr:
            add("**Contratos (maiores por valor):**")
            add("")
            add("| Processo | Ano | Objeto | Critério | Valor (R$) | Unidade |")
            add("|---|---:|---|---|---:|---|")
            for i in _ctr[:10]:
                obj = (i.get("objeto") or "").strip()
                obj = (obj[:55] + "…") if len(obj) > 55 else (obj or "—")
                proc = (i.get("processo") or "").split(",")[0].strip()
                proc = proc + (f" (+{len(i['processo'].split(','))-1})" if "," in (i.get("processo") or "") else "")
                add(f"| {proc} | {i.get('ano_processo','')} | {obj} | {i.get('criterio_julgamento') or '—'} | "
                    f"{moeda(i.get('valor_contrato'))} | {(i.get('unidade') or '')[:28]} |")
            add("")
        if _dispensa:
            add("**Compras diretas (dispensa/inexigibilidade — fundamento legal):**")
            add("")
            add("| Processo | Ano | Objeto | Afastamento | Enquadramento legal | Valor (R$) |")
            add("|---|---:|---|---|---|---:|")
            for i in _dispensa[:10]:
                obj = (i.get("objeto") or "").strip()
                obj = (obj[:40] + "…") if len(obj) > 40 else (obj or "—")
                enq = (i.get("enquadramento_legal") or "").strip()
                enq = (enq[:50] + "…") if len(enq) > 50 else (enq or "—")
                add(f"| {(i.get('processo') or '').split(',')[0].strip()} | {i.get('ano_processo','')} | {obj} | "
                    f"{i.get('afastamento') or '—'} | {enq} | {moeda(i.get('valor'))} |")
            add("")
    else:
        add("_Sem contratos ou compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ "
            "(pode ser contratação municipal/federal ou ainda não publicada)._")
        add("")

    # 6. Sinais de risco (do enriquecimento)
    add("## 5. SINAIS DE RISCO CORPORATIVO")
    add("")
    if ctx["enriq"].get("ok"):
        add(f"**Rating:** {ctx['risco']} (score {ctx['score']}/100).")
        add("")
        for s in (ctx["enriq"].get("sinais") or [])[:30]:
            nivel = s.get("nivel", "")
            emoji = {"ALTO": "🔴", "MÉDIO": "🟡", "BAIXO": "🟢"}.get(nivel, "•")
            desc = s.get("descricao", "")
            det = s.get("detalhe", "")
            add(f"- {emoji} **{nivel}** — {desc}{(' — ' + det) if det else ''}")
        add("")
    else:
        add(f"> Sinais corporativos **{ctx['fonte_enriq']}** ({ctx['enriq'].get('_motivo','—')}).")
        add("")

    # 7. Verificação de sanções
    add("## 6. VERIFICAÇÃO EM LISTAS RESTRITIVAS (CEIS/CNEP/CEPIM)")
    add("")
    sanc = (ctx["enriq"].get("dados") or {}).get("sancoes") if ctx["enriq"].get("ok") else None
    if sanc:
        if sanc.get("verificado"):
            n = sanc.get("n_sancoes", 0)
            add(("✅ Nenhuma sanção identificada." if n == 0 else f"🔴 {n} sanção(ões) identificada(s)!"))
        else:
            add(f"> Verificação não realizada: {sanc.get('motivo','—')}.")
    else:
        add(f"> **{ctx['fonte_enriq']}**.")
    add("")

    # 8. Matriz de risco TCU P×I (qualitativa, a partir do que temos)
    add("## 7. MATRIZ DE RISCO — METODOLOGIA TCU P×I")
    add("")
    add("Escala P (probabilidade) × I (impacto), 1–9 cada. Faixas: Baixo 1–9 | Médio 10–39 | Alto 40–79 | Extremo 80–81.")
    add("")
    add("| Fator de risco | P | I | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for fator, pp, ii in _fatores_risco(ctx):
        sc = pp * ii
        faixa = "Baixo" if sc <= 9 else "Médio" if sc <= 39 else "Alto" if sc <= 79 else "Extremo"
        add(f"| {fator} | {pp} | {ii} | {sc} | {faixa} |")
    add("")

    # 9. Red flags com fundamento
    add("## 8. RED FLAGS DE COMPLIANCE")
    add("")
    rf = _red_flags(ctx)
    if rf:
        for titulo, desc, fund in rf:
            add(f"### {titulo}")
            add(f"{desc}")
            add(f"**Fundamento:** {fund}")
            add("")
    else:
        add("_Nenhum red flag automático disparado a partir dos dados locais._")
        add("")

    # 8-B. Análise estatística (Lei de Benford) — paridade com o PDF
    add(_render_benford(ctx))

    # 8-C. Anomalias nas OBs (modelo de detecção) — M2
    add(_render_anomalias(ctx))

    # 9. Análise jurídica e de mérito — o PARECER escrito do JFN
    add("## 9. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR")
    add("")
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        add("### Análise raciocinada — cruzamento dos achados (IA sobre os fatos coletados)")
        add("")
        add(raciocinio)
        add("")
        add("> _Síntese gerada por IA **a partir dos fatos coletados** (não inventa dados); indícios para "
            "apuração, não conclusão. O parecer estruturado abaixo permanece como base._")
        add("")
    add(parecer_fornecedor(ctx))
    add("")

    # 10. Recomendações
    add("## 10. RECOMENDAÇÕES")
    add("")
    add("**Imediato (0–30 dias):**")
    add("- Cruzar as OBs por ano (tabelas da Seção 2) com os empenhos/liquidações correspondentes no SIAFE.")
    add("- Validar a aderência objeto-contratual dos órgãos de maior concentração (Seção 3).")
    add("")
    add("**Curto prazo (30–90 dias):** abrir os processos SEI dos maiores pagamentos; checar aditivos (>25%).")
    add("")
    add("**Estrutural:** monitoramento contínuo automatizado (timers TFE/OB) e atualização trimestral deste relatório.")
    add("")

    # 11. Referências
    add("## 11. REFERÊNCIAS E FONTES")
    add("")
    add("- **Dados primários:** SIAFE-Rio / Transparência Fiscal RJ (OBs e contratos) — `data/compliance.db`.")
    add("- **Perfil/sanções/rede:** Receita Federal, PNCP, CEIS/CNEP/CEPIM (via `relatorio_riscos`).")
    add("- **Normas:** Lei 14.133/2021; Lei 8.666/93; Lei 4.320/64; CF/88 Art. 37; metodologia TCU P×I; ACFE Report to the Nations 2024.")
    add("")
    add(f"_Relatório gerado automaticamente em {ctx['data']}. "
        "Não substitui análise jurídica especializada._")
    add("")
    return "\n".join(L)


_FONTES_DEJAVU = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
