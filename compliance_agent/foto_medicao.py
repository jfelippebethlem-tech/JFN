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
# PÁGINA DE DOCUMENTO escaneada (folha de ponto, ofício, planilha impressa) vs FOTOGRAFIA. Medido no
# arquivo real: documento tem brilho ~245-253 e saturação ~0,2; as fotos de obra têm brilho 134-168 e
# saturação 38-67 — separação limpa. E 29 de 40 arquivos do diretório "fotos/" são, na verdade, páginas
# de PDF: sem este corte, o detector acusa "reciclagem" de rodapé de formulário, não de registro de obra.
BRILHO_DOCUMENTO = 200.0
SATURACAO_DOCUMENTO = 12.0
_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_LADO = 9               # dHash: 9×8 pixels → 64 comparações horizontais
# Recorte da foto embutida em página de relatório fotográfico (ver `_regioes_foto`). Aferido em
# 070002_005897_2024/023_p29.jpg (INEA/DIRRAM, contrato 35/2023, 7ª medição): as 2 fotos da página
# saem nas coordenadas certas, e o cabeçalho/legenda ficam de fora.
_FUNDO_PAGINA = 235     # canal acima disso em TODOS = branco de página
_LINHA_DENSA = 0.55     # fração de não-branco que caracteriza linha de FOTO (linha de texto fica bem abaixo)
_MIN_ALTURA = 0.06      # faixa mais baixa que isto da página não é foto
_MIN_LARGURA = 0.25
_MIN_AREA_PX = 90_000   # área mínima no ORIGINAL: abaixo disso é selo/assinatura digitalizada
_COBRE_PAGINA = 0.92    # caixa maior que isto = a imagem é a própria foto, não há o que recortar
# Fundo de papel (ver `_fundo_de_papel`) — pega o escaneado BEGE que escapa do corte por saturação.
_MODO_CLARO = 190       # abaixo disso o tom dominante não é papel
_DOMINANCIA_PAPEL = 0.80
_MODO_BRANCO = 235      # fundo BRANCO de página: tabela densa domina menos, mas branco puro entrega
_DOMINANCIA_BRANCO = 0.50


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
            cinza = ImageStat.Stat(im.convert("L"))
            desvio, brilho = cinza.stddev[0], cinza.mean[0]
            saturacao = ImageStat.Stat(im.convert("RGB").convert("HSV")).mean[1]
    except Exception as e:  # noqa: BLE001 — ilegível: trata como não informativa (não acusa)
        logger.debug("informativa falhou (%s): %s", caminho, e)
        return False
    if desvio < DESVIO_MINIMO:
        return False                                   # branco/preto/fundo liso
    if brilho > BRILHO_DOCUMENTO and saturacao < SATURACAO_DOCUMENTO:
        return False                                   # página de documento escaneada, não fotografia
    return True


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


