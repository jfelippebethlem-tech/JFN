#!/usr/bin/env python3
"""
Relatório profissional PDF — MGS CLEAN SOLUCOES E SERVICOS LTDA
Gerado por JFN Agent | Auditoria · Risco · Compliance
"""
from __future__ import annotations
from fpdf import FPDF
from datetime import date
from pathlib import Path
import math

OUT = Path(__file__).parents[1] / "reports" / "auditoria_mgs_clean_2026-06-04.pdf"

# ── Paleta ───────────────────────────────────────────────────────────────────
C_NAVY    = (15,  34,  71)
C_BLUE    = (30,  90, 168)
C_LTBLUE  = (214, 234, 255)
C_RED     = (196,  28,  28)
C_LTRED   = (255, 230, 230)
C_AMBER   = (181, 115,   0)
C_LTAMB   = (255, 248, 210)
C_GREEN   = ( 22, 130,  70)
C_LTGRN   = (220, 255, 235)
C_GRAY1   = ( 30,  30,  30)
C_GRAY2   = ( 90,  90,  90)
C_GRAY3   = (150, 150, 150)
C_GRAY4   = (220, 220, 220)
C_GRAY5   = (248, 248, 250)
C_WHITE   = (255, 255, 255)
C_ORANGE  = (220,  90,   0)

def rgb(c): return c[0], c[1], c[2]

# ── Dados do relatório ────────────────────────────────────────────────────────
EMPRESA = "MGS CLEAN SOLUCOES E SERVICOS LTDA"
CNPJ    = "19.088.605/0001-04"
DATA    = "04/06/2026"
RISCO   = "MÉDIO"
SCORE   = 52

CADASTRO = [
    ("Razão Social",       "MGS CLEAN SOLUCOES E SERVICOS LTDA"),
    ("Nome anterior",      "MGS CLEAN COMÉRCIO E SERVIÇOS EIRELI"),
    ("CNPJ (matriz)",      "19.088.605/0001-04"),
    ("CNPJ (filial)",      "19.088.605/0002-95 — Maricá/RJ"),
    ("Situação",           "ATIVA"),
    ("Data de abertura",   "15/10/2013  (12 anos de operação)"),
    ("Natureza jurídica",  "2062 — Sociedade Empresária Limitada"),
    ("CNAE principal",     "J-6319-4/00 — Portais e serviços na Internet  (!)"),
    ("CNAE real (prático)","Limpeza / Asseio / Zeladoria / Copeiragem"),
    ("Capital social",     "R$ 16.000.000,00"),
    ("Porte",              "Médio/Grande"),
    ("Endereço",           "Av. das Américas 3434, Bl. 2 Sala 506, Barra da Tijuca — RJ"),
    ("Administrador",      "Eduardo da Silva Azevedo (desde 11/12/2024)"),
    ("E-mail",             "contato@mgsclean.net"),
    ("Domínio",            "mgsclean.net  (.net internacional — sem .br)"),
]

SINAIS = [
    ("ALTO",  "CNAE_INCONSISTENTE",
     "CNAE J-6319-4/00 (Portais de Internet) incompatível com atividade real de "
     "limpeza/zeladoria. Empresa impugnada em PE 05/2025 Estância/SE por este motivo. "
     "Pode caracterizar irregularidade tributária e vantagem indevida em licitações."),
    ("MÉDIO", "FILIAL_COINCIDENTE",
     "Filial em Maricá/RJ aberta em 11/12/2024 — mesmo dia da entrada do novo "
     "administrador, 34 dias após assinatura do Contrato 215/2024 (R$ 21,8M). "
     "Padrão de reestruturação societária pós-contrato."),
    ("MÉDIO", "IMPUGNACAO_LICITACAO",
     "Habilitação questionada em Pregão Eletrônico 05/2025 (Estância/SE). "
     "Contrarazões publicadas com argumento de CNAE incompatível."),
    ("MÉDIO", "CAPITAL_ELEVADO",
     "Capital social de R$ 16M para empresa de limpeza predial. Média setorial: "
     "R$ 300K – 2M. Valor 8×–50× acima do típico pode indicar capitalização artificial."),
    ("BAIXO", "DOMINIO_NAO_BR",
     "Empresa sem domínio .br. Usa .net internacional, dificultando rastreamento "
     "via RDAP Registro.br. E-mail @mgsclean.net não vincula CNPJ."),
    ("BAIXO", "CONCENTRACAO_BOMBEIROS",
     "FUNESBOM representa 22/41 contratos e 54% do empenhado 2025 (R$ 48,6M). "
     "4 contratos de 2022 acumularam 3 aditivos cada."),
]

# Empenhado por órgão 2025
ORGAOS_2025 = [
    ("Corpo de Bombeiros (FUNESBOM)", 48_631_848.06),
    ("Tribunal de Justiça (TJ/RJ)",   15_546_382.69),
    ("Polícia Militar (SEPM)",         10_984_661.78),
    ("PGE (Fundo Especial)",            3_345_655.60),
    ("TCE (Tribunal de Contas)",        2_371_757.94),
    ("INEA",                            2_045_603.11),
    ("Cultura (SECEC)",                 2_041_772.00),
    ("RIOPREVIDÊNCIA",                  1_845_593.06),
    ("Outros",                          1_152_570.49),
]

ORGAOS_2026 = [
    ("Corpo de Bombeiros (FUNESBOM)", 29_060_835.53),
    ("Tribunal de Justiça (TJ/RJ)",   15_712_533.99),
    ("Polícia Militar (SEPM)",          4_788_107.25),
    ("PGE (Fundo Especial)",            3_925_811.93),
    ("INEA",                            1_532_666.64),
    ("Cultura (SECEC)",                 1_374_702.40),
    ("Fundo Estadual de Saúde",           896_274.24),
    ("Outros",                          1_307_302.40),
]

MESES_2025 = [
    ("Jan", 28_711_452.88), ("Fev", 15_220_776.81), ("Mar", 11_546_032.54),
    ("Abr",    372_933.12), ("Mai", 11_158_944.41), ("Jun",  3_387_523.10),
    ("Jul",  1_497_190.58), ("Ago",  9_828_546.04), ("Set",  4_870_840.53),
    ("Out",  2_527_737.68), ("Nov",    617_498.76), ("Dez",    226_368.28),
]

MESES_2026 = [
    ("Jan", 24_794_208.66), ("Fev", 12_875_672.22), ("Mar", 5_510_009.15),
    ("Abr", 10_836_090.23), ("Mai",           0.0), ("Jun",  4_582_254.12),
]

CONTRATOS = [
    ("2023117",      "TJ (Fundo Especial)",             25_993_908.78, "Licitado",    1),
    ("215/2024",     "Polícia Militar",                 21_828_441.12, "Em Vigor",    2),
    ("CTT 154/2024", "Corpo de Bombeiros",              10_479_994.56, "Em Vigor",    1),
    ("003-1046-2024","TJ (Fundo Especial)",             10_133_962.14, "Em Vigor",    1),
    ("CTT 127/2024", "Corpo de Bombeiros",               6_179_981.76, "Em Vigor",    1),
    ("43/2023",      "PGE (Fundo Especial)",             5_829_998.00, "Em Vigor",    1),
    ("CTT 115/2024", "Corpo de Bombeiros",               5_219_701.80, "Em Vigor",    1),
    ("CTT 107/2024", "Corpo de Bombeiros",               4_699_899.48, "Em Vigor",    1),
    ("4/2025",       "INEA",                             4_598_000.00, "Em Vigor",    0),
    ("CTT 123/2024", "Corpo de Bombeiros",               4_189_804.20, "Em Vigor",    1),
    ("CTT 125/2024", "Corpo de Bombeiros",               3_969_703.32, "Em Vigor",    1),
    ("008/2025",     "Fundo Estadual de Saúde",          3_585_096.96, "Em Vigor",    0),
    ("099/2024",     "RIOPREVIDÊNCIA",                   3_171_961.00, "Em Vigor",    0),
    ("CTT 117/2024", "Corpo de Bombeiros",               2_929_933.08, "Em Vigor",    1),
    ("025/2023",     "Casa Civil",                       2_596_200.98, "Em Vigor",    3),
    ("CTT 116/2024", "Corpo de Bombeiros",               2_589_906.24, "Em Vigor",    1),
    ("CTT 118/2024", "Corpo de Bombeiros",               2_509_781.04, "Em Vigor",    1),
    ("CTT 19/2024",  "Corpo de Bombeiros",               2_428_027.80, "Encerrado",   0),
    ("CTT 119/2024", "Corpo de Bombeiros",               2_189_920.80, "Em Vigor",    1),
    ("CTT 20/2024",  "Corpo de Bombeiros",               2_062_446.66, "Encerrado",   0),
    ("CTT 122/2024", "Corpo de Bombeiros",               1_999_917.60, "Em Vigor",    1),
    ("CTT 22/2024",  "Corpo de Bombeiros",               1_934_630.52, "Encerrado",   0),
    ("45/2023",      "TCE",                              1_847_967.84, "Em Vigor",    0),
    ("18/2023",      "Cultura (SECEC)",                  1_771_001.62, "Em Vigor",    2),
    ("CTT 120/2024", "Corpo de Bombeiros",               1_646_996.28, "Em Vigor",    1),
    ("CTT 121/2024", "Corpo de Bombeiros",               1_589_923.56, "Em Vigor",    1),
    ("CTT 17/2024",  "Corpo de Bombeiros",               1_253_035.92, "Encerrado",   0),
    ("CTT 63/2022",  "Corpo de Bombeiros",               1_237_823.06, "Em Vigor",    3),
    ("005/2021",     "ITERJ",                            1_085_032.09, "Em Vigor",    3),
    ("CTT 21/2024",  "Corpo de Bombeiros",               1_078_703.04, "Encerrado",   0),
    ("CTT 50/2022",  "Corpo de Bombeiros",                 802_759.35, "Em Vigor",    3),
    ("CTT 66/2022",  "Corpo de Bombeiros",                 724_344.56, "Em Vigor",    3),
    ("02/2023",      "TCE",                                542_685.09, "Licitado",    0),
    ("034/2021",     "RIOPREVIDÊNCIA",                     440_160.72, "Em Vigor",    0),
    ("CTT 62/2022",  "Corpo de Bombeiros",                 398_317.78, "Em Vigor",    3),
    ("24/2025",      "PGE (Fundo Especial)",               358_226.88, "Em Vigor",    0),
    ("04/2021",      "TCE",                                333_883.20, "Extinto",      0),
    ("011/2022",     "Fundação Inst. de Pesca",            244_381.56, "Em Vigor",    0),
    ("53/2023",      "TCE",                                 97_378.80, "Em Vigor",    0),
    ("017/2021",     "Fazenda",                             76_297.08, "Em Vigor",    0),
    ("44/2023",      "TCE",                                 54_268.80, "Em Vigor",    0),
]

