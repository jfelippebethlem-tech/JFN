"""
TCE-RJ (Tribunal de Contas do Estado do Rio de Janeiro) decisions collector.

Scrapes the TCE-RJ jurisprudence search to find condemnations, fines,
and other decisions related to companies and public servants.
"""

import json
import logging
import re
from datetime import datetime, date
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from compliance_agent.database.models import (
    Alerta, DecisaoTCE, Empresa,
)

logger = logging.getLogger(__name__)

TCE_BASE_URL = "https://www.tce.rj.gov.br/web/guest/pesquisa-de-jurisprudencia"

# Keywords that indicate condemnation decisions
PALAVRAS_CONDENACAO = {
    "condeno", "condenado", "condenada", "débito", "debito",
    "multa", "ressarcimento", "irregularidade", "ilegal",
}


def _parse_date_tce(value: str) -> Optional[date]:
    """Parse TCE date formats."""
    if not value or not value.strip():
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _classify_decision(ementa: str) -> str:
    """Determine decision type based on ementa text."""
    if not ementa:
        return "acórdão"
    lower = ementa.lower()
    for palavra in PALAVRAS_CONDENACAO:
        if palavra in lower:
            return "condenação"
    if "arquiv" in lower:
        return "arquivamento"
    return "acórdão"


def _extract_cpfs(text: str) -> list[str]:
    """Extract CPF patterns from text."""
    pattern = r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b"
    found = re.findall(pattern, text)
    # Normalize
    return list({"".join(c for c in f if c.isdigit()) for f in found if len("".join(c for c in f if c.isdigit())) == 11})


def _extract_cnpjs(text: str) -> list[str]:
    """Extract CNPJ patterns from text."""
    pattern = r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b"
    found = re.findall(pattern, text)
    return list({"".join(c for c in f if c.isdigit()) for f in found if len("".join(c for c in f if c.isdigit())) == 14})


def _extract_valor_debito(ementa: str) -> float:
    """Try to extract monetary value from ementa text."""
    if not ementa:
        return 0.0
    # Pattern: R$ 1.234.567,89 or R$ 1234567.89
    pattern = r"R\$\s*([\d.,]+)"
    matches = re.findall(pattern, ementa, re.IGNORECASE)
    for m in matches:
        try:
            valor = float(m.replace(".", "").replace(",", "."))
            if valor > 0:
                return valor
        except ValueError:
            continue
    return 0.0


