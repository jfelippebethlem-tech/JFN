"""
Gerador de relatórios de risco corporativo em Markdown e texto simples.

Estrutura do relatório:
  - Capa (nome, CNPJ, data, nível de risco)
  - Sumário executivo (tabela)
  - Seção 1: Dados cadastrais
  - Seção 2: Rede societária
  - Seção 3: Pessoas-chave
  - Seção 4: Contratos públicos
  - Seção 5: Sanções
  - Seção 6: Sinais de risco
  - Seção 7: Conclusões e recomendações
"""
from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path
from typing import Optional

_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def _fmt_cnpj(cnpj: str) -> str:
    c = re.sub(r"\D", "", cnpj)
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    return cnpj


def _fmt_brl(valor) -> str:
    try:
        v = float(valor or 0)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ —"


def _nivel_emoji(nivel: str) -> str:
    return {"ALTO": "🔴 ALTO", "MÉDIO": "🟡 MÉDIO", "BAIXO": "🟢 BAIXO"}.get(nivel, nivel)


def _nivel_ascii(nivel: str) -> str:
    return {"ALTO": "[ALTO]", "MÉDIO": "[MÉDIO]", "BAIXO": "[BAIXO]"}.get(nivel, nivel)


# ---------------------------------------------------------------------------
# Seções do relatório
# ---------------------------------------------------------------------------

def _sec_capa(empresa: dict, sinais: dict, data_analise: str) -> str:
    nome = empresa.get("razao_social") or "—"
    cnpj = _fmt_cnpj(empresa.get("cnpj") or "")
    nivel = sinais.get("nivel_geral") or "—"
    score = sinais.get("score") or 0
    return f"""# Relatório de Riscos Corporativos

| Campo | Valor |
|---|---|
| **Empresa** | {nome} |
| **CNPJ** | {cnpj} |
| **Data da análise** | {data_analise} |
| **Nível de risco** | {_nivel_emoji(nivel)} |
| **Score de risco** | {score}/100 |

---
"""


def _sec_sumario(empresa: dict, rede: dict, contratos: dict, sancoes: dict, sinais: dict) -> str:
    total_contratos = contratos.get("total") or len(contratos.get("contratos") or [])
    n_sancoes = sancoes.get("n_sancoes") or 0
    sancoes_str = str(n_sancoes) if sancoes.get("verificado") else "não verificado"
    total_rede = rede.get("total_cnpjs") or 1
    pct_baixadas = rede.get("pct_baixadas") or 0.0

    return f"""## Sumário Executivo

| Indicador | Valor |
|---|---|
| Situação cadastral | {empresa.get("situacao") or "—"} |
| Contratos públicos (PNCP) | {total_contratos} |
| Sanções (CEIS/CNEP/CEPIM) | {sancoes_str} |
| Empresas na rede | {total_rede} |
| % Baixadas/inaptas | {pct_baixadas:.1f}% |
| Sinais ALTO | {len(sinais.get("sinais_alto") or [])} |
| Sinais MÉDIO | {len(sinais.get("sinais_medio") or [])} |
| Sinais BAIXO | {len(sinais.get("sinais_baixo") or [])} |

---
"""


def _sec_dados_cadastrais(empresa: dict) -> str:
    socios = empresa.get("socios") or []
    socios_md = ""
    if socios:
        socios_md = "\n\n**Quadro societário:**\n\n| Nome | CPF/CNPJ | Qualificação | Entrada |\n|---|---|---|---|\n"
        for s in socios:
            socios_md += f"| {s.get('nome') or '—'} | {s.get('cpf_cnpj_socio') or '—'} | {s.get('qualificacao') or '—'} | {s.get('data_entrada') or '—'} |\n"

    return f"""## 1. Dados Cadastrais

| Campo | Valor |
|---|---|
| Razão Social | {empresa.get("razao_social") or "—"} |
| Nome Fantasia | {empresa.get("nome_fantasia") or "—"} |
| CNPJ | {_fmt_cnpj(empresa.get("cnpj") or "")} |
| Situação | {empresa.get("situacao") or "—"} |
| Abertura | {empresa.get("data_abertura") or "—"} |
| Capital Social | {_fmt_brl(empresa.get("capital_social"))} |
| Porte | {empresa.get("porte") or "—"} |
| Natureza Jurídica | {empresa.get("natureza_juridica") or "—"} |
| CNAE Principal | {empresa.get("cnae_principal") or "—"} |
| Endereço | {empresa.get("endereco") or "—"} |
| E-mail | {empresa.get("email") or "—"} |
| Telefone | {empresa.get("telefone") or "—"} |
| Simples Nacional | {"Sim" if empresa.get("simples") else "Não"} |
| MEI | {"Sim" if empresa.get("mei") else "Não"} |
{socios_md}
---
"""