def _regioes_foto(im, _amostra: int = 420) -> list[tuple[int, int, int, int]]:
    """Caixas das fotografias EMBUTIDAS numa página de relatório fotográfico.

    Lista vazia = o arquivo já É a fotografia (ou é só texto) — hasheie a imagem inteira.

    Existe porque a medição de obra costuma chegar como RELATÓRIO FOTOGRÁFICO: uma página com
    cabeçalho do órgão, número da medição, período, e as fotos DENTRO dela. Hashear o arquivo
    compara o MODELO da página, não a foto — falha nos dois sentidos (mesma foto em páginas
    diferentes não casa; páginas do mesmo modelo com fotos diferentes casam).

    Fundo de página é quase-branco: a projeção da máscara de não-branco por linha acha as faixas
    de foto, e a projeção por coluna dentro da faixa acha as bordas laterais."""
    import numpy as np
    W, H = im.size
    p = im.copy()
    p.draft("RGB", (_amostra, _amostra))           # decodifica reduzido: o JPEG nem chega inteiro
    p.thumbnail((_amostra, _amostra))
    nb = np.asarray(p.convert("RGB")).min(axis=2) < _FUNDO_PAGINA
    h, w = nb.shape

    faixas, ini = [], None
    for y, dens in enumerate(list(nb.mean(axis=1)) + [0.0]):
        if dens >= _LINHA_DENSA and ini is None:
            ini = y
        elif dens < _LINHA_DENSA and ini is not None:
            if (y - ini) >= _MIN_ALTURA * h:
                faixas.append((ini, y))
            ini = None

    caixas = []
    for y0, y1 in faixas:
        xs = np.flatnonzero(nb[y0:y1].mean(axis=0) >= _LINHA_DENSA)
        if not len(xs) or (xs[-1] + 1 - xs[0]) < _MIN_LARGURA * w:
            continue
        c = (round(int(xs[0]) * W / w), round(y0 * H / h),
             round((int(xs[-1]) + 1) * W / w), round(y1 * H / h))
        area = (c[2] - c[0]) * (c[3] - c[1])
        if _MIN_AREA_PX <= area < _COBRE_PAGINA * W * H:   # cobrir a página inteira = é a própria foto
            caixas.append(c)
    return caixas


def _fundo_de_papel(cinza) -> bool:
    """Papel é papel: UM tom de fundo claro dominando a imagem, com marcas escuras em cima.

    O corte por saturação (`SATURACAO_DOCUMENTO`) só pega documento CINZA. Papel envelhecido é
    bege — saturação 38-40, passava como fotografia — e foi assim que duas folhas de ponto do
    HEGV (CTI ADULTO 2 · Cardiologia) viraram um par de "reciclagem" na varredura do acervo.
    Aqui a cor não importa: mede-se a dominância do MODO do histograma, seja o papel branco,
    bege ou amarelado.

    Medido no acervo (500 imagens ao acaso): a dominância é bimodal, com a massa de papel em
    0,80-1,00. As folhas do HEGV dão 0,91; fotografias de campo verificadas a olho dão 0,30.

    **Perda declarada:** foto de superfície clara e uniforme (parede recém-pintada, céu limpo)
    pode cair aqui e ficar fora do índice de reciclagem. É o lado certo para errar — alarme
    vermelho falso contamina a fila do fiscal; uma foto a menos no índice só deixa de achar."""
    h = cinza.histogram()
    tot = sum(h) or 1
    modo = max(range(256), key=lambda i: h[i])
    if modo < _MODO_CLARO:
        return False
    dom = sum(h[max(0, modo - 18):modo + 19]) / tot
    return dom >= _DOMINANCIA_PAPEL or (modo >= _MODO_BRANCO and dom >= _DOMINANCIA_BRANCO)


def _hashear(im) -> int | None:
    """dHash de UMA fotografia já aberta; None quando a imagem não serve como registro de execução."""
    from PIL import ImageStat
    if min(im.size) < LADO_MINIMO:
        return None
    cinza = im.convert("L")
    st = ImageStat.Stat(cinza)
    if st.stddev[0] < DESVIO_MINIMO:
        return None                                # branco/preto/fundo liso
    if (st.mean[0] > BRILHO_DOCUMENTO
            and ImageStat.Stat(im.convert("RGB").convert("HSV")).mean[1] < SATURACAO_DOCUMENTO):
        return None                                # página de documento escaneada, não fotografia
    if _fundo_de_papel(cinza):
        return None                                # papel AMARELADO: escapava do corte por saturação
    g = cinza.resize((_LADO, 8))
    px = list(g.get_flattened_data() if hasattr(g, "get_flattened_data") else g.getdata())
    h = 0
    for linha in range(8):
        base = linha * _LADO
        for col in range(8):
            h = (h << 1) | int(px[base + col] > px[base + col + 1])
    return h


