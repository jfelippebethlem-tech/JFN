"""
CAGED / Multi-payroll cross-reference collector.

Detects:
  (a) People registered in multiple government payrolls simultaneously.
  (b) People with public employment + private CLT employment.
  (c) Ghost public servants (registered but not paid).

Data sources:
  - RJ state payroll: already in RegistroFolha table
  - Federal payroll: Portal da Transparência Federal API
  - External organs: ALERJ, TJRJ, MPRJ, Defensoria Pública (scraping)
"""

import json
import logging
import os
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from compliance_agent.database.models import Alerta, Pessoa, RegistroFolha

logger = logging.getLogger(__name__)

PORTAL_TRANSPARENCIA_API = "https://portaldatransparencia.gov.br/api-de-dados"

# External organ transparency portal URLs
ORGAO_URLS = {
    "alerj":    "https://www.alerj.rj.gov.br/transparencia/pessoal",
    "tjrj":     "https://www.tjrj.jus.br/web/guest/transparencia",
    "mprj":     "https://www.mprj.mp.br/transparencia",
    "defensoria": "https://defensoria.rj.def.br/transparencia",
}

# CF/88 art. 37, XVI: accumulation ONLY allowed for specific combinations
ACUMULACAO_PERMITIDA = {
    # (cargo_técnico, magistério) is explicitly allowed
    frozenset({"professor", "técnico"}),
    frozenset({"médico", "professor"}),
    frozenset({"engenheiro", "professor"}),
}

# Keywords that suggest a technical/teaching role
TECH_KEYWORDS = {"técnico", "tecnologista", "pesquisador", "analista", "especialista"}
MAGISTERIO_KEYWORDS = {"professor", "docente", "magistério", "ensino"}


def _is_permitted_accumulation(orgaos: list[str], cargos: list[str]) -> bool:
    """
    Returns True if the multi-organ combination is a permitted accumulation
    (e.g., technical career + teaching position under CF/88 art. 37, XVI-b).
    """
    if len(orgaos) <= 1:
        return True

    cargo_set = set()
    for cargo in cargos:
        if not cargo:
            continue
        lower = cargo.lower()
        if any(kw in lower for kw in TECH_KEYWORDS):
            cargo_set.add("técnico")
        if any(kw in lower for kw in MAGISTERIO_KEYWORDS):
            cargo_set.add("professor")

    # If both technical and teaching: permitted
    if "técnico" in cargo_set and "professor" in cargo_set and len(orgaos) == 2:
        return True

    return False


async def buscar_servidor_federal(cpf: str, api_key: str = "") -> dict:
    """
    Query the Portal da Transparência Federal API for a civil servant by CPF.

    Args:
        cpf:     CPF (digits only, 11 chars).
        api_key: Optional API key from portaldatransparencia.gov.br.

    Returns:
        Dict with servant data or {"found": False} if not found / error.
    """
    clean_cpf = "".join(c for c in cpf if c.isdigit())
    if len(clean_cpf) != 11:
        return {"found": False, "erro": "CPF inválido"}

    headers: dict = {
        "Accept": "application/json",
        "User-Agent": "JFN-Compliance/2.0",
    }
    if api_key:
        headers["chave-de-api"] = api_key

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{PORTAL_TRANSPARENCIA_API}/servidores",
                params={"cpf": clean_cpf},
                headers=headers,
            )

            if resp.status_code == 404:
                return {"found": False}
            if resp.status_code == 401:
                return {"found": False, "erro": "API key inválida ou necessária"}
            resp.raise_for_status()

            data = resp.json()
            if not data:
                return {"found": False}

            # Normalize response structure
            item = data[0] if isinstance(data, list) else data
            return {
                "found": True,
                "nome": item.get("nome", ""),
                "cpf": clean_cpf,
                "orgao": item.get("orgaoExercicio", {}).get("nome", "") if isinstance(item.get("orgaoExercicio"), dict) else str(item.get("orgaoExercicio", "")),
                "cargo": item.get("descricaoCargo", ""),
                "situacao": item.get("situacaoVinculo", {}).get("nome", "") if isinstance(item.get("situacaoVinculo"), dict) else str(item.get("situacaoVinculo", "")),
                "remuneracao": item.get("remuneracaoBasicaBruta", 0),
            }

    except httpx.TimeoutException:
        logger.warning(f"Timeout ao consultar transparência federal CPF {clean_cpf}")
        return {"found": False, "erro": "timeout"}
    except Exception as exc:
        logger.error(f"Erro ao consultar transparência federal: {exc}")
        return {"found": False, "erro": str(exc)}


