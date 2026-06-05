#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MGS CLEAN — Gerador de Relatório PDF das Ordens Bancárias (SIAFE)
Lê: data/sei_cache/mgsclean_obs_todas.json  (produzido por auditar_mgs_obs_siafe.py)
Gera: reports/auditoria_mgs_obs_YYYY-MM-DD.pdf

Estrutura do PDF:
  1. Capa
  2. Resumo Global por Ano
  3. Matriz Órgão × Ano
  4. Por Órgão → Por Mês → Cada OB individual
  5. Resumo Mensal Geral (todos os órgãos)

Uso:
  python _SANDBOX/gerar_relatorio_obs_pdf.py
  python _SANDBOX/gerar_relatorio_obs_pdf.py data/sei_cache/mgsclean_obs_todas.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── fpdf2 ────────────────────────────────────────────────────────────────────
try:
    from fpdf import FPDF
except ImportError:
    print("ERRO: instale fpdf2:  pip install fpdf2")
    sys.exit(1)

# ── Paleta profissional (idêntica ao relatório principal) ─────────────────────
C_NAVY  = (27,  42,  74)    # #1B2A4A
C_GOLD  = (201, 168, 76)    # #C9A84C
C_WHITE = (255, 255, 255)
C_LGRAY = (242, 244, 248)   # fundo linhas pares
C_DGRAY = (100, 110, 130)   # textos secundários
C_RED   = (180,  40,  40)   # alertas
C_GREEN = ( 30, 130,  70)   # valores OK

FONT_DIR = Path("/usr/share/fonts/truetype/liberation")
FONT_REG  = str(FONT_DIR / "LiberationSans-Regular.ttf")
FONT_BOLD = str(FONT_DIR / "LiberationSans-Bold.ttf")
FONT_ITAL = str(FONT_DIR / "LiberationSans-Italic.ttf")
FONT_MONO = str(FONT_DIR / "LiberationMono-Regular.ttf")

CNPJ_FMT = "19.088.605/0001-04"
CNPJ_RAW = "19088605000104"

MESES_PT = {
    1: "Janeiro",   2: "Fevereiro",  3: "Março",    4: "Abril",
    5: "Maio",      6: "Junho",      7: "Julho",    8: "Agosto",
    9: "Setembro", 10: "Outubro",  11: "Novembro", 12: "Dezembro",
}

_UG_NOMES = {
    "270001": "SEPM — Polícia Militar",
    "270003": "FUNESBOM — Corpo de Bombeiros",
    "270005": "Tribunal de Justiça (Fundo Especial)",
    "270006": "TCE — Tribunal de Contas do Estado",
    "270009": "PGE — Procuradoria Geral do Estado",
    "270015": "SECEC — Secretaria de Cultura",
    "270016": "FUNESBOM",
    "270020": "RIOPREVIDENCIA",
    "270024": "INEA",
    "270029": "Fundo Estadual de Saude",
    "270042": "ITERJ",
    "270051": "SEPM — Policia Militar",
    "270060": "Casa Civil",
    "300100": "Secretaria de Fazenda",
}


def _ug_nome(codigo: str) -> str:
    return _UG_NOMES.get(str(codigo), str(codigo))