def _triar_e_hashear(caminho) -> list[int]:
    """Filtro + hash em UMA passada. Decodificar a imagem é o custo dominante: manter `informativa()` e
    `dhash()` separados fazia TRÊS decodificações por arquivo, e o sweep das 5,5 mil fotos passava de dez
    minutos.

    Devolve UM hash por FOTOGRAFIA do arquivo — normalmente uma (a imagem inteira), mas página de
    relatório fotográfico traz várias embutidas, e cada uma vira um item do índice. Lista vazia = nada
    no arquivo serve como registro de execução."""
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            alvos = [im.crop(c) for c in _regioes_foto(im)] or [im]
            return [h for h in (_hashear(a) for a in alvos) if h is not None]
    except Exception as e:  # noqa: BLE001 — ilegível/corrompida: fora do índice (não acusa)
        logger.debug("triagem de imagem falhou (%s): %s", caminho, e)
        return []


def indexar(dirs_processos) -> tuple[dict, int]:
    """({dhash: [{processo, arquivo}]}, n_descartadas) — só imagens INFORMATIVAS entram no índice."""
    idx: dict[int, list[dict]] = {}
    descartadas = 0
    for d in dirs_processos or []:
        d = Path(d)
        for f in _fotos_do_processo(d):
            hs = _triar_e_hashear(f)
            if not hs:
                descartadas += 1
                continue
            for i, h in enumerate(hs):
                item = {"processo": d.name, "arquivo": str(f)}
                if len(hs) > 1:                    # foto embutida: dizer QUAL, senão a prova fica vaga
                    item["foto_na_pagina"] = i + 1
                idx.setdefault(h, []).append(item)
    return idx, descartadas


def _cobertura(dirs_processos, idx: dict) -> dict:
    """De quantos processos este veredito realmente fala.

    Medido no acervo em 25/07/2026: dos 2.051 processos com pasta `fotos/`, **1.929 (94%) têm a
    pasta VAZIA**, e de 122 com arquivo, 29 só têm página em branco — sobram 93 com imagem
    aproveitável. Dizer "2.051 processos, nenhuma reciclagem" seria apresentar lacuna de CAPTURA
    como resultado de auditoria; é o mesmo vício que já apareceu nas red flags do SEI."""
    dirs = [Path(d) for d in (dirs_processos or [])]
    com_arquivo = sum(1 for d in dirs if _fotos_do_processo(d))
    com_foto = len({o["processo"] for v in idx.values() for o in v})
    return {"processos_pedidos": len(dirs), "com_arquivo": com_arquivo, "com_foto_utilizavel": com_foto,
            "sem_arquivo": len(dirs) - com_arquivo,
            "observacao": (
                f"o confronto alcançou {com_foto} processo(s) com fotografia utilizável, de "
                f"{len(dirs)} pedido(s): {len(dirs) - com_arquivo} não têm arquivo capturado e "
                f"{max(0, com_arquivo - com_foto)} só trouxeram papel ou página em branco. "
                "Ausência de reciclagem NÃO se estende aos processos não alcançados.")}


