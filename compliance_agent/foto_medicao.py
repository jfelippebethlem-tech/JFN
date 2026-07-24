# -*- coding: utf-8 -*-
"""FOTOS DE MEDIÇÃO — a foto que lastreia o atesto é reciclada? bate com o objeto? (plano #4, item 1.2)

Decisão do dono (2026-07-24): **nada pago**. Isso não custou nada ao poder de fogo, porque o achado mais
grave desta família é OBJETIVO e não precisa de IA nenhuma:

  **A MESMA foto lastreando a medição de DOIS processos diferentes.** Reciclar registro fotográfico é a
  forma clássica de "comprovar" execução que não houve. O hash perceptual (dHash) reconhece a mesma
  imagem mesmo depois de recompressão, redimensionamento e mudança de formato — 100% offline, sem custo,
  sem modelo. É evidência verificável por qualquer auditor: as duas fotos ficam apontadas lado a lado.

A camada SUBJETIVA (a foto corresponde ao objeto contratado?) exige visão, e entra por CALLABLE INJETADO
(`descrever`): em produção, um VLM **local e gratuito** — moondream2 (≈1,9 B) ou SmolVLM (256 M/500 M) em
llama.cpp, que a VM-2 já roda para o Massare. Sem `descrever` a camada fica `pendente_reprocessar` —
nunca "verde" por omissão (a análise não rodou; ausência de parecer ≠ regularidade).

HONESTIDADE: EXIF ausente NÃO é indício de fraude (quase todo anexo de processo perde EXIF ao ser
convertido para PDF e reextraído) — é registrado como limitação, não como achado. Foto repetida DENTRO do
mesmo processo é anexo duplicado, não reciclagem. Cada achado cita os arquivos e processos que o sustentam.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LIMIAR_IGUAL = 6        # distância de Hamming (de 64 bits) até a qual duas fotos são "a mesma"
LADO_MINIMO = 200       # abaixo disso é logo/ícone/carimbo, não registro de execução
# desvio-padrão da luminância abaixo do qual a imagem é "lisa" demais para ser registro de execução.
# CALIBRADO no arquivo SEI real (2026-07-24): página em branco = 0.00; as fotos de medição reais vão de
# 21 a 95 (mediana 40). O corte em 8 fica na terra de ninguém entre os dois — não descarta foto legítima.
DESVIO_MINIMO = 8.0
_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_LADO = 9               # dHash: 9×8 pixels → 64 comparações horizontais


def dhash(caminho) -> int | None:
    """Hash perceptual (dHash, 64 bits) — sobrevive a recompressão/redimensionamento, ao contrário do
    md5 do arquivo. None quando o arquivo não é imagem legível (degrada honesto, não quebra o sweep)."""
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            g = im.convert("L").resize((_LADO, 8))
            # get_flattened_data é a API nova (Pillow ≥11); getdata sai na 14. Aceita as duas.
            px = list(g.get_flattened_data() if hasattr(g, "get_flattened_data") else g.getdata())
    except Exception as e:  # noqa: BLE001 — arquivo corrompido/truncado/formato exótico: ignora a foto
        logger.debug("dhash falhou (%s): %s", caminho, e)
        return None
    h = 0
    for linha in range(8):
        base = linha * _LADO
        for col in range(8):
            h = (h << 1) | int(px[base + col] > px[base + col + 1])
    return h


def informativa(caminho) -> bool:
    """A imagem tem conteúdo que sirva de prova de execução?

    Falso positivo MEDIDO no arquivo SEI real (2026-07-24): 47 processos "compartilhavam" a mesma imagem
    — era **página em branco** extraída do PDF. Página em branco, fundo liso e logotipo aparecem em todo
    processo e produziriam acusação de reciclagem em massa contra o extrator, não contra o gestor.
    Reprova: lado < LADO_MINIMO (logo/ícone) ou luminância quase uniforme (branco/preto/fundo liso)."""
    try:
        from PIL import Image, ImageStat
        with Image.open(caminho) as im:
            if min(im.size) < LADO_MINIMO:
                return False
            desvio = ImageStat.Stat(im.convert("L")).stddev[0]
    except Exception as e:  # noqa: BLE001 — ilegível: trata como não informativa (não acusa)
        logger.debug("informativa falhou (%s): %s", caminho, e)
        return False
    return desvio >= DESVIO_MINIMO


def distancia(a: int | None, b: int | None) -> int:
    """Hamming entre dois dHash. 64 (máximo) quando algum é inválido — nunca 'igual' por omissão."""
    if a is None or b is None:
        return 64
    return bin(a ^ b).count("1")


def exif_resumo(caminho) -> dict:
    """Data/câmera/GPS do EXIF, quando houver. Ausência é LIMITAÇÃO, não achado: anexo de processo
    costuma perder EXIF na conversão para PDF e na reextração."""
    dados: dict = {"tem_exif": False, "data": None, "camera": None, "gps": False}
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            ex = getattr(im, "_getexif", lambda: None)() or {}
        if ex:
            dados["tem_exif"] = True
            dados["data"] = ex.get(36867) or ex.get(306)
            dados["camera"] = ex.get(272) or ex.get(271)
            dados["gps"] = bool(ex.get(34853))
    except Exception as e:  # noqa: BLE001 — EXIF é best-effort; nunca derruba a análise
        logger.debug("exif falhou (%s): %s", caminho, e)
    dados["observacao"] = (
        "EXIF presente — data/câmera podem ser confrontadas com o período medido."
        if dados["tem_exif"] else
        "Sem EXIF: a conversão para PDF costuma removê-lo, então a ausência NÃO é indício de fraude — "
        "apenas impede datar a foto por metadado.")
    return dados


def _fotos_do_processo(dir_processo: Path) -> list[Path]:
    base = Path(dir_processo)
    alvo = base / "fotos" if (base / "fotos").is_dir() else base
    return sorted(p for p in alvo.rglob("*") if p.is_file() and p.suffix.lower() in _EXTS)


_RESSALVA = ("indício a apurar, não acusação; INDISPONÍVEL ≠ irregular; ausência de EXIF não é vício; "
             "presunção de legitimidade")


def indexar(dirs_processos) -> tuple[dict, int]:
    """({dhash: [{processo, arquivo}]}, n_descartadas) — só imagens INFORMATIVAS entram no índice."""
    idx: dict[int, list[dict]] = {}
    descartadas = 0
    for d in dirs_processos or []:
        d = Path(d)
        for f in _fotos_do_processo(d):
            if not informativa(f):
                descartadas += 1
                continue
            h = dhash(f)
            if h is None:
                descartadas += 1
                continue
            idx.setdefault(h, []).append({"processo": d.name, "arquivo": str(f)})
    return idx, descartadas


def reciclagem(dirs_processos, *, limiar: int = LIMIAR_IGUAL) -> dict:
    """MESMA foto em processos DIFERENTES — veredito resolvido.

    Agrupa por proximidade de hash (não por igualdade exata), para pegar a mesma imagem recomprimida.
    Repetição dentro do MESMO processo é ignorada: anexo duplicado é rotina, não indício."""
    idx, descartadas = indexar(dirs_processos)
    if not idx:
        return {"grau": "nao_aplicavel", "n_fotos": 0, "n_grupos": 0, "grupos": [],
                "n_descartadas_nao_informativas": descartadas,
                "resumo": "Nenhuma foto de medição capturada nestes processos — não há o que confrontar.",
                "acao": "capturar as fotos de medição (sei_consultar) e reavaliar",
                "ressalva": _RESSALVA, "fonte": "foto_medicao (dHash, offline)"}
    hashes = list(idx)
    # BUCKETING (princípio da gaveta) — comparar todos contra todos é O(n²) e não termina em volume real
    # (5.5 mil fotos ⇒ ~15 milhões de comparações; medido: não concluiu). Dois hashes a distância ≤ 6 têm,
    # por gaveta, ao menos 2 dos 8 bytes IDÊNTICOS — então basta comparar quem compartilha algum byte na
    # mesma posição. Mesmo resultado, custo de uma fração.
    baldes: dict[tuple[int, int], list[int]] = {}
    for h in hashes:
        for pos in range(8):
            baldes.setdefault((pos, (h >> (pos * 8)) & 0xFF), []).append(h)
    usado: set[int] = set()
    grupos = []
    for h in hashes:
        if h in usado:
            continue
        candidatos = {c for pos in range(8)
                      for c in baldes.get((pos, (h >> (pos * 8)) & 0xFF), ()) if c != h}
        bloco = [h]
        for h2 in candidatos:
            if h2 not in usado and distancia(h, h2) <= limiar:
                bloco.append(h2)
                usado.add(h2)
        usado.add(h)
        ocorrencias = [o for hh in bloco for o in idx[hh]]
        processos = {o["processo"] for o in ocorrencias}
        if len(processos) > 1:                     # só é RECICLAGEM entre processos distintos
            grupos.append({"n_processos": len(processos), "ocorrencias": ocorrencias})
    n_fotos = sum(len(v) for v in idx.values())
    if not grupos:
        return {"grau": "verde", "n_fotos": n_fotos, "n_grupos": 0, "grupos": [],
                "n_descartadas_nao_informativas": descartadas,
                "resumo": f"{n_fotos} foto(s) analisada(s): nenhuma imagem se repete entre processos "
                          "distintos (sem indício de registro fotográfico reciclado).",
                "acao": "", "ressalva": _RESSALVA, "fonte": "foto_medicao (dHash, offline)"}
    total = sum(len(g["ocorrencias"]) for g in grupos)
    return {"grau": "vermelho", "n_fotos": n_fotos, "n_grupos": len(grupos), "grupos": grupos,
            "n_descartadas_nao_informativas": descartadas,
            "resumo": (f"{len(grupos)} imagem(ns) aparece(m) em MAIS DE UM PROCESSO ({total} ocorrências "
                       f"em {n_fotos} fotos): o mesmo registro fotográfico lastreia medições de processos "
                       "diferentes — indício GRAVE de comprovação reciclada, a confirmar nos autos."),
            "acao": "confrontar as fotos apontadas e a medição de cada processo antes de qualquer peça",
            "ressalva": _RESSALVA, "fonte": "foto_medicao (dHash, offline)"}


# ───────────────────── coerência foto × objeto (VLM local e gratuito, injetado) ─────────────────────
def _tokens(txt: str) -> set[str]:
    from compliance_agent.objeto_similaridade import tokens
    return set(tokens(txt or ""))


def coerencia_objeto(descricoes: list[dict], objeto: str) -> dict:
    """A descrição da foto (produzida pelo VLM) conversa com o objeto contratado? Determinístico sobre a
    descrição: compara os termos DISCRIMINANTES do objeto com os da foto (reusa o vocabulário do
    fracionamento — fonte única). Sem descrição → pendente_reprocessar (nunca verde por omissão)."""
    validas = [d for d in descricoes if d.get("descricao")]
    if not validas:
        return {"grau": "pendente_reprocessar", "coerente": None, "descricoes": descricoes,
                "resumo": "A leitura visual das fotos não foi executada — a correspondência entre a foto "
                          "e o objeto contratado continua PENDENTE (não é 'verde').",
                "acao": "rodar o VLM local (moondream2/SmolVLM em llama.cpp na VM-2) e reavaliar"}
    alvo = _tokens(objeto)
    if not alvo:
        return {"grau": "pendente_captura", "coerente": None, "descricoes": descricoes,
                "resumo": "Objeto contratado não informado/insuficiente — sem ele não se afirma nem se "
                          "nega a correspondência da foto.",
                "acao": "informar o objeto do contrato e reavaliar"}
    sem_relacao = [d for d in validas if not (alvo & _tokens(d["descricao"]))]
    if not sem_relacao:
        return {"grau": "verde", "coerente": True, "descricoes": descricoes,
                "resumo": "As fotos descrevem elementos compatíveis com o objeto contratado.", "acao": ""}
    grau = "vermelho" if len(sem_relacao) == len(validas) else "amarelo"
    return {"grau": grau, "coerente": False, "descricoes": descricoes,
            "sem_relacao": [d["arquivo"] for d in sem_relacao],
            "resumo": (f"{len(sem_relacao)} de {len(validas)} foto(s) descrevem cena SEM relação aparente "
                       f"com o objeto contratado ('{objeto[:80]}') — indício a verificar; a leitura "
                       "automática pode errar e a foto pode retratar etapa não descrita no objeto."),
            "acao": "conferir manualmente as fotos apontadas contra o boletim de medição"}


def avaliar_fotos(dir_processo, *, objeto: str = "", descrever=None, outros_processos=()) -> dict:
    """Veredito RESOLVIDO das fotos de um processo: reciclagem (objetivo, offline) + coerência com o
    objeto (VLM local injetado). `descrever`: callable(caminho)->str; None ⇒ só a camada objetiva."""
    d = Path(dir_processo)
    fotos = _fotos_do_processo(d)
    rec = reciclagem([d, *outros_processos]) if outros_processos else reciclagem([d])
    descricoes = []
    for f in fotos:
        item = {"arquivo": str(f), "exif": exif_resumo(f), "descricao": None}
        if descrever is not None:
            try:
                item["descricao"] = descrever(str(f))
            except Exception as e:  # noqa: BLE001 — VLM local pode cair; degrada honesto
                logger.debug("VLM falhou (%s): %s", f, e)
                item["erro"] = str(e)[:100]
        descricoes.append(item)
    coer = coerencia_objeto(descricoes, objeto)
    sinais = []
    if rec["grau"] == "vermelho":
        sinais.append({"tipo": "foto_reciclada_entre_processos", "observacao": rec["resumo"]})
    if coer["grau"] in ("amarelo", "vermelho"):
        sinais.append({"tipo": "foto_nao_corresponde_ao_objeto", "observacao": coer["resumo"]})
    ordem = {"nao_aplicavel": 0, "pendente_captura": 0, "pendente_reprocessar": 0,
             "verde": 0, "amarelo": 1, "vermelho": 2}
    grau = max((rec["grau"], coer["grau"]), key=lambda g: ordem.get(g, 0))
    if ordem.get(grau, 0) == 0:                    # nenhuma das camadas acusou: preserva o estado honesto
        grau = rec["grau"] if rec["grau"] != "verde" else ("verde" if coer["grau"] == "verde"
                                                           else coer["grau"])
    return {"grau": grau, "n_fotos": len(fotos), "reciclagem": rec, "coerencia_objeto": coer,
            "sinais": sinais, "fotos": descricoes,
            "resumo": " ".join(s["observacao"] for s in sinais) or rec["resumo"],
            "ressalva": _RESSALVA, "fonte": "foto_medicao"}