def _brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _brl_plain(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── Classes PDF ───────────────────────────────────────────────────────────────

class ObPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(True, margin=18)
        self._add_fonts()
        self._current_title = ""
        self._current_page_type = ""

    def _add_fonts(self):
        self.add_font("Sans",     "", FONT_REG,  uni=True)
        self.add_font("Sans",     "B", FONT_BOLD, uni=True)
        self.add_font("Sans",     "I", FONT_ITAL, uni=True)
        self.add_font("Mono",     "", FONT_MONO, uni=True)

    # ── Header / Footer ───────────────────────────────────────────────────────
    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*C_NAVY)
        self.rect(0, 0, self.w, 9, "F")
        self.set_font("Sans", "B", 7)
        self.set_text_color(*C_GOLD)
        self.set_xy(12, 1.5)
        self.cell(0, 6, "CONFIDENCIAL — Auditoria MGS CLEAN | Ordens Bancarias SIAFE", ln=False)
        self.set_xy(-60, 1.5)
        self.set_font("Sans", "", 7)
        self.set_text_color(*C_WHITE)
        self.cell(48, 6, self._current_title, align="R", ln=False)
        self.set_text_color(0, 0, 0)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-10)
        self.set_fill_color(*C_NAVY)
        self.rect(0, self.h - 10, self.w, 10, "F")
        self.set_font("Sans", "", 7)
        self.set_text_color(*C_GOLD)
        self.set_x(12)
        self.cell(0, 8, f"Pagina {self.page_no()}  |  CNPJ {CNPJ_FMT}  |  "
                        f"Fonte: SIAFE2 — Execucao Financeira — Ordens Bancarias", ln=False)

    # ── Helpers de desenho ────────────────────────────────────────────────────
    def _section_bar(self, title: str, subtitle: str = ""):
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("Sans", "B", 11)
        self.cell(0, 8, f"  {title}", ln=True, fill=True)
        if subtitle:
            self.set_fill_color(*C_LGRAY)
            self.set_text_color(*C_DGRAY)
            self.set_font("Sans", "I", 8)
            self.cell(0, 5, f"  {subtitle}", ln=True, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def _sub_bar(self, title: str, total: str = ""):
        self.set_fill_color(*C_GOLD)
        self.set_text_color(*C_NAVY)
        self.set_font("Sans", "B", 9)
        txt = f"  {title}"
        if total:
            txt += f"   [{total}]"
        self.cell(0, 7, txt, ln=True, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def _note(self, text: str):
        self.set_font("Sans", "I", 7.5)
        self.set_text_color(*C_DGRAY)
        self.multi_cell(0, 4.5, text)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    # ── Capa ──────────────────────────────────────────────────────────────────
    def page_cover(self, anos: list[int], total: float, n_obs: int):
        self._in_cover = True
        self.add_page()
        self.set_auto_page_break(False)

        # Faixa superior navy
        self.set_fill_color(*C_NAVY)
        self.rect(0, 0, self.w, self.h * 0.55, "F")

        # Acento gold
        self.set_fill_color(*C_GOLD)
        self.rect(0, self.h * 0.55, self.w, 3, "F")

        # Título principal
        self.set_xy(0, 35)
        self.set_font("Sans", "B", 26)
        self.set_text_color(*C_WHITE)
        self.cell(self.w, 14, "ORDENS BANCARIAS PAGAS", align="C", ln=True)

        self.set_font("Sans", "B", 20)
        self.set_text_color(*C_GOLD)
        self.cell(self.w, 12, "MGS CLEAN SOLUCOES E SERVICOS LTDA", align="C", ln=True)

        self.set_font("Sans", "", 13)
        self.set_text_color(*C_WHITE)
        self.cell(self.w, 8, f"CNPJ {CNPJ_FMT}", align="C", ln=True)

        self.ln(6)
        self.set_font("Sans", "", 11)
        self.set_text_color(200, 215, 235)
        anos_str = " | ".join(str(a) for a in sorted(anos))
        self.cell(self.w, 7, f"Exercicios: {anos_str}", align="C", ln=True)

        # Bloco de totais no centro
        self.set_xy(self.w * 0.15, self.h * 0.36)
        self.set_fill_color(0, 0, 0)
        self.set_draw_color(*C_GOLD)
        self.set_line_width(0.6)
        bw = self.w * 0.70
        bh = 36
        # fundo escuro translúcido
        self.set_fill_color(15, 25, 55)
        self.rect(self.w * 0.15, self.h * 0.36, bw, bh, "FD")

        self.set_xy(self.w * 0.15, self.h * 0.36 + 5)
        self.set_font("Sans", "", 9)
        self.set_text_color(180, 200, 225)
        self.cell(bw, 6, "TOTAL GERAL PAGO (OBs liquidadas no SIAFE)", align="C", ln=True)

        self.set_font("Sans", "B", 24)
        self.set_text_color(*C_GOLD)
        self.set_x(self.w * 0.15)
        self.cell(bw, 14, _brl(total), align="C", ln=True)

        self.set_font("Sans", "", 9)
        self.set_text_color(180, 200, 225)
        self.set_x(self.w * 0.15)
        self.cell(bw, 6, f"{n_obs} Ordens Bancarias emitidas", align="C", ln=True)

        # Rodape info
        self.set_xy(0, self.h * 0.62)
        self.set_font("Sans", "", 9)
        self.set_text_color(*C_NAVY)
        self.cell(self.w, 7, f"Fonte: SIAFE2 — Execucao Financeira — Ordens Bancarias", align="C", ln=True)
        self.set_font("Sans", "I", 8)
        self.set_text_color(*C_DGRAY)
        self.cell(self.w, 6, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  CONFIDENCIAL", align="C", ln=True)

        self.set_auto_page_break(True, margin=18)
        self._in_cover = False

    # ── Resumo global ─────────────────────────────────────────────────────────
    def page_resumo_global(self, todas_obs: list[dict], todos_anos: list[int]):
        self._current_title = "Resumo Global"
        self.add_page()
        self._section_bar(
            "1. Resumo Global — Valor Pago por Ano",
            "Ordens Bancarias liquidadas no SIAFE para CNPJ " + CNPJ_FMT,
        )

        # Tabela por ano
        col_ano   = 35
        col_obs   = 25
        col_valor = 60
        col_org   = 55
        total_w   = col_ano + col_obs + col_valor + col_org

        # Header
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("Sans", "B", 8.5)
        x0 = self.get_x()
        self.cell(col_ano,   7, "Ano",                  border=0, fill=True, align="C")
        self.cell(col_obs,   7, "OBs",                  border=0, fill=True, align="C")
        self.cell(col_valor, 7, "Valor Total Pago",      border=0, fill=True, align="R")
        self.cell(col_org,   7, "Orgaos pagadores",      border=0, fill=True, align="C")
        self.ln()
        self.set_text_color(0, 0, 0)

        total_geral = 0.0
        total_n     = 0
        for i, ano in enumerate(todos_anos):
            obs_ano = [ob for ob in todas_obs if ob.get("ano") == ano]
            v = sum(ob["valor"] for ob in obs_ano)
            n = len(obs_ano)
            orgs = len({ob.get("ug_emitente") for ob in obs_ano})
            total_geral += v
            total_n     += n

            self.set_fill_color(*C_LGRAY if i % 2 == 0 else C_WHITE)
            self.set_font("Sans", "", 8.5)
            self.cell(col_ano,   6, str(ano),           border=0, fill=True, align="C")
            self.cell(col_obs,   6, str(n),             border=0, fill=True, align="C")
            self.set_font("Sans", "B", 8.5)
            self.set_text_color(*C_NAVY)
            self.cell(col_valor, 6, _brl_plain(v),      border=0, fill=True, align="R")
            self.set_font("Sans", "", 8.5)
            self.set_text_color(0, 0, 0)
            self.cell(col_org,   6, f"{orgs} orgao(s)", border=0, fill=True, align="C")
            self.ln()

        # Total
        self.set_fill_color(*C_GOLD)
        self.set_text_color(*C_NAVY)
        self.set_font("Sans", "B", 8.5)
        self.cell(col_ano,   7, "TOTAL",              border=0, fill=True, align="C")
        self.cell(col_obs,   7, str(total_n),         border=0, fill=True, align="C")
        self.cell(col_valor, 7, _brl_plain(total_geral), border=0, fill=True, align="R")
        self.cell(col_org,   7, "",                   border=0, fill=True)
        self.ln(10)
        self.set_text_color(0, 0, 0)

        self._note(
            "Nota: 'OBs' = Ordens Bancarias emitidas e liquidadas. Multiplas OBs no mesmo mes "
            "sao normais — cada nota fiscal ou competencia gera uma OB separada, com numero "
            "unico e processo SEI vinculado."
        )

    # ── Matriz orgao x ano ────────────────────────────────────────────────────
    def page_matriz_orgao(self, todas_obs: list[dict], todos_anos: list[int]):
        self._current_title = "Matriz Orgao x Ano"
        self.add_page()
        self._section_bar(
            "2. Matriz Consolidada — Valor Pago por Orgao x Ano",
            "Ordenado por maior volume total (R$)",
        )

        todos_ugs = sorted(
            {ob.get("ug_emitente", "") for ob in todas_obs if ob.get("ug_emitente")},
            key=lambda u: -sum(ob["valor"] for ob in todas_obs if ob.get("ug_emitente") == u),
        )

        n_anos = len(todos_anos)
        col_nome  = 75
        col_cod   = 22
        col_ano   = min(40, max(28, int((self.w - 24 - col_nome - col_cod - 30) / max(n_anos, 1))))
        col_total = 32

        # Header
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("Sans", "B", 7.5)
        self.cell(col_nome,  7, "Orgao",  border=0, fill=True)
        self.cell(col_cod,   7, "UG",     border=0, fill=True, align="C")
        for a in todos_anos:
            self.cell(col_ano, 7, str(a), border=0, fill=True, align="R")
        self.cell(col_total, 7, "TOTAL",  border=0, fill=True, align="R")
        self.ln()
        self.set_text_color(0, 0, 0)

        totais_col = {a: 0.0 for a in todos_anos}
        for i, ug in enumerate(todos_ugs):
            nome = _ug_nome(ug)
            if len(nome) > 35:
                nome = nome[:34] + "."
            self.set_fill_color(*C_LGRAY if i % 2 == 0 else C_WHITE)
            self.set_font("Sans", "", 7.5)
            self.cell(col_nome, 6, nome, border=0, fill=True)
            self.set_font("Mono", "", 7)
            self.cell(col_cod,  6, ug,   border=0, fill=True, align="C")
            self.set_font("Sans", "", 7.5)
            tot_ug = 0.0
            for a in todos_anos:
                v = sum(ob["valor"] for ob in todas_obs
                        if ob.get("ug_emitente") == ug and ob.get("ano") == a)
                totais_col[a] += v
                tot_ug += v
                txt = _brl_plain(v) if v else "—"
                if v:
                    self.set_text_color(*C_NAVY)
                    self.set_font("Sans", "B", 7.5)
                else:
                    self.set_text_color(*C_DGRAY)
                    self.set_font("Sans", "", 7.5)
                self.cell(col_ano, 6, txt, border=0, fill=True, align="R")
            self.set_text_color(*C_NAVY)
            self.set_font("Sans", "B", 7.5)
            self.cell(col_total, 6, _brl_plain(tot_ug), border=0, fill=True, align="R")
            self.ln()
            self.set_text_color(0, 0, 0)

        # Linha de total
        self.set_fill_color(*C_GOLD)
        self.set_text_color(*C_NAVY)
        self.set_font("Sans", "B", 7.5)
        self.cell(col_nome, 7, "TOTAL GERAL", border=0, fill=True)
        self.cell(col_cod,  7, "",            border=0, fill=True)
        tt = 0.0
        for a in todos_anos:
            self.cell(col_ano, 7, _brl_plain(totais_col[a]), border=0, fill=True, align="R")
            tt += totais_col[a]
        self.cell(col_total, 7, _brl_plain(tt), border=0, fill=True, align="R")
        self.ln(2)
        self.set_text_color(0, 0, 0)

    # ── Detalhe por orgao ─────────────────────────────────────────────────────
    def _ob_table_header(self, col_mes, col_ob, col_data, col_valor, col_proc, col_status):
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("Sans", "B", 7)
        self.cell(col_mes,    6, "Mes",           border=0, fill=True, align="C")
        self.cell(col_ob,     6, "No OB",         border=0, fill=True, align="C")
        self.cell(col_data,   6, "Data Emissao",  border=0, fill=True, align="C")
        self.cell(col_valor,  6, "Valor (R$)",    border=0, fill=True, align="R")
        self.cell(col_proc,   6, "Processo SEI",  border=0, fill=True, align="C")
        self.cell(col_status, 6, "Status",        border=0, fill=True, align="C")
        self.ln()
        self.set_text_color(0, 0, 0)

    def page_detalhe_orgao(self, ug: str, obs_ug_por_ano: dict[int, list[dict]]):
        nome = _ug_nome(ug)
        self._current_title = f"OBs — {nome[:30]}"
        self.add_page()

        total_orgao = sum(ob["valor"] for obs in obs_ug_por_ano.values() for ob in obs)
        n_total     = sum(len(obs) for obs in obs_ug_por_ano.values())

        self._section_bar(
            f"3. Detalhamento — {nome}",
            f"UG: {ug}  |  Total pago: {_brl(total_orgao)}  |  {n_total} OBs",
        )

        col_mes    = 22
        col_ob     = 40
        col_data   = 27
        col_valor  = 38
        col_proc   = 65
        col_status = max(0, self.w - 24 - col_mes - col_ob - col_data - col_valor - col_proc)

        for ano in sorted(obs_ug_por_ano.keys()):
            obs_ano = sorted(obs_ug_por_ano[ano],
                             key=lambda o: (o.get("mes") or 0, o.get("data_emissao") or ""))
            total_ano = sum(ob["valor"] for ob in obs_ano)
            n_ano     = len(obs_ano)

            self._sub_bar(f"Exercicio {ano}", f"{_brl(total_ano)} — {n_ano} OBs")
            self._ob_table_header(col_mes, col_ob, col_data, col_valor, col_proc, col_status)

            por_mes: dict[int, list] = defaultdict(list)
            for ob in obs_ano:
                if ob.get("mes"):
                    por_mes[ob["mes"]].append(ob)

            row_idx = 0
            for mes in sorted(por_mes.keys()):
                obs_mes  = sorted(por_mes[mes], key=lambda o: o.get("data_emissao") or "")
                sub_mes  = sum(ob["valor"] for ob in obs_mes)
                mes_abr  = MESES_PT[mes][:3] + f"/{ano}"

                for i, ob in enumerate(obs_mes):
                    # Alterna cor de fundo por OB
                    bg = C_LGRAY if row_idx % 2 == 0 else C_WHITE
                    self.set_fill_color(*bg)

                    # Garantir quebra de página antes de cortar tabela
                    if self.get_y() > self.h - 30:
                        self.add_page()
                        self._ob_table_header(col_mes, col_ob, col_data,
                                              col_valor, col_proc, col_status)

                    mes_label = mes_abr if i == 0 else ""
                    numero_ob = (ob.get("numero_ob") or "")[:18]
                    data_em   = (ob.get("data_emissao") or "")[:10]
                    processo  = (ob.get("processo") or "")[:30]
                    status    = (ob.get("status") or "")[:14]
                    valor     = ob.get("valor", 0.0)

                    self.set_font("Sans", "B" if i == 0 else "", 7)
                    self.set_text_color(*C_NAVY if i == 0 else (0, 0, 0))
                    self.cell(col_mes,  5.5, mes_label,          border=0, fill=True)
                    self.set_font("Mono", "", 7)
                    self.set_text_color(0, 0, 0)
                    self.cell(col_ob,   5.5, numero_ob,           border=0, fill=True)
                    self.set_font("Sans", "", 7)
                    self.cell(col_data,  5.5, data_em,           border=0, fill=True, align="C")
                    self.set_font("Sans", "B", 7)
                    self.set_text_color(*C_NAVY)
                    self.cell(col_valor, 5.5, _brl_plain(valor), border=0, fill=True, align="R")
                    self.set_font("Sans", "", 6.5)
                    self.set_text_color(0, 0, 0)
                    self.cell(col_proc,   5.5, processo,          border=0, fill=True)
                    self.set_text_color(*C_GREEN)
                    self.cell(col_status, 5.5, status,            border=0, fill=True, align="C")
                    self.ln()
                    self.set_text_color(0, 0, 0)
                    row_idx += 1

                # Subtotal do mes
                if self.get_y() > self.h - 22:
                    self.add_page()
                    self._ob_table_header(col_mes, col_ob, col_data,
                                          col_valor, col_proc, col_status)

                self.set_fill_color(230, 235, 245)
                self.set_font("Sans", "B", 7)
                self.set_text_color(*C_NAVY)
                self.cell(col_mes,  5, f"Subtotal {mes_abr}", border=0, fill=True)
                self.cell(col_ob,   5, "",                    border=0, fill=True)
                self.cell(col_data, 5, "",                    border=0, fill=True)
                self.cell(col_valor,5, _brl_plain(sub_mes),   border=0, fill=True, align="R")
                self.cell(col_proc, 5, f"{len(obs_mes)} OBs", border=0, fill=True, align="C")
                self.cell(col_status, 5, "",                  border=0, fill=True)
                self.ln()
                self.set_text_color(0, 0, 0)

            # Total anual do orgao
            self.set_fill_color(*C_GOLD)
            self.set_text_color(*C_NAVY)
            self.set_font("Sans", "B", 7.5)
            self.cell(col_mes,  7, f"TOTAL {ano}", border=0, fill=True)
            self.cell(col_ob,   7, "",             border=0, fill=True)
            self.cell(col_data, 7, "",             border=0, fill=True)
            self.cell(col_valor,7, _brl_plain(total_ano), border=0, fill=True, align="R")
            self.cell(col_proc, 7, f"{n_ano} OBs no exercicio", border=0, fill=True, align="C")
            self.cell(col_status, 7, "",           border=0, fill=True)
            self.ln(3)
            self.set_text_color(0, 0, 0)

    # ── Resumo mensal geral ───────────────────────────────────────────────────
    def page_resumo_mensal(self, todas_obs: list[dict], todos_anos: list[int]):
        self._current_title = "Resumo Mensal Geral"
        self.add_page()
        self._section_bar(
            "4. Resumo Mensal Geral — Todos os Orgaos Combinados",
            "Para cada mes: total pago pelo conjunto de orgaos contratantes",
        )

        for ano in todos_anos:
            obs_ano  = [ob for ob in todas_obs if ob.get("ano") == ano]
            total_ano = sum(ob["valor"] for ob in obs_ano)
            n_ano     = len(obs_ano)

            self._sub_bar(f"Exercicio {ano}", f"{_brl(total_ano)} — {n_ano} OBs")

            col_mes   = 40
            col_obs   = 20
            col_valor = 55
            col_pct   = 22
            col_org   = 35

            self.set_fill_color(*C_NAVY)
            self.set_text_color(*C_WHITE)
            self.set_font("Sans", "B", 8)
            self.cell(col_mes,   6, "Mes",           border=0, fill=True)
            self.cell(col_obs,   6, "OBs",           border=0, fill=True, align="C")
            self.cell(col_valor, 6, "Valor Total",   border=0, fill=True, align="R")
            self.cell(col_pct,   6, "% Ano",         border=0, fill=True, align="C")
            self.cell(col_org,   6, "Orgaos",        border=0, fill=True, align="C")
            self.ln()
            self.set_text_color(0, 0, 0)

            por_mes: dict[int, list] = defaultdict(list)
            for ob in obs_ano:
                if ob.get("mes"):
                    por_mes[ob["mes"]].append(ob)

            for i, mes in enumerate(sorted(por_mes.keys())):
                obs_m  = por_mes[mes]
                v      = sum(ob["valor"] for ob in obs_m)
                pct    = v / total_ano * 100 if total_ano else 0
                n_orgs = len({ob.get("ug_emitente") for ob in obs_m})

                self.set_fill_color(*C_LGRAY if i % 2 == 0 else C_WHITE)
                self.set_font("Sans", "", 8)
                self.cell(col_mes,   6, f"{MESES_PT[mes]}/{ano}", border=0, fill=True)
                self.cell(col_obs,   6, str(len(obs_m)),          border=0, fill=True, align="C")
                self.set_font("Sans", "B", 8)
                self.set_text_color(*C_NAVY)
                self.cell(col_valor, 6, _brl_plain(v),            border=0, fill=True, align="R")
                self.set_font("Sans", "", 8)
                self.set_text_color(0, 0, 0)
                self.cell(col_pct,   6, f"{pct:.1f}%",            border=0, fill=True, align="C")
                self.cell(col_org,   6, str(n_orgs),              border=0, fill=True, align="C")
                self.ln()

            # Total do ano
            self.set_fill_color(*C_GOLD)
            self.set_text_color(*C_NAVY)
            self.set_font("Sans", "B", 8)
            self.cell(col_mes,   7, f"TOTAL {ano}", border=0, fill=True)
            self.cell(col_obs,   7, str(n_ano),     border=0, fill=True, align="C")
            self.cell(col_valor, 7, _brl_plain(total_ano), border=0, fill=True, align="R")
            self.cell(col_pct,   7, "100%",         border=0, fill=True, align="C")
            self.cell(col_org,   7, "",             border=0, fill=True)
            self.ln(6)
            self.set_text_color(0, 0, 0)

    # ── Pagina "aguardando dados" ─────────────────────────────────────────────
    def page_sem_dados(self, json_path: Path):
        self._current_title = "Aguardando Dados SIAFE"
        self.add_page()
        self._section_bar(
            "AGUARDANDO DADOS DO SIAFE",
            "Execute auditar_mgs_obs_siafe.py no computador com acesso ao SIAFE",
        )
        self.ln(10)
        self.set_font("Sans", "B", 12)
        self.set_text_color(*C_RED)
        self.cell(0, 8, "Arquivo de dados nao encontrado:", ln=True, align="C")
        self.set_font("Mono", "", 10)
        self.set_text_color(*C_NAVY)
        self.cell(0, 7, str(json_path), ln=True, align="C")
        self.ln(8)
        self.set_font("Sans", "", 10)
        self.set_text_color(0, 0, 0)
        steps = [
            "1.  Abra o Chrome com depuracao remota:",
            '    chrome --remote-debugging-port=9222 --user-data-dir="C:/JFN/profile"',
            "",
            "2.  Execute o coletor SIAFE:",
            "    cd C:/JFN/jfn",
            "    python _SANDBOX/auditar_mgs_obs_siafe.py 2023 2024 2025 2026",
            "",
            "3.  Aguarde a coleta (pode demorar varios minutos por ano).",
            "",
            "4.  Copie o arquivo gerado para este computador:",
            "    data/sei_cache/mgsclean_obs_todas.json",
            "",
            "5.  Execute novamente este gerador de PDF.",
        ]
        for step in steps:
            self.set_font("Mono" if step.startswith("    ") else "Sans", "", 9)
            self.set_text_color(*C_DGRAY if step.startswith("    ") else (0, 0, 0))
            self.cell(0, 6, step, ln=True)
        self.set_text_color(0, 0, 0)


# ── Main ──────────────────────────────────────────────────────────────────────

def gerar_pdf(json_path: Path, out_path: Path):
    pdf = ObPDF()
    pdf.set_title("MGS CLEAN — Ordens Bancarias SIAFE")
    pdf.set_author("JFN — Sistema de Auditoria")

    if not json_path.exists():
        # Capa de espera + página de instrucoes
        pdf.page_cover([], 0.0, 0)
        pdf.page_sem_dados(json_path)
        pdf.output(str(out_path))
        print(f"  [INFO] PDF placeholder gerado: {out_path}")
        print(f"  [INFO] Dados nao encontrados em: {json_path}")
        return

    data = json.loads(json_path.read_text(encoding="utf-8"))
    todas_obs: list[dict] = data.get("obs", data if isinstance(data, list) else [])

    if not todas_obs:
        print(f"  [ERRO] Nenhuma OB encontrada em {json_path}")
        return

    # Filtrar apenas MGS CLEAN se necessario
    todas_obs = [ob for ob in todas_obs
                 if re.sub(r"\D", "", ob.get("favorecido_cnpj", ""))[:14] == CNPJ_RAW
                 or not ob.get("favorecido_cnpj")]

    todos_anos = sorted({ob["ano"] for ob in todas_obs if ob.get("ano")})
    total_geral = sum(ob["valor"] for ob in todas_obs)
    n_total     = len(todas_obs)

    print(f"  [INFO] {n_total} OBs | {_brl(total_geral)} | Anos: {todos_anos}")

    # Organiza: {ug: {ano: [obs]}}
    por_ug: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for ob in todas_obs:
        ug  = ob.get("ug_emitente", "")
        ano = ob.get("ano")
        if ug and ano:
            por_ug[ug][ano].append(ob)

    # Ordena orgaos por maior volume total
    ugs_ordenadas = sorted(
        por_ug.keys(),
        key=lambda u: -sum(ob["valor"] for obs in por_ug[u].values() for ob in obs),
    )

    # Gera paginas
    pdf.page_cover(todos_anos, total_geral, n_total)
    pdf.page_resumo_global(todas_obs, todos_anos)
    pdf.page_matriz_orgao(todas_obs, todos_anos)

    for ug in ugs_ordenadas:
        pdf.page_detalhe_orgao(ug, por_ug[ug])

    pdf.page_resumo_mensal(todas_obs, todos_anos)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    print(f"  [OK] PDF gerado: {out_path}  ({pdf.page_no()} paginas)")


def main():
    root = Path(__file__).parents[1]
    json_arg = sys.argv[1] if len(sys.argv) > 1 else None
    json_path = Path(json_arg) if json_arg else root / "data" / "sei_cache" / "mgsclean_obs_todas.json"

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = root / "reports" / f"auditoria_mgs_obs_{date_str}.pdf"

    print("MGS CLEAN — Gerador de Relatorio OBs PDF")
    print(f"  Entrada : {json_path}")
    print(f"  Saida   : {out_path}")
    print()

    gerar_pdf(json_path, out_path)


if __name__ == "__main__":
    main()
