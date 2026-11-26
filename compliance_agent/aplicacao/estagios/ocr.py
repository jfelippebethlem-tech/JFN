# -*- coding: utf-8 -*-
"""E5 `ocr` — OCR SÓ ONDE ESTÁ VAZIO, com bbox e motor@versão (plano mestre v2 §3.2 E5, §3.5 (b); item O3.4).
Absorve `sei_ocr_gpu*` (GPU do it-campo), `sei_ocr_reserva` / `vm2_ocr_reserva` / `itcampo_ocr_cpu` (CPU) e
`ocr_contratos_imagem` — como MOTORES (não reescritos): o Surya do `deploy/itcampo/ocr_gpu/ocr_gpu_worker.py` e o
RapidOCR configurado em `tools/sei_ocr_reserva.motor_ocr` (o melhor motor de CPU medido no gabarito de 18/11/2026).

Entrada: `ocr:<processo>|<doc_id>|<sha16>` — o evento `texto/pagina_escaneada` do E4 (ou a fila legada migrada,
`texto_ocr_legado`). Payload `{processo, doc_id, sha256, arquivo?, rel?}`.

REGRAS (lições ocr-novo-nunca-substitui-texto e ocr-gpu-vazio-marcado-feito):
  1. SÓ página `escaneada` do E4 (camada de texto < 40 caracteres E imagem ≥ 35%) vai ao OCR. Página com texto
     nativo NUNCA é lida: o texto do PDF é a verdade. Na página escaneada que tinha algum texto nativo (carimbo,
     "Página 1 de 3"), o nativo FICA, inteiro e primeiro; o OCR vem depois dele (nunca no lugar). O efeito confere
     que o texto composto de cada página começa pelo nativo dela.
  2. VAZIO NUNCA VIRA FEITO. Página que o motor devolve sem nenhum caractere alfanumérico vai a um SEGUNDO motor de
     outra família (GPU → RapidOCR; RapidOCR → Tesseract). Os dois vazios ⇒ `vazia_conferida` (declarado, com os dois
     motores). Sem segundo motor ⇒ `vazia_pendente` ⇒ NADA é gravado no PG e o efeito falha: o job volta (backoff) e,
     esgotado, vai à quarentena — backlog visível, nunca "feito". Erro de inferência (bloco com error e sem texto,
     o modo de falha do Surya de 22/11) é ERRO, não vazio: o job tenta de novo.
     2b. INCOMPLETA TAMBÉM NÃO (O3.6). O Surya devolve bloco de TEXTO com o html vazio e SEM a flag de erro: no
     controle nativo da O3.6 (200 páginas com camada de texto, renderizadas), 27 páginas saíram com < 60% dos
     caracteres e o acerto de número caiu a 69,4% (RapidOCR 94,7%). Página com bloco de texto vazio (rótulo fora
     de `ROTULOS_SEM_TEXTO`) vai ao 2º motor como a vazia; o texto dele entra (`primeiro_incompleto`); sem 2º
     motor, ou com ele também sem texto, a página fica `vazia_pendente` (nada vira feito com pedaço faltando).
  3. bbox de cada linha (coordenadas em pixels na resolução `dpi`, com a dimensão da página), o perfil do E4 e
     motor@versão por página no arquivo lateral `…/<doc>.<sha16>.e5.json`; o sha256 dele vai em
     `transformacao.parametros`. A bbox é o que o E6 recorta para a conferência por recorte (O3.6).
  4. DEDUP POR HASH DE IMAGEM (O3.6, plano §7): cada página escaneada leva `img_sha` = sha256 dos PIXELS renderizados
     a `dpi` (a entrada exata do motor). Página idêntica a outra do mesmo documento, ou a uma já lida pelo MESMO
     motor@versão (cache `CacheImagem`, em `<raiz>/_dedup_imagem/`), reusa a leitura — `dedup_de` diz de onde. Hash
     EXATO de propósito: um hash perceptual juntaria a nota que difere só num dígito do valor. Só leitura ÚTIL entra
     no cache (o vazio segue a regra 2, sempre relido pelo 2º motor).

EXECUTOR (roteamento por capacidade com VOLTA DECLARADA, §3.5): no it-campo com o Surya importável ⇒ GPU; em qualquer
outro nó (ou `JFN_OCR_EXECUTOR=cpu`) ⇒ RapidOCR na CPU (VM-2: mais lento, nunca parado). O job pede `cpu_pesado`
(todo nó tem) com nó preferido it-campo e volta VM-2 — a reserva do motor só troca de NÓ na volta, não de recurso
(fila.reservar: `recursos <@ livres`), então pedir `gpu` deixaria o job preso sem o it-campo. A GPU é serializada
por uma trava de arquivo no próprio it-campo (`JFN_OCR_GPU_TRAVA`), não pelo slot.

Saída (PG): `transformacao` tipo `ocr` (entrada = sha256 do binário, saída = sha256 do texto composto, motor e
versão do motor principal; `parametros`: páginas por estado, motores usados, sha do lateral) e `versoes` (hash_de
`texto`, origem `sei:e5`, `ocr` = motor@versão). Eventos: `ocr/texto_novo` (E8), `ocr/numero_ia` (E6, SEMPRE — com
`numeros` = 0 quando o OCR não traz número crítico: o E6 confirma com 0 números). O E7 (o original pode sair) nasce
da conclusão do E6, não daqui (26/11/2026: corrida E6 × E7).

Efeito conferido (outro processo): transformacao no PG; lateral com o sha gravado; TODA página pedida resolvida
(`texto` com texto e bbox, ou `vazia_conferida` com dois motores); nenhuma página nativa lida; o composto de cada
página começa pelo nativo; sha256 do composto recalculado = saída; versão de texto no PG.

CLI:
    python -m compliance_agent.aplicacao.estagios.ocr ensaio --pdf A.pdf [--pdf B.pdf …] --paginas 20 \\
        [--executor cpu] [--saida rel.json]        # mede páginas/min do executor (não grava no PG)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.aplicacao.estagios import texto as T
from compliance_agent.fluxo.fila import Resultado

VERSAO = "e5-3"                              # e5-2 (O3.6): img_sha por página + dedup por hash de imagem; e5-3
#                                              (O8.5): bbox do Tesseract da MESMA imagem que deu o texto
ORIGEM = "sei:e5"
TIPO_TRANSFORMACAO = "ocr"
DPI = 200                                    # = tools/sei_ocr_reserva.DPI e o worker da GPU (200 dpi)
MAX_PAGINAS = 120                            # páginas por LOTE do E5 (= MAX_PAG do worker da GPU e da reserva); o
#                                              documento maior é lido inteiro, um lote por vez (achado 1.10)
TEXTO, VAZIA_CONFERIDA, VAZIA_PENDENTE = "texto", "vazia_conferida", "vazia_pendente"
ENV_EXECUTOR = "JFN_OCR_EXECUTOR"            # gpu | cpu | tesseract (força; padrão = pelo nó)
ENV_TRAVA_GPU = "JFN_OCR_GPU_TRAVA"
ENV_WORKER_GPU = "JFN_OCR_GPU_DIR"           # onde mora o ocr_gpu_worker.py no it-campo
ENV_RAIZES = "JFN_OCR_RAIZES"                # raízes extras onde procurar o PDF legado (":"-separadas)
PASTA_DEDUP = "_dedup_imagem"
ORCAMENTO_RASTER = 1536 << 20                # bytes de páginas rasterizadas guardadas no job (120 págs A4 a 200 dpi
#                                              ≈ 1,4 GB); acima, a página é renderizada de novo e CONTADA como repetida
# rótulos de bloco do Surya que podem vir sem texto sem perda (figura, foto, logotipo, assinatura desenhada)
ROTULOS_SEM_TEXTO = frozenset({"Picture", "Figure", "Image", "Logo", "Signature"})                # cache das leituras por hash de imagem, dentro da raiz do texto
_RX_UTIL = re.compile(r"\w", re.UNICODE)


class ErroInferencia(RuntimeError):
    """O motor falhou (não é página vazia): o job tenta de novo."""


@dataclass
class Leitura:
    texto: str
    linhas: list[dict] = field(default_factory=list)       # [{texto, bbox: [x0, y0, x1, y1], conf}]
    largura: int = 0
    altura: int = 0
    blocos_vazios: int = 0          # O3.6: blocos de TEXTO que o motor achou e devolveu sem texto (leitura incompleta)


class Executor(Protocol):
    familia: str                                            # gpu | rapidocr | tesseract (2º motor = outra família)

    def motor(self) -> str: ...

    def ler(self, pdf: Path, paginas: list[int]) -> dict[int, Leitura]: ...


def util(texto: str) -> bool:
    """Página tem leitura útil: ao menos um caractere alfanumérico (o vazio do Surya era '' ou só marcação)."""
    return bool(_RX_UTIL.search(texto or ""))


class Rasterizacao:
    """LEITURA ÚNICA dentro do job (O8.5, plano §19): cada PDF é aberto UMA vez e cada (sha256 do documento, página,
    dpi, cor) é rasterizado UMA vez; o hash da imagem, o 1º motor, o 2º motor (E5) e a leitura independente e o
    recorte (E6) usam a mesma imagem. Antes, o E5 rasterizava cada página 2–3× (hash + motor 1 + motor 2) e o E6 2×
    (leitura + recorte), cada vez com um `fitz.open` novo. A imagem guardada é só-leitura (quem a mudasse no lugar
    corromperia o hash e o reuso). Acima de `ORCAMENTO_RASTER` a página não é guardada e a próxima vez renderiza de
    novo — contada em `repetidas`, nunca calada."""

    def __init__(self, orcamento: int | None = None):
        self.orcamento = ORCAMENTO_RASTER if orcamento is None else orcamento
        self._docs: dict[str, tuple] = {}            # caminho → (fitz.Document, sha256 do arquivo)
        self._imgs: dict[tuple, object] = {}
        self._bytes = 0
        self.contagem: dict[tuple, int] = {}         # (sha, página, dpi, cor) → vezes renderizada
        self.aberturas = 0

    def _doc(self, pdf: Path):
        k = str(Path(pdf).resolve())
        if k not in self._docs:
            import fitz
            self._docs[k] = (fitz.open(pdf), T.sha256_arquivo(Path(pdf)))
            self.aberturas += 1
        return self._docs[k]

    def documento(self, pdf: Path):
        """O `fitz.Document` aberto do job (quem usa não fecha: `fechar` fecha)."""
        return self._doc(pdf)[0]

    def paginas(self, pdf: Path) -> int:
        return self._doc(pdf)[0].page_count

    def imagem(self, pdf: Path, n: int, dpi: int = DPI, cinza: bool = False):
        """ndarray da página `n` (1-based): RGB (h, w, 3) ou cinza (h, w)."""
        import fitz
        import numpy as np
        doc, sha = self._doc(pdf)
        k = (sha, n, dpi, "cinza" if cinza else "rgb")
        if k in self._imgs:
            return self._imgs[k]
        pg = doc.load_page(n - 1)
        if cinza:
            pix = pg.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
        else:
            pix = pg.get_pixmap(dpi=dpi)
            img = np.ascontiguousarray(
                np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3])
        self.contagem[k] = self.contagem.get(k, 0) + 1
        img.setflags(write=False)
        if self._bytes + img.nbytes <= self.orcamento:
            self._imgs[k] = img
            self._bytes += img.nbytes
        return img

    def resumo(self) -> dict:
        n = sum(self.contagem.values())
        return {"rasterizacoes": n, "rasterizacoes_distintas": len(self.contagem),
                "rasterizacoes_repetidas": n - len(self.contagem), "pdf_aberturas": self.aberturas}

    def soltar_imagens(self) -> None:
        """Solta as imagens guardadas (o PDF segue aberto e a contagem segue): o E5 chama entre lotes, quando as
        páginas do lote anterior não serão mais pedidas no job."""
        self._imgs.clear()
        self._bytes = 0

    def fechar(self) -> None:
        for doc, _ in self._docs.values():
            doc.close()
        self._docs.clear()
        self._imgs.clear()
        self._bytes = 0


_RASTER: Rasterizacao | None = None


@contextlib.contextmanager
def rasterizacao_unica(orcamento: int | None = None):
    """Liga a `Rasterizacao` do job: `_imagens` (executores, hash, recorte) e as páginas do E6 passam por ela."""
    global _RASTER
    anterior, _RASTER = _RASTER, Rasterizacao(orcamento)
    try:
        yield _RASTER
    finally:
        _RASTER.fechar()
        _RASTER = anterior


def raster_atual() -> Rasterizacao | None:
    return _RASTER


def _imagens(pdf: Path, paginas: list[int]):
    """(página 1-based, ndarray RGB, largura, altura) a `DPI`, uma por vez (memória limitada). Com a
    `rasterizacao_unica` ligada, a imagem vem dela (uma renderização por página no job)."""
    r = _RASTER
    if r is not None:
        total = r.paginas(pdf)
        for n in paginas:
            if not 1 <= n <= total:
                raise ErroPermanente(f"{pdf.name}: página {n} fora do documento")
            img = r.imagem(pdf, n)
            yield n, img, img.shape[1], img.shape[0]
        return
    import fitz
    import numpy as np
    with fitz.open(pdf) as doc:
        for n in paginas:
            if not 1 <= n <= doc.page_count:
                raise ErroPermanente(f"{pdf.name}: página {n} fora do documento")
            pix = doc.load_page(n - 1).get_pixmap(dpi=DPI)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
            yield n, np.ascontiguousarray(img), pix.width, pix.height


def sha_imagem(img) -> str:
    """sha256 da forma + bytes dos pixels (a imagem que o motor recebe)."""
    import hashlib
    h = hashlib.sha256(str(tuple(img.shape)).encode("ascii"))
    h.update(img.tobytes())
    return h.hexdigest()


def hashes_imagem(pdf: Path, paginas: list[int]) -> dict[int, str]:
    """{página: img_sha} das páginas pedidas, na mesma renderização dos executores (`_imagens`)."""
    return {n: sha_imagem(img) for n, img, _, _ in _imagens(pdf, paginas)}


class CacheImagem:
    """Leituras ÚTEIS já feitas, por (img_sha, motor@versão). Arquivo por chave, gravado atômico; a leitura confere
    que o registro é da mesma imagem e do mesmo motor (senão é como se não houvesse)."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)

    def _arq(self, img_sha: str, motor: str) -> Path:
        import hashlib
        return self.raiz / img_sha[:2] / f"{img_sha}.{hashlib.sha1(motor.encode('utf-8')).hexdigest()[:12]}.json"

    def obter(self, img_sha: str, motor: str) -> tuple[Leitura, str] | None:
        lat = T.ler_lateral(self._arq(img_sha, motor))
        if lat is None:
            return None
        d = lat[0]
        if d.get("img_sha") != img_sha or d.get("motor") != motor or not util(d.get("texto") or ""):
            return None
        return Leitura(d["texto"], d.get("linhas") or [], d.get("largura") or 0, d.get("altura") or 0), d.get("origem")

    def guardar(self, img_sha: str, motor: str, le: Leitura, origem: str) -> None:
        if util(le.texto) and not le.blocos_vazios:           # incompleta nunca é reusada
            T.gravar_lateral(self._arq(img_sha, motor), {"img_sha": img_sha, "motor": motor, "texto": le.texto,
                                                         "linhas": le.linhas, "largura": le.largura,
                                                         "altura": le.altura, "origem": origem})


