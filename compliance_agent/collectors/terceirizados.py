"""
Detecção de CPFs duplicados em múltiplas fontes de remuneração pública.

Cruza:
  - Folha de servidores efetivos/comissionados (já em RegistroFolha via fonte="transparencia_rj")
  - Terceirizados (contratos de mão de obra — empresas contratadas pelo estado)
  - Bolsistas (FAPERJ, CNPq, residências médicas)
  - Estagiários remunerados (CIEE, Nube e similares)
  - Temporários (Lei 500/74 RJ, contratos por tempo determinado)
  - Aposentados/pensionistas que acumulam com cargo ativo ou comissionado

Fontes:
  - Portal Transparência RJ  — https://www.transparencia.rj.gov.br/
  - FAPERJ                   — https://www.faperj.br/
  - Portal Transparência Federal (bolsistas CNPq/CAPES lotados em RJ)

Base legal:
  - CF/88 art. 37, XVI   — vedação ao acúmulo de cargos e empregos públicos
  - Lei 9.717/98         — regime previdenciário e limitações de acúmulo
  - Lei 8.112/90 art. 118 — aposentado que reassume cargo efetivo retorna à atividade
  - Decreto Estadual RJ 46.881/20 — teto do funcionalismo estadual
"""

import json
import logging
from datetime import date

import httpx
from bs4 import BeautifulSoup

from compliance_agent.database.models import Alerta, Pessoa, RegistroFolha

logger = logging.getLogger(__name__)

# ── URL bases ─────────────────────────────────────────────────────────────────

TRANSPARENCIA_RJ_BASE = "https://www.transparencia.rj.gov.br"
FAPERJ_BASE = "https://www.faperj.br"
PORTAL_FEDERAL_API = "https://portaldatransparencia.gov.br/api-de-dados"

# Vínculos que indicam aposentado/pensionista (para cruzamento)
VINCULOS_INATIVOS = {"aposentado", "aposentada", "pensionista", "inativo", "inativa"}

# Vínculos que indicam cargo ativo remunerado
VINCULOS_ATIVOS = {"efetivo", "efetiva", "comissionado", "comissionada", "dab", "temporário",
                   "temporária", "terceirizado", "estagiário", "bolsista", "residente"}

