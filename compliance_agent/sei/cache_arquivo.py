# -*- coding: utf-8 -*-
"""Leitura TRANSPARENTE do cache SEI — `.json` ou `.json.zst`, o chamador não precisa saber.

POR QUE ESTE MÓDULO EXISTE. `data/sei_cache/` tinha **23,1 GB em 5.965 blobs `cdp_*.json`** (91,6% do
diretório) contra 180 MB do texto já extraído em `data/sei_arquivo/` — razão de 128×. Não é cache: é
acumulação, porque a política de poda (`sei/indice.podar_cache`) **nunca teve um único caller** e o
seu docstring prometia podar `json` que o código não tocava (só `.pdf/.html/.htm`).

A ordem do dono é clara: **nada é apagado; tudo em arquivos menores.** Então o bruto é comprimido em
zstd, com o sha256 do conteúdo descomprimido conferido antes de o original sair — perda zero, byte a
byte. Mas comprimir quebraria os leitores, e há dois tipos deles:

  • `collectors/sei_cdp.py` só olha cache com menos de 24 h (TTL) — para ele, blob velho é indiferente;
  • `sei/relacionados.py` faz `glob("cdp_SEI_*.json")` e lê blob de **qualquer idade** — para ele,
    comprimir sem leitura transparente seria apagar o dado do ponto de vista de quem consome.

Daí este módulo: quem lê cache passa por aqui e deixa de se importar com a forma no disco.

CUIDADO QUE NÃO É ÓBVIO: `data/sei_cache/` **não é só cache**. Ali moram o estado que evita MFA do
SIAFE por ~30 dias (`siafe_state.json`), o lock de coleta, os checkpoints de OB, o `.mfa_code` e o
progresso do sweep do SEI — somados, menos de 30 MB. Um `find … -name '*.json' -delete` mataria dias
de captura e forçaria MFA. Por isso a whitelist é por PREFIXO e vive em `PREFIXOS_ESTADO_VIVO`.
"""
from __future__ import annotations

import json
import logging
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Estado OPERACIONAL que mora no mesmo diretório do cache. Nunca comprimir, nunca tocar.
# Mapeado lendo os callers: siafe_session/siafe_coord/siafe_ob_orcamentaria/siafe_runner,
# mfa_telegram, rotas/sistema.py e server.py.
PREFIXOS_ESTADO_VIVO = (
    "siafe_", "siafe", "sei_sweep_", ".mfa_code", "ob_orcamentaria_checkpoint",
    "uggrande_", "mgsclean_obs", "manifest.json", "ERRO_", "resume", "corpus",
)


def eh_estado_vivo(nome: str) -> bool:
    """`True` para arquivo de estado operacional — o que a compressão tem de poupar."""
    return any(nome.startswith(p) for p in PREFIXOS_ESTADO_VIVO)


def localizar(caminho: Path) -> Path | None:
    """O caminho pedido, ou a versão `.zst` dele. `None` se nenhuma das duas existe."""
    caminho = Path(caminho)
    if caminho.exists():
        return caminho
    comp = caminho.with_name(caminho.name + ".zst")
    return comp if comp.exists() else None


