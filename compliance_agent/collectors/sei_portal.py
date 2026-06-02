"""
Scraper do Portal SEI-RJ (Sistema Eletrônico de Informações).

Portal público: https://portalsei.rj.gov.br/
Permite consultar processos públicos sem login.

Funcionalidades:
  - Buscar processo por número SEI
  - Listar documentos de um processo
  - Ler conteúdo de documentos públicos
  - Cruzar número SEI com despesas do SIAFE
  - Analisar processo em busca de irregularidades
  - Extrair participantes, valores, datas, objetos

Formato do número SEI-RJ: E-XX/XXXXXX/YYYY ou SEI-XXXXXX/YYYY
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlencode, quote

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from compliance_agent.database.models import ProcessoSEI, Alerta, Contrato

SEI_BASE       = "https://portalsei.rj.gov.br"
SEI_PESQUISA   = f"{SEI_BASE}/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php"
SEI_CONTROLADOR = f"{SEI_BASE}/sei/controlador.php"

CACHE_DIR = Path("data/sei_cache")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": SEI_BASE,
}


def _bloqueado_por_captcha(resultado: dict) -> bool:
    """
    Heurística: a busca via httpx provavelmente esbarrou no CAPTCHA do SEI.
    Sinais: marcação explícita do parser, ou erro genérico sem nenhum documento.
    """
    if resultado.get("captcha"):
        return True
    erro = (resultado.get("erro") or "").lower()
    if any(t in erro for t in ("captcha", "robô", "robo", "verificação", "verificacao")):
        return True
    # Sem documentos e sem erro claro → vale tentar o caminho humano-no-loop.
    if not resultado.get("documentos") and not resultado.get("assunto"):
        return True
    return False


# ── Busca de processos ────────────────────────────────────────────────────────

async def buscar_processo(numero_sei: str, usar_cache: bool = True) -> dict:
    """
    Busca um processo SEI pelo número e retorna seus metadados e documentos.

    Retorna:
      {
        "numero": str,
        "tipo": str,
        "assunto": str,
        "interessados": list[str],
        "data_abertura": str,
        "orgao_origem": str,
        "situacao": str,
        "documentos": list[dict],  # {id, tipo, data, autor, url}
        "cpfs": list[str],
        "cnpjs": list[str],
        "valores": list[str],
        "url": str,
        "erro": str (se falhou)
      }
    """
    numero_limpo = _normalizar_numero_sei(numero_sei)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{numero_limpo.replace('/', '_')}.json"

    if usar_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            # Cache válido por 24h
            if cached.get("_cached_at"):
                delta = datetime.now() - datetime.fromisoformat(cached["_cached_at"])
                if delta.total_seconds() < 86400:
                    return cached
        except Exception:
            pass

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=_HEADERS
    ) as client:
        # Estratégia 1: busca direta por número no portal de pesquisa
        resultado = await _tentar_pesquisa_direta(client, numero_limpo)

        # Estratégia 2: URL de exibição direta (algumas instâncias SEI)
        if resultado.get("erro") and not resultado.get("documentos"):
            resultado = await _tentar_url_direta(client, numero_sei)

    # Estratégia 3: CAPTCHA/restrição bloqueou o httpx → cai para o caminho
    # HUMANO-NO-LOOP via Chrome 9222 (o agente NÃO quebra o CAPTCHA; ele avisa
    # o operador, que resolve uma vez na janela, e então a leitura continua).
    if (not resultado.get("documentos")) and _bloqueado_por_captcha(resultado):
        try:
            from compliance_agent.collectors.sei_cdp import ler_processo_sei
            via_cdp = await ler_processo_sei(numero_sei)
            if via_cdp.get("documentos") or not via_cdp.get("erro"):
                # Normaliza para o formato esperado por buscar_processo
                resultado = {
                    "numero": numero_limpo,
                    "tipo": "", "assunto": "", "interessados": [],
                    "data_abertura": "", "orgao_origem": "", "situacao": "",
                    "documentos": via_cdp.get("documentos", []),
                    "cpfs": via_cdp.get("cpfs", []),
                    "cnpjs": via_cdp.get("cnpjs", []),
                    "valores": via_cdp.get("valores", []),
                    "url": via_cdp.get("url", ""),
                    "texto": via_cdp.get("texto", ""),
                    "via": "chrome_cdp_humano_no_loop",
                    "captcha_resolvido": via_cdp.get("captcha_resolvido", False),
                }
                if via_cdp.get("erro"):
                    resultado["erro"] = via_cdp["erro"]
        except Exception as e:
            resultado.setdefault("erro", f"fallback CDP falhou: {e}")

    resultado["_cached_at"] = datetime.now().isoformat()
    try:
        cache_file.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass

    return resultado


async def _tentar_pesquisa_direta(client: httpx.AsyncClient, numero: str) -> dict:
    """Usa o formulário de pesquisa pública do SEI-RJ."""
    try:
        # GET para obter cookies e possível token CSRF
        resp = await client.get(SEI_PESQUISA)
        if resp.status_code != 200:
            return {"erro": f"Portal SEI retornou HTTP {resp.status_code}"}

        soup = BeautifulSoup(resp.text, "lxml")

        # Extrai campos ocultos do formulário (alguns portais SEI usam token)
        form = soup.find("form")
        hidden_data: dict = {}
        if form:
            for inp in form.find_all("input", {"type": "hidden"}):
                name = inp.get("name", "")
                value = inp.get("value", "")
                if name:
                    hidden_data[name] = value

        # Monta payload de pesquisa
        payload = {
            **hidden_data,
            "txtPesquisaRapida": numero,
            "txtNroProcesso":    numero,
            "chkSinExato":       "on",
            "btnPesquisar":      "Pesquisar",
        }

        resp2 = await client.post(SEI_PESQUISA, data=payload)
        if resp2.status_code != 200:
            return {"erro": f"Pesquisa SEI retornou HTTP {resp2.status_code}"}

        return _parse_resultado_pesquisa(resp2.text, numero)

    except httpx.TimeoutException:
        return {"erro": "Timeout ao acessar portal SEI"}
    except Exception as e:
        return {"erro": str(e)}


async def _tentar_url_direta(client: httpx.AsyncClient, numero: str) -> dict:
    """Tenta acessar o processo via URL direta do controlador SEI."""
    try:
        params = {
            "acao": "procedimento_trabalhar",
            "txtNroProcedimento": numero,
        }
        resp = await client.get(SEI_CONTROLADOR, params=params)
        if resp.status_code == 200:
            return _parse_resultado_pesquisa(resp.text, numero)
        return {"erro": f"URL direta retornou HTTP {resp.status_code}"}
    except Exception as e:
        return {"erro": str(e)}


def _parse_resultado_pesquisa(html: str, numero: str) -> dict:
    """
    Faz parse da página de resultado de pesquisa do SEI.
    Extrai: tipo, assunto, interessados, documentos, valores, CPFs, CNPJs.
    """
    soup = BeautifulSoup(html, "lxml")

    resultado: dict = {
        "numero": numero,
        "tipo": "",
        "assunto": "",
        "interessados": [],
        "data_abertura": "",
        "orgao_origem": "",
        "situacao": "",
        "documentos": [],
        "cpfs": [],
        "cnpjs": [],
        "valores": [],
        "url": "",
    }

    # Detecta CAPTCHA na página (marca para o fallback humano-no-loop via CDP)
    page_text = soup.get_text(" ", strip=True)
    pl = page_text.lower()
    if ("captcha" in pl or "não sou um robô" in pl or "nao sou um robo" in pl
            or "digite os caracteres" in pl or "código da imagem" in pl
            or soup.find("img", src=re.compile(r"[Cc]aptcha"))):
        resultado["captcha"] = True
        resultado["erro"] = "CAPTCHA exigido — use o caminho via Chrome (humano-no-loop)."
        return resultado

    # Detecta "processo não encontrado" ou "acesso restrito"
    if any(t in pl for t in
           ["não encontrado", "acesso restrito", "sigiloso", "não localizado"]):
        resultado["erro"] = "Processo não encontrado ou restrito/sigiloso."
        return resultado

    # ── Extrai metadados da tabela de resumo ──────────────────────────────
    for label_text, field_key in [
        ("tipo do processo", "tipo"),
        ("tipo de processo", "tipo"),
        ("especificação", "assunto"),
        ("assunto", "assunto"),
        ("interessado", "interessados"),
        ("data de geração", "data_abertura"),
        ("data de abertura", "data_abertura"),
        ("órgão gerador", "orgao_origem"),
        ("órgão de origem", "orgao_origem"),
        ("situação", "situacao"),
    ]:
        for tag in soup.find_all(["th", "td", "label", "span"]):
            if label_text in tag.get_text(strip=True).lower():
                # Value is typically the next sibling or adjacent cell
                nxt = tag.find_next_sibling()
                if not nxt:
                    parent_row = tag.find_parent("tr")
                    if parent_row:
                        cells = parent_row.find_all("td")
                        for i, c in enumerate(cells):
                            if label_text in c.get_text(strip=True).lower() and i + 1 < len(cells):
                                nxt = cells[i + 1]
                                break
                if nxt:
                    valor = nxt.get_text(strip=True)
                    if field_key == "interessados":
                        resultado["interessados"].append(valor)
                    else:
                        if not resultado[field_key]:
                            resultado[field_key] = valor
                break

    # ── Extrai lista de documentos ────────────────────────────────────────
    for link in soup.find_all("a", href=True):
        href = link["href"]
        texto = link.get_text(strip=True)

        # Documentos SEI geralmente têm padrão no URL
        if any(p in href.lower() for p in [
            "documento_visualizar", "visualizar_proc", "exibir_documento",
            "md_proc_visualizar", "documento_consultar"
        ]):
            resultado["documentos"].append({
                "texto_link": texto[:100],
                "url": urljoin(SEI_BASE, href),
            })

    # ── Extrai CPFs, CNPJs e valores ──────────────────────────────────────
    resultado["cpfs"]   = list(set(re.findall(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", page_text)))
    resultado["cnpjs"]  = list(set(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", page_text)))
    resultado["valores"] = list(set(re.findall(
        r"R\$\s*[\d.,]+|[\d.,]+\s*(?:reais|mil reais)", page_text, re.IGNORECASE
    )))

    return resultado


# ── Leitura de documentos ─────────────────────────────────────────────────────

async def ler_documento_sei(url: str, usar_cache: bool = True) -> str:
    """
    Lê o conteúdo textual de um documento SEI público.
    Retorna o texto extraído (máximo 10.000 caracteres).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = re.sub(r"[^\w]", "_", url)[-80:]
    cache_file = CACHE_DIR / f"doc_{cache_key}.txt"

    if usar_cache and cache_file.exists():
        age = datetime.now().timestamp() - cache_file.stat().st_mtime
        if age < 86400 * 7:  # 7 dias
            return cache_file.read_text(encoding="utf-8")

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=_HEADERS
    ) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return f"[Erro HTTP {resp.status_code}]"

            soup = BeautifulSoup(resp.text, "lxml")

            # Remove scripts e styles
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()

            # Tenta pegar o conteúdo principal
            main = (
                soup.find("div", id="divArvoreAcoes") or
                soup.find("div", class_="infraAreaTelaD") or
                soup.find("div", id="main-content") or
                soup.find("main") or
                soup.find("body")
            )

            texto = (main or soup).get_text("\n", strip=True)
            texto = re.sub(r"\n{3,}", "\n\n", texto)[:10000]

            if usar_cache:
                cache_file.write_text(texto, encoding="utf-8")
            return texto

        except Exception as e:
            return f"[Erro ao ler documento: {e}]"