def reciclagem(dirs_processos, *, limiar: int = LIMIAR_IGUAL) -> dict:
    """MESMA foto em processos DIFERENTES — veredito resolvido.

    Agrupa por proximidade de hash (não por igualdade exata), para pegar a mesma imagem recomprimida.
    Repetição dentro do MESMO processo é ignorada: anexo duplicado é rotina, não indício."""
    idx, descartadas = indexar(dirs_processos)
    cob = _cobertura(dirs_processos, idx)
    if not idx:
        return {"grau": "nao_aplicavel", "n_fotos": 0, "n_grupos": 0, "grupos": [],
                "n_descartadas_nao_informativas": descartadas, "cobertura": cob,
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
                "n_descartadas_nao_informativas": descartadas, "cobertura": cob,
                "resumo": f"{n_fotos} foto(s) analisada(s): nenhuma imagem se repete entre processos "
                          "distintos (sem indício de registro fotográfico reciclado).",
                "acao": "", "ressalva": _RESSALVA, "fonte": "foto_medicao (dHash, offline)"}
    total = sum(len(g["ocorrencias"]) for g in grupos)
    return {"grau": "vermelho", "n_fotos": n_fotos, "n_grupos": len(grupos), "grupos": grupos,
            "n_descartadas_nao_informativas": descartadas, "cobertura": cob,
            "resumo": (f"{len(grupos)} imagem(ns) aparece(m) em MAIS DE UM PROCESSO ({total} ocorrências "
                       f"em {n_fotos} fotos): o mesmo registro fotográfico lastreia medições de processos "
                       "diferentes — indício GRAVE de comprovação reciclada, a confirmar nos autos."),
            "acao": "confrontar as fotos apontadas e a medição de cada processo antes de qualquer peça",
            "ressalva": _RESSALVA, "fonte": "foto_medicao (dHash, offline)"}


# ───────────────────── coerência foto × objeto (VLM local e gratuito, injetado) ─────────────────────
def _tokens(txt: str) -> set[str]:
    from compliance_agent.objeto_similaridade import tokens
    return set(tokens(txt or ""))


_PROMPT_VISAO = (
    "Você audita a MEDIÇÃO de um contrato público a partir da foto anexada ao processo. Descreva "
    "OBJETIVAMENTE, em português, em até 3 frases: (1) que lugar, obra ou objeto aparece; (2) que "
    "serviço, equipamento ou material está visível, e em que estado; (3) se há placa, régua, "
    "identificação de local ou data na imagem. Use substantivos concretos (asfalto, dragagem, poste, "
    "escavadeira, tubulação, prédio). Se a imagem não permitir dizer, escreva NÃO É POSSÍVEL AFIRMAR. "
    "Nunca invente o que não está visível.")


def descrever_com_visao(caminho, *, max_tokens: int = 260) -> str:
    """`descrever` pronto para `avaliar_fotos`: lê a FOTOGRAFIA e devolve texto em português.

    Devolve '' quando o arquivo não é fotografia (página de texto, papel escaneado) — e isso é
    deliberado: `coerencia_objeto` só conta descrição não vazia, então documento fica FORA da conta
    em vez de virar um 'verde' comprado com descrição de formulário. Se nada no processo for foto,
    o veredito fica `pendente_reprocessar`, que é a verdade.

    Página de relatório fotográfico é descrita FOTO A FOTO (ver `_regioes_foto`), não como página.

    Custo: passa por `llm.visao`, que tem teto (`JFN_VISAO_TETO`) e kill-switch (`JFN_VISAO_OFF`).
    Falha de provedor devolve '' — visão é enriquecimento e não derruba a camada objetiva."""
    import io

    from compliance_agent.llm import visao
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            alvos = [im.crop(c) for c in _regioes_foto(im)] or [im.copy()]
            alvos = [a for a in alvos if _hashear(a) is not None]   # mesma triagem do índice
            if not alvos:
                return ""
            partes = []
            for i, a in enumerate(alvos):
                buf = io.BytesIO()
                a.convert("RGB").save(buf, "JPEG", quality=85)
                r = visao.descrever(buf.getvalue(), _PROMPT_VISAO, max_tokens=max_tokens)
                if r.get("ok"):
                    rot = f"Foto {i + 1} da página: " if len(alvos) > 1 else ""
                    partes.append(rot + r["texto"].strip())
            return "\n".join(partes)
    except Exception as e:  # noqa: BLE001 — leitura visual é enriquecimento, nunca derruba a análise
        logger.debug("descrição visual falhou (%s): %s", caminho, e)
        return ""


