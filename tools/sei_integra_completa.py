#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÍNTEGRA COMPLETA de um processo SEI: pagina TODOS os documentos, baixa cada um (PDF ou HTML→PDF),
junta num PDF único e ENVIA ao Telegram (divide em partes <45MB). Conteúdo lido SEMPRE pela árvore
viva (cross-unit sem envenenar a sessão, 2026-07-23): nativo=texto do editor; escaneado=PDF original
preservado (imagens/fotos de prova) + OCR já feito por _conteudo_via_arvore. Guardado.
Uso: .venv/bin/python tools/sei_integra_completa.py "330020/000762/2021"
"""
import os
import sys
import re
import asyncio
from pathlib import Path
# A RAIZ DESTA ÁRVORE, não `/home/ubuntu/JFN` cravado: no worker da VM-2 (~/JFN-worker) o caminho fixo punha a
# cópia ANTIGA ~/JFN na frente do sys.path e o `tools.sei_reader` importado era o de lá (achado em 14/11/2026).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright, Error as PWError
import httpx
import fitz

PROC = sys.argv[1] if len(sys.argv) > 1 else ""   # import (pytest) não traz argumento
# O PREFIXO `SEI-` TEM DE SAIR ANTES DO TAG. Sem isto, cada letra dele vira um underscore e o
# destino fica `integra_____080002_023009_2024`, enquanto `sei_arquivar.py` procura
# `integra_080002_023009_2024`. Medido em 2026-08-15: a captura do `080002/023009/2024` baixou os
# 69 documentos (206 MB) e o arquivamento seguinte disse "íntegra não encontrada" — 0 documentos
# arquivados, com tudo no disco. Já havia 396 diretórios nesse estado.
#
# O defeito foi DOCUMENTADO em duas rodadas anteriores e mordeu nas duas seguintes (a última
# escondeu 57 docs / 28 MB). Documentar não conserta: o conserto é esta linha.
PROC = re.sub(r"^SEI-", "", PROC.strip())
TAG = re.sub(r"[^0-9]", "_", PROC)
# Códigos de saída — antes LOGIN FALHOU e SEM ÁRVORE saíam com 0 e a fila (`sei_integra_fila`)
# chamava de "ok" uma captura sem documento nenhum (laudo dos motores, 13/11/2026: 255 "ok" em
# 7 dias, 48 processos, todos com 0 documento). 75 (adiado por carga) já existia.
RC_LOGIN_FALHOU = 3
RC_SEM_ARVORE = 4
ENV = Path.home() / ".hermes" / ".env"   # por usuário: `/home/ubuntu` cravado quebrava fora desta VM
# RENOVAÇÃO DA ABA (19/11/2026, it-campo): a aba do 150016/009553/2024 chegou a 4,9 GB de RSS no renderer após 711
# documentos — o CDP dizia 391 `Documents` e 379 `Frames` vivos com só 4 frames na árvore: cada documento clicado deixa
# o anterior desanexado e retido. A cada N documentos BAIXADOS o processo é reaberto numa aba nova (mesmo login) e a
# velha fecha. 0 desliga. Medido ao vivo (19/11, 828 nós): a reabertura custa 90–100 s (busca pelo cracked) e os
# documentos seguintes saem normais (42/42 ok) — 250 docs ≈ 1,7 GB de pico por aba e ~5–8% de tempo de reabertura.
RENOVAR_ABA_DOCS = int(os.environ.get("SEI_RENOVAR_ABA_DOCS", "250"))


def hora_de_renovar(baixados_desde: int, limite: int = RENOVAR_ABA_DOCS) -> bool:
    return limite > 0 and baixados_desde >= limite


async def renovar_aba(ctx, pg, reabrir):
    """Abre o processo numa aba NOVA (`reabrir(aba) -> bool` deixa a árvore viva nela) e só então fecha a velha.
    Falhou ou deu erro → fecha a nova e devolve a velha: a captura segue como estava, sem perder o processo."""
    nova = await ctx.new_page()
    try:
        await nova.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        if await reabrir(nova):
            try:
                await pg.close()
            except PWError:
                pass
            return nova
        print("  aba NÃO renovada (o processo não reabriu) — sigo na aba atual", flush=True)
    except (PWError, asyncio.TimeoutError) as e:
        print(f"  aba NÃO renovada ({str(e)[:60]}) — sigo na aba atual", flush=True)
    try:
        await nova.close()
    except PWError:
        pass
    return pg
def _k(n):
    # `_k` roda no IMPORT (linha abaixo), então não pode depender de arquivo existir: o CI pegou
    # `FileNotFoundError: /home/ubuntu/.hermes/.env` importando este módulo num runner limpo.
    try:
        texto = ENV.read_text()
    except OSError:
        return ""
    m = re.search(rf"^{n}=(.+)$", texto, re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
TOK, CHAT = _k("TELEGRAM_BOT_TOKEN"), _k("TELEGRAM_CHAT_ID")


def envia(path, caption):
    with open(path, "rb") as f:
        return httpx.post(f"https://api.telegram.org/bot{TOK}/sendDocument",
                          data={"chat_id": CHAT, "caption": caption[:1000]},
                          files={"document": (Path(path).name, f, "application/pdf")}, timeout=300).json().get("ok")


# Siglas que só aparecem juntas na TELA DE SELEÇÃO DE UNIDADE do SEI. Quando o
# documento é de outra unidade, o SEI não serve o teor: devolve essa lista. Capturá-la
# como conteúdo grava a relação de órgãos no lugar do comprovante/despacho — falso
# conteúdo, pior que conteúdo ausente (achado em 2026-07-23, SEI-260007/004617/2024).
_SIGLAS_UNIDADE = ("AGENERSA", "AGETRANSP", "CECIERJ", "CEHAB", "DEGASE",
                   "FAETEC", "FAPERJ", "EMATER", "DETRO", "CODIN")


def parece_pagina_de_unidade(texto: str) -> bool:
    """True se o texto é a tela de escolha de unidade, não o documento."""
    t = (texto or "").upper()
    if len(t) < 60:
        return False
    return sum(1 for s in _SIGLAS_UNIDADE if s in t) >= 5


def arvore_anterior(man_path: Path) -> int:
    """Tamanho da árvore que uma captura ANTERIOR desta pasta enumerou (0 se não houver/ilegível).

    A ENUMERAÇÃO NÃO É DETERMINÍSTICA: as pastas lazy-load da árvore às vezes não terminam de carregar e a
    lista volta menor. Medido em 18/11/2026 na VM-2: o `150016/009553/2024` tinha 668 PDFs de uma captura
    (títulos e ids seguindo a ordem da árvore) e a seguinte enumerou só 356 e gravou `completo: True`; no
    acervo da VM-1, o `330001/000788/2024` saiu `captura_completa` com `total_arvore` 15 e 257 documentos."""
    import json as _json
    try:
        d = _json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(d, dict):
        return len(d) if isinstance(d, list) else 0
    try:
        return max(int(d.get("total_arvore") or 0), len(d.get("docs") or []))
    except (TypeError, ValueError):
        return 0


_RX_ID_DOC = re.compile(r"id_documento=(\d+)")
_RX_PECA = re.compile(r"^(\d{3,})\.pdf$")
RETOMADA = "_retomada"          # subpasta onde ficam, pelo id, os PDFs que mudaram de posição (nada é apagado)


def id_documento(entrada: dict) -> str:
    """O IDENTIFICADOR do documento na árvore do SEI (`id_documento` da url do nó), ou "" se não houver."""
    if entrada.get("id_documento"):
        return str(entrada["id_documento"])
    m = _RX_ID_DOC.search(str(entrada.get("u") or entrada.get("url") or ""))
    return m.group(1) if m else ""


def _mover(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    origem.replace(destino)
    ocr = origem.with_suffix(".ocr.txt")
    if ocr.exists():
        ocr.replace(destino.with_suffix(".ocr.txt"))


def preparar_retomada(outdir: Path, docs: list[dict]) -> dict:
    """A RETOMADA É PELO ID, NUNCA PELA POSIÇÃO. Deixa em `NNN.pdf` só o PDF cujo dono (pelo manifesto anterior) é o
    documento que a enumeração ATUAL põe na posição NNN; o resto vai para `_retomada/<id>.pdf` (ou
    `_retomada/sem_id_NNN.pdf`, dono desconhecido) e volta por `arquivo_retomado` quando o seu documento aparecer.

    Por quê: a enumeração da árvore não é determinística (`arvore_anterior`) e a retomada antiga dizia "existe
    `{i:03d}.pdf` → é o documento i" — numa lista que mudou entre rodadas isso colava o PDF de um documento no título
    de outro (o `sei_reparar_vazios` mediu 6 de 7 PDFs conferíveis errados, 04/08/2026). Dono desconhecido (manifesto
    antigo sem url/id, ou ausente) NÃO é reaproveitado no lugar: vazio é lacuna declarada, trocado é prova falsa."""
    import json as _json
    try:
        ant = _json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ant = {}
    entradas = ant.get("docs") if isinstance(ant, dict) else ant
    dono = {str(e.get("arquivo") or ""): id_documento(e) for e in (entradas or []) if isinstance(e, dict)}
    dono.update({k: v for k, v in _donos(outdir).items() if v})   # rodada que morreu no meio: o registro vale mais
    atual = {i: id_documento(x) for i, x in enumerate(docs)}
    mantidos = movidos = 0
    ficam: dict[str, str] = {}
    for fp in sorted(outdir.glob("*.pdf")):
        m = _RX_PECA.match(fp.name)
        if not m:
            continue
        i, quem = int(m.group(1)), dono.get(fp.name, "")
        if quem and atual.get(i) == quem:
            mantidos += 1
            ficam[fp.name] = quem
            continue
        _mover(fp, outdir / RETOMADA / (f"{quem}.pdf" if quem else f"sem_id_{fp.name}"))
        movidos += 1
    _gravar_donos(outdir, ficam)
    return {"mantidos": mantidos, "movidos": movidos}


DONOS = "donos.json"            # {NNN.pdf: id_documento} de cada PDF no lugar — sobrevive à rodada que morre no meio


def _donos(outdir: Path) -> dict[str, str]:
    import json as _json
    try:
        d = _json.loads((outdir / RETOMADA / DONOS).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_donos(outdir: Path, donos: dict[str, str]) -> None:
    import json as _json
    alvo = outdir / RETOMADA / DONOS
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(_json.dumps(donos, ensure_ascii=False), encoding="utf-8")
    tmp.replace(alvo)


def registrar_dono(outdir: Path, i: int, doc: dict) -> None:
    """Grava que `NNN.pdf` é do documento `doc` (chamar logo depois de baixá-lo ou retomá-lo)."""
    ident = id_documento(doc)
    if ident:
        d = _donos(outdir)
        d[f"{i:03d}.pdf"] = ident
        _gravar_donos(outdir, d)


def arquivo_retomado(outdir: Path, i: int, doc: dict) -> Path | None:
    """O PDF já baixado DESTE documento (posição `i` da enumeração atual), ou None. Depois de `preparar_retomada`,
    `NNN.pdf` existente é do documento certo; senão, o PDF dele pode estar em `_retomada/<id>.pdf` (veio noutra
    posição numa rodada anterior) — volta para `NNN.pdf` com data nova, para o `sei_arquivar` reextrair o texto."""
    fp = outdir / f"{i:03d}.pdf"
    if fp.exists() and fp.stat().st_size > 0:
        return fp
    ident = id_documento(doc)
    guardado = outdir / RETOMADA / f"{ident}.pdf" if ident else None
    if guardado is not None and guardado.exists() and guardado.stat().st_size > 0:
        _mover(guardado, fp)
        os.utime(fp)
        return fp
    return None


# ── "GERAR PDF DO PROCESSO" EM LOTES (20/11/2026) ────────────────────────────────────────────────────────────────────
# COMPLEMENTO do laço doc a doc, não substituto. O SEI gera um PDF de vários documentos de uma vez ("Apenas
# selecionados", campo oculto `hdnDocumentosApenas` = `id±título¥…`) e o PDF traz um MARCADOR por documento (título +
# nº SEI). Medido no teste real de 20/11 (5 processos): lotes de 40 = 30–40× mais rápido que doc a doc (10 docs: 11 s ×
# 432 s/897 requisições; 738 docs: 19 lotes ~23 min × 4 timeouts de 3 h). Mas: "Todos" falha ≥ ~150 docs (HTTP 500);
# UM documento ruim aborta o lote inteiro ("Erro na manipulação do documento X"); e 2 de 738 documentos foram OMITIDOS
# SEM AVISO. Por isso: lote de 40, recusado sai do lote (e vai ao laço), 500/teto divide ao meio, e cada documento só
# conta como vindo se o MARCADOR dele está no PDF — casado pelo nº SEI, NUNCA pela posição. O que faltou (omitido calado,
# recusado, vazio, sem nº para casar) fica sem arquivo e o laço atual, que pula o que existe, busca só isso.
# Reversão rápida: SEI_PDF_LOTES=0.
PDF_LOTES = os.environ.get("SEI_PDF_LOTES", "1") != "0"
TAM_LOTE = int(os.environ.get("SEI_PDF_LOTE_TAM", "40"))
TETO_LOTE_S = int(os.environ.get("SEI_PDF_LOTE_TETO_S", "360"))        # medido: lote de 40 em 12–139 s
# JANELA DENTRO DO browser_lock (idade_max 30 min: depois disso outro processo toma a trava como órfã). Contadas da
# aquisição da trava: lotes novos só começam até 20 min; o laço doc a doc para aos 25 min. O que ficou retoma na
# próxima passada a partir do que já está salvo (pelo id).
JANELA_LOTES_S = int(os.environ.get("SEI_PDF_JANELA_S", "1200"))
JANELA_TOTAL_S = int(os.environ.get("SEI_PDF_JANELA_TOTAL_S", "1500"))
LOTES_DIR = "_lotes"            # PDF do lote vive aqui só até ser cortado (disco da VM a 94%: 738 docs = 3,9 GB)
_RX_GERAR = re.compile(r"controlador\.php\?acao=procedimento_gerar_pdf[^\"'\\\s<>]*")
_RX_ERRO_DOC = re.compile(r'Erro na manipula\w+ do documento "([^"]+)"')
_RX_CARIMBO = re.compile(r"^.*SEI SEI-\d{6}/\d{6}/\d{4} / pg\. \d+\s*$", re.M)   # rodapé que o SEI põe em cada página


def _num_sei(titulo: str) -> str:
    from compliance_agent.sei.manifesto_norm import numero_sei_do_titulo
    return numero_sei_do_titulo(titulo)


def valor_documentos_apenas(lote: list[dict]) -> str:
    """O `hdnDocumentosApenas` do formulário: `id±título¥id±título…` (o SEI usa o id; título higienizado)."""
    return "¥".join(f"{id_documento(x)}±{(x.get('t') or '')[:80].replace('¥', ' ').replace('±', ' ')}" for x in lote)


def doc_recusado(mensagem: str, lote: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    """Qual documento do lote o SEI recusou ("Erro na manipulação do documento <título>"): pelo nº SEI do título da
    mensagem; sem nº, pelo título idêntico. Ambíguo ou ausente → None (o chamador divide o lote para isolar)."""
    n = _num_sei(mensagem)
    cands = [(i, x) for i, x in lote if n and _num_sei(x.get("t") or "") == n]
    if not cands:
        alvo = (mensagem or "").strip()
        cands = [(i, x) for i, x in lote if (x.get("t") or "").strip() == alvo]
    return cands[0] if len(cands) == 1 else None


def segmentos_por_marcador(pdf: "fitz.Document") -> dict[str, list | None]:
    """{nº SEI: [páginas (0-based)…]} pelos marcadores de nível 1. Um nº que aparece em dois marcadores fica com
    `None` — ambíguo, não se corta (melhor ir ao laço que gravar o teor de um documento no lugar de outro)."""
    ent = sorted(((t[1], t[2] - 1) for t in pdf.get_toc(simple=True) if t[0] == 1 and t[2] >= 1), key=lambda e: e[1])
    seg: dict[str, list | None] = {}
    for k, (tit, p0) in enumerate(ent):
        p1 = ent[k + 1][1] if k + 1 < len(ent) else pdf.page_count
        n = _num_sei(tit)
        if not n:
            continue
        seg[n] = None if n in seg else list(range(p0, max(p0 + 1, p1)))
    return seg


def _gravar_peca(pdf: "fitz.Document", paginas: list[int], fp: Path, titulo: str) -> bool:
    """Grava UM documento cortado do PDF do lote em `fp`: as PÁGINAS ORIGINAIS do marcador, sem a linha do carimbo de
    rodapé do SEI (removida por redação, para não entrar no texto do acervo). Nativo sai com a camada de texto do SEI;
    escaneado/foto sai como imagem e o `sei_arquivar` faz o OCR como hoje.

    Re-renderizar o texto (`gravar_doc`) era o óbvio e custou 98% do tempo: 46 docs/663 págs em 522 s (16.643
    `insert_textbox`) contra 3,6 s copiando as páginas — e o disco ficou igual (71 × 78 MB), com as fotos preservadas
    (medido 20/11). Sem texto, sem imagem e sem desenho → False (vazio: o laço tenta pela árvore)."""
    tem_teor = False
    for p in paginas:
        pg = pdf[p]
        t = _RX_CARIMBO.sub("", pg.get_text("text")).strip()
        # texto próprio, imagem (scan/foto) ou texto DESENHADO (espelho do SIAFE vem em vetor: 2.431 traços e só o
        # carimbo como texto, medido 20/11 — o OCR do arquivador lê)
        if len(t) >= 15 or pg.get_images() or len(pg.get_drawings()) >= 50:
            tem_teor = True
            break
    if not tem_teor:
        return False
    peca = fitz.open()
    try:
        peca.insert_pdf(pdf, from_page=paginas[0], to_page=paginas[-1])   # páginas contíguas do marcador
        for pg in peca:
            # só a LINHA do carimbo ("<título>   SEI SEI-…/… / pg. N"), pelo bbox dela: uma faixa de largura total
            # apagava célula de tabela e texto vizinho (medido 20/11). O `dict` só na faixa de cada "SEI SEI-" (o da
            # página inteira custava 35 s em 663 págs). Só TEXTO sai: imagem e traço que cruzem a linha ficam.
            # página GIRADA (anexo em paisagem, 270°): a faixa do search_for sai noutro sistema de coordenadas — lá
            # vai o `dict` da página inteira (raro; 3 de 663 págs no 510001/001547/2025)
            achou = False
            faixas = [None] if pg.rotation else [fitz.Rect(pg.rect.x0, r.y0 - 1, pg.rect.x1, r.y1 + 1)
                                                  for r in pg.search_for("SEI SEI-")]
            for faixa in faixas:
                for bloco in pg.get_text("dict", clip=faixa).get("blocks", []):
                    for linha in bloco.get("lines", []):
                        if _RX_CARIMBO.search("".join(s.get("text", "") for s in linha.get("spans", []))):
                            pg.add_redact_annot(fitz.Rect(linha["bbox"]))
                            achou = True
            if achou:
                pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        peca.save(str(fp), garbage=3, deflate=True)
    finally:
        peca.close()
    return True


def cortar_lote(pdf_path: Path, lote: list[tuple[int, dict]], outdir: Path) -> dict:
    """CONFERÊNCIA + CORTE: lista pedida × marcadores presentes. Cada documento pedido cujo nº SEI tem marcador vira
    `outdir/NNN.pdf` (NNN = posição NA ENUMERAÇÃO ATUAL, o mesmo nome do laço) com o dono registrado pelo id.
    Devolve {gravados, omitidos (pedido sem marcador — o SEI omite CALADO), vazios, sem_numero, extras}."""
    r = {"gravados": [], "omitidos": [], "vazios": [], "sem_numero": [], "extras": []}
    pdf = fitz.open(str(pdf_path))
    try:
        seg = segmentos_por_marcador(pdf)
        pedidos = set()
        for i, x in lote:
            n = _num_sei(x.get("t") or "")
            pedidos.add(n)
            if not n:
                r["sem_numero"].append(i)
                continue
            paginas = seg.get(n)
            if not paginas:                     # ausente OU ambíguo
                r["omitidos"].append(i)
                continue
            fp = outdir / f"{i:03d}.pdf"
            try:
                ok = _gravar_peca(pdf, paginas, fp, x.get("t") or "")
            except (RuntimeError, ValueError, OSError):
                ok = False
            if ok and fp.exists() and fp.stat().st_size > 0:
                registrar_dono(outdir, i, x)
                r["gravados"].append(i)
            else:
                fp.unlink(missing_ok=True)
                r["vazios"].append(i)
        r["extras"] = sorted(n for n in seg if n not in pedidos)
    finally:
        pdf.close()
    return r


async def _url_gerar_pdf(pg) -> str | None:
    """O link `procedimento_gerar_pdf` (com o infra_hash da sessão) — está no HTML do frame da árvore."""
    import html as _html
    for fr in pg.frames:
        try:
            m = _RX_GERAR.search(await fr.content())
        except PWError:
            continue
        if m:
            return "https://sei.rj.gov.br/sei/" + _html.unescape(m.group(0))
    return None


async def _pedir_lote_sei(pg, url: str, valor: str, destino: Path, teto: float = TETO_LOTE_S) -> tuple[str, str]:
    """Submete o formulário "Gerar PDF" com os documentos do lote e espera: ("ok", "") com o PDF salvo em `destino`;
    ("erro_doc", título que o SEI recusou); ("erro_500", texto) ou ("teto", ""). O erro vem do TEXTO da página, não
    de um teto fixo de tamanho de lote."""
    import time as _t
    baixados: list = []

    def ouvir(dl):              # função de verdade: o Playwright recusa builtin (`list.append`) como handler
        baixados.append(dl)
    paginas = list(pg.context.pages)
    for p in paginas:
        p.on("download", ouvir)

    def _nova(p):
        paginas.append(p)
        p.on("download", ouvir)
    pg.context.on("page", _nova)
    try:
        vf = await SR._frame_visualizacao(pg)
        if vf is None:
            return "erro_500", "sem ifrVisualizacao"
        await vf.goto(url, timeout=120000)
        vf = await SR._frame_visualizacao(pg)
        await vf.evaluate("""(v)=>{document.getElementById('optApenas').checked=true;
            document.getElementById('hdnDocumentosApenas').value=v;
            document.getElementById('hdnFlagGerar').value='1';
            document.getElementById('frmProcedimentoPdf').submit();}""", valor)
        fim = _t.monotonic() + teto
        while _t.monotonic() < fim:
            await asyncio.sleep(2)
            if baixados:
                await baixados[0].save_as(str(destino))
                return "ok", ""
            try:
                vf = await SR._frame_visualizacao(pg)
                tx = await vf.evaluate("()=>document.body?document.body.innerText:''") if vf else ""
            except PWError:
                continue
            m = _RX_ERRO_DOC.search(tx or "")
            if m:
                return "erro_doc", m.group(1)
            if "Erro gerando PDF" in (tx or ""):
                return "erro_500", (tx or "")[:200]
        return "teto", ""
    finally:
        pg.context.remove_listener("page", _nova)
        for p in paginas:
            try:
                p.remove_listener("download", ouvir)
            except (PWError, ValueError, KeyError):
                pass


async def gerar_pdf_lotes(pg, docs: list[dict], outdir: Path, *, prazo: float | None = None, pedir=None,
                          tam: int = TAM_LOTE) -> dict:
    """Busca pelo "Gerar PDF" em lotes os documentos que ainda NÃO têm arquivo (retomada pelo id) e grava cada um em
    `NNN.pdf`. `prazo` (time.monotonic) = último instante para COMEÇAR um lote. `pedir(lote, destino)` → (status, info)
    é injetável (testes); por padrão submete o formulário do SEI na página `pg`.

    Devolve {via: {i: "pdf_nativo"}, recusados [{i, motivo}], omitidos, vazios, sem_numero, pendentes_janela (posições
    `i`), extras, lotes_ok, lotes_pedidos, erro}. Nada aqui marca captura completa: o laço seguinte decide, documento a
    documento."""
    import time as _t
    r = {"via": {}, "recusados": [], "omitidos": [], "vazios": [], "sem_numero": [], "pendentes_janela": [],
         "extras": [], "lotes_ok": 0, "lotes_pedidos": 0, "erro": None}
    alvo = [(i, x) for i, x in enumerate(docs) if id_documento(x) and arquivo_retomado(outdir, i, x) is None]
    if not alvo:
        return r
    if pedir is None:
        url = await _url_gerar_pdf(pg)
        if not url:
            r["erro"] = "link procedimento_gerar_pdf não achado"
            return r

        async def pedir(lote, destino):
            return await _pedir_lote_sei(pg, url, valor_documentos_apenas([x for _, x in lote]), destino)
    tmp = outdir / LOTES_DIR
    tmp.mkdir(parents=True, exist_ok=True)
    for velho in tmp.glob("*.pdf"):           # lote de uma rodada morta no meio: nunca foi cortado, não vale
        velho.unlink(missing_ok=True)
    fila = [alvo[k:k + tam] for k in range(0, len(alvo), tam)]
    seq = 0
    while fila:
        lote = fila.pop(0)
        if prazo is not None and _t.monotonic() > prazo:
            r["pendentes_janela"] += [i for i, _ in lote] + [i for lt in fila for i, _ in lt]
            break
        seq += 1
        destino = tmp / f"lote_{seq:03d}.pdf"
        r["lotes_pedidos"] += 1
        t0 = _t.monotonic()
        try:
            status, info = await pedir(lote, destino)
        except (PWError, asyncio.TimeoutError, OSError) as e:
            status, info = "erro_500", f"{type(e).__name__}: {str(e)[:80]}"
        print(f"  lote {seq} ({len(lote)} docs): {status} em {_t.monotonic() - t0:.0f}s"
              + (f" — {info[:80]}" if info else ""), flush=True)
        if status == "ok":
            r["lotes_ok"] += 1
            try:
                c = cortar_lote(destino, lote, outdir)
            except (RuntimeError, ValueError, OSError) as e:   # PDF ilegível: nada deste lote conta como vindo
                print(f"  lote {seq}: PDF ilegível ({str(e)[:60]}) — os {len(lote)} docs vão ao laço", flush=True)
                c = {"gravados": [], "omitidos": [i for i, _ in lote], "vazios": [], "sem_numero": [], "extras": []}
            finally:
                destino.unlink(missing_ok=True)   # texto já extraído: o PDF do lote não fica no disco
            for i in c["gravados"]:
                r["via"][i] = "pdf_nativo"
            for k in ("omitidos", "vazios", "sem_numero", "extras"):
                r[k] += c[k]
            if c["omitidos"]:
                print(f"  lote {seq}: {len(c['omitidos'])} documento(s) pedido(s) SEM marcador no PDF (omitidos "
                      "calados pelo SEI) — vão ao laço", flush=True)
            continue
        destino.unlink(missing_ok=True)
        if status == "erro_doc":
            quem = doc_recusado(info, lote)
            if quem is not None:
                r["recusados"].append({"i": quem[0], "motivo": f"SEI: erro na manipulação do documento ({info[:120]})"})
                resto = [e for e in lote if e[0] != quem[0]]
                if resto:
                    fila.insert(0, resto)
                continue
        # 500 / teto / recusa que não se identifica: divide ao meio até isolar
        if len(lote) > 1:
            h = len(lote) // 2
            fila[0:0] = [lote[:h], lote[h:]]
        else:
            r["recusados"].append({"i": lote[0][0], "motivo": f"SEI: {status} com o documento sozinho"})
    return r


def resumo_lotes(res: dict, docs: list[dict]) -> dict:
    """O que vai ao manifest (`pdf_lotes`): contagens e, por documento que NÃO veio pelo PDF, id/nº/título/motivo."""
    def _ent(i, motivo):
        x = docs[i]
        return {"i": i, "id_documento": id_documento(x), "numero_sei": _num_sei(x.get("t") or ""),
                "titulo": x.get("t") or "", "motivo": motivo}
    return {"via_pdf": len(res["via"]), "lotes_ok": res["lotes_ok"], "lotes_pedidos": res["lotes_pedidos"],
            "erro": res["erro"],
            "recusados": [_ent(e["i"], e["motivo"]) for e in res["recusados"]],
            "omitidos": [_ent(i, "sem marcador no PDF do lote") for i in res["omitidos"]],
            "vazios": [_ent(i, "marcador sem texto nem imagem") for i in res["vazios"]],
            "sem_numero": [_ent(i, "título sem nº SEI para casar com o marcador") for i in res["sem_numero"]],
            "pendentes_janela": len(res["pendentes_janela"]), "extras_fora_do_pedido": res["extras"][:50]}


async def main():
    import time as _tm0
    t_ini = _tm0.monotonic()
    G.cleanup_orphans()
    ok, m = G.preflight()
    print("PREFLIGHT:", ok, m, flush=True)
    if not ok:
        ok, m = G.wait_until_safe(150)
        if not ok:
            # ADIADO, não falhado. Saía com código 0 sem capturar nada; o `sei_arquivar` seguinte
            # então falhava por falta de material e a fila registrava "erro" — o mesmo rótulo de
            # uma captura que realmente quebrou. Quem lesse o log diagnosticava problema no
            # processo quando o que houve foi a VM ocupada. 75 = EX_TEMPFAIL.
            print("ADIADO por carga:", m, flush=True)
            return 75
    # SEI_INTEGRA_RAIZ: diretório de ENSAIO (teste real sem tocar o cache de produção); padrão data/sei_cache
    outdir = Path(os.environ.get("SEI_INTEGRA_RAIZ") or "data/sei_cache") / f"integra_{TAG}"
    outdir.mkdir(parents=True, exist_ok=True)
    # MUTEX REAL DO NAVEGADOR — o mesmo que `sei_reader.ler()` e `extrair_primarios_v3` usam. Este
    # roteiro abria o Playwright DIRETO, fora do lock, e por isso quem quisesse não somar dois
    # Chromium (que já derrubaram esta VM 4×) tinha de inventar uma guarda por fora.
    #
    # A guarda que inventei media a coisa errada: ausência de PROCESSO com "sweep" no nome. Medido em
    # 2026-08-15, depois de QUATRO horas de espera sem uma única captura: `browser.lock` inexistente,
    # ZERO Chromium vivo, e o "alheio" que bloqueava era um `sei_sweep --ug 296100` com 2 SEGUNDOS de
    # vida. Os sweeps do cron nascem e morrem o tempo todo; esperar que nenhum exista é esperar por
    # algo que quase nunca acontece — enquanto o recurso disputado de verdade estava livre.
    #
    # Com o lock, a exclusão é sobre o RECURSO (um browser por vez), não sobre um nome de processo,
    # e o `idade_max` ainda descarta lock órfão de sessão que morreu.
    from compliance_agent.recursos import browser_lock_async
    async with browser_lock_async(espera_max=1800), async_playwright() as pw:
        # SEI_HEADED=1: janela do navegador VISÍVEL (it-campo, pedido do dono 14/11/2026: "nada de janelas ocultas")
        # SEI_CHROMIUM_ARGS: posição/tamanho da janela por sessão (it-campo: mosaico fixo, sem cobrir o trabalho do dono)
        # SEI_CDP_URL (it-campo): conecta no navegador FIXO da sessão, aberto e logado — uma aba por processo, sem
        # abrir/fechar janela nem relogar a cada processo. Sem ela, lança um navegador como sempre (VM-1/VM-2).
        b, ctx, fixo = await SR.navegador_sei(
            pw, args=G.guarded_launch_args(os.environ.get("SEI_CHROMIUM_ARGS", "").split() or None))
        import time as _tm
        t_lock = _tm.monotonic()              # as janelas dos lotes contam da aquisição da trava (idade_max 30 min)
        # TEMPO POR ETAPA (22/11/2026): a fila só via o total por processo; onde o tempo vai (trava, login, árvore,
        # lotes, laço doc a doc) não se media. Uma linha `ETAPAS {json}` no fim da captura; a fila a guarda.
        etapas = {"espera_trava_s": round(t_lock - t_ini, 1)}
        n_req = [0]                           # requisições ao SEI nesta captura (medida do custo de cada via)
        ctx.on("request", lambda rq: n_req.__setitem__(0, n_req[0] + ("sei.rj.gov.br" in rq.url)))
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.entrar(pg, fixo=fixo, tentativas=25): print("LOGIN FALHOU", flush=True); return RC_LOGIN_FALHOU
            print("login OK", flush=True)
            etapas["login_s"] = round(_tm.monotonic() - t_lock, 1)
            etapas["navegador_fixo"] = bool(fixo)
            t_arv = _tm.monotonic()
            # ENUMERAÇÃO — caminho CRACKED primeiro (mesmo do ler() canônico): abre processos de OUTRA
            # unidade que o itkava VÊ mas o abrir_processo/arvore_do_fonte não abre (070002/INEA,
            # 070026/SEAS). Provado 2026-07-13: INEA 070002/004135/2025 = 274 docs via cracked. Fallback:
            # arvore_do_fonte (unidade do login). Os docs trazem {titulo,url}; a url é o nó arvore_visualizar.
            arv = []
            dump = {}
            try:
                dump = await SR._ler_cracked(pg, PROC)
                arv = dump.get("documentos") or []
            except (PWError, asyncio.TimeoutError) as e:
                print(f"cracked: {str(e)[:60]}", flush=True)
            fr = None
            origem = "cracked" if arv else None
            if not arv:
                fr = await SR.abrir_processo(pg, PROC)
                if fr:
                    arv = await SR.arvore_do_fonte(pg)
                    origem = "fallback/arvore_do_fonte" if arv else None
            # POR QUAL VIA A ÁRVORE VEIO. O log de sucesso dizia só "baixando N docs" e nunca a
            # origem — e isso escondeu a pergunta que importa. Medido em 2026-08-15: o
            # `080002/011494/2024` falha SEMPRE com `erro_cracked='campo de pesquisa não apareceu'`,
            # enquanto o `080002/023009/2024` abre normalmente. Se o cracked falhar nos DOIS e o
            # segundo estiver entrando pelo fallback, então o cracked está quebrado para todo mundo
            # — e ele é o único caminho para processo de OUTRA unidade, uma classe inteira do acervo
            # que ficaria inalcançável sem ninguém perceber.
            if arv:
                print(f"árvore via {origem}: {len(arv)} nós"
                      + (f" (cracked falhou: {dump.get('erro_cracked')!r})"
                         if origem != "cracked" and dump.get("erro_cracked") else ""), flush=True)
            if not arv:
                # A CAUSA ESTAVA SENDO COLHIDA E JOGADA FORA. `_ler_cracked` NÃO levanta exceção
                # quando falha de leve: devolve `{"documentos": [], "erro_cracked": "..."}` — e ainda
                # marca `cadeado`/`n_docs_restritos` quando o processo tem documento restrito. Nada
                # disso era impresso, então três tentativas seguidas no `080002/011494/2024` (R$ 6,4
                # mi) produziram a MESMA linha muda, "SEM ÁRVORE", sem dizer o que falhou.
                #
                # Log que afirma menos do que o código sabe custa rodada de diagnóstico: eu tinha de
                # abrir o dump à mão para descobrir algo que o processo já tinha em mãos.
                # E A RESPOSTA DO PRÓPRIO SEI. Medido em 13/11/2026 (tela capturada, VM-2): os quatro processos
                # que saíam com "link 'Pesquisa' NÃO ESTÁ no DOM" tinham, na página, "Unidade atual não possui
                # acesso ao processo restrito SEI-…" — nível de acesso RESTRITO do processo, dito pelo SEI. A
                # mensagem do cracked apontava o navegador; a da página aponta o processo. Registrar a da página.
                try:
                    corpo = await pg.evaluate("()=>document.body ? document.body.innerText : ''")
                except PWError:
                    corpo = ""
                aviso = re.search(r"Unidade atual não possui acesso ao processo restrito[^\n.]*", corpo or "")
                print("SEM ÁRVORE (processo não abriu) — "
                      + (f"RESTRITO: SEI diz '{aviso.group(0)}' — " if aviso else "")
                      + f"via={dump.get('via')!r} erro_cracked={dump.get('erro_cracked')!r} "
                      f"cadeado={dump.get('cadeado')!r} "
                      f"n_docs_restritos={dump.get('n_docs_restritos')!r} "
                      f"relacionados={len(dump.get('relacionados') or [])} "
                      f"abrir_processo={'ok' if fr else 'falhou'}", flush=True)
                return RC_SEM_ARVORE
            # formato p/ o resto do script: {t: titulo, u: url, pai: ''}
            docs = [{"t": d.get("titulo") or d.get("texto") or "", "u": d.get("url") or "", "pai": ""}
                    for d in arv if d.get("url")]
            etapas["arvore_s"] = round(_tm.monotonic() - t_arv, 1)
            etapas["arvore_n"] = len(docs)
            print(f"baixando {len(docs)} docs…", flush=True)
            paths = []

            async def baixa_um(x, fp):
                # CONTEÚDO só pela ÁRVORE VIVA (_conteudo_doc). O GET-direto que existia
                # aqui (ctx.request.get de documento_visualizar) ENVENENAVA a sessão para
                # documento de OUTRA unidade: o request com o infra_hash invalidado fazia o
                # SEI resetar o contexto server-side de documento/unidade, e a partir dali
                # TODA leitura pela árvore voltava vazia — causa provada dos 11.9k "brancos"
                # (2026-07-23: 0/646 docs com o GET; _conteudo_via_arvore sozinho rende 2.348
                # chars/doc). O drill na árvore serve nativo (texto do editor) e escaneado
                # (baixa o anexo + OCR) sem envenenar — mesmo caminho de sei_processo_integral.
                c = await SR._conteudo_doc(pg, {"url": x["u"], "texto": x["t"]})
                txt = ((c or {}).get("conteudo") or "").strip()
                if len(txt) < 15:
                    return False
                if parece_pagina_de_unidade(txt):
                    # o SEI não serviu o documento: devolveu a tela de unidades.
                    # Gravar isso seria inventar teor — melhor registrar a falta.
                    print(f"  doc NÃO SERVIDO (tela de unidade): {x['t'][:40]}", flush=True)
                    return False
                # gravar_doc preserva o PDF ORIGINAL quando escaneado (imagens = fotos de
                # prova) e usa texto p/ nativo; nunca deixa página em branco (confere o
                # retorno de insert_textbox). anexo_bytes vem de _conteudo_via_arvore.
                from compliance_agent.sei.pdf_texto import gravar_doc
                if not gravar_doc(fp, x["t"], txt, (c or {}).get("anexo_bytes")):
                    print(f"  doc sem teor gravável: {x['t'][:40]}", flush=True)
                    return False
                # o OCR deste anexo já foi pago aqui: fica ao lado do PDF para o `sei_arquivar` não refazê-lo do
                # zero (ver `_ocr_da_captura`). Texto cortado no teto de caracteres NÃO serve — o arquivador lê inteiro.
                if (c or {}).get("via") == "ocr" and (c or {}).get("anexo_bytes") and len(txt) < SR.MAX_CHARS_DOC:
                    fp.with_suffix(".ocr.txt").write_text(txt, encoding="utf-8")
                return True

            # manifest com os TÍTULOS da árvore: é ele que permite classificar a
            # fase de cada documento depois (tools/sei_arquivar.py).
            # GRAVAÇÃO INCREMENTAL (2026-07-23): antes o manifesto só era escrito DEPOIS do
            # loop inteiro — quando a fila matava o processo por timeout (900s) no meio de
            # centenas de documentos, TODO o trabalho baixado virava lixo não catalogado.
            # Agora cada documento é registrado na hora e `completo` só vira True no fim,
            # então uma morte no meio deixa uma captura PARCIAL aproveitável e retomável.
            import json as _json
            man_path = outdir / "manifest.json"

            # ÁRVORE QUE ENCOLHEU não fecha a captura: a enumeração de agora é menor que a de antes nesta
            # mesma pasta, então o que falta é leitura nossa, não documento inexistente. Guarda o maior
            # tamanho e não marca `completo` — a próxima passada reenumera e retoma.
            n_antes = arvore_anterior(man_path)
            encolheu = n_antes > len(docs)
            if encolheu:
                print(f"ÁRVORE ENCOLHEU: {len(docs)} nós agora, {n_antes} numa captura anterior — "
                      "captura NÃO marcada completa", flush=True)

            lotes_res: dict = {}              # resumo do "Gerar PDF" em lotes (vazio = desligado/não rodou)

            def _grava(man: list, completo: bool) -> None:
                tmp = outdir / "manifest.json.tmp"   # atômico: morte no meio não corrompe
                tmp.write_text(_json.dumps(
                    {"processo": PROC, "total_arvore": max(len(docs), n_antes),
                     "completo": completo and not encolheu,
                     **({"pdf_lotes": lotes_res} if lotes_res else {}),
                     "docs": man}, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(man_path)

            async def reabrir(aba) -> bool:
                """Mesma via que deu a árvore no início; vale só se a aba nova tem árvore viva. A aba nasce em
                about:blank e o cracked procura o link 'Pesquisa' na página atual: primeiro vai ao início do SEI
                (mesma sessão do contexto — sem login novo; sessão caída = não renova). Medido 19/11: sem este passo
                a renovação falhava calada e a aba seguia crescendo (1,4 GB em 159 docs)."""
                if not await SR.ja_logado(aba):
                    return False
                if origem == "cracked":
                    if not ((await SR._ler_cracked(aba, PROC)).get("documentos")):
                        return False
                elif not (await SR.abrir_processo(aba, PROC) and await SR.arvore_do_fonte(aba)):
                    return False
                return await SR._frame_arvore(aba) is not None

            # por qual via cada documento JÁ salvo veio numa rodada anterior (pelo id; lido antes do 1º _grava)
            try:
                _ant = _json.loads(man_path.read_text(encoding="utf-8"))
                via_ant = {id_documento(e): e.get("via") for e in (_ant.get("docs") or [])
                           if isinstance(e, dict) and e.get("via") and id_documento(e)}
            except (OSError, ValueError, AttributeError):
                via_ant = {}
            ret = preparar_retomada(outdir, docs)   # ANTES do primeiro _grava: lê o dono de cada PDF no manifesto anterior
            if ret["movidos"]:
                print(f"RETOMADA POR ID: {ret['mantidos']} PDFs no lugar, {ret['movidos']} mudaram de posição "
                      f"(guardados em {RETOMADA}/ pelo id)", flush=True)
            manifest = []
            _grava(manifest, False)   # marca "em andamento" já no primeiro instante
            # COMPLEMENTO PRIORITÁRIO: "Gerar PDF" em lotes ANTES do laço. O que vier vira `NNN.pdf` (dono pelo id) e o
            # laço abaixo pula; o que faltar (omitido calado, recusado, vazio) o laço busca pela árvore, como sempre.
            # Falha do complemento nunca derruba a captura — o laço segue com tudo o que faltar.
            via_pdf: dict = {}
            pendentes: set = set()
            if PDF_LOTES:
                t_l = _tm.monotonic()
                try:
                    res = await gerar_pdf_lotes(pg, docs, outdir, prazo=t_lock + JANELA_LOTES_S)
                except (PWError, asyncio.TimeoutError, OSError, RuntimeError, ValueError, AttributeError,
                        TypeError, KeyError) as e:
                    # o complemento NUNCA derruba a captura (ensaio 20/11: um AttributeError do Playwright derrubou)
                    print(f"PDF EM LOTES falhou ({type(e).__name__}: {str(e)[:80]}) — sigo pelo laço", flush=True)
                    res = None
                if res is not None:
                    via_pdf, pendentes = res["via"], set(res["pendentes_janela"])
                    lotes_res = resumo_lotes(res, docs)
                    lotes_res["s"] = round(_tm.monotonic() - t_l, 1)
                    print(f"PDF EM LOTES: {len(via_pdf)}/{len(docs)} docs em {lotes_res['s']:.0f}s "
                          f"({res['lotes_ok']}/{res['lotes_pedidos']} lotes; recusados {len(res['recusados'])}, "
                          f"omitidos {len(res['omitidos'])}, vazios {len(res['vazios'])}, "
                          f"sem nº {len(res['sem_numero'])}, pendentes da janela {len(pendentes)})"
                          + (f" — {res['erro']}" if res["erro"] else ""), flush=True)
            cortado_janela = False
            baixados_desde = 0
            t_laco = _tm.monotonic()
            for i, x in enumerate(docs):
                fp = outdir / f"{i:03d}.pdf"
                ok = False
                via = None
                if arquivo_retomado(outdir, i, x) is not None:
                    paths.append(fp); ok = True     # retomada PELO ID: não rebaixa o que já veio deste documento
                    via = via_pdf.get(i) or via_ant.get(id_documento(x))
                elif PDF_LOTES and (i in pendentes or _tm.monotonic() > t_lock + JANELA_TOTAL_S):
                    # JANELA DO browser_lock esgotada: não tenta agora; a próxima passada retoma (pelos lotes, que são
                    # mais rápidos) a partir do que já está salvo. A captura NÃO fecha completa.
                    if not cortado_janela:
                        print(f"JANELA esgotada no doc {i}/{len(docs)} — o resto fica para a próxima passada", flush=True)
                    cortado_janela = True
                else:
                    if hora_de_renovar(baixados_desde):
                        import time as _t
                        t0 = _t.time()
                        nova = await renovar_aba(ctx, pg, reabrir)
                        baixados_desde = 0
                        renovou = nova is not pg
                        if renovou:
                            pg = nova
                            print(f"  aba renovada em {_t.time() - t0:.0f}s (doc {i}/{len(docs)})", flush=True)
                        # a saída da captura não chega ao log da fila: o registro fica aqui para medir a renovação
                        with open("data/sei_aba_renovada.jsonl", "a", encoding="utf-8") as _f:
                            _f.write(_json.dumps({"t": _t.strftime("%F %T"), "processo": PROC, "doc": i,
                                                  "total": len(docs), "renovou": renovou,
                                                  "s": round(_t.time() - t0, 1)}) + "\n")
                    baixados_desde += 1
                    try:
                        # REDE DE SEGURANÇA acima do orçamento do OCR (OCR_BUDGET_S=300s): o
                        # OCR de scan se AUTO-LIMITA por tempo e declara parcial, então este
                        # wait_for não precisa mais casar com nº de páginas (o design frágil
                        # antigo). 450 = 300 do OCR + ~150 de download/render/click, com folga.
                        # Só dispara se algo travar de verdade (o request tem timeout próprio, 45s).
                        if await asyncio.wait_for(baixa_um(x, fp), timeout=int(os.environ.get("SEI_DOC_TIMEOUT", "450"))):
                            paths.append(fp); ok = True; via = "arvore"
                    except (asyncio.TimeoutError, PWError, httpx.HTTPError, RuntimeError, OSError, ValueError) as e:
                        print(f"  doc {i} pulado: {str(e)[:35]}", flush=True)
                if ok:
                    registrar_dono(outdir, i, x)
                manifest.append({"i": i, "arquivo": fp.name, "titulo": x.get("t") or "",
                                 "contexto": x.get("pai") or "", "url": x.get("u") or "",
                                 "id_documento": id_documento(x), "ok": ok, **({"via": via} if via else {})})
                _grava(manifest, False)
                if i % 15 == 0:
                    print(f"  {i}/{len(docs)} ({len(paths)} ok)", flush=True)
            _grava(manifest, not cortado_janela)
            etapas.update({"lotes_s": lotes_res.get("s", 0.0), "laco_s": round(_tm.monotonic() - t_laco, 1),
                           "via_pdf": sum(1 for e in manifest if e.get("via") == "pdf_nativo"),
                           "via_arvore": sum(1 for e in manifest if e.get("via") == "arvore"),
                           "faltando": sum(1 for e in manifest if not e["ok"]), "cortado_janela": cortado_janela,
                           "requisicoes": n_req[0]})
            print("ETAPAS " + _json.dumps(etapas, ensure_ascii=False), flush=True)
            print(f"REQUISIÇÕES SEI: {n_req[0]} · via pdf_nativo {sum(1 for e in manifest if e.get('via') == 'pdf_nativo')}"
                  f" · via arvore {sum(1 for e in manifest if e.get('via') == 'arvore')}"
                  f" · faltando {sum(1 for e in manifest if not e['ok'])}"
                  f" · {_tm.monotonic() - t_lock:.0f}s desde a trava", flush=True)
            # NÓ DE CAPTURA (it-campo): o lote entregue à VM-1 leva `arquivo/` e `cache/integra_<proc>/` — o PDF
            # único abaixo NÃO vai, e `sei_integra_vm2._limpar_local` o apaga depois da entrega. Montá-lo era só
            # custo: 14/11/2026, quatro deles com 0,6–1,0 GB, juntados inteiros na memória (`garbage=4`) por
            # sessão — pico de RAM na máquina onde a memória é o que limita o nº de sessões.
            if os.environ.get("SEI_SEM_PDF_UNICO") == "1":
                print(f"ÍNTEGRA: {len(paths)} docs (PDF único dispensado: SEI_SEM_PDF_UNICO=1)", flush=True)
                return
            # junta
            out = fitz.open()
            sep = fitz.open(); spg = sep.new_page(); spg.insert_text((60, 120), f"ÍNTEGRA — PROCESSO SEI-{PROC} ({len(paths)} documentos)", fontsize=14); out.insert_pdf(sep); sep.close()
            for fp in paths:
                try:
                    s = fitz.open(str(fp))
                    if s.is_pdf and s.page_count: out.insert_pdf(s)
                    s.close()
                except (RuntimeError, ValueError, OSError): pass
            full = Path(f"data/sei_cache/INTEGRA_{TAG}.pdf"); out.save(str(full), deflate=True, garbage=4)
            sz = full.stat().st_size; print(f"ÍNTEGRA: {len(paths)} docs, {out.page_count} págs, {sz/1024/1024:.1f}MB", flush=True)
            # envia (divide se >45MB); SEI_SEM_TG=1 → só baixa/arquiva, sem Telegram
            if os.environ.get("SEI_SEM_TG") == "1":
                print("TG: pulado (SEI_SEM_TG=1)", flush=True)
                return
            LIM = 45 * 1024 * 1024
            if sz <= LIM:
                print("TG:", envia(str(full), f"📚 ÍNTEGRA COMPLETA — Processo SEI-{PROC} ({len(paths)} docs, {out.page_count} págs)"), flush=True)
            else:
                npart = sz // LIM + 1; per = (out.page_count // npart) + 1
                for k in range(0, out.page_count, per):
                    part = fitz.open(); part.insert_pdf(out, from_page=k, to_page=min(k + per - 1, out.page_count - 1))
                    pp = Path(f"data/sei_cache/INTEGRA_{TAG}_p{k//per+1}.pdf"); part.save(str(pp), deflate=True, garbage=4); part.close()
                    print(f"TG parte {k//per+1}:", envia(str(pp), f"📚 ÍNTEGRA SEI-{PROC} (parte {k//per+1}, págs {k+1}-{min(k+per,out.page_count)})"), flush=True)
        finally:
            await SR.fechar_sei(b, pg, fixo=fixo)
    G.cleanup_orphans()

if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    raise SystemExit(asyncio.run(main()) or 0)