# ── Análise de processo ───────────────────────────────────────────────────────

async def analisar_processo_sei(
    numero_sei: str,
    session: Session,
    usar_llm_gratis: bool = True,
) -> dict:
    """
    Busca e analisa um processo SEI completo.

    1. Baixa metadados do processo
    2. Lê até 5 documentos principais
    3. Cruza com contratos no banco (por numero_sei)
    4. Aplica motor de padrões de fraude
    5. Opcionalmente usa LLM gratuito para análise semântica

    Retorna dict com: processo, contratos_associados, red_flags, resumo, alertas_gerados.
    """
    # Busca o processo
    processo = await buscar_processo(numero_sei)
    if processo.get("erro") and not processo.get("documentos"):
        return {"erro": processo["erro"], "numero": numero_sei}

    # Persiste no banco
    sei_db = session.query(ProcessoSEI).filter_by(numero_sei=numero_sei).first()
    if not sei_db:
        sei_db = ProcessoSEI(
            numero_sei    = numero_sei,
            tipo          = processo.get("tipo", "")[:100],
            assunto       = processo.get("assunto", ""),
            orgao_origem  = processo.get("orgao_origem", "")[:200],
            interessado   = ", ".join(processo.get("interessados", []))[:200],
            status        = processo.get("situacao", ""),
            documentos    = json.dumps(processo.get("documentos", []), ensure_ascii=False),
        )
        session.add(sei_db)
        session.commit()

    # Cruza com contratos
    contratos = (
        session.query(Contrato)
        .filter(Contrato.numero_sei == numero_sei)
        .all()
    )

    # Lê documentos principais (até 5)
    textos_docs = []
    for doc in processo.get("documentos", [])[:5]:
        if doc.get("url"):
            texto = await ler_documento_sei(doc["url"])
            if texto and not texto.startswith("[Erro"):
                textos_docs.append(texto[:2000])

    texto_completo = "\n\n---\n\n".join(textos_docs)

    # Análise de red flags
    red_flags = _analisar_red_flags_processo(processo, contratos, texto_completo)

    # Análise com LLM gratuito
    resumo_llm = ""
    if usar_llm_gratis and texto_completo:
        try:
            from compliance_agent.llm.free_llm import best_free_chat_async
            resumo_llm = await best_free_chat_async(
                prompt=(
                    "Analise este processo SEI do governo do RJ e identifique:\n"
                    "1. Objeto da contratação\n"
                    "2. Empresas e pessoas mencionadas\n"
                    "3. Valores envolvidos\n"
                    "4. Possíveis irregularidades\n\n"
                    f"Número SEI: {numero_sei}\n"
                    f"Tipo: {processo.get('tipo', '')}\n"
                    f"Conteúdo:\n{texto_completo[:3000]}"
                ),
                fallback="Análise LLM não disponível.",
            )
        except Exception as e:
            resumo_llm = f"[LLM gratuito indisponível: {e}]"

    # Gera alertas para red flags severos
    alertas_gerados = []
    if red_flags:
        for flag in red_flags:
            if flag.get("severidade") == "alta":
                titulo = f"SEI {numero_sei} — {flag['descricao'][:100]}"
                existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
                if not existe:
                    alerta = Alerta(
                        tipo       = "direcionamento",
                        severidade = "alta",
                        titulo     = titulo[:300],
                        descricao  = flag["descricao"],
                        evidencias = json.dumps(flag, ensure_ascii=False, default=str),
                        processo_sei_id = sei_db.id if sei_db else None,
                    )
                    session.add(alerta)
                    alertas_gerados.append({"titulo": titulo, "severidade": "alta"})
        if alertas_gerados:
            session.commit()

    return {
        "numero":              numero_sei,
        "processo":            processo,
        "contratos_associados": [
            {
                "numero": c.numero,
                "objeto": (c.objeto or "")[:200],
                "valor":  c.valor_total,
                "orgao":  c.orgao_contrat,
            }
            for c in contratos
        ],
        "red_flags":           red_flags,
        "resumo_llm":          resumo_llm,
        "alertas_gerados":     alertas_gerados,
        "n_documentos":        len(processo.get("documentos", [])),
    }


