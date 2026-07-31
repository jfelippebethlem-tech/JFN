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

CURA DEFINITIVA, para decisão do dono: `SQLITE_FCNTL_PERSIST_WAL` faz o SQLite NUNCA desvincular os
arquivos-irmãos. O `sqlite3` da stdlib não expõe file controls; exigiria `apsw`. É uma dependência
nova — não foi adotada por conta própria.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_CONEXAO: sqlite3.Connection | None = None
_CAMINHO: Path | None = None   # lembrado p/ o batimento poder reabrir


def segurar(db_path) -> bool:
    """Abre (uma vez) a conexão guardiã. `True` se há guardiã viva ao final."""
    global _CONEXAO, _CAMINHO
    if _CONEXAO is not None:
        return True
    caminho = Path(db_path)
    if not caminho.exists():
        logger.info("guarda_wal: %s não existe — servidor sobe sem guardiã", caminho.name)
        return False
    try:
        con = sqlite3.connect(str(caminho), timeout=30, check_same_thread=False)
        # força o WAL-index a existir e a ficar mapeado neste processo; sem tocar em escrita.
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
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
    if shm.exists():
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
        except sqlite3.Error:
            pass
        _CONEXAO = None


def vivo() -> bool:
    return _CONEXAO is not None
