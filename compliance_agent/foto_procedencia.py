# -*- coding: utf-8 -*-
"""PROCEDÊNCIA da foto de execução: registro de campo ou imagem baixada da internet?

PEDIDO DO DONO (2026-07-30), verbatim: "criar um detector de imagens pra saber se as fotos de
execucao dos contratos vem do google e so foram falsamente colocadas la."

O QUE JÁ EXISTE E O QUE NÃO EXISTE. `compliance_agent/foto_medicao.py` resolve o vizinho — a MESMA
foto lastreando dois processos diferentes (reciclagem, por dHash, offline) — e está ligado
(`reporting/capitulos_dossie.py:415`). O que não existia é isto: a foto é de campo, ou é uma imagem
de catálogo/notícia/banco de imagens que alguém colou no relatório?

DUAS RESTRIÇÕES QUE A CASA JÁ PAGOU PARA APRENDER, e que este módulo NÃO pode violar:

  1. **EXIF ausente NÃO é indício de fraude.** Está escrito em `foto_medicao.py`: quase todo anexo
     perde EXIF ao virar PDF e ser reextraído. Um detector que acenda por falta de EXIF acende em
     quase tudo — seria o P1 de novo (acusava 71% dos certames). Aqui, a ausência de campos de câmera
     **nunca pontua sozinha**: só compõe, e só quando há OUTRO sinal.
  2. **A foto vem DENTRO da página do relatório fotográfico.** Hashear o arquivo compara o MODELO da
     página, não a foto — foi o que fez "0 recicladas em 2.641 fotos" medir a coisa errada. Por isso
     este módulo aceita `caixa=(x0,y0,x1,y1)` e analisa a REGIÃO recortada; quem chama já tem o
     recorte por `foto_medicao._regioes_foto`.

DESENHO: grau por ACÚMULO de fatores, nunca por fator único (a lição do "ninho é a mesma SALA, não o
mesmo prédio"). Cada sinal declara o que viu; o veredito soma. `INDISPONÍVEL ≠ 0`: sem conseguir ler
a imagem, o resultado é `nao_avaliavel`, não "limpo".

CAMADA 2 (busca reversa real — Google/Bing/TinEye) fica DESLIGADA por padrão e vive em
`buscar_reversa`, que exige um callable injetado. Motivo: são serviços pagos ou bloqueados, e a regra
da casa é dura — **nunca assumir free tier**, chave com billing cobra. O detector tem de ser útil sem
ela, e é.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Dimensões que denunciam DOWNLOAD, não captura. Câmera não produz 1200x630 (card de rede social)
# nem 1024x768 exato com frequência; CDN e CMS produzem, o dia inteiro.
_TAMANHOS_WEB = {
    (1200, 630), (1200, 628), (1080, 1080), (1024, 768), (800, 600), (640, 480),
    (1280, 720), (1920, 1080), (600, 400), (960, 540), (728, 90), (300, 250),
}
_LARGURAS_CDN = {320, 480, 640, 720, 750, 828, 1080, 1200, 1920}

# Texto que só aparece em imagem de terceiro. OCR do acervo já entrega o texto da página.
# ⚠️ O SÍMBOLO `©` SOZINHO SAIU DAQUI, e a medição é o motivo. Varrendo os 7.318 arquivos de texto
# dos 122 processos que têm foto, a regex acendeu 8 vezes — TODAS pelo `©` isolado, e nenhuma era
# imagem de terceiro: eram nota fiscal, certidão negativa de falência e rodapé de software. Marca
# fraca casada contra texto integral é precisamente a falha do P1 (acusava 71% dos certames por
# regex em edital inteiro). Ficam só os nomes que não aparecem por acaso num processo administrativo.
_MARCAS = re.compile(
    r"shutterstock|getty\s*images|istockphoto|adobe\s*stock|dreamstime|123rf|alamy|depositphotos|"
    r"freepik|pexels|unsplash|banco\s+de\s+imagens|imagem\s+meramente\s+ilustrativa|"
    r"reprodu[cç][aã]o\s*/|divulga[cç][aã]o\s*/|foto:\s*(?:ag[eê]ncia|reuters|afp|ap\b)",
    re.I)

# Campos que só uma CÂMERA grava. A ausência não acusa; a PRESENÇA inocenta (é o uso correto).
_CAMPOS_CAMERA = ("Make", "Model", "LensModel", "LensInfo", "ExposureTime", "FNumber",
                  "ISO", "FocalLength", "DateTimeOriginal", "ShutterSpeedValue")


def _exiftool(caminho: Path) -> dict | None:
    """Metadados via ExifTool. `None` = ferramenta ausente (INDISPONÍVEL), `{}` = arquivo sem nada."""
    if not shutil.which("exiftool"):
        return None
    try:
        saida = subprocess.run(["exiftool", "-json", "-n", str(caminho)],
                               capture_output=True, text=True, timeout=30).stdout
        dados = json.loads(saida or "[]")
        return dados[0] if dados else {}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.debug("exiftool falhou em %s: %s", caminho, exc)
        return None


def _tabelas_quantizacao(caminho: Path) -> dict:
    """Assinatura do recompressor.

    Cada codificador tem seu 'ladder' de qualidade. Câmera grava com tabelas próprias do fabricante;
    imagem servida por CDN passou por um re-encode de biblioteca (libjpeg/mozjpeg/Pillow) e carrega a
    tabela DESSA biblioteca. Não identifica a origem sozinho — mas 'tabela de biblioteca' somada a
    'dimensão de web' e 'zero campo de câmera' é um conjunto que registro de campo não produz.
    """
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            q = getattr(im, "quantization", None) or {}
            if not q:
                return {"tem": False}
            # soma dos coeficientes = proxy estável do nível de qualidade do re-encode
            tot = {k: sum(v) for k, v in q.items()}
            return {"tem": True, "tabelas": len(q), "soma": tot,
                    "assinatura": "-".join(str(tot[k]) for k in sorted(tot))}
    except (OSError, ValueError) as exc:   # PIL: UnidentifiedImageError herda de OSError
        logger.debug("quantização ilegível em %s: %s", caminho, exc)
        return {"tem": False, "erro": str(exc)[:60]}


def _dimensoes(caminho: Path, caixa=None) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            if caixa:
                x0, y0, x1, y1 = caixa
                return (abs(x1 - x0), abs(y1 - y0))
            return im.size
    except (OSError, ValueError) as exc:   # PIL: UnidentifiedImageError herda de OSError
        logger.debug("dimensões ilegíveis em %s: %s", caminho, exc)
        return None


def analisar(caminho, *, caixa=None, texto_da_pagina: str = "",
             corpus_web: dict | None = None) -> dict:
    """Sinais de procedência de UMA foto. Grau por acúmulo; nenhum sinal acusa sozinho.

    `caixa`     - região recortada da foto DENTRO da página do relatório (ver restrição 2 no topo).
    `texto_da_pagina` - OCR já disponível no acervo; é onde a marca d'água aparece.
    `corpus_web` - {dhash: procedência} das imagens que a casa obteve legitimamente da web
                   (as verificações de fachada por Static View). Bater com uma delas é achado
                   OBJETIVO e de custo zero.
    """
    p = Path(caminho)
    out: dict = {"arquivo": p.name, "sinais": [], "grau": "nao_avaliavel", "limitacoes": []}
    if not p.exists():
        out["limitacoes"].append("arquivo ausente")
        return out

    dim = _dimensoes(p, caixa)
    if dim is None:
        out["limitacoes"].append("imagem ilegível — INDISPONÍVEL, não 'sem indício'")
        return out
    out["dimensoes"] = dim

    # ── sinal 1: dimensão de web ────────────────────────────────────────────────────────────────
    if dim in _TAMANHOS_WEB:
        out["sinais"].append({"tipo": "dimensao_de_web", "peso": 2,
                              "detalhe": f"{dim[0]}x{dim[1]} é medida canônica de CMS/rede social, "
                                         "não de sensor de câmera"})
    elif dim[0] in _LARGURAS_CDN and dim[0] < 1300:
        out["sinais"].append({"tipo": "largura_de_cdn", "peso": 1,
                              "detalhe": f"largura {dim[0]}px é degrau típico de redimensionador de CDN"})

    # ── sinal 2: marca d'água / crédito de terceiro no texto da página ──────────────────────────
    m = _MARCAS.search(texto_da_pagina or "")
    if m:
        out["sinais"].append({"tipo": "marca_de_banco_de_imagens", "peso": 3,
                              "detalhe": f"a página cita {m.group(0)!r} — crédito de terceiro sobre "
                                         "material que deveria ser registro próprio de execução"})

    # ── sinal 3: metadados ──────────────────────────────────────────────────────────────────────
    meta = _exiftool(p)
    if meta is None:
        out["limitacoes"].append("exiftool ausente — camada de metadado não avaliada")
    else:
        tem_camera = [c for c in _CAMPOS_CAMERA if meta.get(c) not in (None, "")]
        out["campos_de_camera"] = tem_camera
        if tem_camera:
            # PRESENÇA inocenta: é o uso correto do sinal, e o inverso é que é proibido
            out["sinais"].append({"tipo": "tem_metadado_de_camera", "peso": -3,
                                  "detalhe": f"campos de câmera presentes ({', '.join(tem_camera[:4])}) "
                                             "— compatível com captura em campo"})
        else:
            out["limitacoes"].append(
                "sem campos de câmera — NÃO pontua sozinho: anexo de processo perde EXIF ao virar PDF "
                "e ser reextraído (limitação conhecida, registrada em foto_medicao)")
        soft = str(meta.get("Software") or meta.get("ProcessingSoftware") or "")
        if re.search(r"photoshop|gimp|canva|paint|snagit|screenshot", soft, re.I):
            out["sinais"].append({"tipo": "software_de_edicao", "peso": 2,
                                  "detalhe": f"gravada por {soft!r} — peça editada, não capturada"})

    # ── sinal 4: assinatura de recompressão ─────────────────────────────────────────────────────
    q = _tabelas_quantizacao(p)
    out["quantizacao"] = q
    # ⚠️ Este sinal COMPÕE, nunca INICIA — e a primeira versão deste módulo errou exatamente aqui.
    # Ele acendia sempre que havia quantização e nenhum campo de câmera, e como o acervo perde EXIF
    # ao virar PDF e ser reextraído, uma foto perfeitamente comum saía com grau `fraco`. Marcar a
    # maior parte da base é o erro do P1 (acusava 71% dos certames) e do perfil de laranja (55%).
    # Agora ele só entra na conta se OUTRO sinal positivo já existe: sozinho, "não tem EXIF" não diz
    # nada sobre procedência.
    _ja_tem_positivo = any(s["peso"] > 0 for s in out["sinais"])
    if q.get("tem") and not out.get("campos_de_camera"):
        out["sinais"].append({"tipo": "recompressao_sem_camera",
                              "peso": 1 if _ja_tem_positivo else 0,
                              "detalhe": f"assinatura de quantização {q.get('assinatura')} sem campo de "
                                         "câmera — " + ("reforça os demais sinais" if _ja_tem_positivo
                                                        else "ISOLADO não vale nada (o acervo perde EXIF "
                                                             "na conversão); registrado como contexto")})

    # ── sinal 5: bate com imagem que a casa BAIXOU da web ───────────────────────────────────────
    if corpus_web:
        from compliance_agent.foto_medicao import dhash, distancia
        h = dhash(p)
        if h is not None:
            for hw, proc in corpus_web.items():
                if distancia(h, int(hw)) <= 6:
                    out["sinais"].append({"tipo": "igual_a_imagem_da_web", "peso": 5,
                                          "detalhe": f"perceptualmente idêntica a imagem obtida da web "
                                                     f"({proc}) — achado OBJETIVO"})
                    break

    positivos = sum(s["peso"] for s in out["sinais"] if s["peso"] > 0)
    negativos = sum(s["peso"] for s in out["sinais"] if s["peso"] < 0)
    total = positivos + negativos
    out["pontuacao"] = total
    if any(s["tipo"] in ("igual_a_imagem_da_web", "marca_de_banco_de_imagens") for s in out["sinais"]):
        out["grau"] = "forte"
    elif total >= 3:
        out["grau"] = "medio"
    elif total >= 1:
        out["grau"] = "fraco"
    elif out["sinais"]:
        out["grau"] = "descartado"
    out["_nota"] = ("Indício de procedência a verificar, nunca prova. Ausência de EXIF é LIMITAÇÃO, "
                    "não achado. Grau por acúmulo de fatores; fator isolado não sustenta.")
    return out


def buscar_reversa(caminho, *, buscar=None) -> dict:
    """CAMADA 2 — busca reversa real, DESLIGADA por padrão.

    Só roda com um `buscar(caminho) -> list[dict]` injetado pelo chamador. Não há provedor embutido, e
    é deliberado: Google/Bing Visual Search e TinEye são pagos ou bloqueados, e a regra da casa é
    **nunca assumir free tier** — chave com billing cobra, mesmo com crédito de trial. Sem o callable,
    devolve `INDISPONIVEL` com motivo, e o veredito da camada 1 continua publicável sozinho.
    """
    if buscar is None:
        return {"status": "INDISPONIVEL", "motivo":
                "busca reversa não configurada (serviço pago/bloqueado) — camada 1 é offline e basta "
                "para publicar; ligar exige decisão do dono sobre custo, com teto e kill-switch"}
    try:
        achados = buscar(str(caminho)) or []
    except Exception as exc:  # noqa: BLE001
        return {"status": "INDISPONIVEL", "motivo": f"provedor falhou: {str(exc)[:80]}"}
    return {"status": "ok", "n": len(achados), "achados": achados[:10]}