def _ler_dedup(executor: "Executor", motor: str, pdf: Path, paginas: list[int], hashes: dict[int, str],
               cache: CacheImagem | None, origem: str) -> tuple[dict[int, Leitura], dict[int, dict]]:
    """Lê só UMA página por imagem distinta e só o que o cache não tem; devolve (leituras de todas, dedup_de)."""
    rep: dict[str, int] = {}
    dedup: dict[int, dict] = {}
    for n in paginas:
        h = hashes[n]
        if h in rep:
            dedup[n] = {"pagina": rep[h]}
        else:
            rep[h] = n
    lidas: dict[int, Leitura] = {}
    a_ler = []
    for h, n in rep.items():
        achado = cache.obter(h, motor) if cache is not None else None
        if achado is not None:
            lidas[n] = achado[0]
            dedup[n] = {"cache": achado[1]}
        else:
            a_ler.append(n)
    if a_ler:
        novas = executor.ler(pdf, a_ler)
        lidas.update(novas)
        if cache is not None:
            for n in a_ler:
                if n in novas:
                    cache.guardar(hashes[n], motor, novas[n], f"{origem}#p{n}")
    for n, d in dedup.items():
        if "pagina" in d and d["pagina"] in lidas:
            lidas[n] = lidas[d["pagina"]]
    return lidas, dedup


