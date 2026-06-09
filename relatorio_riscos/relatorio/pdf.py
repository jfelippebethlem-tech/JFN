"""
Geração de relatório de riscos em PDF usando fpdf2 (gratuito, sem dependências externas).

Instalação: pip install fpdf2
"""
from __future__ import annotations

import re
from pathlib import Path

_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _strip_md(texto: str) -> str:
    """Remove marcações Markdown básicas para exibição em PDF."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"\*(.+?)\*", r"\1", texto)
    texto = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", texto)
    texto = re.sub(r"`(.+?)`", r"\1", texto)
    texto = re.sub(r"^#+\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^\s*[-*+]\s+", "• ", texto, flags=re.MULTILINE)
    texto = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", texto)
    texto = re.sub(r"---+", "─" * 60, texto)
    return texto


def _nivel_cor(nivel: str) -> tuple[int, int, int]:
    """Retorna a cor RGB para o nível de risco."""
    if nivel == "ALTO":
        return (220, 53, 69)
    elif nivel == "MÉDIO":
        return (255, 193, 7)
    return (40, 167, 69)


def gerar_pdf(
    empresa: dict,
    rede: dict,
    contratos: dict,
    sancoes: dict,
    sinais: dict,
    data_analise: str,
    relatorio_md: str,
) -> bytes:
    """
    Gera PDF do relatório de riscos.

    Retorna os bytes do PDF gerado.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError("fpdf2 não instalado. Rode: pip install fpdf2")

    nivel = sinais.get("nivel_geral", "BAIXO")
    score = sinais.get("score", 0)
    razao_social = empresa.get("razao_social", "")
    cnpj = empresa.get("cnpj", "")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Cabeçalho
    cor = _nivel_cor(nivel)
    pdf.set_fill_color(*cor)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "RELATÓRIO DE RISCOS CORPORATIVOS", fill=True, ln=True, align="C")

    pdf.set_fill_color(50, 50, 50)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"JFN Agent  |  {data_analise}", fill=True, ln=True, align="C")

    pdf.ln(5)

    # Empresa e nível de risco
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, razao_social, ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"CNPJ: {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]} " if len(cnpj) == 14 else f"CNPJ: {cnpj}", ln=True)

    pdf.ln(3)

    # Badge de risco
    pdf.set_fill_color(*cor)
    cor_texto = (0, 0, 0) if nivel == "MÉDIO" else (255, 255, 255)
    pdf.set_text_color(*cor_texto)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(60, 10, f"  RISCO: {nivel}", fill=True, border=0)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(40, 10, f"  Score: {score}/100", fill=True, ln=True)

    pdf.ln(5)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # Dados cadastrais
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 8, "1. Dados Cadastrais", ln=True)
    pdf.set_font("Helvetica", "", 9)

    campos = [
        ("Situação", empresa.get("situacao", "—")),
        ("Data de Abertura", empresa.get("data_abertura", "—")),
        ("Capital Social", f"R$ {empresa.get('capital_social', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        ("Porte", empresa.get("porte", "—")),
        ("Natureza Jurídica", empresa.get("natureza_juridica", "—")),
        ("CNAE Principal", empresa.get("cnae_principal", "—")),
        ("Endereço", empresa.get("endereco", "—")),
        ("E-mail", empresa.get("email", "—")),
    ]
    for rotulo, valor in campos:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(45, 6, rotulo + ":", border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 6, str(valor)[:100], border=0)

    pdf.ln(3)

    # Sócios
    socios = empresa.get("socios", [])
    if socios:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "2. Quadro Societário", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for s in socios[:10]:
            nome = s.get("nome", "")
            qualif = s.get("qualificacao", "")
            entrada = s.get("data_entrada", "")
            pdf.cell(0, 5, f"  • {nome}  [{qualif}]  entrada: {entrada}", ln=True)

    pdf.ln(3)

    # Contratos
    lista_contratos = contratos.get("contratos", [])
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, f"3. Contratos Públicos  (total declarado: {contratos.get('total', 0)})", ln=True)
    pdf.set_font("Helvetica", "", 9)
    if lista_contratos:
        # Cabeçalho da tabela
        pdf.set_fill_color(70, 70, 70)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(70, 6, "Órgão", fill=True, border=1)
        pdf.cell(80, 6, "Objeto", fill=True, border=1)
        pdf.cell(20, 6, "Valor (R$)", fill=True, border=1)
        pdf.cell(20, 6, "Assinatura", fill=True, border=1, ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 7)
        for i, c in enumerate(lista_contratos[:20]):
            pdf.set_fill_color(245, 245, 245) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            orgao = (c.get("orgao") or "—")[:40]
            objeto = (c.get("objeto") or "—")[:55]
            valor = c.get("valor_global", 0)
            valor_str = f"{valor:,.0f}".replace(",", ".") if valor else "—"
            assin = (c.get("data_assinatura") or "—")[:10]
            pdf.cell(70, 5, orgao, fill=True, border=1)
            pdf.cell(80, 5, objeto, fill=True, border=1)
            pdf.cell(20, 5, valor_str, fill=True, border=1, align="R")
            pdf.cell(20, 5, assin, fill=True, border=1, ln=True)
    else:
        pdf.cell(0, 6, "  Nenhum contrato obtido do PNCP.", ln=True)

    pdf.ln(3)

    # Sanções
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "4. Verificação de Sanções (CEIS/CNEP/CEPIM)", ln=True)
    pdf.set_font("Helvetica", "", 9)
    if sancoes.get("verificado"):
        n = sancoes.get("n_sancoes", 0)
        if n == 0:
            pdf.set_text_color(40, 167, 69)
            pdf.cell(0, 6, "  ✓ Nenhuma sanção identificada.", ln=True)
        else:
            pdf.set_text_color(220, 53, 69)
            pdf.cell(0, 6, f"  ✗ {n} sanção(ões) identificada(s)!", ln=True)
        pdf.set_text_color(0, 0, 0)
    else:
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, f"  Verificação não realizada: {sancoes.get('motivo', 'sem chave API')}", ln=True)
        pdf.set_text_color(0, 0, 0)

    pdf.ln(3)

    # Sinais de risco
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "5. Sinais de Risco", ln=True)

    for grupo, label, cor_grupo in [
        ("sinais_alto", "ALTO", (220, 53, 69)),
        ("sinais_medio", "MÉDIO", (255, 150, 0)),
        ("sinais_baixo", "BAIXO", (40, 167, 69)),
    ]:
        lista = sinais.get(grupo, [])
        if not lista:
            continue
        pdf.set_fill_color(*cor_grupo)
        cor_t = (255, 255, 255) if label != "MÉDIO" else (0, 0, 0)
        pdf.set_text_color(*cor_t)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, f"  {label} ({len(lista)})", fill=True, ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 9)
        for s in lista:
            desc = s.get("descricao", "")
            detalhe = s.get("detalhe", "")
            linha = f"  • {desc}"
            if detalhe:
                linha += f" — {detalhe}"
            pdf.multi_cell(0, 5, linha[:120])

    pdf.ln(5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Relatório gerado automaticamente pelo JFN Agent. Não substitui análise jurídica especializada.", ln=True, align="C")

    return bytes(pdf.output())


def salvar_pdf(
    empresa: dict,
    rede: dict,
    contratos: dict,
    sancoes: dict,
    sinais: dict,
    data_analise: str,
    relatorio_md: str,
) -> str:
    """Salva o PDF em /reports/ e retorna o caminho do arquivo."""
    import re as _re
    cnpj = _re.sub(r"\D", "", empresa.get("cnpj", ""))
    data = _re.sub(r"[^\d-]", "", data_analise)[:10]
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = _REPORTS_DIR / f"risco_{cnpj}_{data}.pdf"
    conteudo = gerar_pdf(empresa, rede, contratos, sancoes, sinais, data_analise, relatorio_md)
    caminho.write_bytes(conteudo)
    return str(caminho)