def coerencia_objeto(descricoes: list[dict], objeto: str) -> dict:
    """A descrição da foto (produzida pelo VLM) conversa com o objeto contratado? Determinístico sobre a
    descrição: compara os termos DISCRIMINANTES do objeto com os da foto (reusa o vocabulário do
    fracionamento — fonte única). Sem descrição → pendente_reprocessar (nunca verde por omissão)."""
    validas = [d for d in descricoes if d.get("descricao")]
    if not validas:
        return {"grau": "pendente_reprocessar", "coerente": None, "descricoes": descricoes,
                "resumo": "A leitura visual das fotos não foi executada — a correspondência entre a foto "
                          "e o objeto contratado continua PENDENTE (não é 'verde').",
                "acao": "rodar a leitura visual (`descrever=descrever_com_visao`) e reavaliar"}
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


def _amostra_para_ler(fotos: list, teto: int) -> set:
    """Quais fotos mandar para a leitura visual quando o processo tem mais que o teto.

    Amostra ESPAÇADA sobre a lista ordenada — os anexos vêm em ordem de juntada, então espaçar
    cobre medições diferentes, enquanto pegar as N primeiras leria só a primeira medição."""
    if len(fotos) <= teto:
        return set(range(len(fotos)))
    passo = len(fotos) / teto
    return {min(len(fotos) - 1, int(i * passo)) for i in range(teto)}


def avaliar_fotos(dir_processo, *, objeto: str = "", descrever=None, outros_processos=(),
                  max_descricoes: int = 12) -> dict:
    """Veredito RESOLVIDO das fotos de um processo: reciclagem (objetivo, offline) + coerência com o
    objeto (leitura visual injetada). `descrever`: callable(caminho)->str; None ⇒ só a camada objetiva.

    `max_descricoes` limita a leitura visual. Não é economia decorativa: há processo no acervo com
    **570 e com 1.281** arquivos em `fotos/`, e uma chamada por arquivo não termina nem cabe em cota
    nenhuma. Acima do teto a leitura vira AMOSTRA espaçada — e o resultado **declara** isso em
    `leitura_visual`, porque conclusão tirada de amostra apresentada como se fosse do todo é a
    mentira mais fácil de cometer aqui."""
    d = Path(dir_processo)
    fotos = _fotos_do_processo(d)
    rec = reciclagem([d, *outros_processos]) if outros_processos else reciclagem([d])
    ler = _amostra_para_ler(fotos, max_descricoes) if descrever is not None else set()
    descricoes = []
    for i, f in enumerate(fotos):
        item = {"arquivo": str(f), "exif": exif_resumo(f), "descricao": None}
        if descrever is not None and i in ler:
            try:
                item["descricao"] = descrever(str(f))
            except Exception as e:  # noqa: BLE001 — a leitura visual pode cair; degrada honesto
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
    lidas = sum(1 for x in descricoes if x.get("descricao"))
    leitura = {"executada": descrever is not None, "arquivos_no_processo": len(fotos),
               "arquivos_enviados": len(ler), "com_descricao": lidas,
               "amostra": bool(ler) and len(ler) < len(fotos)}
    leitura["observacao"] = (
        "leitura visual não executada — a correspondência com o objeto não foi apurada"
        if descrever is None else
        f"leitura visual por AMOSTRA: {len(ler)} de {len(fotos)} arquivos, espaçados na ordem de "
        f"juntada ({lidas} renderam descrição; os demais eram papel ou o provedor não respondeu). "
        "A conclusão sobre correspondência vale para a amostra, não para o processo inteiro."
        if leitura["amostra"] else
        f"leitura visual em TODOS os {len(fotos)} arquivos ({lidas} eram fotografia).")
    return {"grau": grau, "n_fotos": len(fotos), "reciclagem": rec, "coerencia_objeto": coer,
            "sinais": sinais, "fotos": descricoes, "leitura_visual": leitura,
            "resumo": " ".join(s["observacao"] for s in sinais) or rec["resumo"],
            "ressalva": _RESSALVA, "fonte": "foto_medicao"}
