# -*- coding: utf-8 -*-
"""
LEX — Agente de avaliação jurídica (Direito Administrativo / Controle Externo).

Emite um PARECER fático-jurídico (tomada de contas) sobre a contratação/licitação/pagamentos de um
fornecedor. Lex agora **LÊ A ÍNTEGRA** de cada processo SEI correlacionado (via o leitor do JFN —
Chrome 9222 + OCR de CAPTCHA; fallback no portal público httpx) e cruza o **texto real** dos documentos
(edital, TR, contrato, despachos) com os red flags do controle externo (TCU/TCE-RJ). Classifica o grau de
atenção (🟢 verde / 🟡 amarelo / 🔴 vermelho), com fundamento legal. Base: `docs/LEX-BASE-JURIDICA.md`.

Princípio (cláusula de honestidade): aponta INDÍCIOS a verificar, sob presunção de legitimidade dos atos
administrativos; NUNCA afirma crime/improbidade/dolo (compete ao TCE-RJ/MP-RJ/Judiciário, após contraditório).

É o 3º documento do `/relatorio` (junto do PDF de inteligência e da planilha). Mesma estética do JFN.
"""
from __future__ import annotations

import logging
import os
import time


from compliance_agent.reporting.inteligencia import (
    _REPORTS, _slug, _termos_significativos,
    troca_controle_societaria, moeda, so_digitos,
)

# Leitura da íntegra do SEI: liga/desliga, quantos processos ler e orçamento de tempo (s).
_LER_SEI = os.environ.get("JFN_LEX_LER_SEI", "1") != "0"
_MAX_SEI = int(os.environ.get("JFN_LEX_MAX_SEI", "3"))
_SEI_BUDGET = float(os.environ.get("JFN_LEX_SEI_BUDGET", "120"))

# ── Split 2026-07-06: conhecimento/leitura/análise/render/órgão em módulos próprios ─────────────
# lex.py continua sendo a FACHADA pública (lex.gerar, lex.parecer_md, lex._grau, …): tudo re-exportado
# abaixo. Snapshot de equivalência: tests/test_lex_snapshot.py.
from compliance_agent.lex_redflags import (  # noqa: F401
    _RF, _MATRIZ, _RAMOS, _SERV_CONTINUO_KW, _EXCULPATORIO, _DESTINATARIO_FAMILIA,
    _MOTIVO_IMPROBIDADE_RF, _RF_DESTINATARIO, _DOLO_RF, _DOLO_OBS,
    _anatomia, _destinatarios, _eh_servico_continuo, _elemento_subjetivo, _exculpatorio,
    _fam_exculpatorio, _fmt_proc, _grau, _primeira_data_pag, _ramo_objeto,
)
from compliance_agent.lex_sei_leitura import (  # noqa: F401
    _bloqueio_rede, _dossie_sei, _eh_interface_sei, _ler_integra_sei, _run_coro, _texto_integra,
)
from compliance_agent.lex_analise_conteudo import (  # noqa: F401
    _analisar_conteudo_sei, _analisar_contratos_tcerj, _detectar, _json_lex, _merge_achados,
    _modalidade, _objeto_valido, _trecho, analisar_texto_edital, analise_discursiva,
)
from compliance_agent.lex_render import (  # noqa: F401
    _analise_merito, _secao_auditoria_contrato, _secao_direcionamento, _secao_investigacao,
    _secao_pacote_fachada, _secao_padroes_ligados, _secao_pesquisa, parecer_md, render_pdf,
)
from compliance_agent.lex_orgao import (  # noqa: F401
    _achados_orgao, _ob_zero_da_ug, _parecer_orgao_md, gerar_orgao,
)


logger = logging.getLogger(__name__)


def _sei_do_fornecedor(cnpj: str) -> list[dict]:
    try:
        from compliance_agent.correlacao_sei import processos_de_fornecedor
        return _priorizar_sei(processos_de_fornecedor(cnpj))
    except Exception:
        return []


