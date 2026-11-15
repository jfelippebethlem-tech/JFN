# -*- coding: utf-8 -*-
"""Veredito da FOTO de fachada — antes de julgar a foto, ela precisa provar que é do endereço.

POR QUE EXISTE (14/11/2026, "tá super furado"). A classe visual do VLM (`verificacao_sede.visual_classe`)
era lida como se a foto fosse da sede. Conjunto de controle rotulado à mão (51 fotos do acervo) e a base
inteira mostraram três furos:

1. **Foto de outro lugar.** 64 grupos de fotos IDÊNTICAS gravadas para empresas de endereços diferentes
   (Itaperuna: 10 endereços, mesma foto, todos "ROOFTOP"; Mangaratiba: 8 empresas com a mesma praia como
   "área rural"). O geocodificador caiu no centro do município — o CEP era o genérico (`xxxxx000`).
   1.163 fotos vinham de coordenada aproximada (GEOMETRIC_CENTER / APPROXIMATE / RANGE_INTERPOLATED):
   a foto é do meio da rua, não do lote. Painéis de terceiros (© The TMax, câmera de painel BLACKVUE,
   interior de garagem) entravam como fachada.
2. **Fachada boa como ruim.** "construcao_precaria_barraco" acertou 2 de 7 casos com endereço provado:
   o resto eram casas de alvenaria comuns (Marquês de Baependi 61 com o número visível no portão).
3. **Mato como normal.** 155 sedes com foto de terreno/mato/barraco ficaram com status AFASTADO, e a
   classe visual não chegava à investigação de fachada (card C / Lex) — só o painel a via.

REGRAS (determinísticas, sem LLM — o VLM já falou; aqui se decide o que a fala dele vale):
  * a foto PROVA o endereço só com: coordenada no número (ROOFTOP), número no endereço, CEP que não é o
    genérico do município, coordenada que não é compartilhada por outro endereço e imagem que não é de
    terceiro. Sem prova → INDISPONÍVEL (não acusa NEM absolve — foto genérica não é "sede real").
  * com prova: terreno/mato → INDÍCIO (confirmar in loco); edificado → AFASTADO; "barraco" → revisão
    humana (o VLM não distingue casa simples de barraco); cadastro de LOJA/SALA/BLOCO com foto de
    terreno/barraco → a foto contradiz o cadastro, logo é de outro ponto → INDISPONÍVEL.
  * nenhuma foto condena sozinha: o INDÍCIO carrega a explicação inocente.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

CLASSES_TERRENO = frozenset({"terreno_baldio", "area_aberta_rural"})
CLASSE_PRECARIA = "construcao_precaria_barraco"
CLASSES_COMERCIAIS = frozenset({"comercial_industrial", "galpao_logistico"})
CLASSES_RESIDENCIAIS = frozenset({"casa_residencial", "predio_residencial"})

# Único geo_tipo que mira o NÚMERO. Os demais são centroide de rua/CEP ou interpolação na faixa.
_GEO_PRECISO = "ROOFTOP"
_SEM_NUMERO = {"", "S/N", "SN", "S N", "SNº", "SNO", "0", "00", "000", "SEM NUMERO", "KM"}
# Complemento que diz "unidade comercial dentro de edificação" — incompatível com foto de terreno/barraco.
_COMPL_COMERCIAL = re.compile(r"\b(LOJA|LOJ|LJ|SALA|SAL|SL|BLOCO|BLC|BL|ANDAR|CONJ|CONJUNTO|GALPAO|BOX|"
                              r"SHOPPING|EDIF|ED|TORRE|PAVIMENTO|PAV)\b\.?")
# Rodapé de câmera de painel (dashcam) que aparece no crédito de painéis enviados por usuários.
_DASHCAM = re.compile(r"(BLACK\s*V|DR\d{3}|1CH|UHD|KM/H)", re.I)


def _sem_acento(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).upper().strip()


def normalizar_classe(classe) -> str:
    """'Terreno baldio' / 'terreno-baldio' → 'terreno_baldio' (antes caía em 'indeterminado')."""
    return re.sub(r"[\s\-]+", "_", str(classe or "").strip().lower())


def cep_generico(cep) -> bool:
    """CEP de faixa/município inteiro (termina em 000): não localiza lote nenhum.

    Mesma régua de `geo.sede_real._cep_confere` ("CEP de município inteiro não prova nem desmente").
    """
    d = re.sub(r"\D", "", str(cep or ""))
    return len(d) == 8 and d.endswith("000")


def credito_de_terceiro(texto) -> bool:
    """O rodapé da imagem diz quem a fez. '© Google' = carro do Google (posição do panorama oficial);
    '© <pessoa/empresa>' ou rodapé de dashcam = painel enviado por usuário, sem posição garantida
    (medido no controle: vista aérea de prédio, garagem subterrânea, corredor interno, pista de rodovia).
    Texto vazio/ilegível → False (não se presume terceiro)."""
    t = str(texto or "").strip()
    if not t:
        return False
    if _DASHCAM.search(t):
        return True
    if "GOOGLE" in t.upper() or "GOOGIE" in t.upper():
        return False
    m = re.search(r"[©@]\s*([A-Za-zÀ-ú][\w .'-]{2,})", t)
    return bool(m)


def _numero(reg: dict) -> str:
    if "numero" in reg:
        return _sem_acento(reg.get("numero")).replace(".", "")
    # endereco da verificacao_sede: "TIPO, LOGRADOURO, NUMERO, COMPL..., BAIRRO, MUN, UF, CEP"
    partes = [p.strip() for p in str(reg.get("endereco") or "").split(",")]
    for p in partes[1:4]:
        q = _sem_acento(p)
        if q in _SEM_NUMERO or re.fullmatch(r"S\s*/?\s*N", q):
            return ""
        if re.fullmatch(r"0*\d{1,6}[A-Z]?", q):
            return q.lstrip("0") or ""
    return ""


def _cep(reg: dict) -> str:
    if reg.get("cep"):
        return re.sub(r"\D", "", str(reg["cep"]))
    m = re.search(r"(\d{5}-?\d{3})\s*$", str(reg.get("endereco") or ""))
    return re.sub(r"\D", "", m.group(1)) if m else ""


def prova_de_endereco(reg: dict) -> tuple[bool, list[str]]:
    """A foto é do lote declarado? → (provada, motivos de NÃO estar provada)."""
    motivos: list[str] = []
    geo = str(reg.get("geo_tipo") or "").upper()
    if geo != _GEO_PRECISO:
        motivos.append(f"coordenada aproximada ({geo or 'sem tipo'}): a foto é do centro da rua/CEP, "
                       "não do lote")
    num = _numero(reg)
    if not num or num in _SEM_NUMERO or re.fullmatch(r"S\s*/?\s*N", num) or not re.search(r"[1-9]", num):
        motivos.append("endereço sem número — o lote não é localizável")
    if cep_generico(_cep(reg)):
        motivos.append("CEP genérico do município (termina em 000) — o geocodificador cai no centro da cidade")
    n = int(reg.get("enderecos_na_coordenada") or 0)
    if n >= 2:
        motivos.append(f"a mesma coordenada está gravada para {n} endereços diferentes — a foto não é de "
                       "nenhum lote específico")
    if credito_de_terceiro(reg.get("credito_imagem")):
        motivos.append(f"imagem enviada por terceiro ({str(reg.get('credito_imagem')).strip()[:40]}), "
                       "sem posição garantida")
    return (not motivos), motivos


_INOCENTE_TERRENO = ("A imagem de rua pode ser antiga (o Street View tem data) e o lote ter sido edificado "
                     "depois; a sede pode ficar ao fundo do terreno ou no lote vizinho; prestadora de serviço "
                     "em campo pode ter sede administrativa mínima. Foto sozinha não condena.")


def veredito_foto(reg: dict) -> dict:
    """Registro de `verificacao_sede` (+ `enderecos_na_coordenada`, `credito_imagem`, opcionalmente
    `numero`/`complemento`/`cep` da Receita) → veredito da foto.

    status: INDICIO | AFASTADO | INDISPONIVEL. `prova_endereco`: True/False, ou None sem foto."""
    classe = normalizar_classe(reg.get("visual_classe"))
    base = {"classe": classe, "prova_endereco": None, "motivos_sem_prova": [], "revisar_humano": False,
            "explicacao_inocente": ""}
    if not classe or classe == "indeterminado":
        return {**base, "status": "INDISPONIVEL",
                "evidencia": "sem foto classificada da sede" if not classe
                else "análise visual inconclusiva (imagem ruim/ambígua)"}
    ok, motivos = prova_de_endereco(reg)
    base.update(prova_endereco=ok, motivos_sem_prova=motivos)
    if not ok:
        return {**base, "status": "INDISPONIVEL",
                "evidencia": (f"A foto ({classe.replace('_', ' ')}) NÃO prova ser do endereço declarado: "
                              + "; ".join(motivos) + ". Não acusa nem afasta — é preciso foto do lote.")}
    compl = _sem_acento(reg.get("complemento"))
    if (classe in CLASSES_TERRENO or classe == CLASSE_PRECARIA) and _COMPL_COMERCIAL.search(compl):
        return {**base, "status": "INDISPONIVEL", "prova_endereco": False,
                "motivos_sem_prova": motivos + ["foto contradiz o cadastro"],
                "evidencia": (f"A foto ({classe.replace('_', ' ')}) contradiz o cadastro, que declara unidade "
                              f"em edificação ('{compl[:40]}'): a coordenada provavelmente caiu em outro ponto. "
                              "Não acusa — obter foto do lote.")}
    if classe in CLASSES_TERRENO:
        conf = float(reg.get("visual_conf") or 0)
        return {**base, "status": "INDICIO", "nivel": "MEDIO",
                "evidencia": (f"Foto de rua do número declarado (coordenada no lote, CEP específico, sem outro "
                              f"endereço no mesmo ponto) mostra **{classe.replace('_', ' ')}** (confiança do "
                              f"classificador {conf:.0%}) — sem edificação compatível com a operação. Indício a "
                              "confirmar in loco."),
                "explicacao_inocente": _INOCENTE_TERRENO}
    if classe == CLASSE_PRECARIA:
        return {**base, "status": "INDISPONIVEL", "revisar_humano": True,
                "evidencia": ("O classificador disse 'construção precária', mas confunde casa simples de "
                              "alvenaria com barraco (no controle de 14/11/2026 acertou 2 de 7) — vai para "
                              "o olho humano antes de qualquer juízo.")}
    if classe in CLASSES_COMERCIAIS:
        return {**base, "status": "AFASTADO",
                "evidencia": f"Foto do lote mostra edificação {classe.replace('_', ' ')} — compatível com sede real."}
    if classe in CLASSES_RESIDENCIAIS:
        return {**base, "status": "AFASTADO",
                "evidencia": (f"Foto do lote mostra edificação ({classe.replace('_', ' ')}): afasta terreno "
                              "vazio; sede em residência é outro sinal (natureza do imóvel), não fachada por si.")}
    return {**base, "status": "INDISPONIVEL", "evidencia": f"classe visual desconhecida '{classe}'"}


# ── dados do acervo ──────────────────────────────────────────────────────────────────────────

def _chave_endereco(endereco: str) -> str:
    partes = [_sem_acento(p) for p in str(endereco or "").split(",")]
    return " ".join(p for p in partes[:3] if p)


_IDX_COORD: dict = {"ts": 0.0, "id": None, "idx": None}


def _indice_coordenadas(con) -> dict | None:
    """coordenada (5 casas) → endereços do acervo. Lido UMA vez por processo/10 min: a consulta por
    coordenada com round() varria a tabela inteira a cada CNPJ (0,4 s; 14 mil fornecedores = 1h30)."""
    import time as _t
    try:
        chave = str(con.execute("PRAGMA database_list").fetchone()[2] or id(con))
    except (sqlite3.Error, AttributeError, TypeError, IndexError):  # conexão sem PRAGMA (mock): chave pela instância
        chave = str(id(con))
    if _IDX_COORD["idx"] is not None and _IDX_COORD["id"] == chave and _t.time() - _IDX_COORD["ts"] < 600:
        return _IDX_COORD["idx"]
    try:
        rows = con.execute("SELECT endereco, geo_lat, geo_lon FROM verificacao_sede "
                           "WHERE geo_lat IS NOT NULL AND geo_lon IS NOT NULL").fetchall()
    except sqlite3.Error as exc:  # tabela ausente: sem dado, não inventa
        logger.debug("coordenada compartilhada indisponível: %s", exc)
        return None
    idx: dict = {}
    for end, la, lo in rows:
        if end:
            idx.setdefault((round(float(la), 5), round(float(lo), 5)), set()).add(_chave_endereco(end))
    _IDX_COORD.update(ts=_t.time(), id=chave, idx=idx)
    return idx


def enderecos_na_coordenada(con, lat, lon, endereco: str = "") -> int:
    """Quantos endereços DISTINTOS (logradouro+número) do acervo estão gravados nesta coordenada.
    1 = só o próprio. ≥2 = a coordenada é um centroide, não um lote."""
    if lat is None or lon is None:
        return 0
    idx = _indice_coordenadas(con)
    if idx is None:
        return 0
    chaves = set(idx.get((round(float(lat), 5), round(float(lon), 5)), ()))
    if endereco:
        chaves.add(_chave_endereco(endereco))
    return len(chaves)


_CACHE_CREDITO = Path("data") / "cache" / "fachada_credito_imagem.json"  # gitignored
_DIR_IMG = Path("data") / "fachada_img"


def credito_da_imagem(caminho) -> str | None:
    """Lê (OCR, tesseract local, grátis) o rodapé '© ...' da foto. Cacheado por arquivo.
    Sem arquivo/tesseract → None (não se presume nada)."""
    p = Path(str(caminho or ""))
    if not p.is_file():
        return None
    try:
        cache = json.loads(_CACHE_CREDITO.read_text("utf-8")) if _CACHE_CREDITO.exists() else {}
    except (OSError, ValueError):
        cache = {}
    chave = f"{p.name}:{p.stat().st_size}"
    if chave in cache:
        return cache[chave]
    try:
        import io

        from PIL import Image
        im = Image.open(p).convert("L")
        w, h = im.size
        recorte = im.crop((max(0, w - 200), max(0, h - 22), w, h)).resize((800, 88))
        buf = io.BytesIO()
        recorte.save(buf, "PNG")
        r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7"], input=buf.getvalue(),
                           capture_output=True, timeout=20)
        texto = r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.debug("OCR do crédito indisponível p/ %s: %s", p, exc)
        return None
    cache[chave] = texto
    try:
        _CACHE_CREDITO.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_CREDITO.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
    except OSError as exc:
        logger.debug("cache de crédito não gravado: %s", exc)
    return texto


def veredito_foto_do_cnpj(cnpj: str, con) -> dict:
    """Monta o registro a partir de `verificacao_sede` (+ Receita, se disponível) e julga a foto."""
    cnpj = re.sub(r"\D", "", str(cnpj or ""))
    try:
        r = con.execute("SELECT endereco, geo_lat, geo_lon, geo_tipo, visual_classe, visual_conf, "
                        "visual_img_path FROM verificacao_sede WHERE cnpj=?", (cnpj,)).fetchone()
    except sqlite3.Error as exc:
        logger.debug("verificacao_sede indisponível p/ %s: %s", cnpj, exc)
        r = None
    if not r:
        return veredito_foto({})
    reg = {"endereco": r[0], "geo_lat": r[1], "geo_lon": r[2], "geo_tipo": r[3], "visual_classe": r[4],
           "visual_conf": r[5]}
    reg["enderecos_na_coordenada"] = enderecos_na_coordenada(con, r[1], r[2], r[0] or "")
    # `visual_img_path` só foi gravado para as classes "flagueadas"; a foto das demais também mora em
    # data/fachada_img/<cnpj>.jpg (32 comerciais no acervo) — sem este fallback, painel de dashcam
    # classificado "comercial" absolvia a sede.
    img = r[6] or (_DIR_IMG / f"{cnpj}.jpg")
    if Path(str(img)).is_file():
        reg["credito_imagem"] = credito_da_imagem(img)
    partes = [p.strip() for p in str(r[0] or "").split(",")]
    if len(partes) > 4:
        reg["complemento"] = " ".join(partes[3:-4])
    return veredito_foto(reg)