async def cruzar_folhas_multiplas(session) -> list[dict]:
    """
    Detect CPFs that appear in multiple government payrolls simultaneously.

    Checks:
      1. Same CPF in multiple distinct organs in our local RegistroFolha table.
      2. Optionally cross-references with the Federal transparency API.

    Args:
        session: SQLAlchemy session.

    Returns:
        List of suspect records: {cpf, nome, orgaos_estado, also_federal, detalhes}.
    """
    from sqlalchemy import func

    suspeitos = []
    api_key = os.environ.get("TRANSPARENCIA_API_KEY", "")

    try:
        # Find CPFs with multiple distinct organs in our DB
        q = (
            session.query(
                RegistroFolha.cpf,
                RegistroFolha.nome,
                func.count(func.distinct(RegistroFolha.orgao_nome)).label("n_orgaos"),
                func.group_concat(func.distinct(RegistroFolha.orgao_nome)).label("lista_orgaos"),
                func.group_concat(func.distinct(RegistroFolha.cargo)).label("lista_cargos"),
                func.sum(RegistroFolha.remuneracao_bruta).label("total_bruto"),
            )
            .filter(
                RegistroFolha.cpf.isnot(None),
                RegistroFolha.cpf != "",
                RegistroFolha.remuneracao_bruta > 0,
            )
            .group_by(RegistroFolha.cpf)
            .having(func.count(func.distinct(RegistroFolha.orgao_nome)) > 1)
            .all()
        )

        for row in q:
            orgaos = [o.strip() for o in (row.lista_orgaos or "").split(",") if o.strip()]
            cargos = [c.strip() for c in (row.lista_cargos or "").split(",") if c.strip()]

            # Skip if permitted accumulation
            if _is_permitted_accumulation(orgaos, cargos):
                continue

            # Check federal payroll if API key configured
            also_federal = False
            federal_data = {}
            if api_key and row.cpf:
                federal_data = await buscar_servidor_federal(row.cpf, api_key)
                also_federal = federal_data.get("found", False)

            suspeito = {
                "cpf": row.cpf,
                "nome": row.nome,
                "orgaos_estado": orgaos,
                "n_orgaos": row.n_orgaos,
                "total_bruto": row.total_bruto,
                "also_federal": also_federal,
                "detalhes": federal_data if also_federal else {},
            }
            suspeitos.append(suspeito)

            # Create alert
            titulo = f"Múltiplos empregos públicos — CPF {row.cpf}"
            existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
            if not existe:
                severidade = "alta" if also_federal or row.n_orgaos > 2 else "média"
                alerta = Alerta(
                    tipo="acumulacao",
                    severidade=severidade,
                    titulo=titulo[:300],
                    descricao=(
                        f"'{row.nome}' (CPF {row.cpf}) aparece em {row.n_orgaos} órgãos "
                        f"distintos: {', '.join(orgaos[:5])}. Remuneração total: "
                        f"R$ {row.total_bruto:,.2f}."
                        + (f" Também encontrado no funcionalismo federal ({federal_data.get('orgao', '')})." if also_federal else "")
                    ),
                    evidencias=json.dumps(suspeito, ensure_ascii=False, default=str),
                    pessoa_id=session.query(Pessoa).filter_by(cpf=row.cpf).first().id
                    if session.query(Pessoa).filter_by(cpf=row.cpf).first()
                    else None,
                )
                session.add(alerta)

        session.commit()
        logger.info(f"cruzar_folhas_multiplas: {len(suspeitos)} suspeitos encontrados.")

    except Exception as exc:
        logger.error(f"Erro em cruzar_folhas_multiplas: {exc}")
        try:
            session.rollback()
        except Exception:
            pass

    return suspeitos


async def verificar_clt_publico(session) -> list[dict]:
    """
    Detect public servants who appear to also have CLT private employment.

    Strategy: flag people on public payroll who have:
      - Role containing 'comissionado' or 'dab'
      - AND have months with remuneracao_bruta == 0 (suggesting they're
        drawing a salary elsewhere while keeping the public position).

    Args:
        session: SQLAlchemy session.

    Returns:
        List of suspect RegistroFolha records.
    """
    suspeitos = []

    try:
        # Find active commissionados with zero-pay months
        registros_zero = (
            session.query(RegistroFolha)
            .filter(
                RegistroFolha.remuneracao_bruta == 0,
                RegistroFolha.remuneracao_liquida == 0,
                RegistroFolha.orgao_nome.isnot(None),
            )
            .filter(
                RegistroFolha.vinculo.ilike("%comissionado%")
                | RegistroFolha.vinculo.ilike("%dab%")
                | RegistroFolha.cargo.ilike("%comissionado%")
                | RegistroFolha.orgao_nome.ilike("%comissionado%")
            )
            .all()
        )

        for reg in registros_zero:
            suspeito = {
                "cpf": reg.cpf,
                "nome": reg.nome,
                "orgao": reg.orgao_nome,
                "cargo": reg.cargo,
                "competencia": reg.competencia,
                "motivo": "Servidor comissionado com remuneração zero — possível CLT ativo em outro vínculo",
            }
            suspeitos.append(suspeito)

            titulo = (
                f"Servidor comissionado com remuneração zero — "
                f"{reg.nome or reg.cpf} / {reg.orgao_nome}"
            )
            existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
            if not existe:
                alerta = Alerta(
                    tipo="fantasma",
                    severidade="média",
                    titulo=titulo[:300],
                    descricao=(
                        f"Servidor '{reg.nome}' (CPF {reg.cpf}), vínculo "
                        f"'{reg.vinculo or reg.cargo}' em '{reg.orgao_nome}', "
                        f"tem remuneração R$ 0,00 na competência {reg.competencia}. "
                        f"Indício de duplo vínculo ou cargo fictício."
                    ),
                    evidencias=json.dumps(suspeito, ensure_ascii=False, default=str),
                    pessoa_id=session.query(Pessoa).filter_by(cpf=reg.cpf).first().id
                    if reg.cpf and session.query(Pessoa).filter_by(cpf=reg.cpf).first()
                    else None,
                )
                session.add(alerta)

        session.commit()
        logger.info(f"verificar_clt_publico: {len(suspeitos)} suspeitos.")

    except Exception as exc:
        logger.error(f"Erro em verificar_clt_publico: {exc}")
        try:
            session.rollback()
        except Exception:
            pass

    return suspeitos