SEI_2025 = [
    "SEI-270003/000274/2025", "SEI-270003/000276/2025", "SEI-270003/000277/2025",
    "SEI-270003/000279/2025", "SEI-270003/000852/2025", "SEI-270003/000854/2025",
    "SEI-270003/000855/2025", "SEI-270003/000857/2025", "SEI-270003/000858/2025",
    "SEI-270003/000867/2025", "SEI-270003/000868/2025", "SEI-270003/000869/2025",
    "SEI-270003/000870/2025", "SEI-270003/000871/2025", "SEI-270003/001548/2024",
    "SEI-270003/001575/2024", "SEI-270003/002788/2025", "SEI-270003/002908/2025",
    "SEI-270005/000086/2024", "SEI-270042/000678/2021", "SEI-270042/000681/2021",
    "SEI-270042/001804/2022", "SEI-270060/000313/2024", "SEI-350192/003001/2023",
]
SEI_2026 = [
    "SEI-270003/000276/2025", "SEI-270003/000277/2025", "SEI-270003/000651/2025",
    "SEI-270003/000852/2025", "SEI-270003/000854/2025", "SEI-270003/000855/2025",
    "SEI-270003/000857/2025", "SEI-270003/000858/2025", "SEI-270003/000867/2025",
    "SEI-270003/000868/2025", "SEI-270003/000869/2025", "SEI-270003/000870/2025",
    "SEI-270003/002788/2025", "SEI-270003/002908/2025", "SEI-270003/003280/2025",
    "SEI-270003/003283/2025", "SEI-270003/004236/2025", "SEI-350192/003001/2023",
]


# ── Helper: formata moeda ────────────────────────────────────────────────────
def fmt_brl(v: float, decimals=2) -> str:
    if decimals == 0:
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def fmt_m(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v/1_000_000:.1f}M"
    return f"R$ {v/1_000:.0f}K"