# ── executores (motores da casa, chamados como estão) ──────────────────────────────────────────────────────────
class ExecutorCPU:
    """RapidOCR (PP-OCRv5 mobile, ONNX) com a configuração e a correção decimal de `tools/sei_ocr_reserva`."""
    familia = "rapidocr"

    def __init__(self):
        self._eng = None

    def motor(self) -> str:
        from importlib.metadata import version
        return f"rapidocr@{version('rapidocr')} PP-OCRv5 mobile+latin (CPU) dpi{DPI}"

    def ler(self, pdf: Path, paginas: list[int]) -> dict[int, Leitura]:
        return {n: self.ler_img(img) for n, img, _, _ in _imagens(pdf, paginas)}

    def ler_img(self, img) -> Leitura:
        """Uma página já renderizada (RGB a `DPI`) — o mesmo caminho do `ler` (a bancada da O3.6 usa este)."""
        import numpy as np

        from tools import sei_ocr_reserva as R
        self._eng = self._eng or R.motor_ocr()
        r = self._eng(img)
        itens, linhas = [], []
        scores = list(r.scores) if getattr(r, "scores", None) is not None else []
        for k, (b, t) in enumerate(zip(r.boxes if r.boxes is not None else [], r.txts or [])):
            b = np.asarray(b)
            itens.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
            linhas.append({"texto": t, "bbox": [round(float(b[:, 0].min()), 1), round(float(b[:, 1].min()), 1),
                                                round(float(b[:, 0].max()), 1), round(float(b[:, 1].max()), 1)],
                           "conf": round(float(scores[k]), 4) if k < len(scores) else None})
        return Leitura(R.corrigir(R._linhas(itens)), linhas, img.shape[1], img.shape[0])