def _sec_rede(rede: dict) -> str:
    nos = rede.get("nos") or {}
    linhas = ""
    for nivel, lista in nos.items():
        for no in lista:
            situacao = (no.get("status") or "—").upper()
            n_socios = len(no.get("socios") or [])
            capital = _fmt_brl(no.get("capital_social"))
            linhas += f"| {nivel} | {_fmt_cnpj(no.get('cnpj') or '')} | {no.get('razao_social') or '—'} | {situacao} | {n_socios} | {capital} |\n"

    if not linhas:
        linhas = "| — | — | Sem dados | — | — | — |\n"

    aviso = ""
    if rede.get("aviso"):
        aviso_txt = rede["aviso"]
        aviso = f"\n> ⚠️ **Aviso:** {aviso_txt}\n"

    total_cnpjs = rede.get("total_cnpjs") or 0
    baixadas = rede.get("baixadas_inaptas") or 0
    pct = rede.get("pct_baixadas") or 0.0

    return (
        "## 2. Rede Societária\n\n"
        "| Nível | CNPJ | Razão Social | Situação | Sócios | Capital Social |\n"
        "|---|---|---|---|---|---|\n"
        f"{linhas}\n"
        f"**Total de CNPJs mapeados:** {total_cnpjs}\n"
        f"**Baixadas/Inaptas:** {baixadas} ({pct:.1f}%)\n"
        f"{aviso}\n"
        "---\n"
    )


def _sec_pessoas_chave(rede: dict) -> str:
    pessoas = rede.get("pessoas_chave") or []
    if not pessoas:
        return """## 3. Pessoas-Chave

Nenhuma pessoa-chave identificada (requer CNPJs adicionais para análise completa).

---
"""
    linhas = ""
    for p in pessoas:
        empresas_str = ", ".join(p.get("empresas") or [])
        linhas += f"| {p.get('nome') or '—'} | {p.get('cpf') or '—'} | {p.get('n_empresas') or 0} | {empresas_str[:80]} |\n"

    return f"""## 3. Pessoas-Chave

Sócios identificados em 2 ou mais empresas:

| Nome | CPF (mascarado) | Nº Empresas | CNPJs |
|---|---|---|---|
{linhas}
---
"""


def _sec_contratos(contratos: dict) -> str:
    lista = contratos.get("contratos") or []
    total = contratos.get("total") or len(lista)

    if not lista:
        status = "Nenhum contrato público encontrado no PNCP." if contratos.get("ok") else f"Falha na consulta: {contratos.get('erro') or '—'}"
        return f"""## 4. Contratos Públicos (PNCP)

{status}

---
"""

    linhas = ""
    for c in lista:
        valor = _fmt_brl(c.get("valor_global"))
        objeto = (c.get("objeto") or "—")[:60]
        linhas += f"| {c.get('numero_contrato') or c.get('id_pncp') or '—'} | {c.get('orgao') or '—'} | {objeto} | {c.get('modalidade') or '—'} | {valor} | {c.get('data_assinatura') or '—'} |\n"

    return f"""## 4. Contratos Públicos (PNCP)

**Total encontrado:** {total}

| Nº Contrato | Órgão | Objeto | Modalidade | Valor Global | Assinatura |
|---|---|---|---|---|---|
{linhas}
---
"""


def _sec_sancoes(sancoes: dict) -> str:
    if not sancoes.get("verificado"):
        motivo = sancoes.get("motivo") or "verificação não realizada"
        return f"""## 5. Sanções (CEIS / CNEP / CEPIM)

> ℹ️ {motivo}

Para ativar a verificação, defina a variável de ambiente `TRANSPARENCIA_API_KEY`.

---
"""

    n = sancoes.get("n_sancoes") or 0
    if n == 0:
        return """## 5. Sanções (CEIS / CNEP / CEPIM)

Nenhuma sanção identificada nos cadastros federais.

---
"""

    lista = sancoes.get("sancoes") or []
    linhas = ""
    for s in lista:
        linhas += f"| {s.get('tipo') or '—'} | {s.get('tipo_sancao') or '—'} | {s.get('orgao_sancionador') or '—'} | {s.get('data_inicio') or '—'} | {s.get('data_fim') or '—'} |\n"

    return f"""## 5. Sanções (CEIS / CNEP / CEPIM)

**Total de sanções:** {n}

| Cadastro | Tipo | Órgão Sancionador | Início | Fim |
|---|---|---|---|---|
{linhas}
---
"""