def _priorizar_sei(sei: list[dict]) -> list[dict]:
    """Ordena os candidatos ANTES do corte `_MAX_SEI` (antes o corte era cego: fornecedor com
    dezenas de processos podia ter os 3 lidos caindo em pura execução). Prioridade: processo com
    fase de SELEÇÃO/edital no arquivo compacto (grátis, sem browser) > maior valor pago > mais OBs.
    Sem arquivo local o processo não perde lugar — só não ganha o bônus (honesto)."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent / "data" / "sei_arquivo"

    def _tem_selecao(numero: str) -> bool:
        slug = re.sub(r"\D+", "_", numero or "").strip("_")
        man = raiz / slug / "manifest.json"
        if not man.exists():
            return False
        try:
            import json
            docs = json.loads(man.read_text()).get("docs") or []
            # o arquivo compacto já classifica a fase de cada doc (sei/fases via sei_consultar)
            return any(d.get("fase") == "selecao" for d in docs if isinstance(d, dict))
        except (OSError, ValueError, AttributeError, TypeError):
            return False  # manifest ilegível = sem bônus (processo não perde lugar)

    # manifest só dos 20 primeiros (I/O barato, mas com teto)
    bonus = {id(s): (1 if i < 20 and _tem_selecao(s.get("numero_sei", "")) else 0)
             for i, s in enumerate(sei)}
    return sorted(sei, key=lambda s: (-bonus[id(s)], -(s.get("total") or 0),
                                      -(s.get("n_obs") or 0)))


def _contratos_tcerj(cnpj: str) -> list[dict]:
    """Contratos + compras diretas do TCE-RJ Dados Abertos (objeto/critério/valores/dispensa). Fonte que
    NÃO depende do SEI (WAF) — traz o texto oficial do controle externo direto da API pública."""
    try:
        from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
        return contratos_de_fornecedor(cnpj, limite=100)
    except Exception:
        return []


def _cartel_do_fornecedor(cnpj: str) -> dict:
    """Ego-rede fornecedor↔órgão (Onda 3): co-ocorrência com outros fornecedores não-ubíquos nos mesmos órgãos."""
    try:
        from compliance_agent.grafo_cartel import vizinhanca_cartel
        return vizinhanca_cartel(cnpj, limite=10)
    except Exception:
        return {}



def _analise(ctx: dict, ler_sei: bool | None = None) -> dict:
    """Computa TODA a análise UMA vez (lê o SEI uma vez) e devolve o dossiê para md/pdf."""
    cnpj = ctx.get("cnpj", "")
    sei = _sei_do_fornecedor(cnpj)
    ach_dados = _detectar(ctx)

    # Onda 2 — contratos/compras do TCE-RJ (não dependem do SEI/WAF)
    itens_tcerj = _contratos_tcerj(cnpj)
    ach_tcerj, resumo_tcerj = _analisar_contratos_tcerj(itens_tcerj)

    # Onda 3 — rede fornecedor↔órgão (indício de rodízio/cartel)
    cartel = _cartel_do_fornecedor(cnpj)
    ach_cartel = []
    fortes = [v for v in (cartel.get("vizinhos") or []) if v.get("orgaos_comuns", 0) >= 3]
    if len(fortes) >= 3 and (cartel.get("n_orgaos") or 0) >= 2:
        nomes = ", ".join((v.get("nome") or "")[:30] for v in fortes[:3])
        ach_cartel.append({"rf": "R8", "grav": 2,
                           "obs": f"{len(fortes)} fornecedores não-ubíquos atuam nos mesmos órgãos deste favorecido "
                                  f"(ex.: {nomes}) — verificar possível **rodízio/cartel** (bid rigging) entre players "
                                  "que compartilham um conjunto estreito de órgãos."})

    # Onda 4 — cruzamento por sócio em comum (indício FORTE quando há co-ocorrência + sócio)
    cruzado = {}
    try:
        from compliance_agent.rede_societaria import cruzar_cartel
        cruzado = cruzar_cartel(cnpj)
    except Exception:
        cruzado = {}
    socio_match = cruzado.get("co_ocorrencia_com_socio_comum") or []
    if socio_match:
        nomes = "; ".join(f"{(m.get('nome') or '')[:28]} (sócio: {(m.get('socios_comuns') or '')[:30]})"
                          for m in socio_match[:3])
        ach_cartel.append({"rf": "R8", "grav": 4,
                           "obs": f"**Indício forte:** {len(socio_match)} fornecedor(es) que co-ocorrem nos mesmos "
                                  f"órgãos **e compartilham sócio** com o favorecido ({nomes}) — possível "
                                  "cartel/laranja/empresas-irmãs (art. 337-F CP; art. 36 Lei 12.529)."})

    leituras: list[dict] = []
    ach_doc: list[dict] = []
    fazer_leitura = _LER_SEI if ler_sei is None else ler_sei
    if fazer_leitura and sei:
        t0 = time.monotonic()
        for s in sei[:_MAX_SEI]:
            if time.monotonic() - t0 > _SEI_BUDGET:
                break
            integra = _ler_integra_sei(s.get("numero_sei", ""))
            ach, resumo = _analisar_conteudo_sei(integra)
            resumo["n_obs"] = s.get("n_obs")
            resumo["total"] = s.get("total")
            leituras.append(resumo)
            ach_doc.extend(ach)

    # Onda estrutural — atividade-fim (CNAE) × objeto contratado (empresa de fachada / qualificação técnica).
    # Conservador: só dispara com ZERO sobreposição de termos significativos entre o CNAE e o objeto REAL
    # do TCE-RJ (o contratos.objeto do SIAFE não serve — guarda "Aditivos:N"). Mesma lógica do RF-05 do relatório.
    ach_estrutural: list[dict] = []
    emp_cad = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") or {}

    # R6 — troca de controle societário posterior a receita pública (helper compartilhado com o RF-04 do relatório).
    tc = troca_controle_societaria(emp_cad, ctx.get("pagamentos") or {})
    if tc:
        ach_estrutural.append({"rf": "R6", "grav": 3,
            "obs": f"Ingresso no quadro societário em **{tc['recente']}** ({tc['quem']}), **posterior** a "
                   f"R$ {moeda(tc['total_antes'])} já pagos pelo Estado ({tc['n_antes']} OBs, {tc['share']:.0f}% do "
                   "total). Mudança de controle em fornecedor com receita pública pré-existente é indício de "
                   "**sucessão/interposição de pessoas** (laranja) ou de aquisição de empresa 'com contratos' — "
                   "verificar o histórico de controle (QSA pretérito) e a cronologia da escalada de pagamentos."})

    cnae = emp_cad.get("cnae_principal") or ""
    objs_reais = [(i.get("objeto") or "").strip() for i in itens_tcerj if len((i.get("objeto") or "").strip()) >= 12]
    if cnae and objs_reais:
        tc = _termos_significativos(cnae)
        to_ = _termos_significativos(" ".join(objs_reais))
        if tc and to_ and not (tc & to_):
            amostra = objs_reais[0][:80]
            ach_estrutural.append({"rf": "R11", "grav": 3,
                "obs": f"O CNAE principal registrado (“{cnae}”) **não evidencia aderência** ao objeto efetivamente "
                       f"contratado (ex.: “{amostra}…”). Atividade econômica de registro incompatível com o objeto "
                       "é indício de **empresa de prateleira/fachada** habilitada para fim diverso ou de **qualificação "
                       "técnica frágil** — verificar a aptidão operacional real e a adequação do CNAE."})
        elif tc and to_ and len(tc & to_) == 1 and len(to_) >= 4:
            # grau intermediário (antes só a disjunção TOTAL disparava — incompatibilidade
            # parcial passava em silêncio): 1 único termo em comum num objeto rico é aderência
            # frágil, não incompatibilidade — indício menor, com os termos citados.
            from compliance_agent.lex_redflags import _ramo_objeto
            if _ramo_objeto(cnae) != _ramo_objeto(" ".join(objs_reais)):
                comum = next(iter(tc & to_))
                ach_estrutural.append({"rf": "R11", "grav": 2,
                    "obs": f"Aderência **frágil** entre o CNAE registrado (“{cnae}”) e o objeto contratado "
                           f"(ex.: “{objs_reais[0][:80]}…”): apenas o termo “{comum}” é comum, e os ramos de "
                           "atividade divergem. Não é incompatibilidade total — verificar a aptidão operacional "
                           "antes de qualquer conclusão."})

    # Investigação de fachada/laranja (motor único — investigacao_dd). O Lex CONDUZ a investigação:
    # cada hipótese CONFIRMADA/INDÍCIO vira um achado (entra no grau); o quadro completo vai à seção
    # dedicada do parecer e alimenta a análise raciocinada (gemini). Honesto: INDISPONÍVEL ≠ achado.
    investigacao = {}
    try:
        from compliance_agent.investigacao_dd import investigar
        p_inv = ctx.get("pagamentos") or {}
        total_pago = p_inv.get("total_geral") or 0.0
        investigacao = investigar(cnpj, cadastral=None, pagamentos={
            "total_pago": total_pago,
            "primeira_data": _primeira_data_pag(p_inv),
        })
        for h in investigacao.get("hipoteses", []):
            if h["status"] in ("CONFIRMADO", "INDICIO"):
                grav = (4 if (h["status"] == "CONFIRMADO" and h["nivel"] == "ALTO")
                        else 3 if h["nivel"] == "ALTO" else 2)
                ach_estrutural.append({"rf": f"DD/{h['codigo']}", "grav": grav,
                                       "obs": f"**{h['titulo']}.** {h['evidencia']}"})
        # Pacote de sinais de fachada (TAC + sede/visual + cadastro + rede) + RACIOCÍNIO LLM (gemini/cerebras).
        # Estende os INPUTS da §II-E sem criar produto novo: o detector TAC determinístico entra como achado
        # (no grau) e o veredito raciocinado anexa-se à investigação. Async+bounded+degrada honesto.
        try:
            from compliance_agent import rede_fachada as rf
            pacote = rf.pacote_sinais(cnpj, total_pago=total_pago,
                                      cadastral=emp_cad if emp_cad else None)
            investigacao["pacote_fachada"] = pacote
            tac = pacote.get("tac") or {}
            if tac.get("codigo") == "RF-TAC":  # red_flag_tac disparou → vira achado no grau
                grav = 4 if tac.get("nivel") == "ALTO" else 3
                ach_estrutural.append({"rf": "DD/RF-TAC", "grav": grav,
                                       "obs": f"**{tac['titulo']}.** {tac['descricao']}"})
            investigacao["veredito_fachada"] = rf.veredito_llm(pacote)
        except Exception as exc:  # noqa: BLE001 — pacote/LLM degradam honesto; a DD básica permanece
            logger.warning("veredito de fachada (LLM) indisponível — parecer segue só com a DD básica: %s", exc)
    except Exception:
        investigacao = {}

    # Direcionamento (Fase 4): parecer LLM ON-DEMAND já persistido (tools.sei_direcionamento_llm) — SURFACE,
    # nunca dispara o LLM aqui (só leitura). Honesto: None se o fornecedor não está nos top-score avaliados.
    direcionamento = None
    try:
        from tools.sei_direcionamento_llm import parecer_fornecedor
        direcionamento = parecer_fornecedor(cnpj)
    except Exception:  # noqa: BLE001 — surface é best-effort; ausência não derruba o parecer
        direcionamento = None

    # Pesquisa-internet (Fase 5): parecer já persistido (tools.lex_pesquisa_internet) — SURFACE só leitura,
    # nunca dispara OSINT/LLM aqui. Honesto: None se o fornecedor ainda não foi pesquisado.
    pesquisa = None
    try:
        from tools.lex_pesquisa_internet import parecer_pesquisa
        pesquisa = parecer_pesquisa(cnpj)
    except Exception:  # noqa: BLE001 — surface best-effort
        pesquisa = None

    # Onda motor — AUDITORIA DE CONTRATO CONTÍNUO (bateria T01–T22 de auditoria_contrato, via pericia_sweep.periciar).
    # Determinística, OBs SIAFE (ob_orcamentaria_siafe), SEM LLM. Só p/ serviço contínuo com acervo SIAFE; audita a
    # UG MAIS MATERIAL (maior volume contabilizado) — a seção II-E.2 é por-contrato (o /orgao cobre o por-UG).
    # Degrada honesto: sem OB SIAFE → dict vazio → o renderer omite a seção. NÃO entra no _grau do Lex (grau próprio).
    aud_contrato: dict = {}
    if cnpj and _eh_servico_continuo([emp_cad.get("cnae_principal"), emp_cad.get("atividade"), ctx.get("nome")]):
        try:
            from compliance_agent.pericia_sweep import periciar, _conn, _eh_nao_contratual
            cc = _conn()
            try:
                ug_row = cc.execute(
                    "SELECT ug_emitente ug, SUM(valor) tot FROM ob_orcamentaria_siafe "
                    "WHERE credor=? AND lower(status) LIKE 'contabiliz%' "
                    "GROUP BY ug_emitente ORDER BY tot DESC LIMIT 1", (cnpj,)).fetchone()
                if ug_row and ug_row["ug"] and not _eh_nao_contratual(ctx.get("nome") or ""):
                    aud_contrato = periciar(cnpj, ug_row["ug"], cc)
            finally:
                cc.close()
        except Exception:  # noqa: BLE001 — motor degrada honesto; ausência não derruba o parecer
            aud_contrato = {}

    achados = _merge_achados(ach_dados + ach_doc + ach_tcerj + ach_cartel + ach_estrutural)
    emoji, rotulo, just = _grau(achados)
    exculpatorio = _exculpatorio(achados)
    destinatarios = _destinatarios(achados)
    return {"cnpj": cnpj, "sei": sei, "leituras": leituras, "achados": achados,
            "tem_leitura_doc": bool(ach_doc), "tcerj": resumo_tcerj, "cartel": cartel,
            "cruzado": cruzado, "investigacao": investigacao, "direcionamento": direcionamento,
            "pesquisa": pesquisa, "auditoria_contrato": aud_contrato,
            "exculpatorio": exculpatorio, "destinatarios": destinatarios,
            "emoji": emoji, "rotulo": rotulo, "just": just}



def gerar(ctx: dict, salvar: bool = True, ler_sei: bool | None = None) -> dict:
    """Gera o parecer Lex (md + pdf). Lê a íntegra do SEI UMA vez. Retorna {ok, grau, n_indicios, n_sei_lidos, path_lex_pdf, path_lex_md}."""
    analise = _analise(ctx, ler_sei=ler_sei)
    # Análise DISCURSIVA (onde+por quê, ancorada no trecho real do SEI). Default ligado; degrada honesto
    # se o LLM cair (achado fica só com a obs determinística). JFN_LEX_DISCURSIVO=0 desliga.
    if os.environ.get("JFN_LEX_DISCURSIVO", "1") == "1" and any(a.get("trecho") for a in analise.get("achados", [])):
        try:
            analise["achados"] = analise_discursiva(analise["achados"])
        except Exception as exc:
            logger.warning("análise discursiva (LLM) caiu — achados ficam só com a obs determinística: %s", exc)
    n_lidos = sum(1 for l in analise["leituras"] if l.get("lido"))
    out = {"ok": True, "grau": analise["rotulo"], "n_indicios": len(analise["achados"]),
           "n_sei": len(analise["sei"]), "n_sei_lidos": n_lidos, "path_lex_pdf": "", "path_lex_md": ""}
    if salvar:
        base = f"parecer_lex_{_slug(ctx.get('nome','')) or so_digitos(ctx.get('cnpj',''))}_{ctx.get('data','')}"
        md_path = _REPORTS / f"{base}.md"
        md_path.write_text(parecer_md(ctx, analise), encoding="utf-8")
        out["path_lex_md"] = str(md_path)
        try:
            out["path_lex_pdf"] = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"), analise)
        except Exception as exc:  # noqa: BLE001
            out["_pdf_erro"] = str(exc)[:160]
    return out