class ExecutorTesseract:
    """Tesseract da casa (`sei/ocr_docs._ocr_tesseract`, melhor dos dois pré-processamentos) + bbox por palavra da
    mesma imagem que deu o texto."""
    familia = "tesseract"

    def motor(self) -> str:
        import pytesseract
        return f"tesseract@{pytesseract.get_tesseract_version()} por dpi{DPI}"

    def ler(self, pdf: Path, paginas: list[int]) -> dict[int, Leitura]:
        from compliance_agent.sei import ocr_docs
        if not ocr_docs._tesseract_ok():
            raise ErroInferencia("tesseract indisponível neste nó")
        return {n: self.ler_img(img) for n, img, _, _ in _imagens(pdf, paginas)}

    def ler_img(self, img) -> Leitura:
        import pytesseract

        from compliance_agent.sei import ocr_docs
        # a bbox da MESMA imagem que deu o texto (O8.5): o texto vinha da pré-processada e a bbox da crua, que na
        # página suja vem vazia ⇒ `texto_com_bbox: false` e o efeito recusava (030002/006189/2026 sei:132894206 p3)
        texto, lida, lang = ocr_docs._ocr_tesseract_lido(img, "por")
        d = pytesseract.image_to_data(lida, lang=lang, output_type=pytesseract.Output.DICT)
        linhas = [{"texto": t, "bbox": [d["left"][i], d["top"][i], d["left"][i] + d["width"][i],
                                        d["top"][i] + d["height"][i]], "conf": float(d["conf"][i])}
                  for i, t in enumerate(d["text"]) if str(t).strip()]
        return Leitura(texto, linhas, img.shape[1], img.shape[0])


class ExecutorGPU:
    """Surya 2.5 (vLLM) do it-campo pelo próprio `ocr_gpu_worker` (mesma montagem do texto, mesma regra de erro)."""
    familia = "gpu"

    def __init__(self):
        self._rec = None
        self._w = None

    def _worker(self):
        if self._w is None:
            d = os.environ.get(ENV_WORKER_GPU) or str(A.RAIZ / "deploy" / "itcampo" / "ocr_gpu")
            if d not in sys.path:
                sys.path.insert(0, d)
            import ocr_gpu_worker as W
            import surya_utf8
            surya_utf8.instalar()
            self._w = W
        return self._w

    def motor(self) -> str:
        from importlib.metadata import version
        return f"surya@{version('surya-ocr')} (vLLM, GPU it-campo) dpi{DPI}"

    def ler(self, pdf: Path, paginas: list[int]) -> dict[int, Leitura]:
        out = {}
        with _trava_gpu():
            for n, img, _, _ in _imagens(pdf, paginas):
                try:
                    out[n] = self.ler_img(img)
                except ErroInferencia as e:
                    raise ErroInferencia(f"{pdf.name} p{n}: {e}") from e
        return out

    def ler_img(self, img) -> Leitura:
        return self.ler_imgs([img])[0]

    def ler_imgs(self, imgs: list) -> list[Leitura]:
        """Lote de páginas numa chamada (o vLLM serve várias ao mesmo tempo; a bancada mede 1 × lote). Quem chama
        segura a trava da GPU (o `ler` segura)."""
        from PIL import Image
        W = self._worker()
        if self._rec is None:
            from surya import RecognitionPredictor, SuryaInferenceManager
            self._rec = RecognitionPredictor(SuryaInferenceManager())
        out = []
        for img, res in zip(imgs, self._rec([Image.fromarray(i) for i in imgs])):
            if any(getattr(b, "error", False) and not getattr(b, "html", "") for b in res.blocks):
                raise ErroInferencia("bloco com erro de inferência (Surya devolveu vazio)")
            linhas = [{"texto": W._txt(b.html), "bbox": [round(float(x), 1) for x in (b.bbox or [])],
                       "conf": getattr(b, "confidence", None), "rotulo": getattr(b, "label", None),
                       "pulado": bool(getattr(b, "skipped", False))}
                      for b in sorted(res.blocks, key=lambda b: b.reading_order or 0)]
            # `skipped` = o Surya pulou de propósito (rótulo de figura); vazio SEM skipped = a geração da página inteira
            # foi cortada (max_tokens) e os blocos do fim voltaram sem texto e sem `error` (surya/recognition)
            vazios = sum(1 for ln in linhas if not util(ln["texto"]) and not ln["pulado"]
                         and ln["rotulo"] not in ROTULOS_SEM_TEXTO)
            out.append(Leitura(W._texto(res), linhas, img.shape[1], img.shape[0], vazios))
        return out


