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

import os
import re
import time
from pathlib import Path

from fpdf.enums import XPos, YPos

from compliance_agent.reporting.inteligencia import (
    _REPORTS, _mc, _registrar_fonte, _render_parecer_pdf, _slug, _termos_significativos,
    troca_controle_societaria, fmt_cnpj, moeda, so_digitos,
)

# Leitura da íntegra do SEI: liga/desliga, quantos processos ler e orçamento de tempo (s).
_LER_SEI = os.environ.get("JFN_LEX_LER_SEI", "1") != "0"
_MAX_SEI = int(os.environ.get("JFN_LEX_MAX_SEI", "3"))
_SEI_BUDGET = float(os.environ.get("JFN_LEX_SEI_BUDGET", "120"))

# Red flags (resumo operacional; detalhe em docs/LEX-BASE-JURIDICA.md)
_RF = {
    "R2": ("Fracionamento de despesa", "Art. 75 §1º Lei 14.133/2021; Art. 23 §§1º-5º Lei 8.666/93"),
    "R3": ("Pesquisa de preços frágil / possível sobrepreço", "Art. 23 Lei 14.133; Acórdão 1875/2021-TCU (cesta de preços)"),
    "R4": ("Sobrepreço / superfaturamento (valores fora de referência)", "Art. 11 III Lei 14.133; Acórdão 2622/2013-TCU (BDI)"),
    "R5": ("Inexigibilidade/dispensa possivelmente indevida", "Art. 74 Lei 14.133 / Art. 25 Lei 8.666; art. 337-E CP"),
    "R6": ("Alteração de controle societário após receita pública relevante", "Art. 14 Lei 14.133/2021 (idoneidade); art. 11 Lei 8.429/92; ACFE — change-of-control/nominee"),
    "R7": ("Restrição de competitividade", "Art. 9º I Lei 14.133; Art. 3º §1º Lei 8.666"),
    "R8": ("Concentração de fornecedor / risco de captura (bid rigging)", "Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE"),
    "R9": ("Aditivos sucessivos acima dos limites", "Arts. 125-126 Lei 14.133; Art. 65 §1º Lei 8.666"),
    "R10": ("Liquidação irregular / pagamento atípico (estornos)", "Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38"),
    "R11": ("Atividade-fim (CNAE) incompatível com o objeto contratado", "Arts. 62-63 Lei 14.133 (qualificação técnica); art. 337-F CP; ACFE — shell company"),
    "R12": ("Planejamento de fachada (DFD/ETP/TR genéricos)", "Art. 5º e Art. 18 Lei 14.133"),
    # Investigação de Due Diligence (fachada/laranja) — motor investigacao_dd; detalhe na seção II-E.
    "DD/H-END-RESID": ("Sede em endereço de natureza residencial", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-END-EXISTE": ("Endereço não confirmado fisicamente (geocodificação)", "art. 337-F CP"),
    "DD/H-COEND": ("Outros fornecedores do Estado na mesma sede", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-CAPITAL": ("Capital social ínfimo frente ao recebido", "art. 11 Lei 8.429/92; Art. 69 Lei 14.133"),
    "DD/H-RECENTE": ("Empresa recém-aberta antes do 1º recebimento", "art. 337-F CP"),
    "DD/H-SITUACAO": ("Situação cadastral irregular na Receita", "Art. 14 Lei 14.133; Art. 87 Lei 8.666/93"),
    "DD/H-PORTE": ("Volume recebido acima do teto do porte declarado", "LC 123/2006; Art. 4º Lei 14.133"),
    "DD/H-SOCIO-UNICO": ("Sócio único com sinais de fachada", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-PEP": ("Sócio politicamente exposto (PEP) — relação política", "Art. 9º Lei 14.133; Lei 12.813/13; art. 11 Lei 8.429/92"),
    "DD/H-BENEFICIO": ("Beneficiário de programa social de subsistência (laranja)", "art. 337-F CP; art. 11 Lei 8.429/92"),
}


# Anatomia do achado (modelo TCU/ISSAI/CGU — ver docs/PESQUISA-DIREITO-ADMIN-CGE.md e
# docs/PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md): critério × condição → causa → efeito, com evidência e
# recomendação. Causa/efeito/recomendação por red flag. Base citável (doutrina/improbidade/controle/RJ) no 2º doc.

# Serviços CONTÍNUOS (Lei 14.133 art. 6º XV; contratos de até 10 anos, arts. 106-107): pluralidade de contratos
# por órgão é NORMAL e NÃO é fracionamento. Usado p/ calibrar o red flag R2 (fracionamento × serviço contínuo).
_SERV_CONTINUO_KW = (
    "limpeza", "conserva", "higieniz", "asseio", "zeladoria", "vigilanc", "vigilânc", "seguranca patrimon",
    "segurança patrimon", "manutenc", "manutenç", "mao de obra", "mão de obra", "mao-de-obra", "posto de trabalho",
    "postos de trabalho", "apoio administrativo", "apoio operacional", "recepc", "recepç", "copeir", "brigad",
    "facilit", "terceiriz", "servico continuad", "serviço continuad", "servicos continu", "serviços contínu",
    "jardinagem", "portaria", "dedetiz", "transporte", "lavanderia", "nutric", "alimentac", "alimentaç",
)


def _eh_servico_continuo(objetos) -> bool:
    """True se os objetos contratuais indicam serviço CONTÍNUO (calibra o R2: não acusar fracionamento)."""
    txt = " ".join((o or "") for o in objetos).lower()
    return any(k in txt for k in _SERV_CONTINUO_KW)


# Classificação grosseira de "ramo/natureza" do objeto — núcleo do teste de fracionamento (mesma natureza).
_RAMOS = {
    "limpeza/conservação": ("limpeza", "conserva", "higieniz", "asseio", "zeladoria", "jardinagem", "dedetiz"),
    "vigilância/segurança": ("vigilanc", "vigilânc", "seguranca", "segurança", "portaria", "brigad"),
    "manutenção/reparo": ("manutenc", "manutenç", "reparo", "reforma", "predial"),
    "obras/engenharia": ("obra", "engenharia", "construç", "construc", "paviment", "infraestrutura"),
    "informática/TI": ("informat", "software", "computad", "notebook", "licenç", "tecnologia da inf"),
    "veículos/transporte": ("veicul", "frota", "transporte", "combustiv", "locaç de veic", "locacao de veic"),
    "material/insumos": ("material", "insumo", "aquisic", "aquisiç", "gênero", "genero", "aliment", "medicament"),
    "mão de obra/apoio": ("mao de obra", "mão de obra", "apoio administrativo", "apoio operacional",
                          "terceiriz", "posto de trabalho", "recepc", "recepç", "copeir"),
    "saúde/serviços médicos": ("hospital", "médic", "medic", "saude", "saúde", "leito", "exame"),
}


def _ramo_objeto(obj) -> str:
    """Natureza grosseira do objeto (p/ agrupar 'mesma natureza' no teste de fracionamento)."""
    t = (obj or "").lower()
    for ramo, kws in _RAMOS.items():
        if any(k in t for k in kws):
            return ramo
    palavras = [w for w in re.findall(r"[a-zçãõáéíóúâêô]+", t) if len(w) > 4][:2]
    return " ".join(palavras) or "objeto"
_MATRIZ = {
    "R2": ("possível divisão da despesa para fugir da modalidade/teto de dispensa",
           "elisão do dever de licitar; restrição à competição e risco de sobrepreço",
           "consolidar a demanda e licitar; apurar o planejamento (DFD/ETP)"),
    "R3": ("instrução deficiente do valor estimado (sem cesta de preços)",
           "risco de sobrepreço não detectado na contratação",
           "exigir pesquisa/cesta de preços (Acórdão 1875/2021-TCU)"),
    "R4": ("ausência de referência de mercado / BDI fora de parâmetro",
           "potencial dano ao erário por preço acima do mercado",
           "recompor preços e, se confirmado, glosar a diferença"),
    "R5": ("enquadramento possivelmente indevido de contratação direta",
           "afastamento da licitação sem amparo legal robusto",
           "verificar a fundamentação (art. 74/75 Lei 14.133); se indevida, anular"),
    "R6": ("controle/administração alterado após a empresa já receber vulto do Estado",
           "possível sucessão/interposição de pessoas (laranja) ou aquisição de empresa 'com contratos'",
           "levantar o histórico de controle (QSA pretérito) e cotejar a troca com a escalada de pagamentos"),
    "R7": ("especificação/habilitação restritiva ou direcionada",
           "redução da competitividade; possível direcionamento",
           "revisar o edital; admitir 'ou equivalente' (art. 9º Lei 14.133)"),
    "R8": ("baixa rotatividade/captura de fornecedor por um órgão",
           "risco de cartel/sobrepreço e dependência do prestador",
           "ampliar a competição; cruzar sócios/endereços dos licitantes"),
    "R9": ("execução além do valor contratado (aditivos sucessivos)",
           "elisão do limite de aditivo (25%/50%) e burla à licitação",
           "auditar os aditivos e os limites (arts. 125-126 Lei 14.133)"),
    "R10": ("falha de liquidação/regularização (estornos, OB R$ 0,00)",
            "risco de pagamento sem liquidação regular",
            "conferir ateste e NL (arts. 62-63 Lei 4.320/64)"),
    "R11": ("atividade econômica de registro (CNAE) diversa do objeto efetivamente contratado",
            "habilitação técnica frágil / empresa de prateleira ou fachada para fim diverso",
            "exigir comprovação de qualificação técnica para o objeto (arts. 62-63 Lei 14.133); "
            "verificar adequação do CNAE e a aptidão operacional real"),
    "R12": ("planejamento de fachada (DFD/ETP/TR genéricos) ou crescimento sem lastro",
            "contratação sem planejamento real; sobre/subdimensionamento",
            "exigir ETP robusto e justificativa da demanda (art. 18 Lei 14.133)"),
}


def _fmt_proc(s: str) -> str:
    """Encurta nº de processo concatenado (a base TCE-RJ às vezes junta vários numa célula)."""
    s = (s or "").strip()
    partes = [p.strip() for p in s.split(",") if p.strip()]
    if len(partes) <= 1:
        return s or "—"
    return f"{partes[0]} (+{len(partes)-1})"


def _anatomia(a: dict) -> dict:
    """Decompõe um indício na anatomia do achado de auditoria (critério/condição/causa/efeito/recomendação)."""
    nome, criterio = _RF.get(a["rf"], (a["rf"], "—"))
    causa, efeito, recom = _MATRIZ.get(a["rf"], ("a apurar", "a apurar", "diligência documental"))
    return {"rf": a["rf"], "nome": nome, "criterio": criterio, "condicao": a["obs"],
            "causa": causa, "efeito": efeito, "recomendacao": recom, "grav": a["grav"]}


def _sei_do_fornecedor(cnpj: str) -> list[dict]:
    try:
        from compliance_agent.correlacao_sei import processos_de_fornecedor
        return processos_de_fornecedor(cnpj)
    except Exception:
        return []


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


# ── Leitura da ÍNTEGRA dos processos SEI ──────────────────────────────────────

def _run_coro(factory):
    """Roda uma corrotina com segurança, mesmo dentro de um event loop (FastAPI)."""
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            return ex.submit(lambda: asyncio.run(factory())).result()
    return asyncio.run(factory())


def _dossie_sei(numero: str) -> dict | None:
    """DOSSIÊ consolidado do processo (`data/sei_trees/` via tabela `sei_arvore`) — o que o sweep já
    destilou (ficha+cadeia+pagamentos OB). Barato, sem WAF e MENOS TOKEN que a íntegra crua → preferido.
    None se ainda não houver dossiê (cai p/ leitura ao vivo)."""
    try:
        import sqlite3
        from compliance_agent.correlacao_sei import _DB
        if not _DB.exists():
            return None
        con = sqlite3.connect(_DB)
        con.execute("PRAGMA busy_timeout=10000")
        try:
            row = con.execute(
                "SELECT txt_path, nivel_risco FROM sei_arvore "
                "WHERE numero_sei = ? OR numero_sei LIKE '%'||?||'%' "
                "ORDER BY length(numero_sei) LIMIT 1",
                (numero.strip(), numero.strip())).fetchone()
        finally:
            con.close()
        if not row or not row[0]:
            return None
        p = Path(row[0])
        if not p.exists():
            return None
        return {"numero": numero, "texto": p.read_text(encoding="utf-8"),
                "conteudo_documentos": [], "_fonte": "dossie_sei", "nivel_risco": row[1] or ""}
    except Exception:  # noqa: BLE001
        return None


def _ler_integra_sei(numero: str) -> dict:
    """Íntegra de UM processo SEI. PREFERE o dossiê consolidado (sweep já destilou — barato/sem WAF/menos
    token); só lê AO VIVO (Chrome 9222 + OCR; fallback portal) se ainda não houver dossiê. Cacheia 24h."""
    _d = _dossie_sei(numero)
    if _d:
        return _d
    res = {}
    try:
        from compliance_agent.collectors import sei_cdp
        # porta ÚNICA → reader itkava/ITERJ (sem captcha). Ver sei_cdp.ler_processo_sei.
        res = _run_coro(lambda: sei_cdp.ler_processo_sei(numero, usar_cache=True)) or {}
        if not res.get("erro") and (res.get("texto") or res.get("conteudo_documentos")):
            return res
    except Exception as exc:  # noqa: BLE001
        res = {"numero": numero, "erro": f"cdp: {str(exc)[:120]}"}
    # fallback: portal público httpx (metadados + documentos)
    try:
        from compliance_agent.collectors import sei_portal
        meta = _run_coro(lambda: sei_portal.buscar_processo(numero, usar_cache=True)) or {}
        if not meta.get("erro"):
            meta.setdefault("texto", "")
            meta.setdefault("conteudo_documentos", [])
            return meta
    except Exception:
        pass
    return res or {"numero": numero, "erro": "indisponível"}


_WAF_MARCADORES = ("web page blocked", "url you requested has been blocked", "attack id",
                   "página não encontrada", "pagina nao encontrada", "acesso negado")


def _bloqueio_rede(integra: dict) -> str:
    """Detecta página de WAF/erro (o IP da VM é barrado no SEI-RJ). Retorna motivo ou ''."""
    amostra = ((integra.get("texto", "") or "") + " " + (integra.get("title", "") or "")).lower()
    if any(m in amostra for m in _WAF_MARCADORES):
        return ("bloqueio de rede (WAF) — o IP de saída da VM (GCP) não é autorizado pelo SEI-RJ; "
                "ler de um IP permitido/proxy ou preencher o cache externamente")
    return ""


_INTERFACE_SEI = ("controle de prazos", "processos recebidos", "processos gerados", "acompanhamento especial",
                  "base de conhecimento", "blocos de assinatura", "registros - 1 a", "menu principal",
                  "controle de processos", "iniciar processo", "retorno programado")


def _eh_interface_sei(integra: dict) -> str:
    """Detecta a TELA/MENU do SEI (desktop após login) — NÃO é o inteiro teor de um processo. Foi a falha
    flagrada no Loop 1: a leitura trazia o menu ('Controle de Prazos', 'Processos recebidos (N registros)')
    e o parecer 'analisava' o menu. Conservador: ≥2 marcadores de UI co-ocorrendo."""
    amostra = ((integra.get("texto", "") or "") + " " + (integra.get("title", "") or "")).lower()
    if sum(1 for m in _INTERFACE_SEI if m in amostra) >= 2:
        return "tela/menu do SEI (não é o inteiro teor do processo) — a leitura não chegou ao documento"
    return ""


def _texto_integra(integra: dict) -> str:
    if _bloqueio_rede(integra):
        return ""  # página de bloqueio (WAF) não é conteúdo de processo
    if _eh_interface_sei(integra):
        return ""  # tela/menu do SEI não é conteúdo de processo (não vira achado/análise)
    txt = integra.get("texto", "") or ""
    for d in integra.get("conteudo_documentos", []) or []:
        txt += "\n" + (d.get("conteudo", "") or "")
    return txt


def _modalidade(low: str) -> str:
    for chave, rotulo in [
        ("pregão eletrônico", "Pregão eletrônico"), ("pregão", "Pregão"),
        ("concorrência", "Concorrência"), ("inexigibilidade", "Inexigibilidade"),
        ("dispensa de licitação", "Dispensa de licitação"), ("dispensa", "Dispensa"),
        ("credenciamento", "Credenciamento"), ("adesão", "Adesão a ata (carona)"),
        ("registro de preços", "Registro de preços"),
    ]:
        if chave in low:
            return rotulo
    return "—"


def _trecho(txt: str, gatilhos, janela: int = 340) -> str:
    """Excerpt em torno do 1º gatilho encontrado no texto real — para o parecer CITAR 'onde' (o trecho do
    documento que disparou o indício). Limpo p/ markdown. Vazio se nenhum gatilho aparece."""
    low = (txt or "").lower()
    pos = -1
    for g in gatilhos:
        p = low.find(g)
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return ""
    ini = max(0, pos - janela // 4)
    fim = min(len(txt), pos + janela)
    ex = re.sub(r"\s+", " ", txt[ini:fim].replace("|", "/")).strip()
    return ("…" if ini > 0 else "") + ex + ("…" if fim < len(txt) else "")


def _analisar_conteudo_sei(integra: dict) -> tuple[list, dict]:
    """Red flags a partir do TEXTO REAL do processo. Retorna (achados, resumo)."""
    txt = _texto_integra(integra)
    low = txt.lower()
    achados: list[dict] = []
    modal = _modalidade(low)

    objeto = ""
    m = re.search(r"objeto[:\s]+([A-Z0-9À-Ú][^\n.;]{15,180})", txt, re.I)
    if m:
        objeto = m.group(1).strip()

    if txt.strip():
        # R5 — contratação direta sem prova robusta de exclusividade/singularidade
        if "dispensa" in low or "inexigibil" in low:
            tem_just = any(k in low for k in [
                "exclusividade", "singular", "notória especialização", "notoria especializacao",
                "inviabilidade de competição", "inviabilidade de competicao", "art. 74", "artigo 74",
            ])
            achados.append({"rf": "R5", "grav": 2 if tem_just else 3,
                            "obs": f"O processo registra **{modal if modal != '—' else 'contratação direta'}**" +
                                   ("." if tem_just else
                                    " — no texto lido **não localizei** prova robusta de exclusividade/singularidade "
                                    "(art. 74 Lei 14.133/Art. 25 Lei 8.666).")})
        # R3 — sem pesquisa/cesta de preços visível
        if any(k in low for k in ["edital", "contrato", "termo de referência", "termo de referencia"]) and \
           not any(k in low for k in ["pesquisa de preç", "cesta de preç", "mapa de preç", "cotaç", "orçament"]):
            achados.append({"rf": "R3", "grav": 2,
                            "obs": "No texto lido **não localizei** pesquisa/cesta de preços (Acórdão 1875/2021-TCU) — "
                                   "verificar a instrução do ETP/valor estimado."})
        # R9 — aditivos
        n_adit = low.count("termo aditivo") + low.count("aditamento")
        if n_adit >= 2:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"{n_adit} menções a termo aditivo/aditamento no processo — verificar se a soma "
                                   "respeita os limites de 25%/50% (arts. 125-126 Lei 14.133)."})
        # R7 — restrição/direcionamento por especificação
        if any(k in low for k in ["atestado de capacidade", "marca", "modelo "]) and "ou equivalente" not in low:
            achados.append({"rf": "R7", "grav": 2,
                            "obs": "Há exigências de habilitação/especificação (atestado/marca) sem a cláusula "
                                   "'ou equivalente' visível — verificar restrição à competitividade (art. 9º Lei 14.133)."})

    # B (qualidade): anexa o TRECHO real do documento + o nº do processo a cada achado, para o parecer
    # citar ONDE (o trecho que disparou o indício). Sem trecho → fica vazio (não inventa).
    _gat = {"R5": ["dispensa", "inexigibil"],
            "R3": ["edital", "termo de referência", "termo de referencia", "contrato"],
            "R9": ["termo aditivo", "aditamento"],
            "R7": ["atestado de capacidade", "marca", "modelo "]}
    for a in achados:
        a["numero_proc"] = integra.get("numero", "")
        a["trecho"] = _trecho(txt, _gat.get(a["rf"], []))

    resumo = {
        "numero": integra.get("numero", ""),
        "objeto": objeto,
        "modalidade": modal,
        "tipo": integra.get("tipo", "") or integra.get("title", ""),
        "n_docs": len(integra.get("documentos", []) or []),
        "n_docs_lidos": len(integra.get("conteudo_documentos", []) or []),
        "cnpjs": (integra.get("cnpjs", []) or [])[:8],
        "valores": (integra.get("valores", []) or [])[:8],
        "url": integra.get("url", ""),
        "lido": bool(txt.strip()),
        "de_cache": bool(integra.get("_de_cache") or integra.get("_cached_at")),
        "erro": integra.get("erro", "") or _bloqueio_rede(integra) or _eh_interface_sei(integra),
    }
    return achados, resumo


_SYS_DISCURSIVO = (
    "Voce e auditor de controle externo (TCU/TCE-RJ) redigindo um parecer. Para cada indicio, com base "
    "ESTRITAMENTE no TRECHO real do documento, escreva 2 a 4 frases de analise: (a) ONDE no documento o "
    "problema aparece (parafraseie/cite o trecho) e (b) POR QUE e um indicio — o MECANISMO concreto (ex.: "
    "'a exigencia de atestado X restringe porque elimina concorrentes que nao tem Y'). NAO invente fato "
    "fora do trecho; se o trecho nao bastar, diga objetivamente o que precisaria conferir. Indicio, nunca "
    "acusacao. Responda SOMENTE JSON."
)


def _json_lex(texto: str):
    """Extrai JSON (lista/obj) de uma resposta de LLM, tolerante a cercas ```json e texto ao redor."""
    import json
    t = (texto or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        return None


def analise_discursiva(achados: list[dict], gerar=None) -> list[dict]:
    """Para cada achado COM trecho (= SEI lido), gera uma 'analise' DISCURSIVA (onde + por que, mecanismo)
    ancorada no texto real, numa UNICA chamada LLM (lote). Robusto: LLM caido/sem trecho → achado segue
    com a obs deterministica (degrada honesto, nao inventa). `gerar` injetavel p/ teste."""
    com = [(i, a) for i, a in enumerate(achados) if (a.get("trecho") or "").strip()]
    if not com:
        return achados
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync
            gerar = lambda p, s="": gerar_sync(p, s, timeout=45.0)  # noqa: E731
        except Exception:
            return achados
    itens = "\n\n".join(
        f'{j}. INDICIO {a["rf"]} ({_RF.get(a["rf"], (a["rf"], ""))[0]}); processo {a.get("numero_proc", "")}\n'
        f'   TRECHO: "{(a.get("trecho") or "")[:600]}"'
        for j, (_i, a) in enumerate(com)
    )
    prompt = ('Analise cada indicio abaixo. Responda SOMENTE JSON: lista de '
              '{"i":<indice>,"analise":"2 a 4 frases citando o trecho e explicando o mecanismo"}.\n\n' + itens)
    try:
        d = _json_lex(gerar(prompt, _SYS_DISCURSIVO))
    except Exception:
        d = None
    por: dict = {}
    if isinstance(d, list):
        for x in d:
            try:
                por[int(x["i"])] = str(x.get("analise", "")).strip()
            except Exception:
                pass
    for j, (_i, a) in enumerate(com):
        if por.get(j):
            a["analise"] = por[j]
    return achados


def analisar_texto_edital(texto: str, numero: str = "", url: str = "") -> dict:
    """API pública (Onda 2c): roda os red flags R3/R5/R7/R9/R12 sobre o texto de um
    edital/TR (ex.: baixado do PNCP) reusando o mesmo motor do SEI (`_analisar_conteudo_sei`).

    Retorna {achados:[{rf,grav,obs}], resumo:{...}, lido:bool}. Honesto: indício, nunca
    acusação; se o texto vier vazio (download/extração falhou), `lido=False` e achados=[]."""
    integra = {"texto": texto or "", "numero": numero, "url": url,
               "conteudo_documentos": [], "documentos": []}
    achados, resumo = _analisar_conteudo_sei(integra)
    return {"achados": _merge_achados(achados), "resumo": resumo, "lido": bool((texto or "").strip())}


def _merge_achados(lst: list[dict]) -> list[dict]:
    """Funde achados por red flag (mantém maior gravidade, concatena observações)."""
    por: dict = {}
    for a in lst:
        k = a["rf"]
        if k not in por:
            por[k] = dict(a)
        else:
            if a["grav"] > por[k]["grav"]:
                por[k]["grav"] = a["grav"]
            if a["obs"] not in por[k]["obs"]:
                por[k]["obs"] += " " + a["obs"]
    return sorted(por.values(), key=lambda x: -x["grav"])


# ── Análise dos contratos/compras do TCE-RJ (Dados Abertos — não depende do SEI) ──

def _analisar_contratos_tcerj(itens: list[dict]) -> tuple[list, dict]:
    """Red flags a partir dos contratos/compras diretas oficiais do TCE-RJ. Retorna (achados, resumo).

    Esta é a fonte que CONTORNA o bloqueio de WAF do SEI: traz objeto, critério de julgamento, valores e —
    sobretudo — o **EnquadramentoLegal** das compras diretas (dispensa/inexigibilidade) direto da API pública."""
    achados: list[dict] = []
    contratos = [i for i in itens if i.get("_tipo") == "contrato"]
    compras = [i for i in itens if i.get("_tipo") == "compra_direta"]

    soma_contr = sum(c.get("valor_contrato") or 0 for c in contratos)
    soma_compras = sum(c.get("valor") or 0 for c in compras)

    # R5 — contratações diretas (dispensa/inexigibilidade) registradas no TCE-RJ
    diretas = [c for c in compras if any(
        k in ((c.get("afastamento") or "") + " " + (c.get("enquadramento_legal") or "")).lower()
        for k in ["dispensa", "inexigibil"])]
    if diretas:
        total_d = sum(c.get("valor") or 0 for c in diretas)
        grav = 3 if len(diretas) >= 5 else 2
        achados.append({"rf": "R5", "grav": grav,
                        "obs": f"O TCE-RJ registra **{len(diretas)} contratação(ões) direta(s)** (dispensa/"
                               f"inexigibilidade) deste fornecedor, somando R$ {moeda(total_d)} — verificar o "
                               "enquadramento legal e a regularidade da fundamentação (art. 74/75 Lei 14.133/Art. 24-25 Lei 8.666)."})

    # R2 — FRACIONAMENTO (teste TCU, Ac. 1.620/2010-Pleno): múltiplas DISPENSAS de objeto de MESMA NATUREZA, na
    # MESMA unidade gestora, no MESMO exercício, cada uma sob o teto de dispensa, somando ACIMA dele (art. 75 §1º
    # Lei 14.133). NÃO é fracionamento: várias OBs de um mesmo contrato (parcelas mensais/medição/pagamento parcial),
    # nem atuar em vários órgãos, nem a pluralidade de contratos de serviço contínuo. Agrupa por (ano, UG, ramo).
    from collections import defaultdict
    _TETO_DISP = 59906.02  # dispensa por valor — art. 75, II, Lei 14.133 (serviços/compras), valor de referência
    grupos = defaultdict(list)
    for c in diretas:
        grupos[(c.get("ano_processo"), (c.get("unidade") or "")[:40], _ramo_objeto(c.get("objeto")))].append(c)
    candidatos = []
    for (ano, unid, ramo), itens in grupos.items():
        sob_teto = [i for i in itens if 0 < (i.get("valor") or 0) <= _TETO_DISP]
        soma = sum(i.get("valor") or 0 for i in itens)
        if len(sob_teto) >= 2 and soma > _TETO_DISP:   # ≥2 dispensas da mesma natureza que, somadas, furam o teto
            candidatos.append((ano, unid, ramo, len(sob_teto), soma))
    if candidatos:
        ano, unid, ramo, n, soma = max(candidatos, key=lambda x: x[4])
        achados.append({"rf": "R2", "grav": 3,
                        "obs": f"**{n} dispensas** de objeto de mesma natureza (**{ramo}**) na unidade **{unid}** no "
                               f"exercício {ano}, cada uma sob o teto de dispensa (≈R$ {moeda(_TETO_DISP)}) mas somando "
                               f"R$ {moeda(soma)} — indício de **FRACIONAMENTO** (substituição da licitação obrigatória "
                               "por múltiplas dispensas do mesmo objeto; art. 75 §1º Lei 14.133; Ac. 1.620/2010-TCU-"
                               "Pleno). Diligência: confirmar identidade de objeto/natureza e somatório no exercício."})
    elif diretas:
        # há dispensas, mas SEM o padrão de fracionamento — registrar a leitura correta (evita falso achado)
        achados.append({"rf": "R2", "grav": 1,
                        "obs": "As contratações diretas registradas **não** apresentam o padrão de fracionamento "
                               "(múltiplas dispensas do MESMO objeto/natureza, na mesma unidade e exercício, somando "
                               "acima do teto). Pluralidade de OBs (parcelas mensais/medição de um contrato) e atuação "
                               "em vários órgãos **não** caracterizam fracionamento — verificar apenas o enquadramento "
                               "de cada dispensa (art. 75 Lei 14.133)."})

    # R9 — execução acima do contratado (valor pago > contrato + 25%, limite de aditivo)
    for c in contratos:
        vc, vp = c.get("valor_contrato") or 0, c.get("valor_pago") or 0
        if vc > 0 and vp > vc * 1.25:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"Contrato {c.get('processo')}: pago R$ {moeda(vp)} sobre valor contratado "
                                   f"R$ {moeda(vc)} (+{((vp-vc)/vc*100):.0f}%) — verificar aditivos e o limite de "
                                   "25%/50% (arts. 125-126 Lei 14.133)."})
            break  # um exemplo basta para o indício

    resumo = {
        "n_contratos": len(contratos), "soma_contratos": soma_contr,
        "n_compras_diretas": len(compras), "soma_compras": soma_compras,
        "n_diretas_dispensa": len(diretas),
        "contratos": contratos[:15], "compras": compras[:15],
    }
    return achados, resumo


# ── Detecção data-driven (carteira de pagamentos) ─────────────────────────────

def _detectar(ctx: dict) -> list[dict]:
    """Indícios a partir dos dados financeiros (OBs). Cada item: {rf, obs, grav(1-5)}."""
    p = ctx.get("pagamentos") or {}
    achados = []
    if not p.get("tem_dados"):
        return achados
    hhi = p.get("hhi", {})
    top = hhi.get("top_share", 0) or 0
    org_top = next(iter(p.get("por_orgao_geral", {})), "—")
    if top >= 60:
        achados.append({"rf": "R8", "grav": 4,
                        "obs": f"{top:.1f}% do valor pago concentrado em um único órgão (**{org_top}**) — "
                               "concentração extrema para um prestador de serviços."})
    elif top >= 40:
        achados.append({"rf": "R8", "grav": 3, "obs": f"Concentração relevante ({top:.1f}%) em **{org_top}**."})
    anos = p.get("anos", [])
    if len(anos) >= 2:
        t0 = p["por_ano"][anos[0]]["total"] or 0
        t1 = p["por_ano"][anos[-1]]["total"] or 0
        if t0 > 0 and t1 > t0 * 3:
            achados.append({"rf": "R12", "grav": 3,
                            "obs": f"Crescimento abrupto dos pagamentos de R$ {moeda(t0)} ({anos[0]}) para "
                                   f"R$ {moeda(t1)} ({anos[-1]}) — {((t1-t0)/t0*100):+.0f}%."})
    zeros = sum(1 for a in anos for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
    if zeros >= 3:
        achados.append({"rf": "R10", "grav": 2,
                        "obs": f"{zeros} ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação."})
    # (Removido o antigo R2 baseado em nº de OBs/órgãos: pluralidade de OBs = parcelas de um contrato (mensal/
    #  medição/parcial) e atuação em vários órgãos NÃO são fracionamento. O fracionamento real é testado sobre as
    #  DISPENSAS do TCE-RJ por (ano, UG, mesma natureza) em _analisar_contratos_tcerj.)
    if ctx.get("risco") == "ALTO":
        achados.append({"rf": "R8", "grav": 2, "obs": f"Rating de risco corporativo ALTO (score {ctx.get('score')}/100) — diligência sobre quadro societário/vínculos."})
    return achados


def _grau(achados: list) -> tuple:
    """(emoji, rótulo, justificativa) conforme convergência + gravidade dos indícios."""
    n = len(achados)
    gmax = max((a["grav"] for a in achados), default=0)
    if n >= 3 and gmax >= 4:
        return "🔴", "VERMELHO", "convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo"
    if n >= 1 and (gmax >= 4 or n >= 2):
        return "🟡", "AMARELO", "indícios pontuais a esclarecer mediante diligência"
    if n >= 1:
        return "🟡", "AMARELO", "indício isolado de baixa gravidade"
    return "🟢", "VERDE", "sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida"


# ── Passo EXCULPATÓRIO (defesa contra si mesmo) ───────────────────────────────────────────────────
# Para CADA indício, a explicação inocente mais plausível + se os DADOS a refutam. Achado cuja própria
# defesa NÃO é refutada pelos dados (a explicação inocente sobrevive) → rebaixado a "monitoramento" (não
# representação). Protege a credibilidade: indício ≠ acusação; presunção de regularidade. Por família de RF.
_EXCULPATORIO = {
    "R2": "Em serviços contínuos, dispensas emergenciais sucessivas podem cobrir o intervalo entre o fim de "
          "um contrato e a conclusão de novo pregão — fracionamento só se confirma com mesmo objeto/local sob o teto.",
    "R3": "A pesquisa de preços pode existir no processo SEI e apenas não ter sido lida nesta varredura "
          "(documento ausente do recorte ≠ ausência do documento).",
    "R4": "O preço pode refletir composição de custo legítima (BDI, encargos, logística regional) — só há "
          "sobrepreço frente a uma referência de mercado efetivamente apurada.",
    "R5": "A contratação direta pode ter amparo legal robusto e justificado (urgência real documentada, "
          "exclusividade de fato do objeto/marca) — afastamento da licitação nem sempre é irregular.",
    "R6": "A troca de controle societário pode ser sucessão empresarial legítima (herança, venda regular) "
          "sem qualquer interposição de pessoas.",
    "R7": "A especificação restritiva pode decorrer de exigência técnica real do objeto, não de direcionamento.",
    "R8": "A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um "
          "ramo de poucos players (ex.: engenharia/consórcio legítimo), sem qualquer conluio.",
    "R9": "Aditivos podem decorrer de fato superveniente legítimo dentro dos limites legais (25%/50%).",
    "R10": "OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular.",
    "R11": "O CNAE pode estar desatualizado no cadastro sem que a empresa careça de aptidão operacional real "
           "para o objeto.",
    "R12": "DFD/ETP genéricos podem refletir padronização administrativa, não ausência de planejamento real.",
    "DD": "Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em "
          "microempresas legítimas e, sozinhos, não caracterizam fachada/laranja.",
}


def _fam_exculpatorio(rf: str) -> str:
    return "DD" if str(rf).startswith("DD/") else str(rf)


def _exculpatorio(achados: list) -> list[dict]:
    """Para cada achado, gera a explicação inocente mais plausível e avalia se os DADOS a refutam.

    A defesa é considerada REFUTADA (achado sobrevive → representação) quando o próprio indício já traz
    convergência/cruzamento confirmatório: gravidade alta (≥3) OU achado de conluio COM sócio em comum.
    Caso contrário a defesa SOBREVIVE → o achado é rebaixado a 'monitoramento' (sobrevive=True). Degrada
    honesto: qualquer falha devolve o achado como representação (não silencia indício). Honestidade: a
    dúvida sobre a economicidade favorece o gestor (presunção de regularidade)."""
    out = []
    for a in achados or []:
        try:
            rf = a.get("rf", "")
            defesa = _EXCULPATORIO.get(_fam_exculpatorio(rf), "Pode haver explicação administrativa regular para o fato.")
            grav = int(a.get("grav", 0) or 0)
            obs = (a.get("obs") or "").lower()
            socio_comum = "sócio" in obs and ("comum" in obs or "irmã" in obs or "compartilh" in obs)
            # Refuta a defesa quando há convergência/cruzamento: gravidade alta OU sócio em comum (cartel forte).
            refuta = grav >= 3 or socio_comum
            sobrevive = not refuta  # defesa sobrevive → achado fraco → monitoramento
            out.append({"rf": rf, "grav": grav, "defesa": defesa,
                        "refuta": ("os dados refutam a defesa (convergência/cruzamento confirmatório) — o "
                                   "indício sobrevive à própria defesa" if refuta else
                                   "os dados NÃO refutam a defesa — a explicação inocente é plausível e não foi "
                                   "afastada"),
                        "sobrevive": sobrevive,
                        "encaminhamento": "monitoramento" if sobrevive else "representação"})
        except Exception:
            out.append({"rf": a.get("rf", ""), "grav": int(a.get("grav", 0) or 0),
                        "defesa": "—", "refuta": "avaliação exculpatória indisponível",
                        "sobrevive": False, "encaminhamento": "representação"})
    return out


# ── Destinatário recomendado por TIPO/família de achado (enquadramento do playbook) ──────────────
# conluio/cartel → MP + CADE · débito/cautelar → TCE-RJ/TCU · improbidade/penal → MP · PAR anticorrupção → CGU/CGE.
_DESTINATARIO_FAMILIA = {
    # família → (rótulo do destinatário, base/motivo)
    "conluio":     ("MP-RJ + CADE", "conluio/cartel (bid rigging) — atuação simultânea (art. 36 Lei 12.529; art. 337-F CP)"),
    "debito":      ("TCE-RJ / TCU", "débito/medida cautelar — dano ao erário/sobrepreço/liquidação (jurisdição de contas)"),
    "improbidade": ("MP-RJ", "improbidade/penal — fracionamento, dispensa indevida, direcionamento (Lei 8.429; CP arts. 337-E ss.)"),
    "par":         ("CGU / CGE-RJ", "PAR anticorrupção — fachada/laranja/idoneidade (Lei 12.846; controle interno)"),
}
# RF → famílias de destinatário (um achado pode disparar mais de uma família).
_RF_DESTINATARIO = {
    "R2": ("improbidade",),
    "R3": ("debito",),
    "R4": ("debito",),
    "R5": ("improbidade",),
    "R6": ("improbidade", "par"),
    "R7": ("improbidade",),
    "R8": ("conluio",),
    "R9": ("debito",),
    "R10": ("debito",),
    "R11": ("improbidade", "par"),
    "R12": ("improbidade",),
    "DD": ("par", "improbidade"),
}


def _destinatarios(achados: list) -> list[dict]:
    """Destinatário(s) recomendado(s) derivado(s) das FAMÍLIAS dos achados presentes (sem duplicar).

    Cartel COM sócio em comum reforça 'conluio'. Degrada honesto: sem achado → lista vazia (presunção
    de regularidade, sem encaminhamento)."""
    fams: list[str] = []
    try:
        for a in achados or []:
            for f in _RF_DESTINATARIO.get(_fam_exculpatorio(a.get("rf", "")), ()):
                if f not in fams:
                    fams.append(f)
    except Exception:
        fams = []
    out = []
    for f in fams:
        rotulo, motivo = _DESTINATARIO_FAMILIA.get(f, (f, ""))
        out.append({"familia": f, "destinatario": rotulo, "motivo": motivo})
    return out


def _primeira_data_pag(p: dict) -> str:
    """Data do PRIMEIRO pagamento (menor `data` entre as linhas das OBs) em ISO, ou '' se indisponível.

    Usada pela investigação de fachada/laranja (H-RECENTE: empresa aberta pouco antes de receber)."""
    import datetime as _dt
    melhor = None
    for ano in (p.get("anos") or []):
        for ln in (p.get("por_ano", {}).get(ano, {}).get("linhas") or []):
            s = str(ln.get("data") or "").strip()
            if not s:
                continue
            d = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    d = _dt.datetime.strptime(s[:10], fmt).date()
                    break
                except ValueError:
                    continue
            if d and (melhor is None or d < melhor):
                melhor = d
    return melhor.isoformat() if melhor else ""


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
        except Exception:  # noqa: BLE001 — pacote/LLM degradam honesto; a DD básica permanece
            pass
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

    achados = _merge_achados(ach_dados + ach_doc + ach_tcerj + ach_cartel + ach_estrutural)
    emoji, rotulo, just = _grau(achados)
    exculpatorio = _exculpatorio(achados)
    destinatarios = _destinatarios(achados)
    return {"cnpj": cnpj, "sei": sei, "leituras": leituras, "achados": achados,
            "tem_leitura_doc": bool(ach_doc), "tcerj": resumo_tcerj, "cartel": cartel,
            "cruzado": cruzado, "investigacao": investigacao, "direcionamento": direcionamento,
            "pesquisa": pesquisa,
            "exculpatorio": exculpatorio, "destinatarios": destinatarios,
            "emoji": emoji, "rotulo": rotulo, "just": just}


def _analise_merito(ctx: dict, analise: dict) -> str:
    """Prosa de mérito (parecer raciocinado), adaptada aos dados — natureza, concentração, dispensas, síntese."""
    p = ctx.get("pagamentos") or {}
    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") or {}
    achados = analise.get("achados", [])
    continuo = _eh_servico_continuo([emp.get("cnae_principal"), emp.get("atividade"), ctx.get("nome")])
    total = p.get("total_geral", 0) or 0
    nob, norg = p.get("n_geral", 0), len(p.get("por_orgao_geral", {}))
    L = []
    try:
        from compliance_agent.lex_base_empirica import contexto_empirico_md
        _emp = contexto_empirico_md(ctx.get("cnpj"))
        if _emp:
            L.append(_emp)
    except Exception:
        pass
    natureza = ("prestadora de **serviços contínuos** (limpeza/conservação/vigilância/mão de obra)"
                if continuo else "fornecedora do Estado")
    L.append(
        f"Trata-se de empresa {natureza}, com exposição de **R$ {moeda(total)}** em {nob} ordens bancárias "
        f"junto a {norg} órgão(s) no período. " + (
            "Para esse segmento, a presença em múltiplos órgãos — cada um com contrato próprio, em regra por pregão "
            "e com vigência de até 10 anos (arts. 106-107 da Lei 14.133/2021) — é a **estrutura ordinária do "
            "mercado** e não evidencia, por si só, irregularidade." if continuo else
            "A pulverização entre órgãos, isoladamente, não indica irregularidade."))
    hhi = p.get("hhi", {})
    if hhi.get("top_share", 0):
        L.append(
            f"A concentração (HHI) é **{hhi.get('indice')}** ({hhi.get('nivel')}), com o maior órgão respondendo por "
            f"**{hhi.get('top_share')}%** do valor pago. " + (
                "Concentração elevada num único contratante, ainda que possa decorrer de mérito técnico, recomenda "
                "conferir a competitividade dos certames e a isonomia (art. 37 CF/88; art. 5º Lei 14.133)."
                if hhi.get("top_share", 0) >= 50 else
                "O grau é compatível com atuação difusa, sem alerta específico de captura."))
    tcerj = analise.get("tcerj") or {}
    if tcerj.get("n_diretas_dispensa"):
        L.append(
            f"O TCE-RJ registra **{tcerj.get('n_diretas_dispensa')} contratação(ões) por dispensa/inexigibilidade**. " + (
                "Em serviços contínuos, a dispensa emergencial costuma cobrir o intervalo entre o fim de um contrato e "
                "a conclusão de novo pregão — regular quando justificada e temporária. O exame deve focar a reiteração "
                "do **mesmo objeto/local** sob o teto, que aí sim configuraria fracionamento (art. 75 §1º Lei 14.133)."
                if continuo else
                "Cabe verificar o enquadramento legal de cada uma e eventual sucessão do mesmo objeto sob o teto."))
    graves = [a for a in achados if a.get("grav", 0) >= 3]
    L.append(
        (f"Em síntese, convergem **{len(achados)} indício(s)**, {len(graves)} de maior gravidade, sustentando a "
         f"classificação **{analise.get('rotulo')}**. " if achados
         else "Em síntese, não há indícios relevantes nos dados disponíveis. ") +
        "Reitere-se que os apontamentos são **indícios** sob **presunção de legitimidade** dos atos administrativos "
        "(o ônus de provar o vício recai sobre quem o invoca — Meirelles); a confirmação depende de diligência "
        "documental nos processos SEI (edital/TR, pesquisa de preços, atestos) e de contraditório. Este parecer **não** "
        "constitui juízo de irregularidade, improbidade ou crime.")
    return "\n\n".join(L)


_BADGE_STATUS = {"CONFIRMADO": "🔴 CONFIRMADO", "INDICIO": "🟡 INDÍCIO",
                 "AFASTADO": "🟢 AFASTADO", "INDISPONIVEL": "⚪ INDISPONÍVEL"}


def _secao_direcionamento(add, direc: dict | None) -> None:
    """§II-F — DIRECIONAMENTO (parecer LLM on-demand sobre o dossiê consolidado das árvores do fornecedor).
    SURFACE do veredito já computado (`tools.sei_direcionamento_llm`). Honesto: indício a verificar, nunca
    acusação; só aparece p/ os top-score efetivamente avaliados (senão a seção é omitida)."""
    if not direc or not (direc.get("grau") or direc.get("resumo")):
        return
    _badge = {"vermelho": "🔴 VERMELHO", "amarelo": "🟡 AMARELO", "verde": "🟢 VERDE",
              "indeterminado": "⚪ INDETERMINADO", "indisponivel": "⚪ INDISPONÍVEL"}
    grau = str(direc.get("grau") or "").lower()
    add("## II-F. DIRECIONAMENTO DE LICITAÇÃO (cérebro on-demand — indício a verificar)")
    add("")
    add("*Avaliação raciocinada (LLM) sobre o **dossiê consolidado** das árvores SEI deste fornecedor: "
        "exigências restritivas + cascata de desclassificações (Súmula TCU 263). Indício a apurar — "
        "presunção de legitimidade dos atos administrativos, NUNCA acusação.*")
    add("")
    add(f"**Grau de direcionamento:** {_badge.get(grau, grau.upper() or '—')} · "
        f"score de triagem {direc.get('score', 0)}/100"
        + (f" · _{direc.get('modelo')}_" if direc.get("modelo") else "")
        + (f" · avaliado {direc.get('avaliado_em')[:10]}" if direc.get("avaliado_em") else ""))
    add("")
    if direc.get("resumo"):
        add(f"> {direc['resumo']}")
        add("")
    if direc.get("raciocinio"):
        add(f"**Raciocínio:** {direc['raciocinio']}")
        add("")
    det = direc.get("detalhe") or {}
    ex = det.get("exigencias_restritivas") or []
    if ex:
        add("**Exigências apontadas como restritivas:**")
        for e in ex[:5]:
            por = (e.get("por_que_restringe") or "")[:160]
            jur = e.get("jurisprudencia") or "—"
            add(f"- {por} _(juris.: {jur})_")
            if e.get("trecho"):
                add(f"  - trecho: “{(e.get('trecho') or '')[:140]}”")
        add("")
    casc = det.get("cascata") or []
    if casc:
        add("**Cascata de julgamento (indício):**")
        add("")
        add("| Licitante | Ordem preço | Situação | Motivo |")
        add("|---|---:|---|---|")
        for c in casc[:8]:
            mot = (c.get("motivo") or "").replace("|", "/")[:60]
            add(f"| {(c.get('licitante') or '?')[:30]} | {c.get('ordem_preco', '?')} | "
                f"{c.get('situacao', '?')} | {mot} |")
        add("")
    if not det.get("dados_suficientes", True):
        add("> ⚠ **Dados insuficientes** no dossiê para um juízo conclusivo — buscar o edital/ata da "
            "licitação (processo de contratação, não o de execução). INDISPONÍVEL ≠ irregular.")
        add("")


_VER_PESQ = {"resolvido": "🟢 RESOLVIDO", "agrava": "🔴 AGRAVA", "inconclusivo": "⚪ INCONCLUSIVO"}


def _secao_pesquisa(add, pesq: dict | None) -> None:
    """§II-G — PESQUISA-INTERNET (Fase 5): o Lex pesquisou as dúvidas (OSINT/web/DOERJ/mídia adversa),
    aprendeu e re-ajustou a análise. SURFACE do que já foi computado (`tools.lex_pesquisa_internet`).
    Honesto: indício a verificar, nunca acusação; INDISPONÍVEL ≠ irregular; cada 'agrava' cita a fonte."""
    if not pesq or not (pesq.get("achados") or pesq.get("resumo")):
        return
    add("## II-G. PESQUISA-INTERNET — dúvidas, aprendizado e re-ajuste (indício a verificar)")
    add("")
    add("*O Lex pesquisou as dúvidas abertas na internet (busca web, notícias, Diário Oficial/Querido Diário, "
        "mídia adversa) e re-ajustou a análise. Indício a apurar — presunção de legitimidade, NUNCA acusação; "
        "ausência de registro NÃO é agravante.*")
    add("")
    cab = f"**{pesq.get('n_fontes', 0)} fonte(s)**"
    if pesq.get("modelo"):
        cab += f" · _{pesq['modelo']}_"
    if pesq.get("avaliado_em"):
        cab += f" · pesquisado {str(pesq['avaliado_em'])[:10]}"
    add(cab)
    add("")
    if pesq.get("resumo"):
        add(f"> {pesq['resumo']}")
        add("")
    for a in (pesq.get("achados") or [])[:8]:
        ver = _VER_PESQ.get(str(a.get("veredito") or "").lower(), (a.get("veredito") or "—").upper())
        add(f"- **{ver}** — {a.get('duvida','')}")
        if a.get("nota"):
            add(f"  - {a['nota']}")
        for f in (a.get("fontes") or [])[:3]:
            add(f"  - fonte: {f}")
    add("")
    if pesq.get("reajuste"):
        add(f"**Re-ajuste da análise:** {pesq['reajuste']}")
        add("")


def _secao_investigacao(add, inv: dict, cnpj: str = "") -> None:
    """Renderiza a seção II-E — a investigação de fachada/laranja que o Lex conduziu (motor investigacao_dd).

    Apresenta cada hipótese com status/nível/evidência/fonte/base legal E a cobertura honesta (o que foi
    verificado e o que ficou INDISPONÍVEL) — indício merece apuração, nunca acusação; INDISPONÍVEL ≠ risco zero."""
    add("## II-E. INVESTIGAÇÃO DE DUE DILIGENCE — empresa de fachada / laranja")
    add("")
    add("*Bateria de hipóteses investigativas (cadastro Receita + base JFN/OBs + OSINT). Base legal: controle "
        "externo e fiscalização (CF art. 70-71; LGPD art. 7º,II e 23). **Honesto:** indício merece apuração, "
        "nunca acusação; **INDISPONÍVEL ≠ ausência de risco**; CPF de pessoa física mascarado (LGPD).*")
    add("")
    # Agregado do sweep de benefícios dos sócios/administradores (socio_beneficio) — cruzamento de laranja
    # independente do motor DD; complementa o H-BENEFICIO por-pessoa com a cobertura honesta do universo do QSA.
    try:
        from compliance_agent.reporting import beneficios_view as bv
        _b = bv.por_fornecedor(cnpj) if cnpj else {}
    except Exception:  # noqa: BLE001
        _b = {}
    if _b.get("n_verificados"):
        if _b.get("n_com_beneficio"):
            add(f"> **Benefícios sociais dos sócios/administradores (sweep):** {_b.get('n_pessoas_beneficio', 0)} de "
                f"{_b['n_verificados']} verificados recebem benefício de subsistência — **indício de interposição de "
                f"pessoas (laranja)** a confirmar no contrato social/procuração/SEI (de {_b['total_qsa']} sócios no "
                f"QSA; {_b['n_indisponivel']} ainda INDISPONÍVEL).")
        else:
            add(f"> **Benefícios sociais dos sócios/administradores (sweep):** {_b['n_verificados']} verificado(s), "
                f"nenhum recebe benefício de subsistência (indício de laranja afastado para os verificados; "
                f"{_b['n_indisponivel']} de {_b['total_qsa']} ainda INDISPONÍVEL).")
        add("")
    if not inv or not isinstance(inv, dict):
        add("> Investigação não disponível para este alvo nesta análise (cadastro/base insuficientes).")
        add("")
        return
    grau = inv.get("grau", "🟢")
    add(f"**Grau da investigação:** {grau} · score {inv.get('score', 0)}/100 · "
        f"{inv.get('n_confirmados', 0)} fato(s) confirmado(s), {inv.get('n_indicios', 0)} indício(s) a apurar.")
    add("")
    add(inv.get("resumo", ""))
    add("")
    hips = inv.get("hipoteses") or []
    if hips:
        for h in hips:
            badge = _BADGE_STATUS.get(h.get("status", ""), h.get("status", ""))
            add(f"### {h.get('codigo', '')} — {h.get('titulo', '')}")
            add(f"- **Status:** {badge}  ·  **Nível:** {h.get('nivel', '—')}")
            add(f"- **Constatação:** {h.get('evidencia', '')}")
            add(f"- **Fonte:** {h.get('fonte', '—')}  ·  **Base legal:** {h.get('base_legal', '—')}")
            add("")
    else:
        add("> Nenhuma hipótese de fachada/laranja se confirmou nas fontes verificáveis nesta varredura.")
        add("")
    cob = inv.get("cobertura") or {}
    if cob:
        itens = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in cob.items())
        add(f"> **Cobertura da investigação (honestidade):** {itens}.")
        add("")
    _secao_pacote_fachada(add, inv.get("pacote_fachada") or {}, inv.get("veredito_fachada") or {})


def _secao_pacote_fachada(add, pac: dict, veredito: dict) -> None:
    """Renderiza os sinais determinísticos do pacote de fachada (TAC com %/UG, sede/visual, REDE) e o
    veredito raciocinado (gemini/cerebras). Tudo consta do parecer. Degrada honesto: bloco vazio = nada."""
    if not pac:
        return
    # 1. RF-TAC (pagamento fora de contrato) — o achado central, com % e UG
    tac = pac.get("tac") or {}
    if tac.get("codigo") == "RF-TAC":
        add(f"### {tac.get('grau', '🟡')} {tac['titulo']}")
        add(f"- **Status:** {_BADGE_STATUS.get('CONFIRMADO', 'CONFIRMADO')}  ·  **Nível:** {tac.get('nivel', '—')}")
        add(f"- **Constatação:** {tac['descricao']}")
        add(f"- **Fonte:** Ordens bancárias (SIAFE — campo observação)  ·  **Base legal:** {tac['fundamento']}")
        add("")
    # 2. sede / visual
    sede = pac.get("sede") or {}
    if sede.get("cobertura", "").startswith("verificado"):
        bits = []
        if sede.get("sem_negocio_google"):
            bits.append("sem negócio operante no Google na sede declarada")
        if sede.get("residencial"):
            bits.append("endereço classificado como residencial")
        if sede.get("visual_suspeito"):
            bits.append(f"imagem da sede: {sede.get('visual_classe')}")
        if bits:
            add(f"### Sinais de SEDE/FACHADA ({sede.get('status', '')})")
            add(f"- **Constatação:** {'; '.join(bits)}. {(sede.get('evidencia') or '')[:200]}")
            add("- **Fonte:** Google (Geocoding+Address Validation+Places) + inspeção visual de imagem.")
            add("")
    # 4. REDE — comando real + outros veículos do administrador
    try:
        from compliance_agent.rede_fachada import render_rede_md
        linhas_rede = render_rede_md(pac.get("rede") or {})
    except Exception:  # noqa: BLE001
        linhas_rede = []
    if linhas_rede:
        add("### Rede de comando e veículos do administrador (QSA real — dump Receita)")
        for ln in linhas_rede:
            add(ln)
        add("")
    # veredito raciocinado (LLM)
    if veredito.get("disponivel"):
        add("### Veredito raciocinado (IA — gemini/cerebras) sobre os sinais")
        add(f"> **{veredito.get('veredito', '—')}** (confiança {veredito.get('confianca', '—')}). "
            f"{veredito.get('fundamentacao', '')}")
        if veredito.get("base_legal"):
            add(f"> **Base legal:** {veredito['base_legal']}")
        add("> *Síntese de IA sobre sinais determinísticos — indício a apurar, não acusação.*")
        add("")
    elif veredito.get("motivo"):
        add(f"> **Veredito raciocinado (IA):** {veredito['motivo']} — os sinais determinísticos acima "
            "permanecem válidos por si (degradação honesta).")
        add("")


def parecer_md(ctx: dict, analise: dict | None = None) -> str:
    if analise is None:
        analise = _analise(ctx)
    cnpj = analise["cnpj"]
    sei = analise["sei"]
    leituras = analise["leituras"]
    achados = analise["achados"]
    emoji, rotulo, just = analise["emoji"], analise["rotulo"], analise["just"]
    tcerj = analise.get("tcerj") or {}
    cartel = analise.get("cartel") or {}
    cruzado = analise.get("cruzado") or {}
    exculpatorio = analise.get("exculpatorio") or []
    destinatarios = analise.get("destinatarios") or []
    # 1º item exculpatório por RF (p/ III-B refletir o rebaixamento a 'monitoramento' quando a defesa sobrevive).
    _exc_por_rf = {}
    for _e in exculpatorio:
        _exc_por_rf.setdefault(_e.get("rf"), _e)
    p = ctx.get("pagamentos") or {}
    lidos = [l for l in leituras if l.get("lido")]
    L = []
    add = L.append

    add(f"# PARECER JURÍDICO PRELIMINAR — {ctx.get('nome','')}")
    add("### Lex · Avaliação fático-jurídica de contratação, licitação e pagamentos")
    add("")
    add("*Tomada de contas preliminar — Direito Administrativo e Controle Externo (TCU/TCE-RJ)*")
    add("")
    add(f"**CNPJ:** {fmt_cnpj(cnpj)}  |  **Data:** {ctx.get('data','')}  |  **Analista:** Agente Lex (JFN)")
    classif = "COM Achado" if achados else "SEM Achado"
    add(f"**Classificação (modelo CGE-RJ — Decreto 47.408/2020):** Nota Técnica **{classif}**.")
    add(f"**Grau de atenção:** {emoji} **{rotulo}** — {just}.")
    add("")
    add("---")
    add("")

    # I. Identificação
    add("## I. IDENTIFICAÇÃO")
    add("")
    add(f"- **Fornecedor:** {ctx.get('nome','')} (CNPJ {fmt_cnpj(cnpj)})")
    if p.get("tem_dados"):
        add(f"- **Exposição:** R$ {moeda(p['total_geral'])} em {p['n_geral']} OBs, {len(p.get('por_orgao_geral',{}))} órgãos, "
            f"exercícios {', '.join(map(str, p.get('anos', [])))}")
    add(f"- **Processos SEI vinculados (origem das OBs):** {len(sei)} identificado(s) na base correlacionada (SIAFE); "
        f"**{len(lidos)} lido(s) na íntegra** nesta análise.")
    add("")

    # II. Fatos
    add("## II. FATOS — processos administrativos")
    add("")
    if sei:
        add("Cada Ordem Bancária remete a um processo SEI (DFD → ETP → TR/edital → contrato → empenho → liquidação → OB). "
            "Processos vinculados a este fornecedor:")
        add("")
        add("| Processo SEI | Nº de OBs | Valor pago (R$) |")
        add("|---|---:|---:|")
        for s in sei[:25]:
            add(f"| {s.get('numero_sei')} | {s.get('n_obs')} | {moeda(s.get('total'))} |")
        add("")
    else:
        add("> Ainda não há processos SEI correlacionados a este CNPJ na base. **Diligência:** rodar a coleta SIAFE "
            "(tela OB Orçamentária) e a correlação para puxar os processos.")
        add("")

    # II-B. Leitura da íntegra
    add("## II-B. LEITURA DOS PROCESSOS SEI (íntegra)")
    add("")
    if lidos:
        add(f"Lex abriu e leu o inteiro teor de **{len(lidos)} processo(s)** no sistema SEI-RJ (pesquisa pública), "
            "extraindo objeto, modalidade, documentos, partes (CNPJs) e valores:")
        add("")
        for l in lidos:
            add(f"### Processo {l.get('numero')}")
            if l.get("tipo"):
                add(f"- **Tipo/título:** {l['tipo']}")
            if l.get("objeto"):
                add(f"- **Objeto (lido):** {l['objeto']}")
            add(f"- **Modalidade/fundamento aparente:** {l.get('modalidade','—')}")
            add(f"- **Documentos no processo:** {l.get('n_docs',0)} (lidos na íntegra: {l.get('n_docs_lidos',0)})")
            if l.get("cnpjs"):
                add(f"- **CNPJs no processo:** {', '.join(l['cnpjs'][:6])}")
            if l.get("valores"):
                add(f"- **Valores citados:** {', '.join(l['valores'][:6])}")
            add(f"- **OBs deste processo:** {l.get('n_obs','—')} (R$ {moeda(l.get('total'))})")
            add("")
    else:
        nao = [l for l in leituras if not l.get("lido")]
        if nao:
            motivos = "; ".join(f"{l.get('numero')}: {l.get('erro') or 'sem texto'}" for l in nao[:5])
            add(f"> A leitura automática não retornou o inteiro teor nesta execução ({motivos}). Causas comuns: "
                "CAPTCHA não resolvido pelo OCR, processo restrito/sigiloso, ou Chrome de leitura (9222) indisponível. "
                "**Diligência:** reexecutar a leitura (o cache é preenchido) ou abrir manualmente.")
        else:
            add("> Não houve leitura de íntegra nesta execução (sem processos correlacionados ou leitura desabilitada).")
        add("")

    # II-C. Contratos e compras diretas no TCE-RJ (Dados Abertos — independe do SEI/WAF)
    add("## II-C. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)")
    add("")
    if tcerj.get("n_contratos") or tcerj.get("n_compras_diretas"):
        add(f"A base de **Dados Abertos do TCE-RJ** (controle externo) registra, para este fornecedor, "
            f"**{tcerj.get('n_contratos',0)} contrato(s)** (R$ {moeda(tcerj.get('soma_contratos',0))}) e "
            f"**{tcerj.get('n_compras_diretas',0)} compra(s) direta(s)** (R$ {moeda(tcerj.get('soma_compras',0))}), "
            f"dos quais **{tcerj.get('n_diretas_dispensa',0)} por dispensa/inexigibilidade**. Esta fonte é oficial e "
            "não depende da leitura do SEI.")
        add("")
        if tcerj.get("contratos"):
            add("**Contratos formais (maiores por valor):**")
            add("")
            add("| Processo | Ano | Objeto | Critério | Valor contrato (R$) | Unidade |")
            add("|---|---:|---|---|---:|---|")
            for c in tcerj["contratos"][:12]:
                obj = (c.get("objeto") or "").strip()
                obj = (obj[:55] + "…") if len(obj) > 55 else (obj or "—")
                add(f"| {_fmt_proc(c.get('processo',''))} | {c.get('ano_processo','')} | {obj} | "
                    f"{c.get('criterio_julgamento') or '—'} | {moeda(c.get('valor_contrato'))} | "
                    f"{(c.get('unidade') or '')[:30]} |")
            add("")
        if tcerj.get("compras"):
            add("**Compras diretas (dispensa/inexigibilidade — fundamento legal citado):**")
            add("")
            add("| Processo | Ano | Objeto | Afastamento | Enquadramento legal | Valor (R$) |")
            add("|---|---:|---|---|---|---:|")
            for c in tcerj["compras"][:12]:
                obj = (c.get("objeto") or "").strip()
                obj = (obj[:45] + "…") if len(obj) > 45 else (obj or "—")
                enq = (c.get("enquadramento_legal") or "").strip()
                enq = (enq[:55] + "…") if len(enq) > 55 else (enq or "—")
                add(f"| {_fmt_proc(c.get('processo',''))} | {c.get('ano_processo','')} | {obj} | "
                    f"{c.get('afastamento') or '—'} | {enq} | {moeda(c.get('valor'))} |")
            add("")
    else:
        add("> Não há contratos nem compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ. Isso pode "
            "ocorrer quando a contratação é municipal, federal, ou ainda não publicada — **diligência:** confirmar "
            "no PNCP e no próprio processo SEI.")
        add("")

    # II-D. Rede fornecedor↔órgão (Onda 3 — indício de rodízio/cartel)
    vz = cartel.get("vizinhos") or []
    if vz:
        add("## II-D. REDE FORNECEDOR–ÓRGÃO (indício de rodízio/cartel)")
        add("")
        add(f"O favorecido atua em **{cartel.get('n_orgaos',0)} órgão(s)**. Outros fornecedores **não-ubíquos** "
            "(excluídas utilities/tributos) que atuam nos **mesmos** órgãos — co-ocorrência estreita é indício de "
            "rodízio/cartel (bid rigging, art. 36 Lei 12.529) a **verificar** (sócios, endereços, datas de proposta):")
        add("")
        add("| Fornecedor co-ocorrente | Órgãos em comum | Footprint total | Valor nesses órgãos (R$) |")
        add("|---|---:|---:|---:|")
        for v in vz[:8]:
            add(f"| {(v.get('nome') or '')[:40]} | {v.get('orgaos_comuns')} | {v.get('footprint_total')} | "
                f"{moeda(v.get('valor_nos_orgaos'))} |")
        add("")
        add("> Co-ocorrência **não prova** conluio (podem ser do mesmo ramo legítimo). É ponto de diligência: "
            "cruzar quadro societário (QSA), endereços e a cronologia das propostas nas licitações comuns.")
        add("")
        # cruzamento por sócio (Onda 4) — quando há QSA ingerido
        match = cruzado.get("co_ocorrencia_com_socio_comum") or []
        if match:
            add("**⚠ Indício forte — co-ocorrência COM sócio em comum (QSA):**")
            add("")
            add("| Fornecedor | Órgãos em comum | Sócio(s) compartilhado(s) |")
            add("|---|---:|---|")
            for m in match[:6]:
                add(f"| {(m.get('nome') or '')[:38]} | {m.get('orgaos_comuns')} | {(m.get('socios_comuns') or '')[:50]} |")
            add("")
            add("> Compartilhar sócio **e** atuar nos mesmos órgãos eleva o indício (possível cartel/laranja/"
                "empresas-irmãs — art. 337-F CP; art. 36 Lei 12.529). Diligência: confirmar no contrato social e nas atas.")
            add("")

    # II-E. Investigação de Due Diligence (fachada/laranja) — o Lex apresenta a investigação que conduziu.
    inv = analise.get("investigacao") or {}
    _secao_investigacao(add, inv, cnpj=so_digitos(ctx.get("cnpj", "")))

    # II-F. Direcionamento de licitação (parecer LLM on-demand) — SURFACE do veredito dos top-score.
    _secao_direcionamento(add, analise.get("direcionamento"))

    # II-G. Pesquisa-internet (Fase 5) — dúvidas pesquisadas, aprendizado e re-ajuste (SURFACE).
    _secao_pesquisa(add, analise.get("pesquisa"))

    # III. Matriz de Achados + análise por red flag
    add("## III. MATRIZ DE ACHADOS (anatomia do achado de auditoria)")
    add("")
    add("*Modelo TCU/ISSAI/CGU: **critério × condição → causa → efeito**, com evidência e recomendação "
        "(ver `docs/PESQUISA-DIREITO-ADMIN-CGE.md`).*")
    add("")
    if achados:
        add("| # | Critério (norma) | Condição (situação) | Causa provável | Efeito potencial | Recomendação |")
        add("|---|---|---|---|---|---|")
        for an in (_anatomia(a) for a in achados):
            cond = an["condicao"].replace("**", "").replace("|", "/")
            cond = (cond[:90] + "…") if len(cond) > 90 else cond
            crit = (an["criterio"][:55] + "…") if len(an["criterio"]) > 55 else an["criterio"]
            add(f"| {an['rf']} | {crit} | {cond} | {an['causa']} | {an['efeito']} | {an['recomendacao']} |")
        add("")
        add("> **Evidência** de todos os achados: Ordens Bancárias (SIAFE/TFE) e contratos/compras diretas do "
            "TCE-RJ (Dados Abertos); quando lida, a íntegra do processo SEI. **Conclusão:** os itens acima são "
            "**indícios** que sustentam a classificação como Nota Técnica COM Achado, sujeitos a contraditório.")
    else:
        add("> **Nota Técnica SEM Achado** — não há indício que sustente um achado. Mantém-se a presunção de "
            "regularidade dos atos administrativos.")
    add("")

    # III-B. Detalhe por indício
    add("## III-B. DETALHAMENTO DOS INDÍCIOS (red flags do controle externo)")
    add("")
    if analise.get("tem_leitura_doc"):
        add("*Indícios marcados abaixo combinam os dados financeiros (OBs) com a **leitura do inteiro teor** dos processos.*")
        add("")
    # Os indícios DD/* (fachada/laranja) são apresentados na seção II-E (não duplicar aqui).
    achados_rf = [a for a in achados if not str(a.get("rf", "")).startswith("DD/")]
    if achados_rf:
        for a in achados_rf:
            nome, fund = _RF.get(a["rf"], (a["rf"], ""))
            add(f"### {a['rf']} — {nome}")
            add(f"- **Observação:** {a['obs']}")
            add(f"- **Fundamento:** {fund}")
            # Análise discursiva (onde no documento + por quê o mecanismo), ancorada no trecho real do SEI.
            if a.get("analise"):
                add(f"- **Análise (onde e por quê):** {a['analise']}")
                if a.get("trecho"):
                    add(f"  > _Trecho do processo {a.get('numero_proc','')}:_ «{a['trecho'][:300]}»")
            add("- **Diligência sugerida:** confrontar com edital (especificações), pesquisa de preços, mapa de "
                "licitantes/sócios, atestos e aditivos do processo SEI.")
            # Encaminhamento por severidade (o que FAZER com este indício) — dirige a ação, não só descreve.
            # Respeita o passo exculpatório: achado cuja defesa inocente SOBREVIVE → rebaixado a monitoramento.
            g = a.get("grav", 0)
            _exc = _exc_por_rf.get(a.get("rf"))
            if _exc and _exc.get("sobrevive"):
                add(f"- **Encaminhamento:** gravidade {g}/5 — a explicação inocente mais plausível **não foi "
                    "refutada** pelos dados (ver passo exculpatório); rebaixado a **monitoramento**, não representação.")
            elif g >= 3:
                add(f"- **⤴ Encaminhamento:** indício relevante (gravidade {g}/5) — cabe **requerimento** ao órgão "
                    "exigindo a justificativa documental; persistindo a dúvida, representação ao TCE-RJ/MP-RJ.")
            else:
                add(f"- **Encaminhamento:** gravidade {g}/5 — manter em diligência/monitoramento; reavaliar com mais dados.")
            add("")
    elif any(str(a.get("rf", "")).startswith("DD/") for a in achados):
        add("Nenhum indício a partir dos dados financeiros/documentais; os achados desta análise são de "
            "**fachada/laranja** e estão detalhados na seção II-E (Investigação de Due Diligence).")
        add("")
    else:
        add("Nenhum indício automático disparou a partir dos dados financeiros nem da leitura documental disponível. "
            "Mantém-se a presunção de regularidade.")
        add("")

    # IV. Matriz P×I
    add("## IV. MATRIZ DE RISCO (P × I — metodologia TCU)")
    add("")
    add("| Indício | P (1-5) | I (1-5) | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for a in achados:
        nome = _RF.get(a["rf"], (a["rf"], ""))[0]
        pp = min(5, 2 + a["grav"] // 2); ii = a["grav"]
        sc = pp * ii
        faixa = "Baixo" if sc <= 4 else "Médio" if sc <= 9 else "Alto" if sc <= 14 else "Extremo"
        add(f"| {a['rf']} {nome} | {pp} | {ii} | {sc} | {faixa} |")
    if not achados:
        add("| — | — | — | — | — |")
    add("")

    # III-C. Triagem por indicadores de risco de fraude (lex_indicadores_fraude)
    try:
        from compliance_agent import lex_indicadores_fraude as _lif
        _sinais = _lif.sinais_do_contexto(ctx, analise)
        add(_lif.parecer_indicadores_md(_lif.triagem(_sinais)))
        add("")
    except Exception:
        pass

    # IV-B. Análise de mérito (parecer raciocinado)
    add("## IV-B. ANÁLISE DE MÉRITO")
    add("")
    add(_analise_merito(ctx, analise))
    add("")

    # IV-D. Defesa contra si mesmo (passo exculpatório obrigatório) — protege a credibilidade do parecer.
    add("## IV-D. DEFESA CONTRA SI MESMO — PASSO EXCULPATÓRIO")
    add("")
    add("*Para cada indício, a **explicação inocente mais plausível** e se os dados a refutam. Achado cuja "
        "defesa **não é refutada** pelos dados fica apenas como **monitoramento** — não representação "
        "(presunção de legitimidade; a dúvida sobre a economicidade favorece o gestor).*")
    add("")
    if exculpatorio:
        add("| Indício | Explicação inocente mais plausível | Os dados refutam? | Encaminhamento |")
        add("|---|---|---|---|")
        for e in exculpatorio:
            nome = _RF.get(e.get("rf"), (e.get("rf"), ""))[0]
            defesa = (e.get("defesa") or "").replace("|", "/")
            defesa = (defesa[:120] + "…") if len(defesa) > 120 else defesa
            refuta = "**Sim** — defesa afastada" if not e.get("sobrevive") else "Não — defesa plausível"
            enc = "monitoramento" if e.get("sobrevive") else "representação"
            add(f"| {e.get('rf')} {nome} | {defesa} | {refuta} | **{enc}** |")
        add("")
        _monit = [e for e in exculpatorio if e.get("sobrevive")]
        if _monit:
            add(f"> **{len(_monit)} indício(s)** tiveram a explicação inocente considerada **plausível** (não "
                "refutada pelos dados) e foram **rebaixados a monitoramento**, não representação. "
                "Isso preserva a credibilidade do parecer: indício ≠ acusação.")
        else:
            add("> Em todos os indícios os **dados refutam** a explicação inocente (convergência/cruzamento "
                "confirmatório) — sustentam encaminhamento, não mero monitoramento.")
    else:
        add("> Sem indícios a submeter ao passo exculpatório — presunção de regularidade mantida.")
    add("")

    # IV-C. Proposta preliminar de sanção administrativa (dosimetria — lex_sancoes)
    # CALIBRAGEM (auditoria 2026-06-18): a dosimetria só incide sobre achados cuja
    # defesa foi REFUTADA pelos dados (representação). Achados rebaixados a
    # monitoramento (explicação inocente plausível) NÃO entram na base de sanção —
    # senão um parecer 🟡 de indícios fracos projeta multa grave (ex.: R$27 mi sem
    # dolo nem dano efetivo), violando indício≠acusação e a doutrina (sanção exige
    # convergência + materialidade/dolo, não indício estatístico isolado).
    try:
        from compliance_agent import lex_sancoes
        _monit_rfs = {e.get("rf") for e in (exculpatorio or []) if e.get("sobrevive")}
        _achados_sancao = [a for a in achados if a.get("rf") not in _monit_rfs]
        if _achados_sancao:
            _valor_sancao = (ctx.get("pagamentos") or {}).get("total_geral") or 0
            _prop_sancao = lex_sancoes.sugerir_sancoes(_achados_sancao, valor_contrato=_valor_sancao, regime="14133")
            add(lex_sancoes.parecer_sancionatorio_md(_prop_sancao))
            add("")
        else:
            add("## IV-C. Proposta preliminar de sanção administrativa")
            add("")
            add("> **Não se propõe sanção nesta fase.** Todos os indícios tiveram a explicação inocente "
                "considerada **plausível** (passo exculpatório) e permanecem como **monitoramento**, não "
                "representação. Sanção administrativa pressupõe achado com defesa **afastada pelos dados** e, "
                "para multa, **dano efetivo mensurado** ou **dolo indiciado** — ausentes aqui. Indício ≠ acusação.")
            add("")
    except Exception:
        pass

    # V. Conclusão
    add("## V. CONCLUSÃO — GRAU DE ATENÇÃO")
    add("")
    add(f"**{emoji} {rotulo}.** {just[0].upper()+just[1:]}.")
    add("")

    # VI. Recomendações
    add("## VI. RECOMENDAÇÕES DE ENCAMINHAMENTO")
    add("")
    # Destinatário recomendado por tipo/família de achado (conluio→MP+CADE · débito→TCE/TCU · improbidade/penal→MP · PAR→CGU/CGE).
    if destinatarios:
        add("**Destinatário recomendado** (derivado das famílias dos achados presentes):")
        add("")
        add("| Destinatário | Fundamento / tipo de achado |")
        add("|---|---|")
        for d in destinatarios:
            add(f"| **{d.get('destinatario')}** | {d.get('motivo')} |")
        add("")
        add("> O roteamento acima segue o enquadramento do playbook (conluio/cartel → MP + CADE; débito/cautelar → "
            "TCE-RJ/TCU; improbidade/penal → MP; PAR anticorrupção → CGU/CGE) e **não** antecipa juízo de mérito — "
            "o encaminhamento concreto observa o passo exculpatório (seção IV-D).")
        add("")
    else:
        add("> **Destinatário recomendado:** nenhum encaminhamento específico — sem achado que indique competência "
            "de controle externo, MP, CADE ou CGE (presunção de regularidade).")
        add("")
    add("- **Diligência documental:** confrontar, nos processos SEI, o edital/TR (especificações), a pesquisa "
        "de preços (cesta — Acórdão 1875/2021-TCU), o mapa de licitantes (sócios/endereços) e os atestos/medições.")
    add("- **Controle externo:** havendo indício de dano, representar ao **TCE-RJ** (jurisdição sobre a despesa estadual).")
    add("- **Demais órgãos:** ciência ao **MP-RJ** (improbidade) e ao **CADE** (conluio/bid rigging, Lei 12.529) se cabível; "
        "PAR (Lei 12.846) e ciência à **CGE-RJ** (controle interno).")
    add("  > Cautela na qualificação de improbidade (Lei 8.429/92 pós-Lei 14.230/2021): exige-se **dolo** nos "
        "arts. 9/10/11 (**STF Tema 1199, ARE 843989/PR**) e, no **art. 10**, **dano efetivo** — fim do dano presumido "
        "(**STJ REsp 1.929.685/TO**, 1ª T., 2024). O Lex aponta o indício; a tipificação é do MP-RJ/Judiciário.")
    add("  > Esfera penal (referência, não imputação): desvios podem tangenciar **CP arts. 312 (peculato), 316 "
        "(concussão), 317 (corrupção passiva), 333 (corrupção ativa)** e os crimes licitatórios da **Lei 14.133, "
        "arts. 337-E a 337-P**. Dispensa/inexigibilidade irregular hoje é **art. 337-E CP** (ex-art. 89/8.666 — "
        "*continuidade típica*, STJ REsp 2.069.436, não abolitio). Confirmar conduta e dolo antes de qualquer juízo.")
    add("  > Base normativa estadual (RJ): Lei 14.133 regulamentada pelo **Decreto 47.680/2021** + **Resoluções "
        "SEPLAG 179/180/2023** e **PGE 4.937/2023**; controle interno na **CGE-RJ** (Lei 7.989/2018); o rito de "
        "Tomada de Contas é a **Deliberação TCE-RJ 279/2017**, cujo **art. 7º** exige apenas *elementos que indiquem* "
        "— o mesmo limiar de **indício** deste parecer.")
    add("")

    # VII. Ressalvas
    add("## VII. RESSALVAS")
    add("")
    add("> 1. Os apontamentos são **INDÍCIOS**, sujeitos a contraditório e ampla defesa. "
        "2. Vigora a **presunção de legitimidade** dos atos administrativos (dúvida sobre economicidade favorece o gestor — "
        "TCE-RJ, Proc. 101.922-9/12). 3. Lex **não afirma crime, improbidade ou dolo** — competência do TCE-RJ, MP-RJ e "
        "Judiciário. 4. Conclusões limitadas aos dados/documentos analisados; lacunas geram **diligência**, não condenação. "
        "5. A leitura automática do SEI extrai texto público; trechos podem faltar por OCR/restrição — sempre confirmar na fonte.")
    add("")
    add(f"_Parecer gerado automaticamente pelo Agente Lex (JFN) em {ctx.get('data','')}. "
        "Base jurídica: docs/LEX-BASE-JURIDICA.md + docs/PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md "
        "(doutrina, improbidade pós-14.230, controle e RJ — CERJ arts. 122-123). Não substitui parecer jurídico formal._")
    return "\n".join(L)


def render_pdf(ctx: dict, destino: str, analise: dict | None = None, md: str | None = None) -> str:
    """PDF do parecer Lex — mesma estética do JFN (capa azul + texto corrido). `md` opcional permite
    reaproveitar a estética para o parecer de ÓRGÃO (sem recomputar o fornecedor)."""
    from fpdf import FPDF
    if analise is None:
        analise = _analise(ctx)
    md = md if md is not None else parecer_md(ctx, analise)
    rotulo = analise["rotulo"]
    cor = {"VERMELHO": (220, 53, 69), "AMARELO": (255, 150, 0), "VERDE": (40, 167, 69)}.get(rotulo, (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s):
        s = s or ""
        # glifos que a DejaVu (Unicode) NÃO possui (emoji de risco, seta ⤴) → equivalentes que ELA possui,
        # senão o fpdf2 emite "missing glyphs" e o PDF entregue mostra tofu. O grau-cor vem da barra colorida.
        if getattr(pdf, "_uni", False):
            return s.replace("🔴", "●").replace("🟡", "●").replace("🟢", "●").replace("⤴", "↗")
        for a, b in (("—", "-"), ("–", "-"), ("·", "-"), ("→", "->"), ("⤴", "->"), ("≥", ">="), ("🟢", ""), ("🟡", ""), ("🔴", "")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("PARECER JURÍDICO — AGENTE LEX"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Avaliação fático-jurídica · Direito Administrativo e Controle Externo (TCU/TCE-RJ)"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx.get('data','')}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx.get("nome", "")))
    _ident = f"CNPJ: {fmt_cnpj(ctx.get('cnpj',''))}" if so_digitos(ctx.get("cnpj", "")) else f"Unidade Gestora (UG): {ctx.get('ug','—')}"
    pdf.set_font(pdf._fam, "", 10); pdf.cell(0, 6, _t(_ident), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_fill_color(*cor)
    pdf.set_text_color(0, 0, 0) if rotulo == "AMARELO" else pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(0, 9, _t(f"  GRAU DE ATENÇÃO: {rotulo}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    corpo = md.split("---\n\n", 1)[-1]
    _render_parecer_pdf(pdf, _t, corpo)

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def gerar(ctx: dict, salvar: bool = True, ler_sei: bool | None = None) -> dict:
    """Gera o parecer Lex (md + pdf). Lê a íntegra do SEI UMA vez. Retorna {ok, grau, n_indicios, n_sei_lidos, path_lex_pdf, path_lex_md}."""
    analise = _analise(ctx, ler_sei=ler_sei)
    # Análise DISCURSIVA (onde+por quê, ancorada no trecho real do SEI). Default ligado; degrada honesto
    # se o LLM cair (achado fica só com a obs determinística). JFN_LEX_DISCURSIVO=0 desliga.
    if os.environ.get("JFN_LEX_DISCURSIVO", "1") == "1" and any(a.get("trecho") for a in analise.get("achados", [])):
        try:
            analise["achados"] = analise_discursiva(analise["achados"])
        except Exception:
            pass
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


# ─────────────────────── PARECER LEX DE ÓRGÃO (UG) ───────────────────────
# O /orgao passa a "pensar" como o /relatorio: além do PDF/XLSX, emite um PARECER LEX próprio. Os indícios
# são de nível ÓRGÃO (concentração/captura, recorrência idêntica, estornos), com os mesmos red flags e
# fundamentos do controle externo, grau 🟢🟡🔴 e encaminhamento. Honesto: indícios a verificar, nunca acusação.

def _ob_zero_da_ug(ug: str) -> int:
    """Quantas OBs de valor <=0 (estornos/regularizações/OB R$ 0,00) a UG tem — insumo do R10."""
    try:
        import sqlite3

        from compliance_agent.reporting.inteligencia import _DB
        if not ug or not _DB.exists():
            return 0
        con = sqlite3.connect(_DB)
        try:
            n = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE ug_codigo=? AND (valor IS NULL OR valor<=0)",
                            (str(ug),)).fetchone()[0]
        finally:
            con.close()
        return int(n or 0)
    except Exception:
        return 0


def _achados_orgao(ctx: dict) -> list[dict]:
    """Indícios de NÍVEL ÓRGÃO a partir dos pagamentos (OB) já consolidados pelo /orgao."""
    p = ctx.get("pagamentos") or {}
    if not p.get("tem_dados"):
        return []
    ach: list[dict] = []
    hhi = p.get("hhi") or {}
    nivel = (hhi.get("nivel") or "").lower()
    top_share = float(hhi.get("top_share") or 0)  # percentual (0-100)
    total = float(p.get("total_geral") or 0) or 1.0
    top_nome, top_val = next(iter((p.get("por_favorecido_geral") or {}).items()), ("—", 0))
    if top_share >= 60:
        ach.append({"rf": "R8", "grav": 4, "obs": f"**{top_nome}** concentra **{top_share:.1f}%** dos pagamentos do órgão "
                    f"(R$ {moeda(top_val)} de R$ {moeda(total)}; HHI {hhi.get('indice')} — {nivel}). Concentração ≥60% em um "
                    "único fornecedor é *red flag* clássico de captura/cartel (ACFE/OCDE) — exige comprovar a competitividade."})
    elif top_share >= 50:
        ach.append({"rf": "R8", "grav": 3, "obs": f"**{top_nome}** concentra **{top_share:.1f}%** (R$ {moeda(top_val)}; HHI "
                    f"{hhi.get('indice')} — {nivel}). Verificar competitividade dos certames ou fracionamento/dispensa reiterada/direcionamento."})
    elif top_share >= 30:
        ach.append({"rf": "R8", "grav": 2, "obs": f"Concentração relevante: **{top_nome}** com **{top_share:.1f}%** "
                    f"(HHI {hhi.get('indice')} — {nivel}). Examinar a competitividade dos certames e o parcelamento do objeto."})
    try:
        from compliance_agent.reporting.inteligencia_orgao import _recorrentes_identicos
        grupos = _recorrentes_identicos(p)
    except Exception:
        grupos = []
    if grupos:
        g0 = grupos[0]
        ach.append({"rf": "R2", "grav": 2, "obs": f"Padrão de **valores idênticos**: **{g0['favorecido']}** recebeu "
                    f"**{g0['n']}×** o valor exato de R$ {moeda(g0['valor'])} (R$ {moeda(g0['total'])} no total). Típico de "
                    "serviço continuado, mas a reiteração integra os *red flags* da ACFE — caracterizar objeto/vigência/medição."})
    n_zero = _ob_zero_da_ug(ctx.get("ug", ""))
    if n_zero >= 10:
        ach.append({"rf": "R10", "grav": 2, "obs": f"A UG tem **{n_zero}** OBs de valor zero/estorno — verificar regularizações/"
                    "anulações de liquidação (Lei 4.320/64 arts. 62-63; Decreto 93.872/86 art. 38) e seu motivo."})
    # Pagamento FORA de contrato regular (TAC/indenização) + emergencial — achado sistêmico de órgão
    # (achado FSERJ codificado). R5 = inexigibilidade/dispensa possivelmente indevida (fuga ao certame).
    tj = ctx.get("tac_orgao") or {}
    if tj.get("ok"):
        ug_m = tj.get("tac_ug") or {}
        emerg = tj.get("emergencial") or {}
        wl = tj.get("worklist") or {}
        pct = float(ug_m.get("pct") or 0)
        tac_val = float(ug_m.get("total_tac") or 0)
        susp = [f for f in (wl.get("fornecedores") or []) if f.get("sede_indicio")]
        if pct >= 25 or tac_val >= 100_000_000:  # sistêmico relevante (faixa FSERJ)
            grav = 4 if (pct >= 25 and tac_val >= 100_000_000) else 3
        elif pct >= 10 and tac_val > 0:
            grav = 2
        else:
            grav = 0
        if grav:
            obs = (f"A UG pagou **{pct:.1f}%** de R$ {moeda(float(ug_m.get('total') or 0))} **FORA de contrato "
                   f"regular** — via TAC/indenização/reconhecimento de dívida (**R$ {moeda(tac_val)}** em "
                   f"{ug_m.get('n_tac', 0)} OBs). Regularização *a posteriori* recorrente e vultosa é indício "
                   "SISTÊMICO de contratação informal/emergencial perpetuada e **fuga ao dever de licitar**.")
            if emerg.get("ok"):
                obs += (f" Soma-se a red flag irmã: **{emerg.get('n_emerg', 0)} OBs** "
                        f"(R$ {moeda(float(emerg.get('total_emerg') or 0))}) por **emergencial/dispensa**.")
            wl_top = (wl.get("fornecedores") or [])[:4]
            if wl_top:
                obs += (" Worklist de co-suspeitos por TAC%: "
                        + "; ".join(f"{(f.get('nome') or '—')[:24]} {f.get('pct', 0):.0f}%"
                                    + (" (sede-fachada)" if f.get("sede_indicio") else "") for f in wl_top) + ".")
            if susp:
                obs += (f" **{len(susp)} desses são fachada-suspeitos** (alto TAC% + sede INDÍCIO/sem-Google) — "
                        "hipótese de interposição/laranja a apurar (indício, não acusação).")
            ach.append({"rf": "R5", "grav": grav, "obs": obs})
    # Cruzamento com o dump da Receita Federal (anomalias nos fornecedores) — alimenta o grau do órgão.
    ar = ctx.get("anomalia_receita") or {}
    if ar.get("ok"):
        sf_flag = [r for r in (ar.get("sem_fins_lucrativos") or []) if not r.get("ressalva")]
        if sf_flag:
            t = sf_flag[0]
            grav = 3 if float(t.get("total") or 0) >= 50_000_000 else 2
            ach.append({"rf": "R5", "grav": grav, "obs":
                        f"**{len(sf_flag)}** entidade(s) **sem fins lucrativos** (associação/fundação/OS, sem "
                        f"perfil de ensino/pesquisa) recebem como fornecedor — maior: **{(t.get('razao_social') or '—')[:40]}** "
                        f"(R$ {moeda(float(t.get('total') or 0))}). Repasse a OS/entidade via contrato de gestão/parceria "
                        "exige confirmar o objeto, o credenciamento e a prestação de contas (Lei 9.637/98; Lei 13.019/2014 — "
                        "MROSC). Indício, não acusação."})
        rede = ar.get("rede_mesmo_orgao") or []
        rede_pf = [r for r in rede if not r.get("eh_pj")]
        if rede_pf:
            t = rede_pf[0]
            ach.append({"rf": "R7", "grav": 3, "obs":
                        f"**{len(rede_pf)}** administrador(es) compartilham **≥2 fornecedores do mesmo órgão** "
                        f"(QSA da Receita) — ex.: **{(t.get('nome_socio') or '—')[:34]}** em **{t.get('n_fornecedores')}** "
                        "fornecedores. Fornecedores aparentemente concorrentes sob a mesma administração indiciam "
                        "**concorrência simulada/concentração oculta** (Art. 90 Lei 8.666; Art. 337-F CP; Art. 36 Lei "
                        "12.529 — CADE) — corroborar os licitantes nos certames (SEI/PNCP)."})
        su = ar.get("socio_unico_alto_valor") or []
        su_priv = [r for r in su if not r.get("sem_fins")]
        if su_priv:
            t = su_priv[0]
            ach.append({"rf": "DD/H-SOCIO-UNICO", "grav": 2, "obs":
                        f"**{len(su_priv)}** fornecedor(es) de alto valor com **administrador único** no QSA — ex.: "
                        f"**{(t.get('razao_social') or '—')[:40]}** (R$ {moeda(float(t.get('total') or 0))}). Gestão "
                        "concentrada num só sócio em contratos vultosos é indício de **interposição (laranja)** ou "
                        "capacidade operacional incompatível — confrontar com a estrutura real. Indício ≠ acusação."})
        cad = ar.get("cadastro") or {}
        if cad.get("ok") and cad.get("achados"):
            ach.append({"rf": "DD/H-SITUACAO", "grav": 4, "obs":
                        f"**{len(cad['achados'])}** fornecedor(es) com **situação cadastral irregular** na Receita "
                        "(INAPTA/baixada/suspensa) — incompatível com o recebimento de pagamento público; conferir a "
                        "vigência contratual (fonte: minhareceita.org)."})
    return ach


def _parecer_orgao_md(ctx: dict, analise: dict, merito: str = "") -> str:
    """Corpo (markdown) do parecer Lex de órgão — mesma anatomia do parecer de fornecedor."""
    achados = analise.get("achados", [])
    L = ["---", ""]
    add = L.append
    add("## I. MÉRITO DA EXECUÇÃO DO ÓRGÃO")
    add("")
    add(merito or "Sem narrativa de mérito disponível.")
    add("")
    add("## II. INDÍCIOS ESTRUTURADOS (red flags do controle externo)")
    add("")
    if achados:
        for a in achados:
            nome, fund = _RF.get(a["rf"], (a["rf"], ""))
            add(f"### {a['rf']} — {nome}")
            add(f"- **Observação:** {a['obs']}")
            add(f"- **Fundamento:** {fund}")
            g = a.get("grav", 0)
            if g >= 3:
                add(f"- **⤴ Encaminhamento:** indício relevante (gravidade {g}/5) — cabe **requerimento** ao órgão exigindo "
                    "justificativa documental (contratos, modalidade, pesquisa de preços); persistindo, representação ao TCE-RJ/MP-RJ.")
            else:
                add(f"- **Encaminhamento:** gravidade {g}/5 — manter em diligência/monitoramento; reavaliar com mais dados.")
            add("")
    else:
        add("Nenhum indício automático disparou a partir dos pagamentos (OB) disponíveis. Mantém-se a presunção de regularidade.")
        add("")
    add("## III. MATRIZ DE RISCO (P × I — metodologia TCU)")
    add("")
    add("| Indício | P (1-5) | I (1-5) | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for a in achados:
        nome = _RF.get(a["rf"], (a["rf"], ""))[0]
        pp = min(5, 2 + a["grav"] // 2); ii = a["grav"]; sc = pp * ii
        faixa = "Baixo" if sc <= 4 else "Médio" if sc <= 9 else "Alto" if sc <= 14 else "Extremo"
        add(f"| {a['rf']} {nome} | {pp} | {ii} | {sc} | {faixa} |")
    if not achados:
        add("| — | — | — | — | — |")
    add("")
    add("## IV. CONCLUSÃO — GRAU DE ATENÇÃO")
    add("")
    add(f"{analise.get('emoji','')} **{analise.get('rotulo','')}** — {analise.get('just','')}.")
    add("")
    add("> **Ressalva:** baseado em dados de pagamento (OB) públicos, sem exame documental dos contratos. "
        "Indícios a verificar, NÃO conclusão de irregularidade — vigora a presunção de regularidade dos atos administrativos.")
    return "\n".join(L)


def gerar_orgao(ctx: dict, salvar: bool = True) -> dict:
    """Parecer LEX de ÓRGÃO (UG) — faz o /orgao 'pensar' como o /relatorio. `ctx` é o contexto do relatório
    de órgão (nome, ug, data, pagamentos). Retorna {ok, grau, n_indicios, path_lex_pdf, path_lex_md}."""
    achados = _achados_orgao(ctx)
    emoji, rotulo, just = _grau(achados)
    analise = {"achados": achados, "emoji": emoji, "rotulo": rotulo, "just": just}
    try:  # mérito jurídico textual do próprio módulo de órgão (import tardio evita ciclo)
        from compliance_agent.reporting.inteligencia_orgao import parecer_orgao
        merito = parecer_orgao(ctx)
    except Exception:
        merito = ""
    md = _parecer_orgao_md(ctx, analise, merito)
    out = {"ok": True, "grau": rotulo, "n_indicios": len(achados), "path_lex_pdf": "", "path_lex_md": ""}
    if salvar:
        base = f"parecer_lex_orgao_{_slug(ctx.get('nome','')) or ctx.get('ug','')}_{ctx.get('data','')}"
        md_path = _REPORTS / f"{base}.md"
        md_path.write_text(md, encoding="utf-8")
        out["path_lex_md"] = str(md_path)
        try:
            out["path_lex_pdf"] = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"), analise, md=md)
        except Exception as exc:  # noqa: BLE001
            out["_pdf_erro"] = str(exc)[:160]
    return out