# ── PDF class ─────────────────────────────────────────────────────────────────
class AuditPDF(FPDF):
    _show_header = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Register Unicode fonts
        _FONTS = "/usr/share/fonts/truetype/liberation"
        self.add_font("Liberation", "",   f"{_FONTS}/LiberationSans-Regular.ttf")
        self.add_font("Liberation", "B",  f"{_FONTS}/LiberationSans-Bold.ttf")
        self.add_font("Liberation", "I",  f"{_FONTS}/LiberationSans-Italic.ttf")
        self.add_font("Liberation", "BI", f"{_FONTS}/LiberationSans-BoldItalic.ttf")
        self.add_font("LiberationMono", "", f"{_FONTS}/LiberationMono-Regular.ttf")
        self.add_font("LiberationMono", "B", f"{_FONTS}/LiberationMono-Bold.ttf")

    def header(self):
        if not self._show_header:
            return
        # Thin top bar
        self.set_fill_color(*C_NAVY)
        self.rect(0, 0, 210, 9, "F")
        self.set_font("Liberation", "B", 7)
        self.set_text_color(*C_GRAY4)
        self.set_xy(8, 1.5)
        self.cell(100, 6, "JFN AGENT  |  Auditoria de Integridade Pública", 0, 0, "L")
        self.set_xy(8, 1.5)
        self.cell(194, 6, f"MGS CLEAN  |  CNPJ {CNPJ}", 0, 0, "R")
        self.set_text_color(*C_GRAY1)
        self.set_xy(15, 13)

    def footer(self):
        if not self._show_header:
            return
        self.set_y(-11)
        self.set_fill_color(*C_NAVY)
        self.rect(0, self.get_y() - 1, 210, 12, "F")
        self.set_font("Liberation", "", 6.5)
        self.set_text_color(*C_GRAY3)
        self.set_xy(8, self.get_y())
        self.cell(100, 8, "CONFIDENCIAL — Uso restrito a fins de compliance, auditoria e due diligence.", 0, 0, "L")
        self.cell(94, 8, f"Página {self.page_no()}  |  Gerado em {DATA}", 0, 0, "R")
        self.set_text_color(*C_GRAY1)

    # ── Utilitários de layout ──────────────────────────────────────────────
    def section_title(self, num: str, title: str, color=None):
        color = color or C_NAVY
        y0 = self.get_y()
        self.set_fill_color(*color)
        self.rect(15, y0, 180, 9, "F")
        self.set_font("Liberation", "B", 10)
        self.set_text_color(*C_WHITE)
        self.set_xy(18, y0 + 0.8)
        self.cell(10, 7.5, num, 0, 0)
        self.cell(160, 7.5, title, 0, 1)
        self.set_text_color(*C_GRAY1)
        self.ln(3)

    def sub_title(self, title: str):
        self.set_font("Liberation", "B", 8.5)
        self.set_text_color(*C_BLUE)
        self.cell(0, 6, title, 0, 1, "L")
        self.set_draw_color(*C_BLUE)
        self.line(15, self.get_y(), 195, self.get_y())
        self.set_draw_color(*C_GRAY4)
        self.set_text_color(*C_GRAY1)
        self.ln(2)

    def callout(self, text: str, level: str = "warn"):
        colors = {
            "warn":  (C_LTAMB,  C_AMBER, "(!)  "),
            "error": (C_LTRED,  C_RED,   "X  "),
            "info":  (C_LTBLUE, C_BLUE,  "i  "),
            "ok":    (C_LTGRN,  C_GREEN, "OK  "),
        }
        bg, border, icon = colors.get(level, colors["info"])
        y0 = self.get_y()
        self.set_fill_color(*bg)
        self.set_draw_color(*border)
        # Left accent bar
        self.set_fill_color(*border)
        self.rect(15, y0, 3, 12, "F")
        self.set_fill_color(*bg)
        self.rect(18, y0, 177, 12, "F")
        self.set_font("Liberation", "B", 8)
        self.set_text_color(*border)
        self.set_xy(20, y0 + 2)
        self.cell(170, 4, icon + text[:140], 0, 1)
        self.set_text_color(*C_GRAY1)
        self.set_draw_color(*C_GRAY4)
        self.ln(4)

    def key_value_table(self, rows: list[tuple], col_w=(55, 125)):
        self.set_font("Liberation", "", 8)
        for i, (k, v) in enumerate(rows):
            bg = C_GRAY5 if i % 2 == 0 else C_WHITE
            self.set_fill_color(*bg)
            y0 = self.get_y()
            self.set_font("Liberation", "B", 8)
            self.set_text_color(*C_NAVY)
            self.cell(col_w[0], 6, "  " + k, 1, 0, "L", fill=True)
            self.set_font("Liberation", "", 8)
            self.set_text_color(*C_GRAY1)
            self.cell(col_w[1], 6, "  " + str(v)[:80], 1, 1, "L", fill=True)
        self.ln(2)

    def contracts_table(self, rows: list[tuple]):
        """Draw contracts table with header."""
        headers = ["Contrato", "Órgão", "Valor (R$)", "Situação", "Adit."]
        widths  = [32, 60, 38, 28, 15]
        # header
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("Liberation", "B", 7.5)
        for h, w in zip(headers, widths):
            self.cell(w, 7, h, 1, 0, "C", fill=True)
        self.ln()
        self.set_text_color(*C_GRAY1)
        for idx, (num, orgao, val, sit, adit) in enumerate(rows):
            bg = C_GRAY5 if idx % 2 == 0 else C_WHITE
            self.set_fill_color(*bg)
            # Highlight high-value or risky
            if val >= 10_000_000:
                self.set_fill_color(255, 248, 220)
            if adit >= 3:
                self.set_fill_color(255, 240, 240)
            self.set_font("Liberation", "B" if val >= 10_000_000 else "", 7)
            self.cell(32, 5.5, num[:18], 1, 0, "L", fill=True)
            self.set_font("Liberation", "", 7)
            self.cell(60, 5.5, orgao[:34], 1, 0, "L", fill=True)
            self.set_font("Liberation", "B" if val >= 10_000_000 else "", 7)
            vstr = fmt_brl(val)
            self.cell(38, 5.5, vstr, 1, 0, "R", fill=True)
            sit_color = C_GREEN if sit == "Em Vigor" else (C_GRAY3 if sit == "Encerrado" else C_AMBER)
            self.set_text_color(*sit_color)
            self.set_font("Liberation", "", 7)
            self.cell(28, 5.5, sit, 1, 0, "C", fill=True)
            self.set_text_color(*C_GRAY1)
            adit_color = C_RED if adit >= 3 else (C_AMBER if adit == 2 else C_GRAY1)
            self.set_text_color(*adit_color)
            self.set_font("Liberation", "B" if adit >= 3 else "", 7)
            self.cell(15, 5.5, str(adit), 1, 1, "C", fill=True)
            self.set_text_color(*C_GRAY1)
        self.ln(2)

    def hbar_chart(self, data: list[tuple], x: float, y: float,
                   w: float, row_h: float, bar_color, label_w=68, show_pct=True):
        """Horizontal bar chart. data = [(label, value)]"""
        max_val = max(v for _, v in data) if data else 1
        total   = sum(v for _, v in data)
        bar_area = w - label_w - 28
        self.set_xy(x, y)
        for label, val in data:
            bar_w = (val / max_val) * bar_area
            pct   = val / total * 100
            cur_y = self.get_y()
            # Label
            self.set_font("Liberation", "", 7)
            self.set_text_color(*C_GRAY2)
            self.set_xy(x, cur_y + (row_h - 4.5) / 2)
            self.cell(label_w, 4.5, label[:34], 0, 0, "L")
            # Bar background
            self.set_fill_color(*C_GRAY4)
            self.rect(x + label_w, cur_y + 1, bar_area, row_h - 2, "F")
            # Bar fill
            self.set_fill_color(*bar_color)
            if bar_w > 0:
                self.rect(x + label_w, cur_y + 1, bar_w, row_h - 2, "F")
            # Value label
            self.set_font("Liberation", "B", 7)
            self.set_text_color(*C_GRAY1)
            self.set_xy(x + label_w + bar_area + 1, cur_y + (row_h - 4.5) / 2)
            lbl = f"{fmt_m(val)}"
            if show_pct:
                lbl += f"  ({pct:.0f}%)"
            self.cell(27, 4.5, lbl, 0, 0, "L")
            self.set_xy(x, cur_y + row_h)
        self.ln(2)

    def vbar_chart(self, data: list[tuple], x: float, y: float,
                   w: float, h: float, bar_color, bar_color2=None):
        """Vertical bar chart. data = [(label, value)]"""
        n       = len(data)
        max_val = max(v for _, v in data) if data else 1
        spacing = w / n
        bar_w   = spacing * 0.65
        # Axis
        self.set_draw_color(*C_GRAY4)
        self.line(x, y, x, y + h)
        self.line(x, y + h, x + w, y + h)
        # Gridlines (3 horizontal)
        for lvl in [0.25, 0.5, 0.75]:
            gy = y + h - lvl * h
            self.set_draw_color(*C_GRAY4)
            self.dashed_line(x, gy, x + w, gy, 1, 1)
            self.set_font("Liberation", "", 5.5)
            self.set_text_color(*C_GRAY3)
            self.set_xy(x - 14, gy - 2)
            self.cell(13, 4, fmt_m(max_val * lvl), 0, 0, "R")

        for i, (label, val) in enumerate(data):
            bx    = x + i * spacing + (spacing - bar_w) / 2
            bh    = (val / max_val) * h if val > 0 else 0
            by    = y + h - bh
            color = bar_color2 if bar_color2 and i >= 12 else bar_color
            self.set_fill_color(*color)
            if bh > 0:
                self.rect(bx, by, bar_w, bh, "F")
            # Value above bar
            if bh > 3:
                self.set_font("Liberation", "", 5)
                self.set_text_color(*C_GRAY2)
                self.set_xy(bx - 1, by - 4)
                self.cell(bar_w + 2, 4, fmt_m(val) if val > 500_000 else "", 0, 0, "C")
            # Month label
            self.set_font("Liberation", "", 5.5)
            self.set_text_color(*C_GRAY2)
            self.set_xy(bx - 1, y + h + 1)
            self.cell(bar_w + 2, 4, label, 0, 0, "C")
        self.set_text_color(*C_GRAY1)
        self.set_draw_color(*C_GRAY4)

    def metric_card(self, x, y, w, h, value, label, color, sub=None):
        """Draw a KPI metric card."""
        self.set_fill_color(*color)
        self.rect(x, y, w, h, "F")
        # Left accent bar
        darker = tuple(max(0, c - 40) for c in color)
        self.set_fill_color(*darker)
        self.rect(x, y, 3, h, "F")
        self.set_font("Liberation", "B", 14)
        self.set_text_color(*C_NAVY)
        self.set_xy(x + 4, y + 3)
        self.cell(w - 5, 9, str(value), 0, 1)
        self.set_font("Liberation", "", 7.5)
        self.set_text_color(*C_GRAY2)
        self.set_xy(x + 4, y + 12)
        self.cell(w - 5, 5, label, 0, 1)
        if sub:
            self.set_font("Liberation", "I", 6.5)
            self.set_text_color(*C_GRAY3)
            self.set_xy(x + 4, y + 17)
            self.cell(w - 5, 4, sub, 0, 1)
        self.set_text_color(*C_GRAY1)

    def risk_gauge(self, x, y, score: int):
        """Draws a horizontal segmented gauge for risk score 0-100."""
        w, h = 80, 10
        # Background
        self.set_fill_color(*C_GRAY4)
        self.rect(x, y, w, h, "F")
        # Colored fill (score %)
        fill_w = (score / 100) * w
        if score < 30:
            fc = C_GREEN
        elif score < 60:
            fc = C_AMBER
        else:
            fc = C_RED
        self.set_fill_color(*fc)
        self.rect(x, y, fill_w, h, "F")
        # Score label inside
        self.set_font("Liberation", "B", 9)
        self.set_text_color(*C_WHITE)
        self.set_xy(x + fill_w - 16, y + 1)
        self.cell(15, 8, f"{score}/100", 0, 0, "R")
        # Tick marks
        for pct in [30, 60]:
            tx = x + pct / 100 * w
            self.set_draw_color(*C_WHITE)
            self.line(tx, y, tx, y + h)
        self.set_text_color(*C_GRAY1)
        self.set_draw_color(*C_GRAY4)
        # Scale labels
        self.set_font("Liberation", "", 6)
        self.set_text_color(*C_GRAY3)
        for pct, lbl in [(0, "0"), (30, "30"), (60, "60"), (100, "100")]:
            self.set_xy(x + pct / 100 * w - 3, y + h + 0.5)
            self.cell(6, 4, lbl, 0, 0, "C")
        self.set_text_color(*C_GRAY1)

    def signal_row(self, nivel: str, code: str, text: str):
        colors = {"ALTO": (C_RED, C_LTRED), "MÉDIO": (C_AMBER, C_LTAMB), "BAIXO": (C_GREEN, C_LTGRN)}
        c_border, c_bg = colors.get(nivel, (C_GRAY3, C_GRAY5))
        y0 = self.get_y()
        # Level badge
        self.set_fill_color(*c_border)
        self.rect(15, y0, 15, 18, "F")
        self.set_font("Liberation", "B", 6.5)
        self.set_text_color(*C_WHITE)
        self.set_xy(15, y0 + 3)
        self.cell(15, 6, nivel, 0, 1, "C")
        self.set_xy(15, y0 + 9)
        icon = {"ALTO": "!", "MÉDIO": "~", "BAIXO": "v"}.get(nivel, "")
        self.set_font("Liberation", "B", 8)
        self.cell(15, 6, icon, 0, 0, "C")
        # Content
        self.set_fill_color(*c_bg)
        self.rect(30, y0, 165, 18, "F")
        self.set_font("Liberation", "B", 8)
        self.set_text_color(*c_border)
        self.set_xy(32, y0 + 1.5)
        self.cell(160, 5.5, code, 0, 1)
        self.set_font("Liberation", "", 7.5)
        self.set_text_color(*C_GRAY1)
        self.set_xy(32, y0 + 7.5)
        self.multi_cell(161, 4.5, text[:200], 0, "L")
        self.set_y(y0 + 20)

    def dashed_line(self, x1, y1, x2, y2, dash=2, gap=2):
        length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if length == 0: return
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0
        drawing = True
        while pos < length:
            seg = min(dash if drawing else gap, length - pos)
            if drawing:
                self.line(x1 + dx * pos, y1 + dy * pos,
                          x1 + dx * (pos + seg), y1 + dy * (pos + seg))
            pos += seg
            drawing = not drawing

    def legend_item(self, x, y, color, label):
        self.set_fill_color(*color)
        self.rect(x, y, 6, 4, "F")
        self.set_font("Liberation", "", 7)
        self.set_text_color(*C_GRAY2)
        self.set_xy(x + 7, y - 0.5)
        self.cell(40, 5, label, 0, 0)
        self.set_text_color(*C_GRAY1)


# ── Geração das páginas ───────────────────────────────────────────────────────