@contextlib.contextmanager
def _trava_gpu():
    """Uma leitura por vez na GPU deste nó (a mesma placa serve as sessões SEI e o lote)."""
    import fcntl
    caminho = Path(os.environ.get(ENV_TRAVA_GPU) or Path.home() / "jfn-gpu" / "ocr" / "e5.lock")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _gpu_disponivel() -> bool:
    try:
        from importlib.util import find_spec
        return find_spec("surya") is not None
    except (ImportError, ValueError):
        return False


def escolher(no: str | None = None) -> tuple[Executor, Executor | None]:
    """(principal, segundo motor para a página vazia). Forçado por `JFN_OCR_EXECUTOR`; senão GPU só no it-campo com
    o Surya importável; senão CPU (a volta declarada)."""
    forcado = (os.environ.get(ENV_EXECUTOR) or "").strip().lower()
    no = no or os.environ.get("JFN_NO") or socket.gethostname()
    if forcado == "tesseract":
        return ExecutorTesseract(), ExecutorCPU()
    if forcado == "gpu" or (not forcado and "itcampo" in str(no).replace("-", "") and _gpu_disponivel()):
        return ExecutorGPU(), ExecutorCPU()
    return ExecutorCPU(), ExecutorTesseract()


# ── OCR de um documento (puro sobre os executores) ─────────────────────────────────────────────────────────────
def _ocr_lote(pdf: Path, alvo: list[int], principal: Executor, m1: str, segundo: Executor | None,
              cache: CacheImagem | None) -> tuple[dict[int, dict], dict[int, str], dict[int, dict]]:
    """Um lote de páginas escaneadas (até `MAX_PAGINAS`): (estado por página, img_sha, dedup_de)."""
    hashes = hashes_imagem(pdf, alvo)
    lidas, dedup = _ler_dedup(principal, m1, pdf, alvo, hashes, cache, pdf.name)
    pags: dict[int, dict] = {}
    vazias: list[int] = []
    incompletas: dict[int, Leitura] = {}
    for n in alvo:
        le = lidas.get(n)
        if le is None:
            raise ErroInferencia(f"{pdf.name}: o motor não devolveu a página {n}")
        if util(le.texto) and not le.blocos_vazios:
            pags[n] = {"estado": TEXTO, "motor": m1, "texto": le.texto, "linhas": le.linhas, "largura": le.largura,
                       "altura": le.altura}
        else:
            vazias.append(n)                          # vazia OU incompleta (bloco de texto sem texto): 2º motor
            if util(le.texto):
                incompletas[n] = le
    if vazias and segundo is not None and segundo.familia != principal.familia:
        m2 = segundo.motor()
        relidas, dedup2 = _ler_dedup(segundo, m2, pdf, vazias, hashes, cache, pdf.name)
        for n in vazias:
            le = relidas.get(n)
            if le is None:                            # achado 1.9: o 2º não leu ⇒ não é "conferida por dois"
                raise ErroInferencia(f"{pdf.name}: o 2º motor ({m2}) não devolveu a página {n}")
            if util(le.texto) and not le.blocos_vazios:
                pags[n] = {"estado": TEXTO, "motor": m2, "texto": le.texto, "linhas": le.linhas,
                           "largura": le.largura, "altura": le.altura,
                           "primeiro_incompleto" if n in incompletas else "primeiro_vazio": m1}
                if n in incompletas:
                    pags[n]["blocos_vazios_do_primeiro"] = incompletas[n].blocos_vazios
                if n in dedup2:
                    dedup[n] = dedup2[n]
            elif n in incompletas:
                # os dois incompletos/vazios: o que o 1º leu não vira "feito" — fica pendente, visível
                pags[n] = {"estado": VAZIA_PENDENTE, "motor": m1, "texto": "", "linhas": [],
                           "motivo": f"leitura incompleta ({incompletas[n].blocos_vazios} bloco(s) de texto vazios) "
                                     f"e o 2º motor não leu a página"}
                dedup.pop(n, None)
            else:
                pags[n] = {"estado": VAZIA_CONFERIDA, "motor": m1, "conferido_por": m2, "texto": "", "linhas": []}
                dedup.pop(n, None)
    else:
        for n in vazias:
            pags[n] = {"estado": VAZIA_PENDENTE, "motor": m1, "texto": "", "linhas": [],
                       "motivo": "incompleta (bloco de texto vazio) no único motor disponível" if n in incompletas
                       else "vazia no único motor disponível: precisa de leitura de outra família"}
            dedup.pop(n, None)
    return pags, hashes, dedup


