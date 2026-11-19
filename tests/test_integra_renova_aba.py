"""A aba de um processo longo é RENOVADA a cada N documentos (19/11/2026).

Medido no it-campo: a aba do 150016/009553/2024 (828 nós) chegou a 4,9 GB de RSS no renderer depois de 711
documentos; o CDP dizia 391 `Documents` e 379 `Frames` vivos com só 4 frames na árvore — cada documento clicado
deixa o anterior desanexado e retido. A renovação abre o processo numa aba nova (mesmo contexto, mesmo login),
e só então fecha a velha; se a reabertura falhar, a captura segue na aba velha (sem regressão).
"""
import asyncio
import os

os.environ.setdefault("SEI_RENOVAR_ABA_DOCS", "120")
from tools import sei_integra_completa as I  # noqa: E402


class _Pg:
    def __init__(self, nome):
        self.nome, self.fechada = nome, False

    async def add_init_script(self, _):
        return None

    async def close(self):
        self.fechada = True


class _Ctx:
    def __init__(self):
        self.abertas = []

    async def new_page(self):
        p = _Pg(f"nova{len(self.abertas)}")
        self.abertas.append(p)
        return p


def test_reabriu_troca_a_aba_e_fecha_a_velha():
    ctx, velha = _Ctx(), _Pg("velha")

    async def reabrir(p):
        return True

    nova = asyncio.run(I.renovar_aba(ctx, velha, reabrir))
    assert nova is ctx.abertas[0] and velha.fechada and not nova.fechada


def test_reabertura_falhou_segue_na_velha_e_fecha_a_nova():
    ctx, velha = _Ctx(), _Pg("velha")

    async def reabrir(p):
        return False

    r = asyncio.run(I.renovar_aba(ctx, velha, reabrir))
    assert r is velha and not velha.fechada and ctx.abertas[0].fechada


def test_excecao_na_reabertura_nao_derruba_a_captura():
    ctx, velha = _Ctx(), _Pg("velha")

    async def reabrir(p):
        raise asyncio.TimeoutError()

    r = asyncio.run(I.renovar_aba(ctx, velha, reabrir))
    assert r is velha and not velha.fechada and ctx.abertas[0].fechada


def test_hora_de_renovar_conta_so_documentos_baixados():
    assert I.hora_de_renovar(120, 120) and not I.hora_de_renovar(119, 120)
    assert not I.hora_de_renovar(500, 0), "0 desliga a renovação"