async def buscar_decisoes_tce(termo: str, session, max_resultados: int = 20) -> list[dict]:
    """
    Search TCE-RJ jurisprudence for decisions related to a term.

    Saves found decisions to the DecisaoTCE table and returns a list of dicts.

    Args:
        termo:           Search term (company name, person name, CNPJ).
        session:         SQLAlchemy session.
        max_resultados:  Maximum number of results to return.

    Returns:
        List of dicts with: numero, data, tipo, ementa (first 400 chars).
        Returns empty list on network/parsing failure.
    """
    resultados = []

    try:
        params = {"termo": termo}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(TCE_BASE_URL, params=params, headers=headers)
            resp.raise_for_status()
            html = resp.text

    except httpx.TimeoutException:
        logger.warning(f"Timeout ao buscar TCE-RJ para '{termo}'")
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning(f"HTTP {exc.response.status_code} ao buscar TCE-RJ para '{termo}'")
        return []
    except Exception as exc:
        logger.error(f"Erro ao buscar TCE-RJ: {exc}")
        return []

    # Parse HTML response
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Try different selectors for TCE-RJ site structure
        decisoes_raw = []

        # Try table rows
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # skip header
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    decisoes_raw.append({
                        "numero": cells[0].get_text(strip=True) if cells else "",
                        "data":   cells[1].get_text(strip=True) if len(cells) > 1 else "",
                        "ementa": cells[-1].get_text(strip=True) if cells else "",
                        "url":    "",
                    })

        # Try article/div elements
        if not decisoes_raw:
            for article in soup.find_all(["article", "div"], class_=re.compile(r"(result|acordao|decisao|jurisprudencia)", re.I)):
                numero_el = article.find(string=re.compile(r"\d{4,}/\d{4}|\d{6}-\d{2}/\d{4}"))
                ementa_el = article.find(["p", "div", "span"], class_=re.compile(r"(ementa|descricao|texto)", re.I))

                numero = numero_el.strip() if numero_el else ""
                ementa = ementa_el.get_text(strip=True) if ementa_el else article.get_text(strip=True)[:500]
                link = article.find("a")
                url = link.get("href", "") if link else ""

                if ementa:
                    decisoes_raw.append({"numero": numero, "data": "", "ementa": ementa, "url": url})

        # Limit results
        decisoes_raw = decisoes_raw[:max_resultados]

        for item in decisoes_raw:
            numero = item.get("numero", "").strip()
            ementa = item.get("ementa", "").strip()
            data_str = item.get("data", "").strip()
            url = item.get("url", "").strip()

            if not ementa:
                continue

            # Generate a synthetic numero if missing
            if not numero:
                import hashlib
                numero = "TCE-" + hashlib.md5((termo + ementa[:50]).encode()).hexdigest()[:10]

            tipo = _classify_decision(ementa)
            data_julg = _parse_date_tce(data_str)
            valor_debito = _extract_valor_debito(ementa)
            cpfs = _extract_cpfs(ementa)
            cnpjs = _extract_cnpjs(ementa)

            # Save to DB if not already present
            existe = session.query(DecisaoTCE).filter_by(numero_acordao=numero[:50]).first()
            if not existe:
                decisao = DecisaoTCE(
                    numero_acordao=numero[:50],
                    data_julgamento=data_julg,
                    ementa=ementa,
                    tipo_decisao=tipo,
                    valor_debito=valor_debito if valor_debito > 0 else None,
                    cpfs_envolvidos=json.dumps(cpfs, ensure_ascii=False),
                    cnpjs_envolvidos=json.dumps(cnpjs, ensure_ascii=False),
                    url_fonte=url[:500] if url else None,
                )
                session.add(decisao)

            resultados.append({
                "numero": numero,
                "data": str(data_julg) if data_julg else None,
                "tipo": tipo,
                "ementa": ementa[:400],
            })

        try:
            session.commit()
        except Exception as exc:
            logger.warning(f"Erro ao salvar decisões TCE: {exc}")
            session.rollback()

    except Exception as exc:
        logger.error(f"Erro ao processar HTML TCE-RJ: {exc}")

    return resultados


async def verificar_sancionados(session) -> list[dict]:
    """
    Check the top 50 companies in the DB against TCE-RJ decisions.

    For each company with condemnation decisions, creates an Alerta
    of type 'direcionamento' with severidade 'alta'.

    Args:
        session: SQLAlchemy session.

    Returns:
        List of dicts with {'empresa', 'decisoes'} for companies with findings.
    """
    resultados = []

    try:
        # Get top 50 companies (by number of contracts)
        from sqlalchemy import func
        from compliance_agent.database.models import Contrato

        top_empresas = (
            session.query(Empresa)
            .join(Contrato, Contrato.empresa_id == Empresa.id)
            .group_by(Empresa.id)
            .order_by(func.count(Contrato.id).desc())
            .limit(50)
            .all()
        )

        for empresa in top_empresas:
            # Use first 30 chars of razao_social as search term
            termo = empresa.razao_social[:30].strip()
            decisoes = await buscar_decisoes_tce(termo, session, max_resultados=5)

            condenacoes = [d for d in decisoes if d.get("tipo") == "condenação"]

            if condenacoes:
                titulo = f"Empresa sancionada pelo TCE-RJ — {empresa.razao_social}"
                existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()

                if not existe:
                    alerta = Alerta(
                        tipo="direcionamento",
                        severidade="alta",
                        titulo=titulo[:300],
                        descricao=(
                            f"A empresa '{empresa.razao_social}' (CNPJ {empresa.cnpj}) "
                            f"possui {len(condenacoes)} decisão(ões) de condenação no "
                            f"TCE-RJ. Primeira: {condenacoes[0].get('ementa', '')[:200]}"
                        ),
                        evidencias=json.dumps(
                            {
                                "cnpj": empresa.cnpj,
                                "empresa": empresa.razao_social,
                                "n_condenacoes": len(condenacoes),
                                "decisoes": condenacoes[:3],
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                        empresa_id=empresa.id,
                    )
                    session.add(alerta)

                resultados.append({
                    "empresa": empresa.razao_social,
                    "decisoes": condenacoes,
                })

        session.commit()
        logger.info(f"verificar_sancionados: {len(resultados)} empresas com condenações.")

    except Exception as exc:
        logger.error(f"Erro em verificar_sancionados: {exc}")
        try:
            session.rollback()
        except Exception:
            pass

    return resultados
