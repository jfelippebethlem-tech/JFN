#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprime o dossiê-mestre para caber no Telegram (<48MB) SEM perder o índice clicável: rasteriza
apenas as páginas dominadas por imagem escaneada (TCE/instrumentos/CEDAE), mantendo intacto o texto
vetorial (peça analítica + Anexo D) e o sumário (TOC/bookmarks). Uso: comprimir_master.py entrada.pdf saida.pdf [alvo_mb]
"""
import sys
import fitz

SRC = sys.argv[1]
OUT = sys.argv[2]
ALVO_MB = float(sys.argv[3]) if len(sys.argv) > 3 else 47.0
DPI = int(__import__("os").environ.get("MASTER_DPI", "100"))

src = fitz.open(SRC)
toc = src.get_toc()
out = fitz.open()
mat = fitz.Matrix(DPI / 72, DPI / 72)
rasterizadas = 0
for pg in src:
    # heurística: página "escaneada" = tem imagem grande e pouquíssimo texto extraível
    imgs = pg.get_images(full=True)
    txt = len(pg.get_text().strip())
    grande = any((im[2] * im[3]) > 200_000 for im in imgs)  # >0,2 MP
    if imgs and grande and txt < 120:
        pix = pg.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        np = out.new_page(width=pg.rect.width, height=pg.rect.height)
        np.insert_image(pg.rect, pixmap=pix)  # JPEG embutido pelo deflate/garbage
        rasterizadas += 1
    else:
        out.insert_pdf(src, from_page=pg.number, to_page=pg.number)

out.set_toc(toc)  # mantém o índice clicável (páginas na mesma ordem 1:1)
out.save(OUT, deflate=True, deflate_images=True, garbage=4)
mb = __import__("os").path.getsize(OUT) / 1e6
print(f"COMPRIMIDO: {OUT} · {out.page_count} págs · {mb:.1f}MB · {rasterizadas} págs rasterizadas ({DPI}dpi) · TOC {len(toc)}")
if mb > ALVO_MB:
    print(f"AVISO: ainda acima de {ALVO_MB}MB — reduzir MASTER_DPI (ex.: 84) ou dividir em partes")