def _sec_sinais(sinais: dict) -> str:
    def lista_sinais(lista, nivel_str):
        if not lista:
            return f"Nenhum sinal {nivel_str}.\n"
        out = ""
        for s in lista:
            detalhe = f" — {s['detalhe']}" if s.get("detalhe") else ""
            out += f"- {s['descricao']}{detalhe}\n"
        return out

    alto = sinais.get("sinais_alto") or []
    medio = sinais.get("sinais_medio") or []
    baixo = sinais.get("sinais_baixo") or []

    return f"""## 6. Sinais de Risco

### 🔴 Sinais ALTO ({len(alto)})
{lista_sinais(alto, "ALTO")}
### 🟡 Sinais MÉDIO ({len(medio)})
{lista_sinais(medio, "MÉDIO")}
### 🟢 Sinais BAIXO ({len(baixo)})
{lista_sinais(baixo, "BAIXO")}
---
"""


def _sec_conclusoes(empresa: dict, sinais: dict, sancoes: dict) -> str:
    nivel = sinais.get("nivel_geral") or "BAIXO"
    score = sinais.get("score") or 0
    n_alto = len(sinais.get("sinais_alto") or [])
    n_total = sinais.get("n_sinais") or 0
    nome = empresa.get("razao_social") or "a empresa"

    if nivel == "ALTO":
        recomendacao = (
            f"Recomenda-se **não contratar** ou **suspender** eventuais processos em andamento "
            f"com {nome} até esclarecimento dos sinais de alto risco identificados. "
            "Solicitar documentação comprobatória adicional e acionar área de compliance."
        )
    elif nivel == "MÉDIO":
        recomendacao = (
            f"Recomenda-se **due diligence reforçada** antes de contratar {nome}. "
            "Verificar documentação societária, certidões negativas e histórico de contratos anteriores."
        )
    else:
        recomendacao = (
            f"Não foram identificados sinais graves para {nome}. "
            "Recomenda-se manutenção do monitoramento periódico."
        )

    return f"""## 7. Conclusões e Recomendações

A análise identificou **{n_total} sinal(is)** ({n_alto} de nível ALTO), resultando em nível geral de risco **{nivel}** com score {score}/100.

{recomendacao}

**Fontes consultadas:**
- Receita Federal via BrasilAPI / ReceitaWS
- Portal Nacional de Contratações Públicas (PNCP)
- Portal da Transparência — CEIS/CNEP/CEPIM{" (não verificado — sem chave API)" if not sancoes.get("verificado") else ""}
- RDAP Registro.br (domínios .br)

> _Este relatório foi gerado automaticamente e não substitui análise jurídica especializada._
"""


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def gerar_md(
    empresa: dict,
    rede: dict,
    contratos: dict,
    sancoes: dict,
    sinais: dict,
    data_analise: str,
) -> str:
    """Gera relatório completo em Markdown."""
    partes = [
        _sec_capa(empresa, sinais, data_analise),
        _sec_sumario(empresa, rede, contratos, sancoes, sinais),
        _sec_dados_cadastrais(empresa),
        _sec_rede(rede),
        _sec_pessoas_chave(rede),
        _sec_contratos(contratos),
        _sec_sancoes(sancoes),
        _sec_sinais(sinais),
        _sec_conclusoes(empresa, sinais, sancoes),
    ]
    return "\n".join(partes)


def gerar_txt(
    empresa: dict,
    rede: dict,
    contratos: dict,
    sancoes: dict,
    sinais: dict,
    data_analise: str,
) -> str:
    """Gera relatório em texto simples (sem markdown)."""
    md = gerar_md(empresa, rede, contratos, sancoes, sinais, data_analise)
    # Remove markdown
    txt = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    txt = re.sub(r"#+\s*", "", txt)
    txt = re.sub(r"\|[-:]+\|[-:| ]+\n", "", txt)
    txt = re.sub(r"\|", " | ", txt)
    txt = re.sub(r"> (.+)", r"  [\1]", txt)
    txt = re.sub(r"---+\n?", "-" * 60 + "\n", txt)
    # Remove emoji
    txt = re.sub(r"[🔴🟡🟢⚠️ℹ️_]", "", txt)
    return txt


def salvar_relatorio(
    conteudo: str,
    cnpj: str,
    data_analise: str,
    formato: str = "md",
) -> str:
    """
    Salva o relatório em /reports/risco_{cnpj}_{data}.{formato}.

    Retorna o caminho absoluto do arquivo salvo.
    """
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    data_limpa = re.sub(r"[^\d-]", "", data_analise)[:10]
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    nome_arquivo = f"risco_{cnpj_limpo}_{data_limpa}.{formato}"
    caminho = _REPORTS_DIR / nome_arquivo
    caminho.write_text(conteudo, encoding="utf-8")
    return str(caminho)