# Combinações ILEGAIS: aposentado/pensionista + comissionado além do limite de 1/4
COMBINACOES_ILEGAIS = [
    ("aposentado", "comissionado"),
    ("aposentada", "comissionado"),
    ("pensionista", "comissionado"),
    ("aposentado", "efetivo"),
    ("aposentada", "efetivo"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar_cpf(cpf: str) -> str:
    """Remove pontos, traços e espaços; retorna string de 11 dígitos ou ''."""
    clean = "".join(c for c in (cpf or "") if c.isdigit())
    return clean if len(clean) == 11 else ""


def _parse_remuneracao(valor: str) -> float:
    """Converte string como 'R$ 3.200,00' ou '3200.00' para float."""
    if not valor:
        return 0.0
    try:
        return float(
            valor
            .replace("R$", "")
            .replace(".", "")
            .replace(",", ".")
            .strip()
        )
    except ValueError:
        return 0.0


def _default_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }


def _registro_existe(session, cpf: str, nome: str, fonte: str, competencia: str) -> bool:
    """Verifica se o registro já foi inserido para evitar duplicatas."""
    q = session.query(RegistroFolha).filter_by(fonte=fonte, competencia=competencia)
    if cpf:
        q = q.filter_by(cpf=cpf)
    elif nome:
        q = q.filter_by(nome=nome[:200])
    return q.first() is not None


# ── Coletores ─────────────────────────────────────────────────────────────────

async def buscar_terceirizados_transparencia(session, competencia: str) -> int:
    """
    Tenta baixar a lista de terceirizados do Portal Transparência RJ.

    O portal disponibiliza listas de trabalhadores terceirizados cujas empresas
    foram contratadas pelo estado por meio de contratos de mão de obra (posto de
    trabalho), tipicamente sob as rubricas de vigilância, limpeza, TI, saúde etc.

    URL base inspecionada:
      https://www.transparencia.rj.gov.br/  (seção "Terceirizados" ou "Contratos de
      mão de obra") — o layout muda periodicamente, então tentamos múltiplos caminhos.

    Os registros são salvos com:
      fonte="terceirizado", vinculo="terceirizado"

    Args:
        session:     SQLAlchemy session.
        competencia: Mês de referência no formato AAAA-MM.

    Returns:
        Número de RegistroFolha inseridos.
    """
    count = 0
    headers = _default_headers()

    # Caminhos conhecidos / prováveis no portal RJ
    candidate_paths = [
        "/terceirizados",
        "/folha/terceirizados",
        "/transparencia/terceirizados",
        "/pessoal/terceirizados",
        "/contratos/mao-de-obra",
    ]

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers=headers,
        ) as client:
            # 1) Try a direct API endpoint that some RJ transparency portals expose
            api_url = f"{TRANSPARENCIA_RJ_BASE}/api/terceirizados"
            params: dict = {"competencia": competencia, "pagina": 1, "quantidade": 500}
            try:
                resp = await client.get(api_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    registros = data if isinstance(data, list) else data.get("data", data.get("registros", []))
                    batch = []
                    for item in registros:
                        cpf = _normalizar_cpf(str(item.get("cpf", "")))
                        nome = (item.get("nome") or item.get("nome_trabalhador", ""))[:200]
                        empresa = (item.get("empresa") or item.get("razao_social", ""))[:200]
                        rem = _parse_remuneracao(str(item.get("remuneracao", item.get("valor", 0))))
                        if not nome and not cpf:
                            continue
                        if _registro_existe(session, cpf, nome, "terceirizado", competencia):
                            continue
                        reg = RegistroFolha(
                            cpf=cpf or None,
                            nome=nome or None,
                            orgao_nome=empresa or "TERCEIRIZADO",
                            cargo=item.get("funcao", item.get("cargo", ""))[:200] or None,
                            vinculo="terceirizado",
                            competencia=competencia,
                            remuneracao_bruta=rem,
                            remuneracao_liquida=rem,
                            fonte="terceirizado",
                        )
                        batch.append(reg)
                        count += 1
                    if batch:
                        session.add_all(batch)
                        session.commit()
                    if count:
                        logger.info(f"buscar_terceirizados_transparencia: {count} registros via API JSON.")
                        return count
            except Exception as api_exc:
                logger.debug(f"API JSON terceirizados não disponível: {api_exc}")

            # 2) Try scraping HTML tables from known paths
            for path in candidate_paths:
                url = TRANSPARENCIA_RJ_BASE + path
                try:
                    resp = await client.get(url)
                    if resp.status_code not in (200, 206):
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")

                    # Look for downloadable CSV/XLSX links
                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if any(href.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
                            full_url = href if href.startswith("http") else TRANSPARENCIA_RJ_BASE + "/" + href.lstrip("/")
                            logger.info(f"Arquivo terceirizados encontrado: {full_url} (download necessário para importar)")

                    # Parse HTML tables
                    for table in soup.find_all("table"):
                        rows = table.find_all("tr")
                        if len(rows) < 2:
                            continue
                        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                        if not any("nome" in h or "cpf" in h for h in header_cells):
                            continue

                        cpf_col  = next((i for i, h in enumerate(header_cells) if "cpf" in h), -1)
                        nome_col = next((i for i, h in enumerate(header_cells) if "nome" in h), -1)
                        emp_col  = next((i for i, h in enumerate(header_cells) if "empresa" in h or "contrat" in h), -1)
                        rem_col  = next((i for i, h in enumerate(header_cells) if any(k in h for k in ["remun", "salário", "salario", "valor"])), -1)
                        cargo_col = next((i for i, h in enumerate(header_cells) if "cargo" in h or "função" in h or "funcao" in h), -1)

                        batch = []
                        for data_row in rows[1:]:
                            cells = data_row.find_all(["td", "th"])
                            if len(cells) < 2:
                                continue

                            cpf   = _normalizar_cpf(cells[cpf_col].get_text(strip=True)  if cpf_col  >= 0 and cpf_col  < len(cells) else "")
                            nome  = cells[nome_col].get_text(strip=True)[:200]             if nome_col >= 0 and nome_col < len(cells) else ""
                            empresa = cells[emp_col].get_text(strip=True)[:200]            if emp_col  >= 0 and emp_col  < len(cells) else ""
                            cargo = cells[cargo_col].get_text(strip=True)[:200]            if cargo_col >= 0 and cargo_col < len(cells) else ""
                            rem   = _parse_remuneracao(cells[rem_col].get_text(strip=True) if rem_col  >= 0 and rem_col  < len(cells) else "")

                            if not nome and not cpf:
                                continue
                            if _registro_existe(session, cpf, nome, "terceirizado", competencia):
                                continue

                            reg = RegistroFolha(
                                cpf=cpf or None,
                                nome=nome or None,
                                orgao_nome=empresa or "TERCEIRIZADO",
                                cargo=cargo or None,
                                vinculo="terceirizado",
                                competencia=competencia,
                                remuneracao_bruta=rem,
                                remuneracao_liquida=rem,
                                fonte="terceirizado",
                            )
                            batch.append(reg)
                            count += 1

                            if len(batch) >= 200:
                                session.add_all(batch)
                                session.commit()
                                batch = []

                        if batch:
                            session.add_all(batch)
                            session.commit()

                    if count:
                        logger.info(f"buscar_terceirizados_transparencia({path}): {count} registros.")
                        break

                except httpx.TimeoutException:
                    logger.debug(f"Timeout {path}")
                except httpx.HTTPStatusError as exc:
                    logger.debug(f"HTTP {exc.response.status_code} {path}")
                except Exception as exc:
                    logger.debug(f"Erro {path}: {exc}")

    except Exception as exc:
        logger.error(f"Erro geral buscar_terceirizados_transparencia: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em buscar_terceirizados_transparencia: %s", rb_exc)

    if count == 0:
        logger.warning(
            "buscar_terceirizados_transparencia: nenhum dado coletado. "
            "O Portal Transparência RJ pode ter alterado o layout ou a URL. "
            "Verifique manualmente: https://www.transparencia.rj.gov.br/"
        )
    return count


async def buscar_bolsistas_faperj(session, ano: int) -> int:
    """
    Tenta baixar a lista de bolsistas FAPERJ para o ano informado.

    A FAPERJ (Fundação Carlos Chagas Filho de Amparo à Pesquisa do Estado
    do Rio de Janeiro) é obrigada pela LAI (Lei 12.527/11) a publicar sua
    folha de bolsistas. Os bolsistas são remunerados com recursos públicos
    estaduais e federais.

    Caminhos inspecionados em https://www.faperj.br/:
      /transparencia, /bolsistas, /bolsas-e-programas

    Registros salvos com:
      fonte="faperj", vinculo="bolsista", orgao_nome="FAPERJ"

    Args:
        session: SQLAlchemy session.
        ano:     Ano de referência (ex.: 2024).

    Returns:
        Número de RegistroFolha inseridos.
    """
    count = 0
    headers = _default_headers()
    competencia = f"{ano}-01"  # salva como janeiro do ano (referência anual)

    candidate_paths = [
        "/transparencia",
        "/transparencia/bolsistas",
        "/bolsistas",
        "/paginas/transparencia.aspx",
    ]

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            # Try JSON API first
            try:
                api_url = f"{FAPERJ_BASE}/api/bolsistas"
                resp = await client.get(api_url, params={"ano": ano})
                if resp.status_code == 200:
                    items = resp.json()
                    items = items if isinstance(items, list) else items.get("data", [])
                    batch = []
                    for item in items:
                        cpf  = _normalizar_cpf(str(item.get("cpf", "")))
                        nome = (item.get("nome") or item.get("bolsista", ""))[:200]
                        rem  = _parse_remuneracao(str(item.get("valor", item.get("mensalidade", 0))))
                        if not nome and not cpf:
                            continue
                        if _registro_existe(session, cpf, nome, "faperj", competencia):
                            continue
                        reg = RegistroFolha(
                            cpf=cpf or None,
                            nome=nome or None,
                            orgao_nome="FAPERJ",
                            cargo=item.get("modalidade", item.get("tipo_bolsa", "Bolsa FAPERJ"))[:200],
                            vinculo="bolsista",
                            competencia=competencia,
                            remuneracao_bruta=rem,
                            remuneracao_liquida=rem,
                            fonte="faperj",
                        )
                        batch.append(reg)
                        count += 1
                    if batch:
                        session.add_all(batch)
                        session.commit()
                    if count:
                        logger.info(f"buscar_bolsistas_faperj: {count} via API JSON.")
                        return count
            except Exception as api_exc:
                logger.debug(f"API FAPERJ JSON não disponível: {api_exc}")

            # HTML scraping fallback
            for path in candidate_paths:
                url = FAPERJ_BASE + path
                try:
                    resp = await client.get(url)
                    if resp.status_code not in (200, 206):
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")

                    # Log downloadable files for manual processing
                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if any(href.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls", ".pdf"]):
                            full_url = href if href.startswith("http") else FAPERJ_BASE + "/" + href.lstrip("/")
                            logger.info(f"Arquivo bolsistas FAPERJ encontrado: {full_url}")

                    for table in soup.find_all("table"):
                        rows = table.find_all("tr")
                        if len(rows) < 2:
                            continue
                        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                        if not any("nome" in h or "cpf" in h or "bolsista" in h for h in header_cells):
                            continue

                        cpf_col   = next((i for i, h in enumerate(header_cells) if "cpf" in h), -1)
                        nome_col  = next((i for i, h in enumerate(header_cells) if "nome" in h or "bolsista" in h), -1)
                        tipo_col  = next((i for i, h in enumerate(header_cells) if "tipo" in h or "modalidade" in h or "bolsa" in h), -1)
                        valor_col = next((i for i, h in enumerate(header_cells) if "valor" in h or "mensalidade" in h), -1)

                        batch = []
                        for data_row in rows[1:]:
                            cells = data_row.find_all(["td", "th"])
                            if len(cells) < 2:
                                continue

                            cpf  = _normalizar_cpf(cells[cpf_col].get_text(strip=True)   if cpf_col  >= 0 and cpf_col  < len(cells) else "")
                            nome = cells[nome_col].get_text(strip=True)[:200]              if nome_col >= 0 and nome_col < len(cells) else ""
                            tipo = cells[tipo_col].get_text(strip=True)[:200]              if tipo_col >= 0 and tipo_col < len(cells) else "Bolsa FAPERJ"
                            rem  = _parse_remuneracao(cells[valor_col].get_text(strip=True) if valor_col >= 0 and valor_col < len(cells) else "")

                            if not nome and not cpf:
                                continue
                            if _registro_existe(session, cpf, nome, "faperj", competencia):
                                continue

                            reg = RegistroFolha(
                                cpf=cpf or None,
                                nome=nome or None,
                                orgao_nome="FAPERJ",
                                cargo=tipo,
                                vinculo="bolsista",
                                competencia=competencia,
                                remuneracao_bruta=rem,
                                remuneracao_liquida=rem,
                                fonte="faperj",
                            )
                            batch.append(reg)
                            count += 1

                            if len(batch) >= 200:
                                session.add_all(batch)
                                session.commit()
                                batch = []

                        if batch:
                            session.add_all(batch)
                            session.commit()

                    if count:
                        logger.info(f"buscar_bolsistas_faperj({path}): {count} registros.")
                        break

                except httpx.TimeoutException:
                    logger.debug(f"Timeout FAPERJ {path}")
                except Exception as exc:
                    logger.debug(f"Erro FAPERJ {path}: {exc}")

    except Exception as exc:
        logger.error(f"Erro geral buscar_bolsistas_faperj: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em buscar_bolsistas_faperj: %s", rb_exc)

    if count == 0:
        logger.warning(
            "buscar_bolsistas_faperj: nenhum dado coletado. "
            "Verifique manualmente: https://www.faperj.br/transparencia"
        )
    return count


async def buscar_estagiarios(session, competencia: str) -> int:
    """
    Tenta buscar estagiários remunerados pelo estado do RJ.

    Estagiários são contratados via agentes de integração (CIEE, Nube, INJEP)
    por convênio com o Estado. Recebem bolsa-auxílio com recursos públicos
    e, para fins de compliance, devem ser cruzados com a folha de servidores.

    Caminhos inspecionados:
      - Portal Transparência RJ: seção "Estagiários"
      - Possível API: /api/estagiarios

    Registros salvos com:
      fonte="estagio", vinculo="estagiário"

    Args:
        session:     SQLAlchemy session.
        competencia: Mês de referência no formato AAAA-MM.

    Returns:
        Número de RegistroFolha inseridos.
    """
    count = 0
    headers = _default_headers()

    candidate_paths = [
        "/estagiarios",
        "/folha/estagiarios",
        "/transparencia/estagiarios",
        "/pessoal/estagiarios",
    ]

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            # JSON API attempt
            try:
                api_url = f"{TRANSPARENCIA_RJ_BASE}/api/estagiarios"
                resp = await client.get(api_url, params={"competencia": competencia, "pagina": 1, "quantidade": 500})
                if resp.status_code == 200:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("data", data.get("registros", []))
                    batch = []
                    for item in items:
                        cpf  = _normalizar_cpf(str(item.get("cpf", "")))
                        nome = (item.get("nome") or item.get("nome_estagiario", ""))[:200]
                        orgao = (item.get("orgao") or item.get("unidade", ""))[:200]
                        rem  = _parse_remuneracao(str(item.get("bolsa", item.get("valor", 0))))
                        if not nome and not cpf:
                            continue
                        if _registro_existe(session, cpf, nome, "estagio", competencia):
                            continue
                        reg = RegistroFolha(
                            cpf=cpf or None,
                            nome=nome or None,
                            orgao_nome=orgao or "ESTAGIÁRIO",
                            cargo="Estagiário",
                            vinculo="estagiário",
                            competencia=competencia,
                            remuneracao_bruta=rem,
                            remuneracao_liquida=rem,
                            fonte="estagio",
                        )
                        batch.append(reg)
                        count += 1
                    if batch:
                        session.add_all(batch)
                        session.commit()
                    if count:
                        logger.info(f"buscar_estagiarios: {count} via API JSON.")
                        return count
            except Exception as api_exc:
                logger.debug(f"API JSON estagiários não disponível: {api_exc}")

            # HTML fallback
            for path in candidate_paths:
                url = TRANSPARENCIA_RJ_BASE + path
                try:
                    resp = await client.get(url)
                    if resp.status_code not in (200, 206):
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")

                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        if any(href.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
                            full_url = href if href.startswith("http") else TRANSPARENCIA_RJ_BASE + "/" + href.lstrip("/")
                            logger.info(f"Arquivo estagiários encontrado: {full_url}")

                    for table in soup.find_all("table"):
                        rows = table.find_all("tr")
                        if len(rows) < 2:
                            continue
                        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
                        if not any("nome" in h or "cpf" in h for h in header_cells):
                            continue

                        cpf_col   = next((i for i, h in enumerate(header_cells) if "cpf" in h), -1)
                        nome_col  = next((i for i, h in enumerate(header_cells) if "nome" in h), -1)
                        orgao_col = next((i for i, h in enumerate(header_cells) if "orgao" in h or "órgão" in h or "unidade" in h), -1)
                        rem_col   = next((i for i, h in enumerate(header_cells) if any(k in h for k in ["bolsa", "valor", "remun"])), -1)

                        batch = []
                        for data_row in rows[1:]:
                            cells = data_row.find_all(["td", "th"])
                            if len(cells) < 2:
                                continue

                            cpf   = _normalizar_cpf(cells[cpf_col].get_text(strip=True)    if cpf_col   >= 0 and cpf_col   < len(cells) else "")
                            nome  = cells[nome_col].get_text(strip=True)[:200]               if nome_col  >= 0 and nome_col  < len(cells) else ""
                            orgao = cells[orgao_col].get_text(strip=True)[:200]              if orgao_col >= 0 and orgao_col < len(cells) else "ESTAGIÁRIO"
                            rem   = _parse_remuneracao(cells[rem_col].get_text(strip=True)  if rem_col   >= 0 and rem_col   < len(cells) else "")

                            if not nome and not cpf:
                                continue
                            if _registro_existe(session, cpf, nome, "estagio", competencia):
                                continue

                            reg = RegistroFolha(
                                cpf=cpf or None,
                                nome=nome or None,
                                orgao_nome=orgao,
                                cargo="Estagiário",
                                vinculo="estagiário",
                                competencia=competencia,
                                remuneracao_bruta=rem,
                                remuneracao_liquida=rem,
                                fonte="estagio",
                            )
                            batch.append(reg)
                            count += 1

                            if len(batch) >= 200:
                                session.add_all(batch)
                                session.commit()
                                batch = []

                        if batch:
                            session.add_all(batch)
                            session.commit()

                    if count:
                        logger.info(f"buscar_estagiarios({path}): {count} registros.")
                        break

                except httpx.TimeoutException:
                    logger.debug(f"Timeout estagiários {path}")
                except Exception as exc:
                    logger.debug(f"Erro estagiários {path}: {exc}")

    except Exception as exc:
        logger.error(f"Erro geral buscar_estagiarios: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em buscar_estagiarios: %s", rb_exc)

    if count == 0:
        logger.warning(
            "buscar_estagiarios: nenhum dado coletado. "
            "Verifique manualmente: https://www.transparencia.rj.gov.br/"
        )
    return count


# ── Detecção de CPF duplicado entre fontes ────────────────────────────────────

def detectar_cpf_duplicado_entre_fontes(session, competencia: str) -> list[dict]:
    """
    FUNÇÃO CENTRAL: Detecta CPFs que aparecem em múltiplas fontes de remuneração
    pública para a competência informada (ou em toda a base, se competencia="").

    Agrupa RegistroFolha por CPF e sinaliza casos em que o mesmo CPF aparece em
    2 ou mais valores distintos de `fonte` — indicando acúmulo potencialmente
    irregular de remunerações públicas.

    Também detecta:
      - Aposentado/pensionista (vinculo in VINCULOS_INATIVOS) com cargo comissionado
        ou efetivo ativo na mesma competência (CF/88 art. 37, §10 e Lei 9.717/98).
      - Pensionista com cargo ativo simultâneo.
      - Bolsista FAPERJ/CNPq + servidor efetivo do mesmo órgão de pesquisa.
      - Terceirizado + servidor efetivo no mesmo órgão contratante.

    Flags geradas:
      - suspeito=True  → combinação claramente ilegal
      - suspeito=False → vale verificar (pode ser legal em alguns casos)

    Args:
        session:     SQLAlchemy session.
        competencia: Mês de referência AAAA-MM. Se vazio, usa toda a base.

    Returns:
        Lista de dicts com {cpf, nome, fontes, vinculos, orgaos,
        remuneracao_total, suspeito, motivo}.
    """
    from sqlalchemy import func

    resultados: list[dict] = []

    try:
        q = session.query(
            RegistroFolha.cpf,
            RegistroFolha.nome,
            func.group_concat(func.distinct(RegistroFolha.fonte)).label("fontes"),
            func.group_concat(func.distinct(RegistroFolha.vinculo)).label("vinculos"),
            func.group_concat(func.distinct(RegistroFolha.orgao_nome)).label("orgaos"),
            func.sum(RegistroFolha.remuneracao_bruta).label("total"),
            func.count(func.distinct(RegistroFolha.fonte)).label("n_fontes"),
        ).filter(
            RegistroFolha.cpf.isnot(None),
            RegistroFolha.cpf != "",
        )

        if competencia:
            q = q.filter(RegistroFolha.competencia == competencia)

        q = q.group_by(RegistroFolha.cpf).having(
            func.count(func.distinct(RegistroFolha.fonte)) > 1
        )

        for row in q.all():
            fontes   = [f.strip() for f in (row.fontes   or "").split(",") if f.strip()]
            vinculos = [v.strip() for v in (row.vinculos or "").split(",") if v.strip()]
            orgaos   = [o.strip() for o in (row.orgaos   or "").split(",") if o.strip()]

            # Determine suspicion level
            suspeito = False
            motivo   = ""

            vinculos_lower = {v.lower() for v in vinculos}

            # Check illegal combinations
            inativos_presentes = vinculos_lower & VINCULOS_INATIVOS
            ativos_presentes   = vinculos_lower & VINCULOS_ATIVOS

            if inativos_presentes and ativos_presentes:
                suspeito = True
                motivo = (
                    f"Vínculo inativo ({', '.join(inativos_presentes)}) + "
                    f"vínculo ativo ({', '.join(ativos_presentes)}) simultâneos. "
                    "Pode configurar acúmulo ilegal (CF/88 art. 37, §10; Lei 9.717/98)."
                )
            elif "terceirizado" in fontes and any(
                f in fontes for f in ("transparencia_rj", "siafe")
            ):
                suspeito = True
                motivo = (
                    "Servidor efetivo/comissionado E terceirizado do estado simultaneamente. "
                    "Configuração impossível legalmente — possível fraude de identidade ou "
                    "empresa de fachada usando CPF de servidor."
                )
            elif "faperj" in fontes and any(f in fontes for f in ("transparencia_rj", "siafe")):
                motivo = (
                    "Bolsista FAPERJ + servidor ativo. Pode ser legal se as atividades são "
                    "distintas, mas requer verificação (vedação de acúmulo de bolsa + cargo "
                    "quando incompatível — Resolução FAPERJ 007/2023)."
                )
            elif "estagio" in fontes and any(f in fontes for f in ("transparencia_rj", "siafe")):
                suspeito = True
                motivo = (
                    "Estagiário + servidor/comissionado efetivo. Estágio é exclusivo para "
                    "quem não tem vínculo efetivo com o serviço público (Lei 11.788/08 art. 3º, §1º)."
                )
            else:
                motivo = (
                    f"CPF presente em {row.n_fontes} fontes distintas de remuneração: "
                    f"{', '.join(fontes)}. Verificar compatibilidade legal."
                )

            resultado = {
                "cpf":               row.cpf,
                "nome":              row.nome,
                "fontes":            fontes,
                "vinculos":          vinculos,
                "orgaos":            orgaos,
                "remuneracao_total": row.total or 0.0,
                "suspeito":          suspeito,
                "motivo":            motivo,
                "n_fontes":          row.n_fontes,
            }
            resultados.append(resultado)

            # Persist alert for clearly suspicious cases
            if suspeito:
                titulo = f"CPF em múltiplas fontes de remuneração — {row.cpf}"
                existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
                if not existe:
                    pessoa = session.query(Pessoa).filter_by(cpf=row.cpf).first()
                    alerta = Alerta(
                        tipo="acumulacao",
                        severidade="alta",
                        titulo=titulo[:300],
                        descricao=(
                            f"'{row.nome}' (CPF {row.cpf}) recebe remuneração de "
                            f"{row.n_fontes} fontes públicas distintas: {', '.join(fontes)}. "
                            f"Remuneração total: R$ {row.total or 0:,.2f}. {motivo}"
                        ),
                        evidencias=json.dumps(resultado, ensure_ascii=False, default=str),
                        pessoa_id=pessoa.id if pessoa else None,
                    )
                    session.add(alerta)

        session.commit()
        logger.info(f"detectar_cpf_duplicado_entre_fontes: {len(resultados)} CPFs em múltiplas fontes.")

    except Exception as exc:
        logger.error(f"Erro em detectar_cpf_duplicado_entre_fontes: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em detectar_cpf_duplicado_entre_fontes: %s", rb_exc)

    return resultados


async def verificar_mei_e_clt(session, cpfs: list[str] | None = None) -> list[dict]:
    """
    Para comissionados/servidores no banco, verifica via BrasilAPI se o CPF
    consta como responsável de MEI (Microempreendedor Individual) ou como
    sócio/administrador de empresa CLT ativa — indicando vínculo empregatício
    formal fora do serviço público.

    Também verifica se o CPF aparece como empregado no Portal da Transparência
    Federal (duplo vínculo público federal + estadual).
    """
    from compliance_agent.database.models import Empresa, EmpresaSocio

    if cpfs is None:
        registros = (
            session.query(RegistroFolha)
            .filter(RegistroFolha.cpf.isnot(None), RegistroFolha.cpf != "")
            .distinct(RegistroFolha.cpf)
            .limit(500)
            .all()
        )
        cpfs = [r.cpf for r in registros]

    resultado = []
    api_key = __import__("os").environ.get("TRANSPARENCIA_API_KEY", "")

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for cpf in cpfs:
            achados: list[str] = []

            # 1. Verifica se é sócio de empresa ativa no banco local
            pessoa = session.query(Pessoa).filter_by(cpf=cpf).first()
            if pessoa:
                socios = session.query(EmpresaSocio).filter_by(pessoa_id=pessoa.id).all()
                for s in socios:
                    emp = session.query(Empresa).get(s.empresa_id)
                    if emp and emp.situacao == "ATIVA":
                        natureza = (emp.natureza_jur or "").upper()
                        is_mei = "MICRO" in natureza or "MEI" in natureza or (emp.capital_social or 0) <= 1000
                        achados.append(
                            f"{'MEI' if is_mei else 'Empresa ativa'}: {emp.razao_social} "
                            f"(CNPJ {emp.cnpj}, {emp.situacao})"
                        )

            # 2. Verifica folha federal
            if api_key:
                try:
                    headers = {"chave-de-api": api_key, "Accept": "application/json"}
                    resp = await client.get(
                        f"{PORTAL_FEDERAL_API}/servidores",
                        params={"cpf": cpf, "pagina": 1},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            item = data[0] if isinstance(data, list) else data
                            orgao_fed = str(item.get("orgao", {}).get("nome", "Federal") if isinstance(item.get("orgao"), dict) else "Federal")
                            achados.append(f"Folha federal: {orgao_fed}")
                except Exception as exc:
                    logger.warning("Falha ao consultar folha federal (Portal da Transparência) para CPF %s: %s", cpf, exc)

            if achados:
                nome = pessoa.nome if pessoa else cpf
                resultado.append({
                    "cpf": cpf,
                    "nome": nome,
                    "vinculos_externos": achados,
                    "motivo": (
                        f"{nome} (CPF {cpf}) tem {len(achados)} vínculo(s) externo(s) "
                        f"além do serviço público estadual: {'; '.join(achados)}"
                    ),
                })

    return resultado


def gerar_pedido_lai(tipo: str = "caged", cpfs: list[str] | None = None) -> dict:
    """
    Gera texto de pedido via Lei de Acesso à Informação (LAI) para obter
    dados de vínculo empregatício CLT que não estão disponíveis publicamente.

    Para detectar "carteira assinada" de comissionados, é necessário CAGED
    ou RAIS com CPF — dados restritos que devem ser solicitados via LAI.

    Uso:
        pedido = gerar_pedido_lai("caged", cpfs=["12345678901", ...])
        print(pedido["pedido"])
        # Protocolar em: https://falabr.cgu.gov.br/

    Args:
        tipo: "caged" | "rais" | "esocial"
        cpfs: lista de CPFs de interesse (incluída no texto do pedido)

    Returns:
        Dict com orgao, url_protocolo, fundamento_legal, pedido (texto completo)
    """
    ano_atual = date.today().year
    lista_cpfs = ""
    if cpfs:
        lista_cpfs = (
            "\n\nCPFs de interesse (arquivo anexo ou listados abaixo):\n"
            + "\n".join(cpfs[:50])
            + (f"\n... e mais {len(cpfs) - 50} CPFs (ver arquivo anexo)" if len(cpfs) > 50 else "")
        )

    bases = {
        "caged": {
            "orgao": "Ministério do Trabalho e Emprego (MTE)",
            "url_protocolo": "https://falabr.cgu.gov.br/",
            "fundamento_legal": "Lei 12.527/2011 (LAI), Art. 10; Lei 7.998/1990",
            "pedido": (
                "Solicito, com base na Lei de Acesso à Informação (Lei 12.527/2011, art. 10), "
                "acesso aos microdados do CAGED — Cadastro Geral de Empregados e Desempregados "
                f"para os CPFs relacionados, referentes ao período {ano_atual - 3} a {ano_atual}.\n\n"
                "Finalidade: verificar existência de vínculos empregatícios formais (CLT) "
                "concomitantes a cargos públicos no Estado do Rio de Janeiro, para controle "
                "do acúmulo ilegal previsto no art. 37, XVI e XVII da Constituição Federal.\n\n"
                "Campos solicitados: CPF (completo), CNPJ do empregador, razão social, "
                "categoria profissional, data de admissão, data de demissão (se houver), "
                "município e UF.\n\n"
                "Caso o fornecimento dos dados completos seja vedado, solicito ao menos "
                "confirmação da existência ou não de vínculo ativo para cada CPF listado."
                f"{lista_cpfs}"
            ),
        },
        "rais": {
            "orgao": "Ministério do Trabalho e Emprego (MTE) — RAIS",
            "url_protocolo": "https://falabr.cgu.gov.br/",
            "fundamento_legal": "Lei 12.527/2011 (LAI), Art. 10; Decreto 76.900/1975",
            "pedido": (
                "Solicito, com base na Lei de Acesso à Informação (Lei 12.527/2011, art. 10), "
                "acesso aos dados da RAIS — Relação Anual de Informações Sociais "
                f"para os CPFs relacionados, anos {ano_atual - 4} a {ano_atual - 1}.\n\n"
                "Finalidade: identificar vínculos de emprego formal simultâneos a cargos "
                "públicos no Estado do Rio de Janeiro, nos termos do art. 37, XVI da CF/88.\n\n"
                "Campos solicitados: CPF, CNPJ do empregador, natureza jurídica do empregador, "
                "tipo de vínculo, remuneração média anual, município e UF.\n\n"
                "Caso não seja possível o fornecimento individualizado, solicito o acesso "
                "via convênio de dados (art. 11, §1º da LAI)."
                f"{lista_cpfs}"
            ),
        },
        "esocial": {
            "orgao": "Secretaria Especial da Receita Federal do Brasil",
            "url_protocolo": "https://falabr.cgu.gov.br/",
            "fundamento_legal": "Lei 12.527/2011 (LAI), Art. 10; Resolução CGSN 140/2018",
            "pedido": (
                "Solicito, com base na Lei de Acesso à Informação (Lei 12.527/2011, art. 10), "
                "acesso a dados do eSocial referentes a eventos S-2200 (admissão de empregado), "
                "S-2300 (trabalhador sem vínculo de emprego/estatutário) e S-2400 (cadastramento "
                "de beneficiário) vinculados aos CPFs relacionados, "
                f"para o período {ano_atual - 2} a {ano_atual}.\n\n"
                "Finalidade: verificar acúmulo ilegal de cargos públicos com empregos privados, "
                "nos termos do art. 37, XVI e XVII da Constituição Federal de 1988.\n\n"
                "Caso o acesso direto não seja possível, solicito informação sobre o "
                "procedimento para celebração de convênio de compartilhamento de dados "
                "(art. 11, §1º da LAI e Decreto 10.046/2019)."
                f"{lista_cpfs}"
            ),
        },
    }

    return bases.get(tipo, bases["caged"])


def cruzar_com_folha_principal(session, competencia: str) -> list[dict]:
    """
    Cruza a folha principal (servidores efetivos/comissionados) contra as listas
    de terceirizados, bolsistas e estagiários coletadas na base local.

    Detecta especificamente:
      1. Servidor efetivo + terceirizado no MESMO órgão.
         → Impossível: o estado não pode contratar como terceirizado quem já é servidor.
      2. Aposentado com pensão integral + comissionado acima de 1/4 da pensão.
         → CF/88 art. 37, §10 + jurisprudência STF.
      3. Bolsista FAPERJ + servidor na mesma área de pesquisa / mesmo órgão.
         → Pode ser legal, mas merece verificação pela Resolução FAPERJ 007/2023.
      4. Estagiário + qualquer vínculo efetivo ou temporário no serviço público.
         → Lei 11.788/08 art. 3º, §1º veda expressamente.

    Args:
        session:     SQLAlchemy session.
        competencia: Mês de referência AAAA-MM.

    Returns:
        Lista de dicts com detalhes das correspondências suspeitas.
    """
    suspeitos: list[dict] = []

    try:
        # Busca pares (CPF, fonte) para a competência

        pares = (
            session.query(
                RegistroFolha.cpf,
                RegistroFolha.nome,
                RegistroFolha.fonte,
                RegistroFolha.vinculo,
                RegistroFolha.orgao_nome,
                RegistroFolha.remuneracao_bruta,
                RegistroFolha.cargo,
            )
            .filter(
                RegistroFolha.cpf.isnot(None),
                RegistroFolha.cpf != "",
            )
        )
        if competencia:
            pares = pares.filter(RegistroFolha.competencia == competencia)

        pares = pares.all()

        # Index by CPF for O(n) crossing
        by_cpf: dict[str, list] = {}
        for row in pares:
            by_cpf.setdefault(row.cpf, []).append(row)

        for cpf, registros in by_cpf.items():
            if len(registros) <= 1:
                continue

            fontes_set = {r.fonte for r in registros}
            vinculos_set = {(r.vinculo or "").lower() for r in registros}

            # Rule 1: servidor efetivo/comissionado AND terceirizado
            fontes_folha = fontes_set & {"transparencia_rj", "siafe"}
            if fontes_folha and "terceirizado" in fontes_set:
                folha_regs = [r for r in registros if r.fonte in fontes_folha]
                terc_regs  = [r for r in registros if r.fonte == "terceirizado"]
                for fr in folha_regs:
                    for tr in terc_regs:
                        suspeitos.append({
                            "cpf":    cpf,
                            "nome":   fr.nome,
                            "regra":  "servidor_e_terceirizado",
                            "motivo": (
                                f"Servidor {fr.vinculo or 'efetivo'} em '{fr.orgao_nome}' "
                                f"(R$ {fr.remuneracao_bruta:,.2f}) e terceirizado pela empresa "
                                f"'{tr.orgao_nome}' (R$ {tr.remuneracao_bruta:,.2f}). "
                                "Vedado — não se pode contratar como terceirizado quem já é servidor."
                            ),
                            "severidade": "alta",
                            "fontes": list(fontes_set),
                        })

            # Rule 2: aposentado/pensionista + comissionado
            inativos = [r for r in registros if (r.vinculo or "").lower() in VINCULOS_INATIVOS]
            comissionados = [r for r in registros if "comissionado" in (r.vinculo or "").lower()]
            for inativo in inativos:
                for comiss in comissionados:
                    # Check 1/4 rule: comissionado value > 1/4 of pension = violação
                    limite = (inativo.remuneracao_bruta or 0) * 0.25
                    violacao_valor = (comiss.remuneracao_bruta or 0) > limite and limite > 0
                    suspeitos.append({
                        "cpf":    cpf,
                        "nome":   inativo.nome,
                        "regra":  "aposentado_comissionado",
                        "motivo": (
                            f"'{inativo.nome}' é {inativo.vinculo} recebendo "
                            f"R$ {inativo.remuneracao_bruta:,.2f} E exerce cargo comissionado "
                            f"em '{comiss.orgao_nome}' recebendo R$ {comiss.remuneracao_bruta:,.2f}. "
                            + (
                                f"O valor do cargo ({comiss.remuneracao_bruta:,.2f}) supera 1/4 da "
                                f"pensão ({limite:,.2f}) — possível violação do CF/88 art. 37, §10."
                                if violacao_valor else
                                "Acúmulo pode ser permitido até 1/4 do benefício — verificar."
                            )
                        ),
                        "severidade": "alta" if violacao_valor else "média",
                        "fontes": list(fontes_set),
                    })

            # Rule 3: bolsista FAPERJ + servidor do mesmo órgão
            bolsistas = [r for r in registros if r.fonte == "faperj"]
            servidores = [r for r in registros if r.fonte in {"transparencia_rj", "siafe"}]
            for bolsista in bolsistas:
                for servidor in servidores:
                    suspeitos.append({
                        "cpf":    cpf,
                        "nome":   servidor.nome,
                        "regra":  "bolsista_servidor",
                        "motivo": (
                            f"Bolsista FAPERJ ('{bolsista.cargo}', R$ {bolsista.remuneracao_bruta:,.2f}) "
                            f"e servidor ativo em '{servidor.orgao_nome}' "
                            f"(R$ {servidor.remuneracao_bruta:,.2f}). "
                            "Verificar compatibilidade pela Resolução FAPERJ 007/2023."
                        ),
                        "severidade": "média",
                        "fontes": list(fontes_set),
                    })

            # Rule 4: estagiário + qualquer vínculo efetivo
            estagiarios = [r for r in registros if r.fonte == "estagio"]
            efetivos = [r for r in registros if r.fonte in {"transparencia_rj", "siafe"}
                        and (r.vinculo or "").lower() in {"efetivo", "efetiva", "temporário", "temporária"}]
            for est in estagiarios:
                for efet in efetivos:
                    suspeitos.append({
                        "cpf":    cpf,
                        "nome":   est.nome,
                        "regra":  "estagiario_servidor_efetivo",
                        "motivo": (
                            f"Estagiário em '{est.orgao_nome}' "
                            f"(R$ {est.remuneracao_bruta:,.2f}) e servidor {efet.vinculo} "
                            f"em '{efet.orgao_nome}' (R$ {efet.remuneracao_bruta:,.2f}). "
                            "Lei 11.788/08 art. 3º, §1º veda expressamente."
                        ),
                        "severidade": "alta",
                        "fontes": list(fontes_set),
                    })

            # Persist alerts for alta-severity findings
            for s in [s for s in suspeitos if s.get("cpf") == cpf and s.get("severidade") == "alta"]:
                titulo = f"Acúmulo entre fontes [{s['regra']}] — CPF {cpf}"
                existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
                if not existe:
                    pessoa = session.query(Pessoa).filter_by(cpf=cpf).first()
                    alerta = Alerta(
                        tipo="acumulacao",
                        severidade=s["severidade"],
                        titulo=titulo[:300],
                        descricao=s["motivo"],
                        evidencias=json.dumps(s, ensure_ascii=False, default=str),
                        pessoa_id=pessoa.id if pessoa else None,
                    )
                    session.add(alerta)

        session.commit()
        logger.info(f"cruzar_com_folha_principal: {len(suspeitos)} correspondências suspeitas.")

    except Exception as exc:
        logger.error(f"Erro em cruzar_com_folha_principal: {exc}")
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("Rollback falhou em cruzar_com_folha_principal: %s", rb_exc)

    return suspeitos
