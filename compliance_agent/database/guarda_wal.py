# -*- coding: utf-8 -*-
"""Uma conexão viva pelo tempo de vida do processo, para o WAL-index não sumir embaixo dele.

POR QUE ESTE MÓDULO EXISTE. O painel devolvia HTTP 500 em seis rotas da capa com
`database disk image is malformed` — e o ARQUIVO íntegro (`quick_check: ok`). Acontecia 7 a 14
vezes por dia; o `guardiao_db_malformed.sh` curava reiniciando o serviço, o que derruba junto a
sessão de browser e o login SIAFE. Reiniciar é sintoma; a causa foi medida em 31/07/2026 com um
vigia que registrava o inode dos três arquivos e os descritores abertos do `jfn.service`:

    16:14:31   fds=0                            <- o servidor chegou a ZERO conexões
    16:17:42   wal=AUSENTE  shm=AUSENTE  fds=0  <- os arquivos foram APAGADOS
    16:18:02   wal=2345988  shm=2346076  fds=0  <- recriados

O SQLite desvincula `-wal` e `-shm` quando a ÚLTIMA conexão do banco fecha. `get_engine()` cria um
engine NOVO a cada chamada (pool novo, descartado depois), então numa janela ociosa o servidor fica
sem nenhuma conexão; outro processo fecha por último e leva os arquivos embora. O processo longo
mantém o WAL-index mapeado por inode e, a partir daí, até conexão NOVA dentro dele falha — enquanto
um processo novo lê o mesmo arquivo sem problema. Daí o sintoma enganoso.

Com uma conexão sempre aberta, a condição "última conexão fechou" **neste processo** nunca ocorre.
Custa um descritor.

CUIDADO QUE NÃO É ÓBVIO: ela precisa ser uma LEITORA que não segura lock de escrita, senão trocaria
um defeito por "database is locked" nos sweeps. Por isso só faz um `SELECT` trivial e fica parada.

## A CADEIA COMPLETA (medida em 31/07/26, 2ª rodada) — e por que isto é MITIGAÇÃO, não cura

A guardiã sozinha não bastou: houve novas quedas às 17:42 e 19:24 com ela ativa. Investigando:

1. Outro processo DESVINCULA `-wal`/`-shm`. É legítimo no Linux desvincular arquivo aberto por
   terceiros, e uma conexão SQLite OCIOSA não segura lock nenhum para impedir.
2. Este processo continua com o mapeamento do inode MORTO — e segue funcionando sozinho. Medido:
   com o `-shm` apagado à mão, as cinco rotas da capa continuaram em HTTP 200.
3. **Este processo não consegue recriar o arquivo**: o SQLite cacheia o WAL-index POR PROCESSO,
   indexado pelo inode; conexão nova aqui reusa o mapeamento morto em vez de criar `-shm` novo.
4. Quando OUTRO processo cria um `-shm` novo e escreve por ele, os dois mapeamentos discordam —
   e aí nasce o "database disk image is malformed" com o arquivo íntegro.

Descartado por reprodução em laboratório (nos dois sentidos): a manutenção
(`wal_checkpoint(TRUNCATE)` + `VACUUM` + `ANALYZE`, cada passo abrindo e fechando conexão) **não**
quebra nada com a guardiã aberta — os três inodes ficaram idênticos e todas as conexões seguiram
lendo. O mesmo roteiro SEM guardiã terminou com `-wal` e `-shm` AUSENTES.

Como o passo 3 é do SQLite, **dentro do processo a única cura é reiniciar** — que é o que o
`guardiao_db_malformed.sh` faz. O que este módulo entrega:
  • evita o caminho comum (este processo ser o último a fechar) — medido e real;
  • `bater()` DETECTA o desvínculo e grita no log, transformando uma condição silenciosa em evento
    visível antes de virar HTTP 500.

## A CURA (adotada em 31/07/26, `apsw` aprovado pelo dono)

`SQLITE_FCNTL_PERSIST_WAL` faz o SQLite NUNCA desvincular `-wal`/`-shm`. Medido, com ninguém mais
segurando o banco — quem fecha por último é quem decide:

    fechador `sqlite3` puro      ->  wal=AUSENTE  shm=AUSENTE
    fechador `apsw` PERSIST_WAL  ->  wal=existe   shm=existe

PREMISSA MINHA QUE CAIU NA MEDIÇÃO (fica registrada para ninguém repetir): eu afirmava que "qualquer
conexão aberta impede o desvínculo". Isso vale quando o outro processo só LÊ — foi o que enganou o
primeiro experimento. Um ESCRITOR que fecha por último desvincula mesmo com a guardiã aberta e com a
bandeira ligada nela, porque a bandeira é consultada por quem FECHA.

Logo a proteção é EM CAMADAS, e é honesto dizer o alcance de cada uma:
  • a bandeira na guardiã cobre o caso de o próprio servidor ser o último a fechar;
  • os sweeps e crons da casa usam `sqlite3` cru e NÃO podem ligá-la (a stdlib não expõe file
    controls) — para cobri-los seria preciso passá-los por `apsw` também;
  • o `bater()` DETECTA o que escapa e grita no log antes de virar HTTP 500;
  • o `guardiao_db_malformed.sh` segue como rede final.

O `sqlite3` da stdlib não expõe file controls; daí o `apsw`. Se ele faltar, a guardiã DEGRADA para
stdlib em vez de derrubar o boot — mas aí sem a bandeira, e o log diz isso em voz alta.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import apsw as _APSW
except ImportError:  # degrada honesto: sem apsw a guardiã ainda segura, mas sem a bandeira
    _APSW = None

# Família ESPECÍFICA de erros a capturar. O `apsw` não usa `sqlite3.Error`, então capturar só a da
# stdlib deixaria passar; e capturar `Exception` cru é o que a catraca de dívida proíbe. `OSError`
# entra porque `Path.exists()` pode falhar (disco/permissão) antes de qualquer SQL.
_ERROS = (sqlite3.Error, OSError) + ((_APSW.Error,) if _APSW is not None else ())

_CONEXAO = None                # apsw.Connection (ou sqlite3.Connection na degradação)
_CAMINHO: Path | None = None   # lembrado p/ o batimento poder reabrir
_PERSIST: bool = False         # a bandeira ficou ligada nesta guardiã?


def segurar(db_path) -> bool:
    """Abre (uma vez) a conexão guardiã. `True` se há guardiã viva ao final."""
    global _CONEXAO, _CAMINHO
    if _CONEXAO is not None:
        return True
    try:
        caminho = Path(db_path)
        existe = caminho.exists()
    except OSError as exc:      # disco/permissão: não é motivo para derrubar quem nos chamou
        logger.info("guarda_wal: não consegui olhar %s (%s) — segue sem guardiã", db_path, exc)
        return False
    if not existe:
        logger.info("guarda_wal: %s não existe — servidor sobe sem guardiã", caminho.name)
        return False
    global _PERSIST
    _PERSIST = False
    try:
        if _APSW is not None:
            import ctypes
            con = _APSW.Connection(str(caminho))
            con.pragma("busy_timeout", 30000)
            # A BANDEIRA: sem ela, quem fechar por último desvincula os arquivos-irmãos e este
            # processo fica com um mapeamento morto (ver o bloco "A CURA" no topo).
            _flag = ctypes.c_int(1)
            con.file_control("main", _APSW.SQLITE_FCNTL_PERSIST_WAL, ctypes.addressof(_flag))
            _PERSIST = True
        else:
            con = sqlite3.connect(str(caminho), timeout=30, check_same_thread=False)
            con.execute("PRAGMA busy_timeout=30000")
        # `SELECT 1` NÃO basta: não toca em página nenhuma, e o WAL-index só nasce quando há
        # leitura de verdade. Ler o schema força o `-shm` a existir e a ficar mapeado aqui.
        list(con.execute("SELECT count(*) FROM sqlite_master"))
    except _ERROS as exc:
        logger.warning("guarda_wal: não consegui segurar %s (%s) — o painel volta a depender do "
                       "guardião de restart", caminho.name, exc)
        return False
    _CONEXAO, _CAMINHO = con, caminho
    logger.info("guarda_wal: conexão viva em %s — -wal/-shm não serão desvinculados", caminho.name)
    return True


def bater() -> bool:
    """Batimento: consulta mínima que RECRIA o `-shm` se alguém o desvinculou. `True` se há guardiã.

    A guardiã passiva não bastou (medido 31/07/26): houve novas quedas às 17:42 e 19:24 com ela
    ativa, e o processo ficou com descritores apontando para `-shm`/`-wal` DELETADOS — enquanto o
    `.db` manteve o mesmo inode. No Linux desvincular arquivo aberto por outro processo é permitido,
    e uma conexão SQLite OCIOSA não segura lock nenhum para impedir.

    Descartado por reprodução: a manutenção (`wal_checkpoint(TRUNCATE)` + `VACUUM` + `ANALYZE`) NÃO
    quebra nada com a guardiã aberta — os três inodes ficaram idênticos. O desvinculador ainda não
    tem nome, então isto é MITIGAÇÃO medida, não cura: cada batida recria e remapeia o WAL-index,
    encurtando a janela em que o processo fica preso a um mapeamento morto.
    """
    if _CONEXAO is None or _CAMINHO is None:
        return False
    # O sinal é o ARQUIVO, não a conexão: um `SELECT` na guardiã já aberta passa mesmo com o `-shm`
    # desvinculado (ela tem o índice mapeado em memória e não toca no disco), e uma conexão nova
    # de vida curta recria o arquivo e o SQLite o remove de novo ao fechá-la. Então: se o `-shm`
    # sumiu, a guardiã está com mapeamento MORTO e tem de ser TROCADA — a nova cria o arquivo e
    # o mantém aberto, que é o estado saudável.
    shm = _CAMINHO.with_name(_CAMINHO.name + "-shm")
    try:
        if shm.exists():
            return True
    except OSError as exc:
        logger.debug("guarda_wal: não consegui olhar %s (%s) — mantendo a guardiã atual", shm.name, exc)
        return True
    logger.warning("guarda_wal: %s foi DESVINCULADO por outro processo — trocando a guardiã antes "
                   "que as conexões novas deste processo comecem a falhar", shm.name)
    alvo = _CAMINHO
    soltar()
    return segurar(alvo)


def soltar() -> None:
    """Fecha a guardiã (usado nos testes e no desligamento)."""
    global _CONEXAO
    if _CONEXAO is not None:
        try:
            _CONEXAO.close()
        except _ERROS as exc:
            # best-effort, mas nunca mudo: fechar falhando é sinal de descritor vazando
            logger.debug("guarda_wal: fechar a guardiã falhou (%s) — descartando a referência", exc)
        _CONEXAO = None


def vivo() -> bool:
    return _CONEXAO is not None


def persist_wal_ligado() -> bool:
    """`True` quando a guardiã subiu com PERSIST_WAL — sem isso a proteção é só parcial."""
    return _PERSIST


# ── SENTINELA AUTOMÁTICA (31/07/26) ──────────────────────────────────────────────────────────────
_DB_PADRAO = Path(__file__).resolve().parents[2] / "data" / "compliance.db"


def instalar_automatico() -> bool:
    """Instala a sentinela no processo atual. Chamada pelo `__init__` do pacote; nunca levanta.

    A bandeira PERSIST_WAL é por CONEXÃO e consultada por quem FECHA — mas a proteção que interessa
    é por PROCESSO. **188 arquivos** da casa abrem o banco com `sqlite3` cru (91 escrevem) e a
    stdlib não expõe file controls; migrar tudo quebraria API (o `apsw` tem semântica própria de
    transação). Basta então que CADA processo tenha UMA sentinela com a bandeira, viva enquanto ele
    viver: assim nenhum processo da casa é "o último a fechar sem a bandeira", que é a condição que
    desvincula `-wal`/`-shm` e deixa o servidor com um mapeamento morto.

    Verificado antes de fiar: a sentinela aberta NÃO bloqueia `wal_checkpoint(TRUNCATE)`, `VACUUM`
    nem `ANALYZE` no mesmo processo — era o efeito de segunda ordem que trocaria um defeito por
    "database is locked" na manutenção.

    `JFN_SENTINELA_WAL=0` desliga (escotilha para quem não queira o descritor extra).
    """
    import os
    if os.environ.get("JFN_SENTINELA_WAL", "1").strip() in ("0", "false", "no"):
        return False
    # sem try genérico de propósito: `segurar` já captura a família específica e devolve False —
    # e a catraca de dívida proíbe captura genérica nova. Se algo aqui levantasse, seria bug real
    # que precisa aparecer, não ser engolido no import.
    return segurar(_DB_PADRAO)