async def baixar_folha_orgao_externo(orgao: str, session) -> int:
    """
    Attempt to download payroll data from an external government organ.

    Supported organs: alerj | tjrj | mprj | defensoria

    Scrapes the transparency portal for each organ looking for:
      - Downloadable CSV/XLSX files
      - HTML tables with servidor/CPF/remuneração data

    Args:
        orgao:   One of "alerj", "tjrj", "mprj", "defensoria".
        session: SQLAlchemy session.

    Returns:
        Number of RegistroFolha records inserted.
    """
    orgao = orgao.lower().strip()
    if orgao not in ORGAO_URLS:
        logger.warning(f"Órgão desconhecido: {orgao}. Use: {list(ORGAO_URLS.keys())}")
        return 0

    url = ORGAO_URLS[orgao]
    count = 0

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        # Look for downloadable files (CSV, XLSX, XLS)
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if any(href.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"]):
                full_url = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
                logger.info(f"Encontrado arquivo de folha: {full_url}")
                # We found a link but downloading/parsing XLSX would require openpyxl
                # Log it for manual processing
                logger.info(f"Arquivo de folha {orgao}: {full_url} (download manual necessário)")

        # Try to parse HTML table directly
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers_row = rows[0]
            header_cells = [th.get_text(strip=True).lower() for th in headers_row.find_all(["th", "td"])]

            # Check if this looks like a payroll table
            has_cpf = any("cpf" in h for h in header_cells)
            has_nome = any("nome" in h for h in header_cells)
            has_rem = any(any(k in h for k in ["remun", "salário", "salario", "vencimento"]) for h in header_cells)

            if not (has_nome or has_cpf):
                continue

            # Try to identify columns
            cpf_col = next((i for i, h in enumerate(header_cells) if "cpf" in h), -1)
            nome_col = next((i for i, h in enumerate(header_cells) if "nome" in h), -1)
            cargo_col = next((i for i, h in enumerate(header_cells) if "cargo" in h), -1)
            rem_col = next((i for i, h in enumerate(header_cells) if any(k in h for k in ["remun", "salário", "salario", "vencimento"])), -1)

            batch = []
            for data_row in rows[1:]:
                cells = data_row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                cpf = cells[cpf_col].get_text(strip=True) if cpf_col >= 0 and cpf_col < len(cells) else ""
                nome = cells[nome_col].get_text(strip=True) if nome_col >= 0 and nome_col < len(cells) else ""
                cargo = cells[cargo_col].get_text(strip=True) if cargo_col >= 0 and cargo_col < len(cells) else ""
                rem_str = cells[rem_col].get_text(strip=True) if rem_col >= 0 and rem_col < len(cells) else "0"

                if not nome and not cpf:
                    continue

                # Normalize CPF
                cpf_clean = "".join(c for c in cpf if c.isdigit())
                if cpf_clean and len(cpf_clean) != 11:
                    cpf_clean = ""

                # Parse remuneração
                try:
                    rem = float(rem_str.replace(".", "").replace(",", ".").replace("R$", "").strip())
                except ValueError:
                    rem = 0.0

                # Check for duplicate
                from datetime import date
                competencia = date.today().strftime("%Y-%m")

                existe = (
                    session.query(RegistroFolha)
                    .filter_by(
                        cpf=cpf_clean or None,
                        nome=nome[:200] if nome else None,
                        orgao_nome=orgao.upper(),
                        competencia=competencia,
                    )
                    .first()
                )
                if existe:
                    continue

                reg = RegistroFolha(
                    cpf=cpf_clean or None,
                    nome=nome[:200] if nome else None,
                    orgao_nome=orgao.upper(),
                    cargo=cargo[:200] if cargo else None,
                    competencia=competencia,
                    remuneracao_bruta=rem,
                    fonte=orgao,
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

        logger.info(f"baixar_folha_orgao_externo({orgao}): {count} registros inseridos.")

    except httpx.TimeoutException:
        logger.warning(f"Timeout ao acessar transparência {orgao}: {url}")
    except httpx.HTTPStatusError as exc:
        logger.warning(f"HTTP {exc.response.status_code} ao acessar {orgao}: {url}")
    except Exception as exc:
        logger.error(f"Erro ao baixar folha {orgao}: {exc}")
        try:
            session.rollback()
        except Exception:
            pass

    return count
