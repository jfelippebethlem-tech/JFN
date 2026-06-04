"""
Calculador de sinais de risco corporativo.

Classifica padrões em ALTO / MÉDIO / BAIXO com base em dados
coletados da empresa, rede societária, contratos e sanções.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_data(s: str) -> Optional[date]:
    """Tenta converter string de data em objeto date."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _anos_desde(data_str: str) -> Optional[float]:
    """Retorna anos decorridos desde a data informada até hoje."""
    d = _parse_data(data_str)
    if d is None:
        return None
    delta = date.today() - d
    return delta.days / 365.25


def _email_generico(email: str) -> bool:
    """Retorna True se o e-mail usa provedor genérico (gmail, hotmail, etc.)."""
    if not email:
        return False
    provedores = ("gmail.com", "hotmail.com", "yahoo.com", "outlook.com",
                  "live.com", "bol.com.br", "uol.com.br", "terra.com.br")
    return any(email.lower().endswith(p) for p in provedores)


def _porte_pequeno(porte: str) -> bool:
    """Retorna True para micro empresa ou empresa de pequeno porte."""
    return any(p in (porte or "").upper() for p in ("MICRO", "PEQUENO", "ME", "EPP"))


def _tem_natureza_holding(natureza: str) -> bool:
    return "HOLDING" in (natureza or "").upper()


def _tem_natureza_sa(natureza: str) -> bool:
    return "ANON" in (natureza or "").upper() or "S/A" in (natureza or "").upper() or "S.A" in (natureza or "").upper()


# ---------------------------------------------------------------------------
# Detector de sinais
# ---------------------------------------------------------------------------

def _sinal(nivel: str, descricao: str, detalhe: str = "") -> dict:
    return {"nivel": nivel, "descricao": descricao, "detalhe": detalhe}


def _sinais_empresa(empresa: dict) -> list[dict]:
    sinais = []

    capital = empresa.get("capital_social") or 0.0
    porte = empresa.get("porte") or ""
    natureza = empresa.get("natureza_juridica") or ""
    data_abertura = empresa.get("data_abertura") or ""
    email = empresa.get("email") or ""

    # ALTO: capital social desproporcional ao porte
    if capital >= 5_000_000 and _porte_pequeno(porte):
        sinais.append(_sinal(
            "ALTO",
            "Capital social desproporcional ao porte",
            f"Capital R$ {capital:,.2f} em empresa classificada como {porte or 'micro/pequena'}",
        ))

    # MÉDIO: email genérico como contato fiscal
    if _email_generico(email):
        sinais.append(_sinal(
            "MÉDIO",
            "Email administrativo não-corporativo",
            f"Email cadastrado: {email}",
        ))

    # MÉDIO: S/A com capital zero
    if _tem_natureza_sa(natureza) and capital == 0:
        sinais.append(_sinal(
            "MÉDIO",
            "S/A com capital zero (irregular)",
            f"Natureza jurídica: {natureza} — capital social: R$ 0,00",
        ))

    # BAIXO: holding na rede
    if _tem_natureza_holding(natureza):
        sinais.append(_sinal(
            "BAIXO",
            "Estrutura holding identificada",
            f"Natureza jurídica: {natureza}",
        ))

    return sinais


def _sinais_contratos(empresa: dict, contratos: dict) -> list[dict]:
    sinais = []

    lista = contratos.get("contratos") or []
    data_abertura = empresa.get("data_abertura") or ""
    anos_empresa = _anos_desde(data_abertura)

    modalidades = [c.get("modalidade") or "" for c in lista]
    valores = [c.get("valor_global") or 0.0 for c in lista]

    # ALTO: contrato simbólico R$ 0,01
    for c in lista:
        v = c.get("valor_global") or 0.0
        if 0 < v <= 0.01:
            sinais.append(_sinal(
                "ALTO",
                "Contrato simbólico: possível remuneração oculta",
                f"Contrato {c.get('numero_contrato') or c.get('id_pncp') or 'S/N'} com valor R$ {v:.2f}",
            ))

    # ALTO: inexigibilidade
    for mod in modalidades:
        if "INEXIGIBILIDADE" in mod.upper():
            sinais.append(_sinal(
                "ALTO",
                "Contratação por inexigibilidade detectada",
                f"Modalidade: {mod}",
            ))
            break  # um único sinal por padrão

    # ALTO: empresa jovem com contratos vultosos
    if anos_empresa is not None and anos_empresa < 2 and lista:
        max_valor = max(valores) if valores else 0
        if max_valor >= 1_000_000:
            sinais.append(_sinal(
                "ALTO",
                "Empresa jovem com contratos vultosos",
                f"Empresa com {anos_empresa:.1f} anos e contrato máximo de R$ {max_valor:,.2f}",
            ))

    return sinais