def ocr_documento(pdf: Path, e4: dict, principal: Executor, segundo: Executor | None,
                  cache: CacheImagem | None = None) -> dict:
    """Lê SÓ as páginas escaneadas do E4 e compõe o texto sem tocar no nativo. Devolve o conteúdo do lateral.
    Página com imagem idêntica (no documento ou no `cache`, mesmo motor@versão) não é relida (regra 4)."""
    nativas = {p["pagina"]: p for p in e4["paginas"]}
    todas = [p["pagina"] for p in e4["paginas"] if p["perfil"] == T.ESCANEADA]
    if not todas:
        raise ErroPermanente("documento sem página escaneada: nada a fazer no E5 (o E4 manda direto ao E7)")
    # achado 1.10: o teto é o tamanho do LOTE, não um corte. Antes, a página acima dele ficava `vazia_pendente` ⇒ nada
    # no PG, `falhou_efeito` terminal sem evento e o E7 preso em `ocr_pendente`. Lote a lote, as imagens do anterior
    # são soltas (memória limitada) e cada página segue rasterizada uma vez (hash, 1º e 2º motor na mesma imagem)
    m1 = principal.motor()
    pags: dict[int, dict] = {}
    hashes: dict[int, str] = {}
    dedup: dict[int, dict] = {}
    for i in range(0, len(todas), MAX_PAGINAS):
        if i and _RASTER is not None:
            _RASTER.soltar_imagens()
        p, h, d = _ocr_lote(pdf, todas[i:i + MAX_PAGINAS], principal, m1, segundo, cache)
        pags.update(p)
        hashes.update(h)
        dedup.update(d)
    for n, v in pags.items():
        if n in hashes:
            v["img_sha"] = hashes[n]
        v["perfil"] = T.ESCANEADA
        if "pagina" in dedup.get(n, {}) and v["estado"] == TEXTO:
            v["dedup_de"] = dedup[n]                  # só o reuso DENTRO do documento vai ao lateral (determinístico)
    cache_reusadas = sorted(n for n, d in dedup.items() if "cache" in d and pags[n]["estado"] == TEXTO)
    compostas = []
    for n in sorted(nativas):
        nat = nativas[n].get("texto") or ""
        o = pags.get(n)
        if o and o["estado"] == TEXTO:
            compostas.append(nat.rstrip() + ("\n" if nat.strip() else "") + o["texto"] if nat.strip() else o["texto"])
        else:
            compostas.append(nat)
    composto = T.QUEBRA.join(compostas)
    return {"paginas": {str(n): v for n, v in sorted(pags.items())}, "alvo": todas, "dpi": DPI,
            "texto_composto": composto, "texto_sha": T.sha256_texto(composto), "chars": len(composto.strip()),
            # O3.6: as páginas compostas, uma a uma — o texto NATIVO pode trazer `\f` (o PyMuPDF emite em 5,5% dos
            # mistos medidos), e partir o composto pelo separador desalinhava as páginas e reprovava o efeito
            "compostas": compostas,
            "motores": sorted({v["motor"] for v in pags.values()} | {v["conferido_por"] for v in pags.values()
                                                                      if v.get("conferido_por")}),
            "pendentes": [n for n, v in pags.items() if v["estado"] == VAZIA_PENDENTE],
            "dedup": {"paginas": len(todas), "imagens_distintas": len(set(hashes.values())),
                      "reusadas": sorted(n for n, v in pags.items() if v.get("dedup_de"))},
            # FORA do lateral (o `_handler` tira): de onde veio a leitura reusada do cache depende do estado do cache,
            # e o lateral da mesma versão tem de sair igual na reexecução (o sha dele está no PG)
            "cache_reusadas": cache_reusadas}


# ── onde está o PDF ────────────────────────────────────────────────────────────────────────────────────────────
def raizes_legado() -> list[Path]:
    """Onde o PDF da fila legada pode estar, na ordem: o cache da VM-1, o morno da VM-2, o disco e o HD do it-campo."""
    extra = [Path(p) for p in (os.environ.get(ENV_RAIZES) or "").split(":") if p]
    return extra + [A.RAIZ / "data" / "sei_cache", Path.home() / "arquivo_frio" / "sei_cache",
                    Path.home() / "arquivo_frio" / "sei_pdfs", Path("/mnt/c/JFN-Arquivo/sei_pdfs"),
                    Path("/mnt/d/JFN-Frio/sei/pdfs_escaneados"), Path("/mnt/d/JFN-Frio/sei/integras_cache")]


def localizar_pdf(con, processo: str, doc_id: str, sha: str, payload: dict) -> Path:
    """O binário do E3 (pela aquisição) ou, na fila legada, `rel` (`integra_<tag>/NNN.pdf`) nas raízes conhecidas e,
    não achando, pela porta única (`armazenamento.obter`) antes de concluir que não existe."""
    if not payload.get("rel"):
        return T.localizar_binario(con, processo, doc_id, sha, payload.get("arquivo"))
    rel = str(payload["rel"])
    if ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ErroPermanente(f"rel inválido: {rel!r}")
    for raiz in raizes_legado():
        p = raiz / rel
        if p.is_file():
            if sha and T.sha256_arquivo(p) != sha:
                raise ErroPermanente(f"{rel}: sha256 diferente do declarado na migração")
            return p
    from compliance_agent import armazenamento
    try:
        return armazenamento.obter(A.RAIZ / "data" / "sei_cache" / rel)
    except FileNotFoundError as e:
        raise RuntimeError(f"{rel}: PDF não está em nenhuma raiz nem na porta única (HD desligado?)") from e


def e4_do(con, processo: str, doc_id: str, sha: str, pdf: Path, raiz: Path | None) -> dict:
    """O lateral do E4 desta versão; sem ele (fila legada, antes da esteira), extrai agora — declarado `e4_implicito`."""
    lat = T.ler_lateral(T.caminho_lateral(processo, doc_id, sha, "e4", raiz))
    if lat is not None:
        return lat[0] | {"e4_implicito": False}
    return T.extrair(pdf) | {"e4_implicito": True}


# ── PG ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# a versão do ESTÁGIO entra na chave (texto_ocr_002): reprocessar com lógica nova grava linha nova (histórico), nunca
# DO NOTHING sobre a linha da versão velha
_INS_TR = ("INSERT INTO transformacao(processo, doc_id, tipo, entrada_sha, saida_sha, motor, versao_motor, parametros, "
           "versao_estagio) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
           "ON CONFLICT ON CONSTRAINT transformacao_unica DO NOTHING")


