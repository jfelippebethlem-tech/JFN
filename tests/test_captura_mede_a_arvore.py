# -*- coding: utf-8 -*-
"""O gate de captura passa a medir o que EXISTE, não só o que foi lido.

O DEFEITO, medido em 2026-08-07. `sei_arquivar_do_cache` lê o cache do sweep, que traz DUAS listas:
`documentos` (a árvore inteira do processo) e `conteudo_documentos` (o que se conseguiu ler). Ele
usava a segunda e jogava a primeira fora. O manifesto saía com `lacunas: []` e
`qualidade_cache: completo` sobre processos com **40 de 956 documentos** — e o motor, sem nada que
o desmentisse, afirmava ausência de prova de execução sobre um arquivo que tinha 4% do processo.

`captura_integra` até tinha uma defesa, mas era HEURÍSTICA: reconhecia a assinatura do corte antigo
(exatamente 40 documentos vindos do cache). Heurística erra nos dois sentidos, e as duas foram
medidas no acervo real:

- **171 processos truncados** que ela pegava por sorte — porque o corte de então era 40. Um corte
  em qualquer outro número passaria batido.
- **21 processos COMPLETOS** cuja árvore tem exatamente 40 documentos. Estavam sendo excluídos da
  análise por causa de um número redondo.

O conserto é gravar o fato: `docs_na_arvore` no manifesto, e o gate obedecendo a ele quando existe.

POR QUE NÃO TOLERAR UMA FOLGA. A distribuição do acervo mostra 497 processos com exatamente dois
documentos faltando — um deslocamento fixo tem cara de nó estrutural da árvore, e a tentação é
tolerá-lo. Fui ver QUAIS documentos são: "Nota de Liquidação", "Comprovante", "Anexo NOB - IRRF",
"Despacho de Formalização de Liquidação de Despesa". São exatamente as peças que provam pagamento
e execução — justamente o que as acusações de ausência afirmam não existir. Folga aqui seria
tolerância no lugar onde ela mais custa.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.sei import manifesto_norm


def _pasta_com_textos(tmp_path, n: int):
    txt = tmp_path / "texto"
    txt.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (txt / f"{i:03d}_doc.txt").write_text(
            f"[Documento {i}] conteúdo suficiente para contar como lido, com folga sobre o "
            f"mínimo que o acervo_texto exige para não ser considerado etiqueta vazia." * 3,
            encoding="utf-8")
    return tmp_path


def _manifest(n_docs: int, *, na_arvore=None, do_cache=True):
    m = {"processo": "080002/000001/2024",
         "docs": [{"titulo": f"Documento {i}", "tipo": "despacho"} for i in range(n_docs)]}
    if do_cache:
        m["aviso"] = "arquivo montado a partir do CACHE do sweep: contém o TEXTO dos documentos"
    if na_arvore is not None:
        m["docs_na_arvore"] = na_arvore
    return m


def test_arvore_maior_que_o_arquivo_derruba_a_captura_integra(tmp_path):
    """40 de 956 documentos não é captura íntegra, por mais denso que seja o texto dos 40."""
    pasta = _pasta_com_textos(tmp_path, 40)
    integra, ev = manifesto_norm.captura_integra(_manifest(40, na_arvore=956), pasta)
    assert integra is False
    assert ev["teto_de_coleta"] is True
    assert ev["docs_na_arvore"] == 956
    assert ev["faltam_capturar"] == 916, "o TAMANHO do buraco tem de viajar com o veredito"


def test_arvore_de_exatamente_40_nao_e_truncamento(tmp_path):
    """Os 21 processos que a heurística punia por causa de um número redondo.

    Árvore com 40 documentos e 40 documentos lidos é captura COMPLETA. A regra anterior via '40
    vindo do cache' e vetava — excluindo da análise processos que tinham sido lidos por inteiro.
    """
    pasta = _pasta_com_textos(tmp_path, 40)
    integra, ev = manifesto_norm.captura_integra(_manifest(40, na_arvore=40), pasta)
    assert integra is True, "árvore de 40 com 40 lidos está COMPLETA — o número redondo é coincidência"
    assert ev["teto_de_coleta"] is False
    assert ev["faltam_capturar"] == 0


def test_faltar_dois_documentos_ainda_e_truncamento(tmp_path):
    """497 processos do acervo estão a exatamente dois documentos do total — e isso NÃO é folga.

    Os que faltam são Nota de Liquidação, Comprovante e Anexo: as peças que sustentam a prova de
    pagamento e execução. Tolerar dois seria abrir exceção exatamente onde ela mais custa.
    """
    pasta = _pasta_com_textos(tmp_path, 8)
    integra, ev = manifesto_norm.captura_integra(_manifest(8, na_arvore=10), pasta)
    assert integra is False
    assert ev["faltam_capturar"] == 2


def test_manifesto_legado_sem_o_campo_cai_na_heuristica_antiga(tmp_path):
    """Compatibilidade: 52 manifestos não têm cache correspondente e nunca ganharão o campo.

    Para eles a heurística do 40 continua sendo a única defesa — retirá-la devolveria ao acervo
    o defeito que ela cobria. Ela só perde a vez quando existe fato melhor.
    """
    pasta = _pasta_com_textos(tmp_path, 40)
    integra, ev = manifesto_norm.captura_integra(_manifest(40), pasta)
    assert integra is False
    assert ev["teto_de_coleta"] is True
    assert ev["docs_na_arvore"] is None


def test_o_fato_manda_sobre_a_heuristica(tmp_path):
    """Prova negativa da regra: com o campo presente, o número 40 deixa de ter poder próprio."""
    pasta = _pasta_com_textos(tmp_path, 40)
    com_fato, _ = manifesto_norm.captura_integra(_manifest(40, na_arvore=40), pasta)
    sem_fato, _ = manifesto_norm.captura_integra(_manifest(40), pasta)
    assert com_fato != sem_fato, (
        "o campo `docs_na_arvore` não está mandando — se os dois derem o mesmo veredito, o "
        "conserto não chegou ao gate e os 21 completos seguem excluídos")


def test_arquivador_grava_arvore_e_lacuna_declarada(tmp_path, monkeypatch):
    """O arquivador tem o tamanho da árvore em mãos: a lacuna precisa sair ESCRITA, não implícita.

    `lacunas: []` sobre 40 de 956 é o que fazia o motor ler ausência de prova como ausência do
    fato. A lacuna declarada diz, no próprio arquivo, que a falta é NOSSA.
    """
    from tools import sei_arquivar_do_cache as A

    destino = tmp_path / "arquivo"
    monkeypatch.setattr(A, "ARQUIVO", destino)
    item = {"numero": "SEI-080002/000001/2024", "cache": tmp_path / "cdp_x.json",
            "chars": 10_000, "qualidade": "completo", "na_arvore": 100,
            "dados": {"numero": "SEI-080002/000001/2024",
                      "documentos": [{"titulo": f"D{i}"} for i in range(100)],
                      "conteudo_documentos": [
                          {"titulo": f"D{i}", "conteudo": "texto real do documento " * 40}
                          for i in range(30)]}}
    A.arquivar(item, aplicar=True)
    man = json.loads((destino / "080002_000001_2024" / "manifest.json").read_text(encoding="utf-8"))
    assert man["docs_na_arvore"] == 100
    lac = man["lacunas"]
    assert len(lac) == 1 and lac[0]["tipo"] == "captura_truncada"
    assert lac[0]["faltam"] == 70
    assert "não do processo" in lac[0]["consequencia"], (
        "a lacuna precisa dizer de quem é a falta — sem isso ela vira acusação contra o processo")


def test_arquivo_completo_nao_ganha_lacuna_inventada(tmp_path, monkeypatch):
    """Controle: quem leu a árvore inteira não pode sair com lacuna — ruído desacredita o resto."""
    from tools import sei_arquivar_do_cache as A

    destino = tmp_path / "arquivo"
    monkeypatch.setattr(A, "ARQUIVO", destino)
    item = {"numero": "SEI-080002/000002/2024", "cache": tmp_path / "cdp_y.json",
            "chars": 10_000, "qualidade": "completo", "na_arvore": 12,
            "dados": {"numero": "SEI-080002/000002/2024",
                      "documentos": [{"titulo": f"D{i}"} for i in range(12)],
                      "conteudo_documentos": [
                          {"titulo": f"D{i}", "conteudo": "texto real do documento " * 40}
                          for i in range(12)]}}
    A.arquivar(item, aplicar=True)
    man = json.loads((destino / "080002_000002_2024" / "manifest.json").read_text(encoding="utf-8"))
    assert man["docs_na_arvore"] == 12
    assert man["lacunas"] == []


def test_arquivador_enxerga_cache_comprimido():
    """5.660 dos 6.195 blobs estão em `.json.zst` — com o glob cru, via 535 (8,6%).

    Terceira ferramenta da casa cega à compressão. O teste não depende do acervo: exige que o
    arquivador use os leitores que sabem descomprimir, em vez de `Path.glob` + `read_text`.
    """
    from pathlib import Path as _P

    fonte = _P("tools/sei_arquivar_do_cache.py").read_text(encoding="utf-8")
    assert "glob_cache(" in fonte, "voltou a varrer o cache com glob cru — perde 91% do acervo"
    assert "ler_json(" in fonte, "voltou a ler o cache com read_text — quebra no blob comprimido"
    assert 'CACHE.glob("cdp_*.json")' not in fonte
