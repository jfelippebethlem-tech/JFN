# -*- coding: utf-8 -*-
"""Storage DURÁVEL e VERSIONADO das análises de processos SEI (reusa anexos_remotes: R2→B2).

Diretriz do dono (2026-07-24): "as analises dos processos precisam ficar guardadas porque esses processos
sei sao alterados e podem surgir novos documentos". Cada análise vira um SNAPSHOT imutável versionado pelo
HASH do conteúdo capturado (árvore/manifesto). Processo muda → hash novo → nova versão; histórico preservado.

Tudo sem rede: as primitivas de upload/list (rclone) são injetáveis.
"""
from __future__ import annotations

import json

from compliance_agent import analise_remotes as AR


def test_hash_versao_estavel_e_sensivel():
    h1 = AR.hash_versao("conteudo da arvore A")
    assert h1 == AR.hash_versao("conteudo da arvore A")     # estável
    assert h1 != AR.hash_versao("conteudo da arvore A'")    # muda com o conteúdo
    assert isinstance(h1, str) and len(h1) >= 12
    # aceita dict (manifesto) de forma determinística (ordem de chaves não importa)
    assert AR.hash_versao({"a": 1, "b": 2}) == AR.hash_versao({"b": 2, "a": 1})


def test_objeto_analise_formato():
    obj = AR.objeto_analise("SEI-330003/002534/2024", "abc123def456")
    assert obj.endswith("/abc123def456.json")
    assert "analises" in obj and "330003" in obj


def test_guardar_analise_sobe_snapshot_com_metadados(tmp_path):
    capturado = {"subiu": None, "objeto": None, "pacote": None}
    def _subir(local_path, objeto_rel):
        capturado["objeto"] = objeto_rel
        capturado["pacote"] = json.loads(open(local_path, encoding="utf-8").read())
        return f"r2:jorgefelippe/{objeto_rel}"      # ponteiro canônico
    def _existe(loc):
        return False
    veredito = {"grau": "vermelho", "resumo": "cascata + cláusula forte"}
    loc = AR.guardar_analise("SEI-1/2/2024", veredito, versao_hash="deadbeef1234",
                             criado_em="2026-07-24T14:00:00", subir=_subir, existe=_existe)
    assert loc == "r2:jorgefelippe/" + capturado["objeto"]
    assert capturado["objeto"].endswith("/deadbeef1234.json")
    # o snapshot carrega o veredito + metadados de versão (imutável, auditável)
    assert capturado["pacote"]["veredito"]["grau"] == "vermelho"
    assert capturado["pacote"]["versao_hash"] == "deadbeef1234"
    assert capturado["pacote"]["criado_em"] == "2026-07-24T14:00:00"
    assert capturado["pacote"]["numero_sei"] == "SEI-1/2/2024"


def test_guardar_idempotente_nao_ressobe_versao_existente():
    chamou = {"n": 0}
    def _subir(local_path, objeto_rel):
        chamou["n"] += 1
        return f"b2:jfn-backup-jorge/{objeto_rel}"
    def _existe(loc):
        return True         # a versão JÁ está no remote
    loc = AR.guardar_analise("SEI-1/2/2024", {"grau": "amarelo"}, versao_hash="v1",
                             criado_em="2026-07-24T14:00:00", subir=_subir, existe=_existe,
                             loc_conhecida="b2:jfn-backup-jorge/analises/SEI-1_2_2024/v1.json")
    assert chamou["n"] == 0                              # não re-subiu
    assert loc == "b2:jfn-backup-jorge/analises/SEI-1_2_2024/v1.json"


def test_degrada_honesto_quando_upload_falha():
    def _subir(local_path, objeto_rel):
        return None         # rclone falhou / remotes cheios
    loc = AR.guardar_analise("SEI-1/2/2024", {"grau": "verde"}, versao_hash="v9",
                             criado_em="2026-07-24T14:00:00", subir=_subir, existe=lambda l: False)
    assert loc is None


def test_mudou_detecta_delta_de_versao():
    conhecidas = {"v1", "v2"}
    assert AR.mudou("v3", conhecidas) is True            # processo mudou (doc novo) → nova versão
    assert AR.mudou("v2", conhecidas) is False           # mesma captura → sem delta