def transformacao_da_versao(con, processo: str, doc_id: str, entrada_sha: str, versao: str) -> dict | None:
    """A transformação `ocr` desta entrada gravada pela MESMA versão do estágio (a conferência do efeito)."""
    r = con.execute("SELECT saida_sha, motor, versao_motor, parametros FROM transformacao WHERE processo = %s AND "
                    "doc_id = %s AND tipo = %s AND entrada_sha = %s AND versao_estagio = %s ORDER BY id DESC LIMIT 1",
                    (processo, doc_id, TIPO_TRANSFORMACAO, entrada_sha, versao)).fetchone()
    return None if r is None else {"saida_sha": r[0], "motor": r[1], "versao_motor": r[2], "parametros": r[3]}


def registrar(con, processo: str, doc_id: str, sha: str, ocr: dict, lateral: Path, lateral_sha: str,
              ctx: Contexto) -> dict:
    por_estado: dict[str, list[int]] = {}
    for n, v in ocr["paginas"].items():
        por_estado.setdefault(v["estado"], []).append(int(n))
    principal = ocr["paginas"][str(ocr["alvo"][0])]["motor"]
    motor, _, versao = principal.partition("@")
    params = {"paginas": por_estado, "motores": ocr["motores"], "lateral": str(lateral), "lateral_sha": lateral_sha,
              "dpi": DPI, "versao": VERSAO, "job": ctx.chave, "ficha": ctx.ficha}
    with con.transaction():
        con.execute(_INS_TR, (processo, doc_id, TIPO_TRANSFORMACAO, sha, ocr["texto_sha"], motor, versao,
                              json.dumps(params, ensure_ascii=False), VERSAO))
        con.execute(T._INS_VER, (processo, doc_id, ocr["texto_sha"], ocr["chars"], ORIGEM, principal,
                                 time.strftime("%Y-%m-%d %H:%M:%S")))
    return {"processo": processo, "doc_id": doc_id, "entrada_sha": sha, "texto_sha": ocr["texto_sha"],
            "paginas": por_estado, "motores": ocr["motores"], "lateral": str(lateral), "chars": ocr["chars"],
            "versao": VERSAO, "gravado": True}


def _handler(payload: dict, ctx: Contexto) -> Resultado:
    processo, doc_id, sha = T.alvo_do(payload, ctx)
    raiz = Path(payload["raiz_texto"]) if payload.get("raiz_texto") else None
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        pdf = localizar_pdf(con, processo, doc_id, sha, payload)
        sha = sha or T.sha256_arquivo(pdf)                    # item legado: a versão é o arquivo achado
        e4 = e4_do(con, processo, doc_id, sha, pdf, raiz)
        principal, segundo = obter_executores(ctx.no)
        cache = CacheImagem((raiz or T.raiz_texto()) / PASTA_DEDUP)
        with rasterizacao_unica() as ras:
            ocr = ocr_documento(pdf, e4, principal, segundo, cache)
        rasterizacao = ras.resumo()
        cache_reusadas = ocr.pop("cache_reusadas")
        lat = T.caminho_lateral(processo, doc_id, sha, "e5", raiz)
        nat = {str(p["pagina"]): p.get("texto") or "" for p in e4["paginas"]}
        lat_sha = T.gravar_lateral(lat, {"versao": VERSAO, "processo": processo, "doc_id": doc_id, "entrada_sha": sha,
                                         "e4_texto_sha": e4.get("texto_sha"), "e4_implicito": e4["e4_implicito"],
                                         "nativo": nat, "perfis": {str(p["pagina"]): p["perfil"]
                                                                   for p in e4["paginas"]}, **ocr})
        if ocr["pendentes"]:
            # vazio NUNCA vira feito: nada no PG; o efeito falha e o job volta (ou vai à quarentena, visível)
            ef = {"processo": processo, "doc_id": doc_id, "entrada_sha": sha, "texto_sha": ocr["texto_sha"],
                  "pendentes": ocr["pendentes"], "lateral": str(lat), "gravado": False, "versao": VERSAO,
                  **rasterizacao}
            return Resultado(efeito=ef, eventos=[])
        ef = registrar(con, processo, doc_id, sha, ocr, lat, lat_sha, ctx)
    finally:
        con.close()
    ef["pendentes"] = []
    ef["cache_reusadas"] = cache_reusadas
    ef.update(rasterizacao)
    k = f"{processo}|{doc_id}"
    det = {"sha256": sha, "texto_sha": ocr["texto_sha"]}
    eventos = [{"fonte": "ocr", "tipo": "texto_novo", "chave": k, "detalhe": det}]
    from compliance_agent.sei import ocr_ia_prova as P
    # SEMPRE vai ao E6 (O8.5, frente B1): a porta do E8 exige a conferência do E6 de todo documento com OCR; só com
    # número crítico, o OCR sem número nunca era conferido e o processo ficava barrado para sempre (330002/028372/2026
    # sei:142180617). Sem número, o E6 grava `confirmado` com 0 números (sem abrir o PDF)
    n_num = sum(len(P.extrair(v["texto"])) for v in ocr["paginas"].values() if v["estado"] == TEXTO)
    eventos.append({"fonte": "ocr", "tipo": "numero_ia", "chave": k, "detalhe": det | {"numeros": n_num}})
    # 26/11/2026: sem `ocr/terminado` — o E7 nascia dele ao mesmo tempo que o E6 e arquivava o original ANTES de o E6
    # conferir o número no PDF («binário não está no disco»); o E7 agora nasce da conclusão do E6 (confirmar_ocr/*)
    return Resultado(efeito=ef, eventos=eventos)


def obter_executores(no: str) -> tuple[Executor, Executor | None]:
    """Injetável nos testes (o real escolhe pelo nó: GPU no it-campo, CPU no resto)."""
    return escolher(no)