def _sinais_rede(rede: dict) -> list[dict]:
    sinais = []

    pct_baixadas = rede.get("pct_baixadas") or 0.0
    pessoas_chave = rede.get("pessoas_chave") or []

    # MÉDIO: alto índice de empresas encerradas
    if pct_baixadas >= 40:
        total = rede.get("total_cnpjs") or 0
        baixadas = rede.get("baixadas_inaptas") or 0
        sinais.append(_sinal(
            "MÉDIO",
            "Alto índice de empresas encerradas na rede",
            f"{baixadas}/{total} empresas baixadas/inaptas ({pct_baixadas:.1f}%)",
        ))

    # BAIXO: sócio com alta concentração societária
    for p in pessoas_chave:
        if p.get("n_empresas") or 0 >= 5:
            sinais.append(_sinal(
                "BAIXO",
                "Sócio com alta concentração societária",
                f"{p['nome']} aparece em {p['n_empresas']} empresas",
            ))
            break  # um sinal por padrão para não poluir

    # MÉDIO: concentração de empresas no mesmo endereço
    todos_nos = [
        no
        for nivel in rede.get("nos", {}).values()
        for no in nivel
    ]
    enderecos: dict[str, list[str]] = {}
    for no in todos_nos:
        end = (no.get("endereco") or "").strip().upper()
        if end:
            enderecos.setdefault(end, []).append(no.get("cnpj") or "")
    for end, cnpjs in enderecos.items():
        if len(cnpjs) >= 3:
            sinais.append(_sinal(
                "MÉDIO",
                "Concentração de empresas no mesmo endereço",
                f"{len(cnpjs)} empresas no endereço: {end[:80]}",
            ))
            break

    return sinais


def _sinais_sancoes(sancoes: dict) -> list[dict]:
    sinais = []
    if sancoes.get("verificado") and (sancoes.get("n_sancoes") or 0) > 0:
        n = sancoes["n_sancoes"]
        sinais.append(_sinal(
            "ALTO",
            "Sanções identificadas nos cadastros federais",
            f"{n} sanção(ões) ativa(s) no CEIS/CNEP/CEPIM",
        ))
    return sinais


# ---------------------------------------------------------------------------
# Cálculo consolidado
# ---------------------------------------------------------------------------

_NIVEL_PESO = {"ALTO": 3, "MÉDIO": 2, "BAIXO": 1}


def _nivel_geral(todos: list[dict]) -> str:
    if not todos:
        return "BAIXO"
    maximo = max(_NIVEL_PESO.get(s["nivel"], 0) for s in todos)
    for nivel, peso in _NIVEL_PESO.items():
        if peso == maximo:
            return nivel
    return "BAIXO"


def _calcular_score(alto: int, medio: int, baixo: int) -> int:
    """Calcula score 0–100 proporcional aos sinais."""
    raw = alto * 30 + medio * 10 + baixo * 3
    return min(100, raw)


def calcular_sinais(
    dados_empresa: dict,
    rede: dict,
    contratos: dict,
    sancoes: dict,
) -> dict:
    """
    Detecta padrões de risco e classifica em ALTO/MÉDIO/BAIXO.

    Parâmetros
    ----------
    dados_empresa : saída de buscar_cnpj()
    rede          : saída de expandir_rede()
    contratos     : saída de buscar_contratos_por_cnpj()
    sancoes       : saída de verificar_sancoes()

    Retorno
    -------
    dict com nivel_geral, n_sinais, sinais_alto, sinais_medio, sinais_baixo, score
    """
    todos: list[dict] = []

    todos.extend(_sinais_empresa(dados_empresa))
    todos.extend(_sinais_contratos(dados_empresa, contratos))
    todos.extend(_sinais_rede(rede))
    todos.extend(_sinais_sancoes(sancoes))

    sinais_alto = [s for s in todos if s["nivel"] == "ALTO"]
    sinais_medio = [s for s in todos if s["nivel"] == "MÉDIO"]
    sinais_baixo = [s for s in todos if s["nivel"] == "BAIXO"]

    return {
        "nivel_geral": _nivel_geral(todos),
        "n_sinais": len(todos),
        "sinais_alto": sinais_alto,
        "sinais_medio": sinais_medio,
        "sinais_baixo": sinais_baixo,
        "score": _calcular_score(len(sinais_alto), len(sinais_medio), len(sinais_baixo)),
    }