def ler_bytes(caminho: Path) -> bytes | None:
    """Conteúdo cru, descomprimindo se for `.zst`. `None` quando não há arquivo nem erro do chamador."""
    achado = localizar(caminho)
    if achado is None:
        return None
    if achado.suffix != ".zst":
        return achado.read_bytes()
    try:
        return subprocess.run(["zstd", "-dc", str(achado)], capture_output=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("cache %s comprimido e ilegível (%s) — tratado como AUSENTE, não como vazio",
                       achado.name, exc)
        return None


def ler_json(caminho: Path) -> dict | list | None:
    """JSON do cache, comprimido ou não. `None` = ausente/ilegível — nunca `{}` (vazio ≠ ausente)."""
    cru = ler_bytes(caminho)
    if cru is None:
        return None
    try:
        return json.loads(cru.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        logger.debug("cache %s com JSON inválido: %s", Path(caminho).name, exc)
        return None


def escrever_json(caminho: Path, obj) -> Path:
    """Grava `obj` no cache PRESERVANDO a forma em disco (`.json` ou `.json.zst`). Devolve o alvo real.

    Sem isto, quem enxerga o acervo por `glob_cache` (que devolve `.zst`) e grava com `write_text`
    escreveria texto puro por cima do blob comprimido — corrompendo-o. Escreve em `.tmp` e só então
    troca, para que uma falha no meio preserve o conteúdo anterior em vez de deixar blob pela metade.
    """
    caminho = Path(caminho)
    alvo = localizar(caminho) or caminho
    cru = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    tmp = alvo.with_name(alvo.name + ".tmp")
    try:
        if alvo.suffix == ".zst":
            tmp.write_bytes(subprocess.run(["zstd", "-q", "-c", "-"], input=cru,
                                           capture_output=True, check=True).stdout)
        else:
            tmp.write_bytes(cru)
        tmp.replace(alvo)
    finally:
        tmp.unlink(missing_ok=True)
    return alvo


_UNIDADE = {"B": 1, "KB": 1024, "KiB": 1024, "MB": 1024 ** 2, "MiB": 1024 ** 2,
            "GB": 1024 ** 3, "GiB": 1024 ** 3}


@lru_cache(maxsize=8192)
def _tamanho_logico(caminho_str: str, mtime: float) -> int:
    """Tamanho do conteúdo DESCOMPRIMIDO, para comparar `.json` com `.json.zst`.

    CUSTO IMPORTA: `glob_cache` roda em toda ferramenta da casa, e descomprimir para medir custava
    ~82 ms por blob — 214 pares davam 31 s em CADA varredura, inviabilizando o arquivador.
    A saída é o cabeçalho do próprio zstd: `zstd -l` informa o tamanho descomprimido em **7 ms**,
    sem descomprimir nada. Memoizado por (caminho, mtime): a mesma varredura no mesmo processo não
    paga de novo, e um blob reescrito invalida a entrada sozinho.

    Falha vira 0 (o outro lado ganha) — nunca exceção: um blob corrompido não pode derrubar a
    varredura inteira do acervo.
    """
    caminho = Path(caminho_str)
    try:
        if caminho.suffix != ".zst":
            return caminho.stat().st_size
        saida = subprocess.run(["zstd", "-l", str(caminho)],
                               capture_output=True, text=True, timeout=10).stdout
        # linha de dados: "Frames Skips Compressed Uncompressed Ratio Check Filename"
        for linha in saida.splitlines()[1:]:
            campos = linha.split()
            # `zstd -l` imprime "…  532   B   832   B  1.564 …": o 1º par é comprimido, o 2º é o
            # descomprimido — que é o que interessa para comparar com o `.json` solto.
            nums = [(float(campos[i]), campos[i + 1]) for i in range(len(campos) - 1)
                    if campos[i].replace(".", "").replace(",", "").isdigit()
                    and campos[i + 1] in _UNIDADE]
            if len(nums) >= 2:
                v, un = nums[1]
                return int(v * _UNIDADE[un])
        # CABEÇALHO SEM O TAMANHO. `zstd -l` deixa `Uncompressed` VAZIO quando o blob foi
        # comprimido a partir de STDIN — que é exatamente como `escrever_json` grava (`zstd -c -`
        # com `input=`). Ou seja: o atalho barato NÃO vale para os nossos próprios arquivos, só
        # para os que vieram comprimidos de fora. Sem este fallback o tamanho voltava 0 e o `.json`
        # POBRE vencia — a regressão apareceu no par `270006/006457/2024` (zst=0 vs json=150.862)
        # e foi pega pelo teste, não por leitura do código.
        b = ler_bytes(caminho)
        return len(b) if b else 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0


def _maior(a: Path, b: Path) -> Path:
    """O dos dois caminhos cujo conteúdo lógico é maior; empate fica com o primeiro."""
    ta = _tamanho_logico(str(a), a.stat().st_mtime)
    tb = _tamanho_logico(str(b), b.stat().st_mtime)
    return b if tb > ta else a


def glob_cache(cache_dir: Path, padrao: str):
    """Itera `padrao` e `padrao + '.zst'`, recursivo, sem repetir o mesmo conteúdo lógico.

    Ex.: `glob_cache(d, 'cdp_SEI_*.json')` devolve tanto `cdp_SEI_x.json` quanto
    `cdp_SEI_x.json.zst`.

    QUANDO AS DUAS FORMAS EXISTEM, GANHA A MAIOR — não a não-comprimida.
    A regra antiga ("a não comprimida ganha, é janela entre comprimir e remover") partia de uma
    premissa falsa: a coexistência NÃO é transitória. Medido em 2026-08-27: **130 pares
    permanentes**, e em **81 deles o `.json` solto tem MENOS texto que o `.zst`** — somando
    **27.427.878 caracteres** que o acervo tinha e nenhuma ferramenta enxergava. O caso extremo é
    o `270006/006457/2024`: 16.000 chars no `.json` (40 documentos trimados a 400 cada) contra
    **787.668** no `.zst`. Em 45 pares o `.json` é que é maior, então trocar a preferência
    cegamente só inverteria o prejuízo — a regra tem de ser pelo TAMANHO.
    Comparar bytes em disco seria errado (um está comprimido); a comparação é pelo conteúdo
    descomprimido, e o custo se paga: sem isso o arquivador classifica o cache como "amostra" e
    RECUSA o processo, deixando texto já pago fora do alcance.
    """
    cache_dir = Path(cache_dir)
    vistos: dict[str, Path] = {}
    for p in sorted(cache_dir.rglob(padrao)):
        vistos.setdefault(p.name, p)
    for p in sorted(cache_dir.rglob(padrao + ".zst")):
        chave = p.name[: -len(".zst")]
        atual = vistos.get(chave)
        if atual is None:
            vistos[chave] = p
        else:
            vistos[chave] = _maior(atual, p)   # ganha quem tem mais conteúdo, não a forma
    return list(vistos.values())


def nome_logico(caminho: Path) -> str:
    """`cdp_SEI_x.json.zst` → `cdp_SEI_x.json`. Para quem deriva chave do nome do arquivo."""
    n = Path(caminho).name
    return n[: -len(".zst")] if n.endswith(".zst") else n