def _analisar_red_flags_processo(
    processo: dict,
    contratos: list,
    texto: str,
) -> list[dict]:
    """Aplica regras locais para identificar red flags no processo SEI."""
    from compliance_agent.knowledge.fraudes_licitacao import TODOS_RED_FLAGS
    from compliance_agent.knowledge.pattern_engine import match_patterns

    flags = []
    texto_lower = (
        processo.get("tipo", "") + " " +
        processo.get("assunto", "") + " " +
        texto
    ).lower()

    # Red flags por palavras-chave
    for flag_kw, pattern_id in TODOS_RED_FLAGS:
        if flag_kw in texto_lower:
            flags.append({
                "tipo":      "palavra_chave",
                "pattern":   pattern_id,
                "descricao": f"Termo suspeito encontrado: '{flag_kw}' (padrão: {pattern_id})",
                "severidade": "média",
            })

    # Cruza com padrões de fraude conhecidos
    contexto = {
        "objeto":     processo.get("assunto", ""),
        "tipo":       processo.get("tipo", ""),
        "texto":      texto[:1000],
        "n_contratos": len(contratos),
    }
    matches = match_patterns(contexto)
    for m in matches:
        flags.append({
            "tipo":      "padrao_fraude",
            "pattern":   m["pattern_id"],
            "descricao": m["descricao"],
            "score":     m["score"],
            "severidade": "alta" if m["score"] >= 0.7 else "média",
        })

    # Processos de reforma escolar: alerta especial (caso Thiago Rangel)
    termos_escola = ["reforma", "escola", "unidade escolar", "ensino", "educação",
                     "SEEDUC", "FAETEC", "CECIERJ"]
    if any(t in texto_lower for t in termos_escola):
        flags.append({
            "tipo":      "setor_monitorado",
            "pattern":   "reforma_escolar_rj",
            "descricao": (
                "Processo envolve setor de reformas escolares — monitorado por "
                "suspeitas de superfaturamento (caso em investigação, 2024-2025)."
            ),
            "severidade": "média",
        })

    # Deduplica
    vistos = set()
    unicos = []
    for f in flags:
        chave = f.get("pattern", "") + f.get("descricao", "")[:50]
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(f)

    return unicos