def conferir(con, ef: dict) -> dict:
    if not ef.get("gravado"):
        return {"ok": False, "motivo": f"páginas vazias sem 2ª leitura: {ef.get('pendentes')} (vazio não é feito)"}
    t = transformacao_da_versao(con, ef["processo"], ef["doc_id"], ef["entrada_sha"], ef.get("versao") or VERSAO)
    if t is None:
        return {"ok": False, "motivo": "transformacao ocr desta versão do estágio não está no PG"}
    lat = T.ler_lateral(Path(ef["lateral"]))
    if lat is None:
        return {"ok": False, "motivo": "lateral do E5 ausente"}
    d, lat_sha = lat
    pags = d.get("paginas") or {}
    perfis = d.get("perfis") or {}
    nativo = d.get("nativo") or {}
    alvo = [str(n) for n in d.get("alvo") or []]
    compostas = d.get("compostas")
    if compostas is None:                                    # lateral e5-1 (antes da O3.6)
        compostas = (d.get("texto_composto") or "").split(T.QUEBRA)
    c = {"lateral_sha": lat_sha == (t["parametros"] or {}).get("lateral_sha"),
         "saida_sha": t["saida_sha"] == ef["texto_sha"] == T.sha256_texto(d.get("texto_composto") or ""),
         "todas_resolvidas": bool(alvo) and all((pags.get(n) or {}).get("estado") in (TEXTO, VAZIA_CONFERIDA)
                                                for n in alvo),
         "texto_com_bbox": all(util(v["texto"]) and v.get("linhas") and v.get("motor") for v in pags.values()
                               if v["estado"] == TEXTO),
         "vazia_com_dois_motores": all(v.get("conferido_por") and v["conferido_por"] != v["motor"]
                                       for v in pags.values() if v["estado"] == VAZIA_CONFERIDA),
         "nativa_nao_lida": all(perfis.get(n) == T.ESCANEADA for n in pags),
         "img_sha_por_pagina": all(len(v.get("img_sha") or "") == 64 for v in pags.values()),
         "dedup_coerente": all(_dedup_ok(pags, v) for v in pags.values() if v.get("dedup_de")),
         "nativo_preservado": len(compostas) == len(nativo) and all(
             compostas[int(n) - 1].startswith((nativo[n] or "").rstrip()) for n in nativo),
         "compostas_formam_o_texto": T.QUEBRA.join(compostas) == (d.get("texto_composto") or "")}
    c["versao_texto"] = con.execute("SELECT 1 FROM versoes WHERE processo = %s AND doc_id = %s AND sha256 = %s AND "
                                    "hash_de = 'texto' AND origem = %s", (ef["processo"], ef["doc_id"],
                                                                         ef["texto_sha"], ORIGEM)).fetchone() is not None
    c["ok"] = all(c.values())
    return c


def _dedup_ok(pags: dict, v: dict) -> bool:
    """Reuso de página do mesmo documento: a origem tem a MESMA imagem e o mesmo texto (o reuso do cache não vai ao
    lateral; o registro do cache é conferido na leitura: imagem e motor iguais aos pedidos)."""
    o = pags.get(str(v["dedup_de"].get("pagina"))) or {}
    return o.get("img_sha") == v.get("img_sha") and o.get("texto") == v.get("texto")


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    con = T.conectar(payload.get("dsn"), payload.get("esquema"))
    try:
        c = conferir(con, resultado.efeito)
    finally:
        con.close()
    resultado.efeito["conferencia"] = c
    return bool(c["ok"])


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["cpu_pesado"], prioridade=55,
                  volta={"nos": ["vm2"], "nota": "GPU (Surya) no it-campo; sem ele, RapidOCR na CPU da VM-2 (§3.5 b)"})
NOS = ["itcampo"]                                  # nó preferido do job (payload.nos); a volta acima é a VM-2


# ── ensaio: páginas/min de um executor sobre PDFs reais (cópias), sem PG ────────────────────────────────────────
def ensaio(pdfs: list[Path], n_paginas: int, executor: Executor) -> dict:
    """Lê até `n_paginas` páginas ESCANEADAS (perfil do E4) dos PDFs dados com o executor e mede o tempo. Não grava
    nada no PG; o texto fica só no resultado (contagens), nunca no log."""
    alvo: list[tuple[Path, int]] = []
    for p in pdfs:
        ex = T.extrair(p)
        alvo += [(p, n) for n in ex["escaneadas"]]
        if len(alvo) >= n_paginas:
            break
    alvo = alvo[:n_paginas]
    motor = executor.motor()
    t0 = time.monotonic()
    uteis, vazias, chars = 0, 0, 0
    por_pdf: dict[Path, list[int]] = {}
    for p, n in alvo:
        por_pdf.setdefault(p, []).append(n)
    for p, ns in por_pdf.items():
        for le in executor.ler(p, ns).values():
            if util(le.texto):
                uteis += 1
                chars += len(le.texto.strip())
            else:
                vazias += 1
    s = time.monotonic() - t0
    return {"motor": motor, "paginas": len(alvo), "pdfs": len(por_pdf), "uteis": uteis, "vazias": vazias,
            "chars": chars, "segundos": round(s, 1), "s_por_pagina": round(s / max(len(alvo), 1), 2),
            "paginas_por_min": round(60 * len(alvo) / s, 2) if s else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E5 ocr (O3.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensaio")
    e.add_argument("--pdf", action="append", required=True)
    e.add_argument("--paginas", type=int, default=20)
    e.add_argument("--executor", choices=["cpu", "gpu", "tesseract"], default="cpu")
    e.add_argument("--saida")
    a = ap.parse_args(argv)
    ex = {"cpu": ExecutorCPU, "gpu": ExecutorGPU, "tesseract": ExecutorTesseract}[a.executor]()
    r = ensaio([Path(p) for p in a.pdf], a.paginas, ex) | {"no": socket.gethostname(),
                                                           "em": time.strftime("%Y-%m-%d %H:%M:%S%z")}
    if a.saida:
        Path(a.saida).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
