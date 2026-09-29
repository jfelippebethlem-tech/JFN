# -*- coding: utf-8 -*-
"""40 documentos exatos, e nada acima: o arquivo do cache tem TETO, e o gate não o via.

Medido em 2026-08-05 sobre o acervo inteiro. Dos **1.902 arquivos montados a partir do CACHE do
sweep, 176 param em exatamente 40 documentos e ZERO passa de 40** — 31 em 39, 11 em 38, e depois o
muro. Nos 274 montados por outro caminho não há muro: 2 em 40, 1 em 41, 1 em 42, 1 em 43. É a
assinatura de contagem redonda que a casa já conhece: o corte `documentos[:40]` que existia no
sweep, hoje já removido do código, mas **congelado nesses arquivos**.

`captura_integra` mede densidade de TEXTO — 40 de 40 documentos com teor — e respondia "íntegro".
Só que a pergunta dela é "capturei tudo?", não "li tudo o que capturei". Sobre esses 176 a
resposta é não, e eles sustentavam **134 acusações de AUSÊNCIA** (63 de pagamento sem evidência de
execução, 25 de planejamento, 22 de formalização, 12 de seleção, 12 de art. 53) e **14 dos 28
processos EXTREMO do acervo**.

`tools/sei_sweep._arquivo_incompleto` usa a MESMA função, então reconhecer o teto aqui devolve
esses processos à fila de recaptura — não é só deixar de acusar, é ir buscar o que falta.
"""
from __future__ import annotations

import json
from pathlib import Path

from compliance_agent.sei import manifesto_norm

_AVISO_CACHE = ("arquivo montado a partir do CACHE do sweep: contém o TEXTO dos documentos, "
                "não os anexos binários nem as fotos de medição")


def _arquivo(tmp_path: Path, n_docs: int, aviso: str | None) -> Path:
    (tmp_path / "texto").mkdir(exist_ok=True)
    docs = []
    for i in range(n_docs):
        nome = f"{i:03d}_doc.txt"
        (tmp_path / "texto" / nome).write_text(
            f"[Documento {i}] (tipo: despacho)\n\nTeor com conteúdo suficiente para contar como "
            f"documento lido de verdade, com mais de quarenta caracteres.", encoding="utf-8")
        docs.append({"i": i, "titulo": f"Documento {i}", "tipo": "despacho",
                     "texto": f"texto/{nome}"})
    man = {"processo": "SEI-000000/000000/2025", "docs": docs}
    if aviso:
        man["aviso"] = aviso
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def test_arquivo_do_cache_com_40_docs_nao_e_integro(tmp_path):
    pasta = _arquivo(tmp_path, 40, _AVISO_CACHE)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    ok, ev = manifesto_norm.captura_integra(man, pasta)
    assert ok is False, "40 documentos vindos do cache é teto de coleta, não processo completo"
    assert ev["teto_de_coleta"] is True
    assert ev["n_com_texto"] == 40, "os 40 têm teor — o problema não é leitura, é captura"


def test_arquivo_do_cache_com_39_docs_segue_integro(tmp_path):
    """O muro é em 40. Trinta e nove é contagem natural — 31 processos do acervo estão ali."""
    pasta = _arquivo(tmp_path, 39, _AVISO_CACHE)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    ok, ev = manifesto_norm.captura_integra(man, pasta)
    assert ok is True and ev["teto_de_coleta"] is False


def test_arquivo_de_OUTRA_origem_com_40_docs_segue_integro(tmp_path):
    """Nos 274 arquivos que não vêm do cache não há muro nenhum (2 em 40, 1 em 41, 1 em 42, 1 em
    43): ali 40 é só um número."""
    pasta = _arquivo(tmp_path, 40, aviso=None)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    ok, ev = manifesto_norm.captura_integra(man, pasta)
    assert ok is True and ev["teto_de_coleta"] is False


def test_teto_nao_e_bandeira_velha_que_o_disco_desmente(tmp_path):
    """A regra do `veto_obsoleto` existe para bandeira posta por captura que falhou e foi refeita
    — o disco a desmente. O teto é o oposto: o disco confirma os 40 textos justamente porque os 40
    são tudo o que se capturou."""
    pasta = _arquivo(tmp_path, 40, _AVISO_CACHE)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    ok, ev = manifesto_norm.captura_integra(man, pasta)
    assert ev["veto_obsoleto"] is False and ok is False