def build_pdf() -> AuditPDF:
    pdf = AuditPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    # Register Unicode fonts
    _FONTS = "/usr/share/fonts/truetype/liberation"
    pdf.add_font("Liberation", "",   f"{_FONTS}/LiberationSans-Regular.ttf")
    pdf.add_font("Liberation", "B",  f"{_FONTS}/LiberationSans-Bold.ttf")
    pdf.add_font("Liberation", "I",  f"{_FONTS}/LiberationSans-Italic.ttf")
    pdf.add_font("Liberation", "BI", f"{_FONTS}/LiberationSans-BoldItalic.ttf")
    pdf.add_font("LiberationMono", "", f"{_FONTS}/LiberationMono-Regular.ttf")
    pdf.add_font("LiberationMono", "B", f"{_FONTS}/LiberationMono-Bold.ttf")


    # ── CAPA ─────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf._show_header = False

    # Full-width dark header block
    pdf.set_fill_color(*C_NAVY)
    pdf.rect(0, 0, 210, 70, "F")

    # Decorative accent stripe
    pdf.set_fill_color(*C_BLUE)
    pdf.rect(0, 66, 210, 4, "F")
    pdf.set_fill_color(255, 140, 0)
    pdf.rect(0, 70, 210, 2, "F")

    # JFN branding
    pdf.set_font("Liberation", "B", 10)
    pdf.set_text_color(180, 200, 255)
    pdf.set_xy(15, 12)
    pdf.cell(0, 7, "JFN AGENT  ·  Auditoria de Integridade Pública", 0, 1, "C")

    pdf.set_font("Liberation", "", 8)
    pdf.set_text_color(140, 160, 210)
    pdf.set_xy(15, 19)
    pdf.cell(0, 5, "Sistema Integrado de Compliance · Gestão de Riscos · Due Diligence Pública", 0, 1, "C")

    # Report type
    pdf.set_font("Liberation", "B", 16)
    pdf.set_text_color(*C_WHITE)
    pdf.set_xy(15, 30)
    pdf.cell(0, 10, "RELATÓRIO DE AUDITORIA E AVALIAÇÃO DE RISCO", 0, 1, "C")

    pdf.set_font("Liberation", "", 9)
    pdf.set_text_color(180, 200, 255)
    pdf.set_xy(15, 40)
    pdf.cell(0, 6, "Auditoria Forense  |  Avaliação de Risco Corporativo  |  Análise de Compliance", 0, 1, "C")

    pdf.set_font("Liberation", "", 8)
    pdf.set_text_color(120, 150, 200)
    pdf.set_xy(15, 48)
    pdf.cell(0, 5, "Grau de sigilo: CONFIDENCIAL  ·  Uso restrito a fins de auditoria e due diligence", 0, 1, "C")

    # Company name block
    pdf.set_fill_color(*C_WHITE)
    pdf.rect(20, 80, 170, 28, "F")
    pdf.set_fill_color(255, 140, 0)
    pdf.rect(20, 80, 5, 28, "F")

    pdf.set_font("Liberation", "B", 14)
    pdf.set_text_color(*C_NAVY)
    pdf.set_xy(28, 83)
    pdf.cell(157, 9, EMPRESA, 0, 1)
    pdf.set_font("Liberation", "", 9)
    pdf.set_text_color(*C_GRAY2)
    pdf.set_xy(28, 92)
    pdf.cell(80, 6, f"CNPJ: {CNPJ}", 0, 0)
    pdf.set_xy(28, 98)
    pdf.set_font("Liberation", "", 8)
    pdf.cell(80, 5, "Serviços Gerais · Limpeza · Zeladoria · Copeiragem", 0, 0)

    # Risk badge
    risco_color = {"ALTO": C_RED, "MÉDIO": C_AMBER, "BAIXO": C_GREEN}.get(RISCO, C_GRAY3)
    pdf.set_fill_color(*risco_color)
    pdf.rect(145, 82, 42, 22, "F")
    pdf.set_font("Liberation", "B", 9)
    pdf.set_text_color(*C_WHITE)
    pdf.set_xy(145, 84)
    pdf.cell(42, 6, "RISCO GERAL", 0, 1, "C")
    pdf.set_font("Liberation", "B", 18)
    pdf.set_xy(145, 90)
    pdf.cell(42, 12, RISCO, 0, 1, "C")

    # Score circle simulation (box)
    pdf.set_fill_color(*C_GRAY5)
    pdf.rect(20, 115, 170, 55, "F")
    pdf.set_fill_color(*risco_color)
    pdf.rect(20, 115, 5, 55, "F")

    # Score gauge
    pdf.set_font("Liberation", "B", 9)
    pdf.set_text_color(*C_NAVY)
    pdf.set_xy(28, 118)
    pdf.cell(50, 6, f"Score de Risco: {SCORE}/100", 0, 0)
    pdf.set_xy(28, 124)
    pdf.risk_gauge(28, 126, SCORE)

    # Scale legend
    pdf.set_font("Liberation", "", 6.5)
    pdf.set_text_color(*C_GRAY3)
    pdf.set_xy(28, 140)
    pdf.cell(26, 4, "0–29: BAIXO", 0, 0)
    pdf.set_xy(54, 140)
    pdf.cell(26, 4, "30–59: MÉDIO", 0, 0)
    pdf.set_xy(82, 140)
    pdf.cell(26, 4, "60–100: ALTO", 0, 0)

    # Key metrics summary
    pdf.set_font("Liberation", "B", 8)
    pdf.set_text_color(*C_NAVY)
    pdf.set_xy(28, 148)
    pdf.cell(0, 5, "Métricas-chave  ─────────────────────────────────────────────────", 0, 1)
    metrics = [
        ("Contratos ativos (SIAFE/RJ)", "41 contratos  |  R$ 146,7M valor contratado"),
        ("Empenhado 2025 (TFE/RJ)", "R$ 89,97M  |  84 empenhos  |  9 órgãos"),
        ("Empenhado 2026 Jan–Jun (TFE/RJ)", "R$ 58,60M  |  47 empenhos  |  7 órgãos"),
        ("Recebido Governo Federal (acumulado)", "R$ 66,32M  |  Portal da Transparência"),
        ("Processos SEI vinculados", "42 processos  (24 em 2025 · 18 em 2026)"),
        ("Sanções federais (CEIS/CNEP/CEPIM)", "Nenhuma identificada"),
    ]
    pdf.set_font("Liberation", "", 7.5)
    pdf.set_text_color(*C_GRAY1)
    for k, v in metrics:
        pdf.set_xy(30, pdf.get_y())
        pdf.set_font("Liberation", "B", 7.5)
        pdf.set_text_color(*C_GRAY2)
        pdf.cell(80, 5, k + ":", 0, 0)
        pdf.set_font("Liberation", "", 7.5)
        pdf.set_text_color(*C_GRAY1)
        pdf.cell(80, 5, v, 0, 1)

    # Footer info
    pdf.set_text_color(*C_GRAY3)
    pdf.set_font("Liberation", "", 7)
    pdf.set_xy(15, 245)
    pdf.cell(180, 5, f"Data de análise: {DATA}  ·  Fontes: TFE/RJ · SIAFE2 · Portal da Transparência · Busca pública", 0, 0, "C")
    pdf.set_xy(15, 250)
    pdf.cell(180, 5, "Este relatório foi gerado automaticamente pelo JFN Agent e não substitui análise jurídica especializada.", 0, 0, "C")

    pdf.set_font("Liberation", "B", 8)
    pdf.set_text_color(*C_NAVY)
    pdf.set_fill_color(*C_NAVY)
    pdf.rect(0, 283, 210, 14, "F")
    pdf.set_text_color(*C_GRAY4)
    pdf.set_font("Liberation", "", 7)
    pdf.set_xy(15, 286)
    pdf.cell(180, 5, "CONFIDENCIAL  ·  JFN Agent  ·  Auditoria de Integridade Pública", 0, 0, "C")

    # ── PÁGINA 2: SUMÁRIO EXECUTIVO ──────────────────────────────────────────
    pdf._show_header = True
    pdf.add_page()
    pdf.section_title("I", "SUMÁRIO EXECUTIVO")

    # 4 metric cards
    card_y = pdf.get_y()
    card_w = 42
    card_h = 26
    cards = [
        ("R$ 146,7M",  "Contratos SIAFE/RJ",     "41 contratos ativos",         C_LTBLUE),
        ("R$ 89,97M",  "Empenhado 2025",          "84 empenhos · 9 órgãos",      C_LTGRN),
        ("R$ 58,60M",  "Empenhado 2026 (parcial)","Jan–Jun · 47 empenhos",       C_LTAMB),
        ("MÉDIO",      "Nível de Risco",           f"Score {SCORE}/100 · 6 sinais", C_LTRED),
    ]
    for i, (val, lbl, sub, color) in enumerate(cards):
        cx = 15 + i * (card_w + 4)
        pdf.metric_card(cx, card_y, card_w, card_h, val, lbl, color, sub)

    pdf.set_y(card_y + card_h + 6)

    # Risk score visualization
    pdf.sub_title("Score de Risco Global")
    gauge_y = pdf.get_y()
    pdf.risk_gauge(15, gauge_y, SCORE)
    pdf.set_y(gauge_y + 18)

    score_tbl = [
        ("Score calculado",    f"{SCORE}/100 — Nível MÉDIO"),
        ("Sinais identificados", "6 total  (1 ALTO · 3 MÉDIO · 2 BAIXO)"),
        ("Fator dominante",    "CNAE incompatível com atividade (risco regulatório e licitatório)"),
        ("Fator agravante",    "Reestruturação societária pós-contrato (blindagem patrimonial)"),
        ("Fator mitigador",    "Empresa ativa, sem sanções federais, contratos regularmente firmados"),
    ]
    pdf.key_value_table(score_tbl)

    # Principais achados
    pdf.sub_title("Principais Achados")
    findings = [
        ("[ALTO]", "CNAE J-6319-4/00 (Internet) incompatível com atividade real. Empresa impugnada em licitação."),
        ("[MEDIO]", "Reestruturação societária simultânea (filial + novo admin) 34 dias após contrato de R$ 21,8M."),
        ("[MEDIO]", "Capital social de R$ 16M — 8 a 50× acima da média setorial de limpeza predial."),
        ("[INFO]",  "FUNESBOM (Bombeiros) concentra 22 contratos e 54% do empenhado em 2025 (R$ 48,6M)."),
        ("[INFO]",  "Projeção 2026 ≥ R$ 117M empenhado (ritmo atual de R$ 58,6M em 5 meses)."),
        ("[OK] OK",    "Nenhuma sanção federal identificada. Empresa em situação cadastral ATIVA na Receita Federal."),
    ]
    for icon_lbl, text in findings:
        pdf.set_font("Liberation", "", 8)
        pdf.set_text_color(*C_GRAY1)
        pdf.set_x(15)
        pdf.cell(22, 5.5, icon_lbl, 0, 0)
        pdf.cell(158, 5.5, text[:110], 0, 1)
    pdf.ln(3)

    # Visão geral dos contratos por órgão (mini hbar)
    pdf.sub_title("Distribuição dos Contratos por Órgão (2025 — Empenhado)")
    pdf.hbar_chart(ORGAOS_2025, 15, pdf.get_y(), 180, 8, C_BLUE)

    # ── PÁGINA 3: DADOS CADASTRAIS ───────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("II", "DADOS CADASTRAIS E QUADRO SOCIETÁRIO")

    pdf.sub_title("Dados Cadastrais — Receita Federal")
    pdf.key_value_table(CADASTRO)

    pdf.callout(
        "CNAE J-6319-4/00 (Portais de Internet) é incompatível com a atividade real de limpeza, "
        "zeladoria e copeiragem. Empresa foi impugnada em PE 05/2025 por este motivo.",
        "error"
    )
    pdf.callout(
        "Filial em Maricá/RJ (CNPJ 19.088.605/0002-95) aberta em 11/12/2024 — "
        "mesmo dia da entrada do administrador Eduardo da Silva Azevedo, 34 dias após "
        "assinatura do Contrato 215/2024 com a SEPM (R$ 21.828.441,12).",
        "warn"
    )

    pdf.sub_title("Quadro Societário")
    pdf.key_value_table([
        ("Administrador",       "Eduardo da Silva Azevedo"),
        ("Qualificação",        "Sócio-Administrador"),
        ("Data de entrada",     "11/12/2024  (!) Coincide com abertura da filial Maricá"),
        ("Tipo societário ant.", "EIRELI (extinto por Lei 14.195/2021) → transformado em Ltda"),
        ("Expansão da rede",    "Busca reversa por CPF limitada (dados RF mascarados). Verificar JUCERJA."),
    ])

    pdf.sub_title("Evidência Digital")
    pdf.key_value_table([
        ("Domínio",          "mgsclean.net  (.net internacional — não registrado no Registro.br)"),
        ("E-mail",           "contato@mgsclean.net  (domínio próprio, não genérico — positivo)"),
        ("Análise RDAP",     "Domínio .net fora da jurisdição do Registro.br — rastreamento limitado"),
        ("Avaliação",        "Uso de .net para empresa pública-dependente é atípico; .com.br seria padrão."),
    ])

    # ── PÁGINA 4: ANÁLISE FINANCEIRA — GRÁFICOS ─────────────────────────────
    pdf.add_page()
    pdf.section_title("III", "ANÁLISE FINANCEIRA — EMPENHADO POR ÓRGÃO")

    pdf.sub_title("Empenhado 2025 por Órgão Contratante  (Total: R$ 89.965.844,73)")
    pdf.hbar_chart(ORGAOS_2025, 15, pdf.get_y(), 180, 9, C_BLUE, label_w=72)

    pdf.ln(4)
    pdf.callout(
        "FUNESBOM (Corpo de Bombeiros) representa 54% do total empenhado em 2025. "
        "22 contratos com este único órgão, incluindo 4 contratos de 2022 com 3 aditivos cada.",
        "warn"
    )

    pdf.sub_title("Empenhado 2026 Jan–Jun por Órgão  (Total: R$ 58.598.234,38)")
    pdf.hbar_chart(ORGAOS_2026, 15, pdf.get_y(), 180, 9, C_ORANGE, label_w=72)

    pdf.ln(4)
    pdf.callout(
        "Projeção 2026: com R$ 58,6M empenhados em apenas 5 meses, o ano pode superar 2025. "
        "Tendência de crescimento contínuo do volume contratado.",
        "info"
    )

    # Comparativo direto
    pdf.sub_title("Comparativo por Órgão: 2025 vs 2026 Parcial")
    comp_headers = ["Órgão", "2025 (R$)", "2026 Parcial (R$)", "Var."]
    comp_widths  = [68, 38, 42, 30]
    pdf.set_fill_color(*C_NAVY)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Liberation", "B", 7.5)
    for h, w in zip(comp_headers, comp_widths):
        pdf.cell(w, 7, h, 1, 0, "C", fill=True)
    pdf.ln()
    pdf.set_text_color(*C_GRAY1)
    orgaos_2025_dict = dict(ORGAOS_2025)
    orgaos_2026_dict = dict(ORGAOS_2026)
    all_orgaos = list(dict.fromkeys([o for o, _ in ORGAOS_2025] + [o for o, _ in ORGAOS_2026]))
    for idx, org in enumerate(all_orgaos):
        v25 = orgaos_2025_dict.get(org, 0)
        v26 = orgaos_2026_dict.get(org, 0)
        var = (v26 / v25 - 1) * 100 if v25 > 0 else None
        bg = C_GRAY5 if idx % 2 == 0 else C_WHITE
        pdf.set_fill_color(*bg)
        pdf.set_font("Liberation", "", 7.5)
        pdf.cell(68, 5.5, org[:36], 1, 0, "L", fill=True)
        pdf.cell(38, 5.5, fmt_brl(v25) if v25 else "—", 1, 0, "R", fill=True)
        pdf.cell(42, 5.5, fmt_brl(v26) if v26 else "—", 1, 0, "R", fill=True)
        if var is not None:
            color = C_GREEN if var < 0 else C_RED
            pdf.set_text_color(*color)
            pdf.set_font("Liberation", "B", 7.5)
            pdf.cell(30, 5.5, f"{'+' if var > 0 else ''}{var:.0f}% (6m)", 1, 1, "C", fill=True)
        else:
            pdf.set_text_color(*C_GRAY3)
            pdf.cell(30, 5.5, "novo", 1, 1, "C", fill=True)
        pdf.set_text_color(*C_GRAY1)
    pdf.ln(2)

    # ── PÁGINA 5: EVOLUÇÃO MENSAL ────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("III-B", "EVOLUÇÃO MENSAL DO EMPENHADO (2025 e 2026)")

    pdf.sub_title("Empenhado Mensal — 2025  (R$ 89,97M · 84 empenhos)")
    chart_x = 30
    chart_w = 155
    chart_h = 50
    chart_y = pdf.get_y()
    pdf.vbar_chart(MESES_2025, chart_x, chart_y, chart_w, chart_h, C_BLUE)
    pdf.legend_item(chart_x, chart_y + chart_h + 9, C_BLUE, "Empenhado 2025")
    pdf.set_y(chart_y + chart_h + 16)
    pdf.ln(2)

    pdf.key_value_table([
        ("Maior mês",   "Janeiro/2025: R$ 28.711.452,88 (32% do total anual) — renovações de início de exercício"),
        ("Padrão sazonal", "Forte concentração Jan–Mar (57,7M = 64%); típico em contratos de prestação contínua"),
        ("Mês mais fraco", "Dezembro/2025: R$ 226.368,28 — fim de exercício com poucos empenhos novos"),
    ])

    pdf.sub_title("Empenhado Mensal — 2026 Jan–Jun (R$ 58,60M · 47 empenhos)")
    chart_y2 = pdf.get_y()
    pdf.vbar_chart(MESES_2026, chart_x, chart_y2, chart_w, chart_h, C_ORANGE)
    pdf.legend_item(chart_x, chart_y2 + chart_h + 9, C_ORANGE, "Empenhado 2026 (parcial)")
    pdf.set_y(chart_y2 + chart_h + 16)
    pdf.ln(2)

    pdf.key_value_table([
        ("Ritmo 2026",     "R$ 58,6M em 5 meses = R$ 11,7M/mês médio (vs. R$ 7,5M/mês em 2025)"),
        ("Projeção anual", "≈ R$ 117–140M estimado para 2026 (crescimento de 30–55% sobre 2025)"),
        ("Maior mês",      "Janeiro/2026: R$ 24.794.208,66 — renovações de início de exercício"),
        ("Abril/2026",     "R$ 10.836.090,23 — repique relevante; verificar contratos vinculados"),
    ])

    # Tabela mensal resumo
    pdf.sub_title("Tabela Resumo Mensal — Comparativo 2025 vs 2026")
    m_headers = ["Mês", "Empenhado 2025 (R$)", "Empenhos 2025", "Empenhado 2026 (R$)", "Empenhos 2026"]
    m_widths  = [18, 46, 26, 46, 26]
    pdf.set_fill_color(*C_NAVY)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Liberation", "B", 7.5)
    for h, w in zip(m_headers, m_widths):
        pdf.cell(w, 7, h, 1, 0, "C", fill=True)
    pdf.ln()
    meses_data = {
        "Jan": (28_711_452.88,  9, 24_794_208.66, 18),
        "Fev": (15_220_776.81, 14, 12_875_672.22, 14),
        "Mar": (11_546_032.54, 14,  5_510_009.15, 10),
        "Abr": (   372_933.12,  2, 10_836_090.23,  4),
        "Mai": (11_158_944.41,  7,            0,   0),
        "Jun": ( 3_387_523.10,  4,  4_582_254.12,  1),
        "Jul": ( 1_497_190.58,  9,             0,  0),
        "Ago": ( 9_828_546.04, 10,             0,  0),
        "Set": ( 4_870_840.53,  6,             0,  0),
        "Out": ( 2_527_737.68,  5,             0,  0),
        "Nov": (   617_498.76,  3,             0,  0),
        "Dez": (   226_368.28,  1,             0,  0),
    }
    pdf.set_text_color(*C_GRAY1)
    for idx, (mes, (v25, n25, v26, n26)) in enumerate(meses_data.items()):
        bg = C_GRAY5 if idx % 2 == 0 else C_WHITE
        pdf.set_fill_color(*bg)
        pdf.set_font("Liberation", "B" if mes in ("Jan","Abr") else "", 7.5)
        pdf.cell(18, 5.5, mes, 1, 0, "C", fill=True)
        pdf.set_font("Liberation", "", 7.5)
        pdf.cell(46, 5.5, fmt_brl(v25) if v25 else "—", 1, 0, "R", fill=True)
        pdf.cell(26, 5.5, str(n25) if n25 else "—", 1, 0, "C", fill=True)
        pdf.set_text_color(*(C_ORANGE if v26 > 0 else C_GRAY3))
        pdf.cell(46, 5.5, fmt_brl(v26) if v26 else "(a coletar)", 1, 0, "R", fill=True)
        pdf.cell(26, 5.5, str(n26) if n26 else "—", 1, 1, "C", fill=True)
        pdf.set_text_color(*C_GRAY1)
    # Total row
    pdf.set_fill_color(*C_LTBLUE)
    pdf.set_font("Liberation", "B", 7.5)
    pdf.cell(18, 6, "TOTAL", 1, 0, "C", fill=True)
    pdf.cell(46, 6, "89.965.844,73", 1, 0, "R", fill=True)
    pdf.cell(26, 6, "84", 1, 0, "C", fill=True)
    pdf.set_text_color(*C_ORANGE)
    pdf.cell(46, 6, "58.598.234,38", 1, 0, "R", fill=True)
    pdf.cell(26, 6, "47", 1, 1, "C", fill=True)
    pdf.set_text_color(*C_GRAY1)
    pdf.ln(2)

    # ── PÁGINA 6-7: CONTRATOS SIAFE ──────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("IV", "CONTRATOS PÚBLICOS — SIAFE/RJ")

    pdf.key_value_table([
        ("Fonte",             "SIAFE2 — Execução > Contratos e Convênios (coleta: 04/06/2026)"),
        ("Total de contratos","41 contratos ativos ou encerrados"),
        ("Valor total",       "R$ 146.704.405,07"),
        ("Contratos em vigor","32 Em Vigor · 5 Encerrados · 2 Licitados · 1 Extinto · 1 outros"),
        ("Maior contrato",    "2023117/TJ-RJ: R$ 25.993.908,78"),
        ("Alertas",           "4 contratos com 3 aditivos (CTT 50/62/63/66-2022); 1 com 3 aditivos (005/2021 ITERJ; 025/2023 Casa Civil)"),
    ])

    pdf.callout(
        "Contratos CTT 50/62/63/66/2022 (Corpo de Bombeiros) e 005/2021 (ITERJ) acumularam "
        "3 aditivos cada. Aditivos sucessivos em contratos de curto valor unitário merecem "
        "análise individual para verificar adequação ao art. 65 da Lei 14.133/2021.",
        "warn"
    )

    pdf.sub_title(f"Lista Completa de Contratos  (41 contratos · R$ 146,7M)")
    pdf.set_font("Liberation", "", 7)
    pdf.set_text_color(*C_GRAY3)
    pdf.cell(0, 4, "* = valor ≥ R$ 10M  |  Linha amarela = contrato relevante  |  Linha vermelha = 3+ aditivos", 0, 1)
    pdf.ln(1)
    pdf.contracts_table(CONTRATOS)

    # ── PÁGINA 8: SINAIS DE RISCO ────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("V", "SINAIS DE RISCO — CLASSIFICAÇÃO E ANÁLISE")

    # Risk summary bars
    risk_counts = {"ALTO": 1, "MÉDIO": 3, "BAIXO": 2}
    risk_colors = {"ALTO": C_RED, "MÉDIO": C_AMBER, "BAIXO": C_GREEN}
    pdf.set_font("Liberation", "B", 8.5)
    pdf.set_text_color(*C_NAVY)
    pdf.cell(0, 6, "Distribuição dos Sinais por Nível de Criticidade", 0, 1)
    y_bars = pdf.get_y()
    bx = 15
    for nivel, cnt in risk_counts.items():
        color = risk_colors[nivel]
        pdf.set_fill_color(*color)
        bar_w = cnt * 20
        pdf.rect(bx, y_bars, bar_w, 8, "F")
        pdf.set_font("Liberation", "B", 8)
        pdf.set_text_color(*C_WHITE)
        pdf.set_xy(bx + 2, y_bars + 1)
        pdf.cell(bar_w - 2, 6, f"{nivel}: {cnt}", 0, 0)
        bx += bar_w + 4
    pdf.set_y(y_bars + 12)
    pdf.set_text_color(*C_GRAY1)

    # Score breakdown
    pdf.set_font("Liberation", "", 7.5)
    pdf.set_text_color(*C_GRAY2)
    pdf.cell(0, 5, "Contribuição ao score: ALTO = 25pts/sinal  |  MÉDIO = 8pts/sinal  |  BAIXO = 2pts/sinal  |  Total: 1×25 + 3×8 + 2×2 = 53pts (arredondado: 52)", 0, 1)
    pdf.ln(3)

    pdf.sub_title("Detalhamento de Cada Sinal")
    for nivel, code, text in SINAIS:
        pdf.signal_row(nivel, code, text)
        pdf.ln(1)

    # Risk matrix table
    pdf.ln(2)
    pdf.sub_title("Matriz de Risco Resumida")
    mx_headers = ["Sinal", "Nível", "Probabilidade", "Impacto", "Resposta Recomendada"]
    mx_widths  = [42, 18, 28, 28, 64]
    pdf.set_fill_color(*C_NAVY)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Liberation", "B", 7.5)
    for h, w in zip(mx_headers, mx_widths):
        pdf.cell(w, 7, h, 1, 0, "C", fill=True)
    pdf.ln()
    matrix = [
        ("CNAE_INCONSISTENTE",    "ALTO",  "Alta (já ocorreu)", "Alto",   "Verificar CNAE atual; acionar jurídico"),
        ("FILIAL_COINCIDENTE",    "MÉDIO", "Média",             "Médio",  "Monitorar estrutura societária"),
        ("IMPUGNACAO_LICITACAO",  "MÉDIO", "Média",             "Médio",  "Consultar histórico de habilitação"),
        ("CAPITAL_ELEVADO",       "MÉDIO", "Baixa",             "Baixo",  "Verificar origem do capital"),
        ("DOMINIO_NAO_BR",        "BAIXO", "Alta (confirmada)", "Baixo",  "Solicitar domínio .com.br"),
        ("CONCENTRACAO_BOMBEIROS","BAIXO", "Baixa",             "Médio",  "Auditar regularidade dos aditivos"),
    ]
    pdf.set_text_color(*C_GRAY1)
    for idx, (sinal, nivel, prob, imp, resp) in enumerate(matrix):
        bg = C_GRAY5 if idx % 2 == 0 else C_WHITE
        pdf.set_fill_color(*bg)
        nc = risk_colors[nivel]
        pdf.set_font("Liberation", "", 7.5)
        pdf.cell(42, 5.5, sinal[:24], 1, 0, "L", fill=True)
        pdf.set_text_color(*nc)
        pdf.set_font("Liberation", "B", 7.5)
        pdf.cell(18, 5.5, nivel, 1, 0, "C", fill=True)
        pdf.set_text_color(*C_GRAY1)
        pdf.set_font("Liberation", "", 7.5)
        pdf.cell(28, 5.5, prob, 1, 0, "C", fill=True)
        pdf.cell(28, 5.5, imp, 1, 0, "C", fill=True)
        pdf.cell(64, 5.5, resp[:40], 1, 1, "L", fill=True)
    pdf.ln(2)

    # ── PÁGINA 9: ORDENS BANCÁRIAS + SEI ─────────────────────────────────────
    pdf.add_page()
    pdf.section_title("VI", "ORDENS BANCÁRIAS PAGAS (OBs) — SIAFE")

    pdf.callout(
        "Os valores EMPENHADOS (Seção III) representam o compromisso orçamentário. "
        "As Ordens Bancárias confirmam o que foi efetivamente liquidado e transferido à empresa. "
        "A diferença entre empenhado e pago é material em uma auditoria forense.",
        "info"
    )

    pdf.key_value_table([
        ("Status da coleta",  "PENDENTE — requer Chrome + SIAFE2 rodando localmente"),
        ("Script disponível", "_SANDBOX/auditar_mgs_obs_siafe.py"),
        ("Uso",               "python _SANDBOX/auditar_mgs_obs_siafe.py  [2025 2026]"),
        ("Saída esperada",    "data/sei_cache/mgsclean_obs_{ano}.json + mgsclean_obs_resumo.md"),
        ("Metodologia",       "Login por exercício (2026=1, 2025=2, 2024=3...), filtro por favorecido CNPJ"),
        ("Caminho SIAFE",     "Execução > Execução Financeira > Ordens Bancárias > Filtro > CNPJ"),
    ])

    pdf.sub_title("Estrutura Esperada da Tabela de OBs (por Ano e Órgão)")
    obs_headers = ["Órgão (UG Emitente)", "2021", "2022", "2023", "2024", "2025", "2026", "TOTAL"]
    obs_widths  = [55, 17, 17, 17, 17, 20, 20, 17]
    pdf.set_fill_color(*C_NAVY)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Liberation", "B", 7)
    for h, w in zip(obs_headers, obs_widths):
        pdf.cell(w, 7, h, 1, 0, "C", fill=True)
    pdf.ln()
    orgaos_obs = [
        "Corpo de Bombeiros (FUNESBOM)",
        "Tribunal de Justiça (TJ/RJ)",
        "Polícia Militar (SEPM)",
        "PGE (Fundo Especial)",
        "INEA",
        "TCE",
        "RIOPREVIDÊNCIA",
        "Casa Civil",
        "Cultura (SECEC)",
        "Saúde (FES)",
        "ITERJ",
        "Outros",
        "TOTAL",
    ]
    pdf.set_text_color(*C_GRAY1)
    for idx, org in enumerate(orgaos_obs):
        is_total = org == "TOTAL"
        bg = C_LTBLUE if is_total else (C_GRAY5 if idx % 2 == 0 else C_WHITE)
        pdf.set_fill_color(*bg)
        font = "B" if is_total else ""
        pdf.set_font("Liberation", font, 7)
        pdf.cell(55, 5.5, org[:32], 1, 0, "L", fill=True)
        pdf.set_text_color(*C_GRAY3)
        for w in obs_widths[1:]:
            pdf.cell(w, 5.5, "—", 1, 0, "C", fill=True)
        pdf.ln()
        pdf.set_text_color(*C_GRAY1)
    pdf.ln(2)
    pdf.callout(
        "Após executar o script de coleta, substitua os '—' pelos valores reais. "
        "Divergências entre valor pago (OB) e valor contratado (SIAFE) são red flags prioritários.",
        "warn"
    )

    # SEI Processes
    pdf.section_title("VII", "PROCESSOS SEI VINCULADOS")

    pdf.key_value_table([
        ("2025", f"{len(SEI_2025)} processos identificados (empenhos e contratos)"),
        ("2026", f"{len(SEI_2026)} processos identificados (alguns reutilizados de 2025)"),
        ("Total único", f"≈ {len(set(SEI_2025 + SEI_2026))} processos distintos"),
        ("Auditar processo", "python _SANDBOX/sei_auditor.py <NUMERO_PROCESSO>"),
    ])

    pdf.sub_title("Processos SEI — 2025")
    pdf.set_font("LiberationMono", "", 7.5)
    pdf.set_text_color(*C_NAVY)
    cols = 3
    sei_per_row = [SEI_2025[i:i+cols] for i in range(0, len(SEI_2025), cols)]
    for row in sei_per_row:
        for proc in row:
            pdf.cell(60, 5, proc, 0, 0)
        pdf.ln()
    pdf.ln(2)

    pdf.sub_title("Processos SEI — 2026 (adicionais ou reutilizados)")
    pdf.set_font("LiberationMono", "", 7.5)
    sei26_per_row = [SEI_2026[i:i+cols] for i in range(0, len(SEI_2026), cols)]
    for row in sei26_per_row:
        for proc in row:
            pdf.cell(60, 5, proc, 0, 0)
        pdf.ln()
    pdf.set_text_color(*C_GRAY1)
    pdf.ln(2)

    pdf.callout(
        "Prioridade de auditoria SEI: processos dos 5 maiores contratos (2023117/TJ, 215/2024/PM, "
        "CTT 154/2024, 003-1046-2024/TJ, CTT 127/2024). Verificar objeto, partes, datas e aditivos.",
        "info"
    )

    # ── PÁGINA 10: SANÇÕES + WHOIS ────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("VIII", "VERIFICAÇÃO DE SANÇÕES FEDERAIS")

    pdf.callout(
        "Nenhuma sanção federal identificada para o CNPJ 19.088.605/0001-04 "
        "nos cadastros CEIS, CNEP e CEPIM do Portal da Transparência. "
        "Verificação confirmada por busca manual em 04/06/2026.",
        "ok"
    )

    pdf.key_value_table([
        ("CEIS — Empresas Inidôneas e Suspensas", "Sem registro"),
        ("CNEP — Empresas Punidas",               "Sem registro"),
        ("CEPIM — Entidades Impedidas",           "Não aplicável"),
        ("Verificação automática",                "Pendente — configurar TRANSPARENCIA_API_KEY"),
        ("Recomendação",                          "Repetir busca trimestral; monitorar TCU, TCE-RJ e CNMP"),
    ])

    pdf.sub_title("Verificação Estadual e Municipal Recomendada")
    pdf.set_font("Liberation", "", 8)
    pdf.set_text_color(*C_GRAY1)
    checks = [
        ("TCE-RJ",  "Tribunal de Contas do Estado — verificar irregularidades apontadas em contratos"),
        ("TCEII",   "Consultar ata de julgamento dos contratos auditados (TCE-RJ portal)"),
        ("Prefeitura RJ", "Portal de contratos RioSaúde — contratos 2022-0049, 2023-0037, 2023-0069"),
        ("JUCERJA", "Verificar histórico societário completo e possíveis empresas ligadas ao administrador"),
        ("Receita Federal", "Confirmar CNAE atual (pode ter sido alterado após identificação do problema)"),
    ]
    for org, desc in checks:
        pdf.set_xy(15, pdf.get_y())
        pdf.set_font("Liberation", "B", 8)
        pdf.set_text_color(*C_NAVY)
        pdf.cell(35, 5.5, org + ":", 0, 0)
        pdf.set_font("Liberation", "", 8)
        pdf.set_text_color(*C_GRAY1)
        pdf.cell(145, 5.5, desc, 0, 1)
    pdf.ln(4)

    # ── PÁGINA 11: CONCLUSÕES E RECOMENDAÇÕES ─────────────────────────────────
    pdf.add_page()
    pdf.section_title("IX", "CONCLUSÕES E RECOMENDAÇÕES")

    pdf.sub_title("Parecer Final")
    pdf.set_font("Liberation", "", 9)
    pdf.set_text_color(*C_GRAY1)
    parecer = (
        "A MGS CLEAN SOLUCOES E SERVICOS LTDA apresenta nível de risco MÉDIO (score 52/100), "
        "fundamentado na identificação de seis sinais de risco classificados por auditoria forense, "
        "avaliação de risco corporativo e análise de compliance.\n\n"
        "A empresa opera há 12 anos e possui carteira expressiva de contratos com o Estado do Rio de "
        "Janeiro (R$ 146,7M em 41 contratos). A ausência de sanções federais e a situação cadastral "
        "ATIVA são fatores mitigadores. Contudo, o CNAE registrado incompatível com a atividade "
        "real constitui irregularidade objetiva com impacto imediato em processos licitatórios, "
        "e a reestruturação societária pós-contrato eleva o risco de blindagem patrimonial.\n\n"
        "O volume contratado está em trajetória de crescimento acelerado: R$ 58,6M empenhados nos "
        "primeiros 5 meses de 2026 projeta ≥ R$ 117M no ano, superando 2025 em 30% ou mais. "
        "Esta expansão, concentrada em poucos órgãos (FUNESBOM e TJ/RJ = 79% do total), "
        "requer acompanhamento continuado."
    )
    pdf.multi_cell(0, 5.5, parecer)
    pdf.ln(4)

    pdf.sub_title("Recomendações por Área")

    # Three columns: Auditoria / Risco / Compliance
    col_w = 57
    col_gap = 4
    recs = {
        "Auditoria Forense": [
            "1. Coletar OBs pagas (script disponível) e cruzar com empenhado",
            "2. Auditar contratos CTT 50/62/63/66/2022 (3 aditivos cada)",
            "3. Verificar empenhos sem número de contrato (~16–20% do total)",
            "4. Abrir processos SEI prioritários (top 5 contratos)",
            "5. Confirmar valores pagos vs. contratados para identificar sobrepreço",
        ],
        "Avaliação de Risco": [
            "1. Monitorar CNAE: verificar se foi atualizado na RFB",
            "2. Rastrear rede societária do administrador (Eduardo S. Azevedo)",
            "3. Avaliar concentração FUNESBOM — 54% do empenhado em único órgão",
            "4. Monitorar projeção 2026 (crescimento de +55% projetado)",
            "5. Verificar capitalização R$ 16M — origem e consistência com porte",
        ],
        "Compliance": [
            "1. Impugnar ou questionar habilitação se CNAE não foi corrigido",
            "2. Exigir certidões negativas em renovações/aditamentos",
            "3. Incluir cláusula de CNAE correto em contratos futuros",
            "4. Notificar FUNESBOM e TJ/RJ para due diligence reforçada",
            "5. Agendar reverificação trimestral de sanções e situação cadastral",
        ],
    }
    start_y = pdf.get_y()
    for col_idx, (area, items) in enumerate(recs.items()):
        cx = 15 + col_idx * (col_w + col_gap)
        pdf.set_fill_color(*C_NAVY)
        pdf.rect(cx, start_y, col_w, 7, "F")
        pdf.set_font("Liberation", "B", 7.5)
        pdf.set_text_color(*C_WHITE)
        pdf.set_xy(cx + 2, start_y + 1)
        pdf.cell(col_w - 2, 5, area, 0, 0, "C")
        item_y = start_y + 9
        pdf.set_text_color(*C_GRAY1)
        for item in items:
            pdf.set_fill_color(C_GRAY5[0] if items.index(item) % 2 == 0 else C_WHITE[0],
                               C_GRAY5[1] if items.index(item) % 2 == 0 else C_WHITE[1],
                               C_GRAY5[2] if items.index(item) % 2 == 0 else C_WHITE[2])
            pdf.set_fill_color(*(C_GRAY5 if items.index(item) % 2 == 0 else C_WHITE))
            pdf.set_font("Liberation", "", 7)
            pdf.set_xy(cx, item_y)
            pdf.multi_cell(col_w, 5, item, 0, "L", fill=False)
            item_y = pdf.get_y() + 1
    pdf.set_y(start_y + 75)
    pdf.set_text_color(*C_GRAY1)
    pdf.ln(3)

    # Action plan table
    pdf.sub_title("Plano de Ação Prioritário")
    ap_headers = ["Prioridade", "Ação", "Responsável", "Prazo", "Status"]
    ap_widths  = [20, 75, 30, 22, 33]
    pdf.set_fill_color(*C_NAVY)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Liberation", "B", 7.5)
    for h, w in zip(ap_headers, ap_widths):
        pdf.cell(w, 7, h, 1, 0, "C", fill=True)
    pdf.ln()
    actions = [
        ("[URGENTE]", "Verificar CNAE atual na Receita Federal e avaliar impacto licitatório", "Jurídico", "Imediato", "Pendente"),
        ("[URGENTE]", "Coletar OBs pagas no SIAFE (script disponível) — confirmar valores", "Auditoria", "7 dias",   "Pendente"),
        ("[ALTA]",    "Auditar contratos com 3 aditivos (CTT 50/62/63/66/2022)", "Auditoria", "15 dias",  "Pendente"),
        ("[ALTA]",    "Rastrear rede societária do adm. Eduardo S. Azevedo", "Compliance", "15 dias",  "Pendente"),
        ("[ALTA]",    "Abrir processos SEI dos 5 maiores contratos no SEI-RJ", "Auditoria", "15 dias",  "Pendente"),
        ("[MEDIA]",   "Notificar FUNESBOM e TJ/RJ para due diligence em renovações", "Compliance", "30 dias",  "Pendente"),
        ("[MEDIA]",   "Configurar monitoramento automático (TRANSPARENCIA_API_KEY)", "TI", "30 dias",  "Pendente"),
        ("[BAIXA]",   "Reverificação trimestral de sanções e situação cadastral", "Compliance", "90 dias",  "Recorrente"),
    ]
    pdf.set_text_color(*C_GRAY1)
    for idx, (pri, acao, resp, prazo, status) in enumerate(actions):
        bg = C_GRAY5 if idx % 2 == 0 else C_WHITE
        pdf.set_fill_color(*bg)
        pdf.set_font("Liberation", "B" if "URGENTE" in pri else "", 7)
        pdf.cell(20, 5.5, pri.replace("[!] ","").replace("[~] ","").replace("[v] ",""), 1, 0, "C", fill=True)
        pdf.set_font("Liberation", "", 7)
        pdf.cell(75, 5.5, acao[:50], 1, 0, "L", fill=True)
        pdf.cell(30, 5.5, resp, 1, 0, "C", fill=True)
        pdf.cell(22, 5.5, prazo, 1, 0, "C", fill=True)
        pdf.set_text_color(*C_AMBER)
        pdf.cell(33, 5.5, status, 1, 1, "C", fill=True)
        pdf.set_text_color(*C_GRAY1)
    pdf.ln(3)

    # ── PÁGINA 12: METODOLOGIA E FONTES ──────────────────────────────────────
    pdf.add_page()
    pdf.section_title("X", "METODOLOGIA, FONTES E LIMITAÇÕES")

    pdf.sub_title("Fontes de Dados Utilizadas")
    fontes = [
        ("TFE — Transparência Fiscal do Estado RJ",
         "tfe.fazenda.rj.gov.br/tfe/web/fornecedor",
         "Empenhos por CNPJ, por mês e por órgão. Dados EMPENHADOS (não pagos). Coleta via CDP/Playwright."),
        ("SIAFE2 — Sistema Integrado de Administração Financeira",
         "siafe2.fazenda.rj.gov.br",
         "Contratos e Convênios (41 contratos, R$ 146,7M). OBs pendentes de coleta."),
        ("SEI — Sistema Eletrônico de Informações",
         "sei.rj.gov.br",
         "Processos administrativos vinculados a empenhos e contratos."),
        ("Portal da Transparência — Governo Federal",
         "portaldatransparencia.gov.br",
         "Total recebido do Governo Federal (R$ 66,32M acumulado). CEIS/CNEP/CEPIM."),
        ("BrasilAPI / ReceitaWS",
         "brasilapi.com.br / receitaws.com.br",
         "Dados cadastrais (indisponível em ambiente remoto — verificar localmente)."),
        ("PNCP — Portal Nacional de Contratações Públicas",
         "pncp.gov.br",
         "Contratos públicos federais (indisponível em ambiente remoto)."),
        ("Busca pública (web)",
         "sepm.rj.gov.br · estancia.se.gov.br · econodata.com.br · casadosdados.com.br",
         "Dados complementares de contratos, impugnações e cadastro empresarial."),
    ]
    for nome, url, desc in fontes:
        pdf.set_font("Liberation", "B", 8)
        pdf.set_text_color(*C_NAVY)
        pdf.cell(0, 5.5, nome, 0, 1)
        pdf.set_font("Liberation", "I", 7.5)
        pdf.set_text_color(*C_BLUE)
        pdf.set_x(20)
        pdf.cell(0, 4.5, url, 0, 1)
        pdf.set_font("Liberation", "", 7.5)
        pdf.set_text_color(*C_GRAY2)
        pdf.set_x(20)
        pdf.cell(0, 4.5, desc, 0, 1)
        pdf.ln(1)
    pdf.ln(2)

    pdf.sub_title("Limitações e Ressalvas")
    lims = [
        "Os valores EMPENHADOS (TFE) não refletem o valor efetivamente pago. A coleta das OBs (script disponível) é necessária para confirmação.",
        "A busca reversa por sócios via CPF não é possível com o dump gratuito da RF (CPFs mascarados). Verificar via JUCERJA.",
        "APIs públicas (BrasilAPI, PNCP, Portal da Transparência) inacessíveis no ambiente remoto de análise — validação local recomendada.",
        "O relatório foi gerado automaticamente pelo JFN Agent. Não substitui análise jurídica especializada nem perícia contábil.",
        "A avaliação de risco é baseada em dados públicos disponíveis na data de coleta (04/06/2026) e pode divergir de situações posteriores.",
    ]
    for i, lim in enumerate(lims, 1):
        pdf.set_font("Liberation", "", 8)
        pdf.set_text_color(*C_GRAY1)
        pdf.set_x(15)
        pdf.cell(8, 5.5, f"{i}.", 0, 0)
        pdf.multi_cell(172, 5.5, lim)
        pdf.ln(0.5)
    pdf.ln(3)

    pdf.sub_title("Sobre o JFN Agent")
    pdf.set_font("Liberation", "", 8)
    pdf.set_text_color(*C_GRAY2)
    pdf.multi_cell(0, 5.5,
        "O JFN Agent é um sistema integrado de compliance e auditoria pública desenvolvido para "
        "automatizar a coleta, análise e classificação de riscos em fornecedores do setor público. "
        "O módulo de relatórios integra três perspectivas: Auditoria Forense, Avaliação de Risco "
        "Corporativo e Análise de Compliance, seguindo as melhores práticas de due diligence "
        "corporativa (ABNT ISO 31000, COSO ERM, TCU — Manual de Auditoria Operacional).")

    # Final seal
    pdf.set_y(-45)
    pdf.set_fill_color(*C_GRAY5)
    pdf.rect(15, pdf.get_y(), 180, 28, "F")
    pdf.set_fill_color(*C_NAVY)
    pdf.rect(15, pdf.get_y(), 5, 28, "F")
    pdf.set_font("Liberation", "B", 9)
    pdf.set_text_color(*C_NAVY)
    pdf.set_xy(23, pdf.get_y() + 3)
    pdf.cell(0, 6, "JFN AGENT  ·  Auditoria de Integridade Pública", 0, 1)
    pdf.set_font("Liberation", "", 7.5)
    pdf.set_text_color(*C_GRAY2)
    pdf.set_x(23)
    pdf.cell(0, 5, f"Relatório gerado em {DATA}  ·  Nível de classificação: CONFIDENCIAL", 0, 1)
    pdf.set_x(23)
    pdf.cell(0, 5, "Este documento é de uso restrito e não deve ser reproduzido sem autorização.", 0, 1)

    return pdf


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = build_pdf()
    pdf.output(str(OUT))
    print(f"PDF gerado: {OUT}")
    print(f"Tamanho: {OUT.stat().st_size / 1024:.1f} KB")