# ── Cruzamento SEI × SIAFE ────────────────────────────────────────────────────

def cruzar_sei_siafe(session: Session, numero_sei: str) -> dict:
    """
    Encontra todas as despesas SIAFE vinculadas a um processo SEI.
    Retorna: contratos, OBs (ordens bancárias), total empenhado, total pago.
    """
    contratos = (
        session.query(Contrato)
        .filter(Contrato.numero_sei.ilike(f"%{numero_sei}%"))
        .all()
    )

    total_valor = sum(c.valor_total or 0 for c in contratos)
    orgaos = list({c.orgao_contrat for c in contratos if c.orgao_contrat})
    empresas = list({c.empresa.razao_social if c.empresa else "" for c in contratos} - {""})

    return {
        "numero_sei":      numero_sei,
        "contratos":       [
            {
                "numero":     c.numero,
                "objeto":     (c.objeto or "")[:200],
                "orgao":      c.orgao_contrat,
                "empresa":    c.empresa.razao_social if c.empresa else "N/D",
                "valor":      c.valor_total,
                "modalidade": c.modalidade,
                "data":       str(c.data_assinatura) if c.data_assinatura else "",
            }
            for c in contratos
        ],
        "total_contratos": len(contratos),
        "valor_total":     total_valor,
        "orgaos":          orgaos,
        "empresas":        empresas,
    }


def buscar_sei_por_objeto(session: Session, termo: str) -> list[dict]:
    """Busca processos SEI indexados por termo no assunto."""
    processos = (
        session.query(ProcessoSEI)
        .filter(ProcessoSEI.assunto.ilike(f"%{termo}%"))
        .limit(30)
        .all()
    )
    return [
        {
            "numero_sei":  p.numero_sei,
            "tipo":        p.tipo,
            "assunto":     p.assunto,
            "orgao":       p.orgao_origem,
            "interessado": p.interessado,
            "status":      p.status,
        }
        for p in processos
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar_numero_sei(numero: str) -> str:
    """Normaliza número SEI para formato de busca."""
    return re.sub(r"\s+", "", numero.strip().upper())
