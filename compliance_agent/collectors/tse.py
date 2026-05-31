"""
TSE (Tribunal Superior Eleitoral) electoral donations collector.

Downloads candidacy financial disclosure data from TSE's open data portal
and cross-references donors with public contracts to detect quid pro quo patterns.
"""

import asyncio
import csv
import io
import json
import logging
import os
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx

from compliance_agent.database.models import (
    Alerta, Contrato, DoacaoEleitoral, Empresa, get_session,
)

logger = logging.getLogger(__name__)

TSE_CACHE_DIR = Path("data/tse_cache")

# TSE open data URL pattern for candidate financial disclosures
TSE_URL_PATTERN = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"
    "prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
)


def _normalize_cpf_cnpj(value: str) -> str:
    """Strip formatting characters from CPF/CNPJ."""
    if not value:
        return ""
    return "".join(c for c in value if c.isdigit())


def _parse_date(value: str) -> Optional[date]:
    """Try to parse a date string in various formats."""
    if not value or not value.strip():
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_value(value: str) -> float:
    """Parse a Brazilian decimal number (comma as decimal separator)."""
    if not value or not value.strip():
        return 0.0
    try:
        return float(value.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _get_column(row: dict, *candidates: str) -> str:
    """Return the first matching column value from a CSV row."""
    for col in candidates:
        val = row.get(col, "")
        if val:
            return val.strip()
    return ""


async def baixar_doacoes_ano(ano: int, session, uf: str = "RJ") -> int:
    """
    Download and index electoral donation records for a given year and state.

    Downloads the TSE ZIP file, parses the CSV inside (latin-1 encoding),
    filters by state (uf), and inserts new DoacaoEleitoral records into the DB.

    Args:
        ano:     Election year (e.g. 2018, 2020, 2022, 2024).
        session: SQLAlchemy session.
        uf:      State abbreviation to filter (default "RJ").

    Returns:
        Number of new records inserted.
    """
    TSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    url = TSE_URL_PATTERN.format(ano=ano)
    zip_path = TSE_CACHE_DIR / f"prestacao_contas_{ano}.zip"

    # Download ZIP if not already cached
    if not zip_path.exists():
        logger.info(f"Baixando doações TSE {ano}: {url}")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                zip_path.write_bytes(resp.content)
                logger.info(f"ZIP salvo em {zip_path} ({len(resp.content):,} bytes)")
        except httpx.HTTPError as exc:
            logger.error(f"Erro ao baixar TSE {ano}: {exc}")
            return 0
        except Exception as exc:
            logger.error(f"Erro inesperado baixar TSE {ano}: {exc}")
            return 0
    else:
        logger.info(f"Usando cache TSE {ano}: {zip_path}")

    # Parse CSV inside ZIP
    count = 0
    batch: list[DoacaoEleitoral] = []
    BATCH_SIZE = 500

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            # Find CSV files inside the ZIP
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                logger.warning(f"Nenhum CSV no ZIP {zip_path}")
                return 0

            for csv_name in csv_names:
                logger.info(f"Processando {csv_name}")
                with zf.open(csv_name) as raw_file:
                    # TSE files use latin-1 (ISO-8859-1) encoding
                    text_file = io.TextIOWrapper(raw_file, encoding="latin-1", errors="replace")
                    reader = csv.DictReader(text_file, delimiter=";")

                    for row in reader:
                        # Determine which UF column is present
                        uf_val = _get_column(row, "SG_UF", "SG_UF_CANDIDATO")
                        if uf_val.upper() != uf.upper():
                            continue

                        # Extract fields with fallback column names
                        cpf_cnpj = _normalize_cpf_cnpj(
                            _get_column(row, "CPF_CNPJ_DOADOR", "NR_CPF_CNPJ_DOADOR")
                        )
                        nome_doador = _get_column(row, "NM_DOADOR", "NM_DOADOR_RFB")
                        nome_candidato = _get_column(row, "NM_CANDIDATO")
                        cargo = _get_column(row, "DS_CARGO", "DS_CARGO_CANDIDATO")
                        partido = _get_column(row, "SG_PARTIDO")
                        valor_str = _get_column(row, "VR_RECEITA", "VR_VALOR")
                        data_str = _get_column(row, "DT_RECEITA", "DT_DATA")

                        valor = _parse_value(valor_str)
                        data_doacao = _parse_date(data_str)

                        # Skip if doador has no identifier
                        if not cpf_cnpj and not nome_doador:
                            continue

                        # Check for duplicate (same doador + candidato + valor + ano)
                        existe = (
                            session.query(DoacaoEleitoral)
                            .filter_by(
                                cpf_cnpj_doador=cpf_cnpj or None,
                                nome_doador=nome_doador[:300] if nome_doador else None,
                                nome_candidato=nome_candidato[:300] if nome_candidato else None,
                                ano_eleicao=ano,
                            )
                            .first()
                        )
                        if existe:
                            continue

                        doacao = DoacaoEleitoral(
                            cpf_cnpj_doador=cpf_cnpj or None,
                            nome_doador=nome_doador[:300] if nome_doador else None,
                            nome_candidato=nome_candidato[:300] if nome_candidato else None,
                            cargo_candidato=cargo[:100] if cargo else None,
                            partido=partido[:20] if partido else None,
                            uf=uf.upper(),
                            valor=valor,
                            data_doacao=data_doacao,
                            ano_eleicao=ano,
                        )
                        batch.append(doacao)
                        count += 1

                        if len(batch) >= BATCH_SIZE:
                            session.add_all(batch)
                            session.commit()
                            batch = []
                            logger.info(f"  {count} registros inseridos...")

        if batch:
            session.add_all(batch)
            session.commit()

        logger.info(f"TSE {ano} {uf}: {count} doações importadas.")
        return count

    except zipfile.BadZipFile:
        logger.error(f"Arquivo ZIP inválido: {zip_path}")
        # Remove corrupted cache so it gets re-downloaded next time
        zip_path.unlink(missing_ok=True)
        return 0
    except Exception as exc:
        logger.error(f"Erro ao processar TSE {ano}: {exc}")
        session.rollback()
        return 0


def cruzar_doacoes_contratos(session) -> list[dict]:
    """
    Cross-reference electoral donors with companies holding public contracts.

    For each company CNPJ found in both DoacaoEleitoral and Contrato tables,
    creates an Alerta of type 'nomeacao_suspeita'.

    Args:
        session: SQLAlchemy session.

    Returns:
        List of dicts with {'titulo', 'severidade'} for newly created alerts.
    """
    novos_alertas = []

    try:
        # Get all CNPJ donors (only legal entities have 14-digit CNPJ)
        doacoes = (
            session.query(DoacaoEleitoral)
            .filter(
                DoacaoEleitoral.cpf_cnpj_doador.isnot(None),
                # CNPJ has 14 digits; CPF has 11
                DoacaoEleitoral.cpf_cnpj_doador.like("______________"),  # 14 chars
            )
            .all()
        )

        for doacao in doacoes:
            cnpj = doacao.cpf_cnpj_doador
            if not cnpj or len(cnpj) != 14:
                continue

            # Check if this CNPJ has contracts in our DB
            empresa = session.query(Empresa).filter_by(cnpj=cnpj).first()
            if not empresa:
                continue

            contratos = session.query(Contrato).filter_by(empresa_id=empresa.id).all()
            if not contratos:
                continue

            # Calculate total donations
            total_doacoes = (
                session.query(DoacaoEleitoral)
                .filter_by(cpf_cnpj_doador=cnpj)
                .all()
            )
            soma_doacoes = sum(d.valor or 0 for d in total_doacoes)
            soma_contratos = sum(c.valor_total or 0 for c in contratos)

            severidade = "alta" if soma_doacoes > 50_000 else "média"

            titulo = (
                f"Doação eleitoral × contrato público — "
                f"{empresa.razao_social} (CNPJ {cnpj})"
            )

            # Avoid duplicate alerts
            existe = session.query(Alerta).filter_by(titulo=titulo[:300]).first()
            if existe:
                continue

            candidatos = list({d.nome_candidato for d in total_doacoes if d.nome_candidato})
            anos = list({d.ano_eleicao for d in total_doacoes if d.ano_eleicao})

            alerta = Alerta(
                tipo="nomeacao_suspeita",
                severidade=severidade,
                titulo=titulo[:300],
                descricao=(
                    f"A empresa '{empresa.razao_social}' (CNPJ {cnpj}) realizou doações "
                    f"eleitorais totalizando R$ {soma_doacoes:,.2f} para candidatos "
                    f"({', '.join(str(a) for a in anos)}) e possui {len(contratos)} "
                    f"contrato(s) com o governo no valor total de R$ {soma_contratos:,.2f}. "
                    f"Candidatos beneficiados: {', '.join(candidatos[:5])}."
                ),
                evidencias=json.dumps(
                    {
                        "cnpj": cnpj,
                        "empresa": empresa.razao_social,
                        "soma_doacoes": soma_doacoes,
                        "soma_contratos": soma_contratos,
                        "n_contratos": len(contratos),
                        "candidatos": candidatos[:10],
                        "anos_eleicao": anos,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                empresa_id=empresa.id,
            )
            session.add(alerta)
            novos_alertas.append({"titulo": titulo[:300], "severidade": severidade})

        session.commit()
        logger.info(f"cruzar_doacoes_contratos: {len(novos_alertas)} alertas criados.")

    except Exception as exc:
        logger.error(f"Erro em cruzar_doacoes_contratos: {exc}")
        session.rollback()

    return novos_alertas
