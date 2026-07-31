# -*- coding: utf-8 -*-
"""Uma conexão viva impede que o WAL-index seja desvinculado embaixo do servidor.

DEFEITO MEDIDO (31/07/2026). O painel devolvia HTTP 500 em seis rotas da capa
(`/api/compliance/painel`, `/api/comparador/{economia,vedada,dossie}`, `/api/intel/{lift,fenix}`),
todas com `database disk image is malformed` — e o ARQUIVO íntegro (`quick_check: ok`). Acontecia
**7 a 14 vezes por dia**; o `guardiao_db_malformed.sh` curava reiniciando o serviço, o que derruba
junto a sessão de browser e o login SIAFE.

A causa foi pega no flagrante por um vigia que registrava o inode dos três arquivos e a contagem de
descritores do `jfn.service`:

    16:14:31   fds=0                            <- o servidor chegou a ZERO conexões
    16:17:42   wal=AUSENTE  shm=AUSENTE  fds=0  <- os arquivos foram APAGADOS
    16:18:02   wal=2345988  shm=2346076  fds=0  <- recriados

O SQLite desvincula `-wal` e `-shm` quando a ÚLTIMA conexão do banco fecha. `get_engine()` cria um
engine NOVO a cada chamada (pool novo, conexões descartadas depois), então numa janela ociosa o
servidor fica sem nenhuma conexão; outro processo fecha por último e leva os arquivos embora. O
processo longo mantém o WAL-index mapeado por inode e, a partir daí, até conexão NOVA dentro dele
falha — enquanto um processo novo lê o mesmo arquivo sem problema. Daí o sintoma enganoso:
"malformed" num banco que está perfeito.

A cura é manter UMA conexão viva pelo tempo de vida do processo: com ela aberta, o SQLite nunca
chega à condição de "última conexão fechou", e a desvinculação não acontece. É barato (um
descritor) e ataca a causa, não o sintoma.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.database import guarda_wal


@pytest.fixture()
def banco(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    return p


def test_segurar_deixa_uma_conexao_viva(banco):
    """O ponto do defeito: enquanto houver conexão, o SQLite não desvincula os arquivos-irmãos."""
    guarda_wal.soltar()
    assert guarda_wal.segurar(banco) is True
    try:
        assert guarda_wal.vivo() is True
    finally:
        guarda_wal.soltar()


def test_o_wal_index_sobrevive_ao_fechamento_de_outro_processo(banco):
    """Simula o que foi medido: outro escritor abre, escreve e fecha por último."""
    guarda_wal.segurar(banco)
    try:
        outro = sqlite3.connect(banco)
        outro.execute("INSERT INTO t VALUES (2)")
        outro.commit()
        outro.close()   # sem a guardiã, ESTE close levaria -wal e -shm embora

        assert (banco.parent / (banco.name + "-shm")).exists(), (
            "o -shm foi desvinculado mesmo com a conexão guardiã aberta")
    finally:
        guarda_wal.soltar()


def test_segurar_e_idempotente(banco):
    """O lifespan pode rodar mais de uma vez (reload): não pode vazar descritor."""
    guarda_wal.soltar()
    guarda_wal.segurar(banco)
    primeira = guarda_wal._CONEXAO
    guarda_wal.segurar(banco)
    try:
        assert guarda_wal._CONEXAO is primeira, "abriu uma segunda conexão em vez de reusar"
    finally:
        guarda_wal.soltar()


def test_banco_inexistente_nao_derruba_o_boot(tmp_path):
    """Degrada honesto: sem banco, o servidor sobe igual — a guardiã é otimização, não requisito."""
    guarda_wal.soltar()
    assert guarda_wal.segurar(tmp_path / "nao_existe" / "x.db") is False
    assert guarda_wal.vivo() is False


def test_a_guardia_nao_segura_lock_de_escrita(banco):
    """Ela lê e some do caminho: um escritor concorrente não pode ser bloqueado por ela."""
    guarda_wal.segurar(banco)
    try:
        outro = sqlite3.connect(banco, timeout=5)
        outro.execute("INSERT INTO t VALUES (3)")
        outro.commit()   # se a guardiã segurasse lock, isto estouraria "database is locked"
        outro.close()
    finally:
        guarda_wal.soltar()


# ── BATIMENTO (2026-07-31, 2ª rodada) ────────────────────────────────────────────────────────────
# A guardiã PASSIVA não bastou: houve novas quedas às 17:42 e 19:24 com ela ativa, e o processo
# ficou com descritores apontando para `-shm`/`-wal` DELETADOS enquanto o `.db` mantinha o mesmo
# inode. Ou seja: outro processo DESVINCULA os arquivos-irmãos por baixo dela — no Linux isso é
# permitido, e uma conexão SQLite ociosa não segura lock nenhum para impedir.
#
# Descartado por reprodução em laboratório: a manutenção (`wal_checkpoint(TRUNCATE)` + `VACUUM` +
# `ANALYZE`, cada passo abrindo e fechando conexão) NÃO quebra nada com a guardiã aberta — os três
# inodes ficaram idênticos e todas as conexões seguiram lendo. O controle sem guardiã, no mesmo
# roteiro, terminou com `-wal` e `-shm` AUSENTES. O mecanismo original está certo; falta cobrir
# quem desvincula com a guardiã aberta.
#
# Daí o batimento: se o `-shm` sumiu, uma consulta nova o recria e remapeia. É mitigação medida, não
# cura da causa — e o teste guarda a propriedade que importa: depois do batimento, o arquivo existe.

def test_batimento_recria_o_shm_que_sumiu(banco):
    """O ponto do defeito remanescente: alguém desvincula o -shm com a guardiã aberta."""
    guarda_wal.segurar(banco)
    try:
        shm = banco.parent / (banco.name + "-shm")
        assert shm.exists(), "a guardiã deveria ter aberto o WAL-index"
        shm.unlink()          # simula o desvinculador ainda não identificado

        assert guarda_wal.bater() is True
        assert shm.exists(), "o batimento não recriou o -shm"
    finally:
        guarda_wal.soltar()


def test_batimento_sem_guardia_nao_estoura(banco):
    """O ciclo do servidor chama isto sempre; sem guardiã tem de degradar honesto."""
    guarda_wal.soltar()
    assert guarda_wal.bater() is False


def test_batimento_sobrevive_a_conexao_morta(banco):
    """Se a conexão guardiã morreu, o batimento a REABRE em vez de ficar mudo para sempre."""
    guarda_wal.segurar(banco)
    try:
        guarda_wal._CONEXAO.close()     # morta, mas ainda referenciada
        assert guarda_wal.bater() is True
        assert guarda_wal.vivo() is True
    finally:
        guarda_wal.soltar()
