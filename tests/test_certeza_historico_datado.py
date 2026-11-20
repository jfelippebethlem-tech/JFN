# -*- coding: utf-8 -*-
"""Defeitos medidos em 20/11/2026 no verificador de menções (certeza.db de produção, só leitura):

  · 4 das 4 divergências abertas em `cerebro_registro` eram memórias DATADAS ("medido em 18/11/2026 … R$ X") cujo
    valor era o do registro naquela data — histórico correto acusado como "valor superado";
  · divergência do índice vista UMA vez (19/11 15:30) seguia aberta: com 34 valores superados e teto de 12 buscas
    por ciclo, a superfície `cerebro_indice` nunca era dada por lida — nada curava, e as mesmas 12 eram conferidas;
  · a nota diária da automelhoria transcreve o alarme ("… diz R$ X, vigente R$ …") e o índice a devolvia como
    divergência nova: o alarme se realimentava (a superfície `vault` ignora essa pasta; a do índice não ignorava).

Cada um com controle positivo e negativo. Sem rede, sem tocar em data/."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from compliance_agent.certeza import citacoes, config, fatos

FATO = "pericia_contabil:estado:pago_acima_do_contratado_valor"
BRT = timezone(timedelta(hours=-3))


def _em(dia, mes, hora=12):
    return datetime(2026, mes, dia, hora, tzinfo=BRT).timestamp()


@pytest.fixture()
def cz(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CERTEZA_DIR", str(tmp_path / "certeza"))
    for k in ("SINCRONIZAR", "CEREBRO", "GATILHOS", "KILL"):
        monkeypatch.delenv(f"JFN_CERTEZA_{k}", raising=False)
    con = fatos.conectar()
    yield con
    con.close()


def _registrar(cz, valor, quando, fid=FATO, superados=()):
    vig = fatos.vigente(cz, fid)
    r = fatos.registrar(cz, {"fato_id": fid, "valor": valor, "unidade": "BRL", "estado": "VERIFICADO", "nivel_prova": 2,
                             "fonte": "perícia contábil", "consulta": "data/pericia_contabil.json › excesso",
                             "data_ref": "2026-11-18T19:00:00", "hash_fonte": str(valor), "produtor": "teste",
                             "rotulo": "Pago acima do contratado", "meta": {"superados": list(superados)}},
                        vig["hash_versao"] if vig else None, agora=quando)
    assert r["status"] in ("novo", "atualizado"), r


@pytest.fixture()
def tres_versoes(cz):
    """18/11 19h → 21.824.089,12 · 19/11 15h → 21.821.329,12 · 19/11 16h → 21.817.629,12 (como na produção)."""
    _registrar(cz, 21824089.12, _em(18, 11, 19))
    _registrar(cz, 21821329.12, _em(19, 11, 15))
    _registrar(cz, 21817629.12, _em(19, 11, 16))
    return cz


def _registro(tmp_path, linhas):
    db = tmp_path / "propagacao.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cerebro(chave TEXT PRIMARY KEY, conteudo TEXT)")
    con.executemany("INSERT INTO cerebro VALUES (?,?)", linhas)
    con.commit()
    con.close()
    return db


def _varrer_registro(cz, tmp_path, linhas):
    return citacoes.varrer(cz, {"cerebro": {"registro": True}}, prop_db=_registro(tmp_path, linhas))["divergencias"]


# ════════════════════ memória datada: histórico correto não é alarme ════════════════════

def test_memoria_datada_com_o_valor_que_valia_na_data_nao_e_acusada(tres_versoes, tmp_path):
    d = _varrer_registro(tres_versoes, tmp_path, [
        ("jfn:medicao", "JFN — medido em 18/11/2026: o que passa do valor contratado é R$ 21.824.089,12."),
        # data anterior ao registro existir (o commit é de 17/11): vale a primeira versão conhecida
        ("commit:ba010ffc", "JFN — correção em 17/11/2026 (ba010ffc): o excesso global é R$ 21.824.089,12 (JSON de 17/11 13:57)."),
        ("jfn:iso", "Rodada de 2026-11-19: excesso global de R$ 21.821.329,12 às 15h; depois caiu."),
    ])
    assert d == []


def test_controle_positivo_memoria_sem_data_ou_com_data_que_nao_sustenta_o_valor_e_acusada(tres_versoes, tmp_path):
    d = _varrer_registro(tres_versoes, tmp_path, [
        ("derivado:pericia", "Perícia contábil — pago acima do contratado = R$ 21.824.089,12."),               # sem data
        ("jfn:depois", "JFN — conferido em 20/11/2026: pago acima do contratado R$ 21.824.089,12."),           # já havia o vigente
        ("jfn:errado", "JFN — medido em 18/11/2026: pago acima do contratado R$ 21.821.329,12."),              # não valia em 18/11
    ])
    assert sorted((x["local"], x["encontrado"]) for x in d) == [
        ("memória derivado:pericia", "R$ 21.824.089,12"), ("memória jfn:depois", "R$ 21.824.089,12"),
        ("memória jfn:errado", "R$ 21.821.329,12")]
    assert {x["esperado"] for x in d} == {"R$ 21.817.629,12"}


def test_memoria_datada_que_narra_a_correcao_cita_o_anterior_e_o_que_valia_na_data(cz, tmp_path):
    """A memória #471 real: em 18/11 a nota foi corrigida para 2.437.189,45 e o índice ainda servia 2.270.009,39
    (valor de antes do registro existir — `superados` do mapa). Hoje vigora 2.560.162,04."""
    fid = "iss_nao_retido:00801512000157:180100:valor"
    _registrar(cz, 2437189.45, _em(18, 11, 19), fid, superados=[2270009.39])
    _registrar(cz, 2560162.04, _em(19, 11, 18), fid, superados=[2270009.39])
    txt = ("JFN — em 18/11/2026 a nota do caso foi corrigida às 18:40 (ISS não retido: R$ 2.437.189,45) e a busca "
           "ainda devolvia o valor anterior, R$ 2.270.009,39.")
    assert _varrer_registro(cz, tmp_path, [("jfn:cerebro:indice-defasado", txt)]) == []
    # controle: o mesmo valor pré-registro, sem o que valia na data ao lado → acusado
    d = _varrer_registro(cz, tmp_path, [("jfn:x", "Em 19/11/2026 o ISS não retido era R$ 2.270.009,39.")])
    assert [(x["encontrado"], x["esperado"]) for x in d] == [("R$ 2.270.009,39", "R$ 2.560.162,04")]


def test_nota_viva_do_vault_continua_estrita_mesmo_datada(tres_versoes, tmp_path):
    """Nota é documento vivo (o leitor toma o número por atual): data no parágrafo não a isenta — lá o histórico se
    marca com `<!--fato-historico-->`. Só o registro de memórias (imutável, só-acréscimo) lê a data do texto."""
    pasta = tmp_path / "vault"
    pasta.mkdir()
    (pasta / "caso.md").write_text("Medição de 18/11/2026: R$ 21.824.089,12 acima do contratado.\n", encoding="utf-8")
    v = citacoes.varrer(tres_versoes, {"vault": {"pasta": str(pasta), "glob": "*.md"}})
    assert [x["encontrado"] for x in v["divergencias"]] == ["R$ 21.824.089,12"]


# ════════════════════ índice do cérebro: cura por busca feita, rodízio e pasta ignorada ════════════════════

def _muitos_superados(cz, n=5):
    """n fatos, cada um com um valor superado — mais do que o teto de buscas do ciclo."""
    for i in range(n):
        _registrar(cz, 1000000.11 + i, _em(18, 11, 10), f"teste:f{i}:valor")
        _registrar(cz, 2000000.22 + i, _em(19, 11, 10), f"teste:f{i}:valor")


def _velho(q, k):
    return [{"source": "vault", "path": "jfn/x.md", "heading": "", "snippet": f"total R$ {q} no mês"}]


def test_divergencia_do_indice_cura_quando_a_busca_daquele_valor_volta_limpa_mesmo_sem_ler_tudo(cz, monkeypatch):
    monkeypatch.setattr(config, "TETO_BUSCAS_CEREBRO", 2)
    _muitos_superados(cz)
    sup = {"cerebro": {"busca": True}}
    v = citacoes.varrer(cz, sup, buscar=_velho, agora=1000.0)
    assert len(v["divergencias"]) == 2 and "cerebro_indice" not in v["superficies_lidas"]
    assert citacoes.conciliar(cz, v["divergencias"], v["conferidas"], 1000.0)["abertas"] == 2
    # o índice foi reindexado: as MESMAS buscas voltam limpas → curadas, embora o teto não deixe ler a superfície inteira
    pedidas = []
    for ciclo in range(1, 4):                                   # 5 valores, 2 por ciclo: em 3 ciclos todos foram vistos
        v = citacoes.varrer(cz, sup, buscar=lambda q, k: pedidas.append(q) or [], agora=1000.0 + ciclo)
        r = citacoes.conciliar(cz, v["divergencias"], v["conferidas"], 1000.0 + ciclo)
    assert r["abertas"] == 0
    assert len(set(pedidas)) == 5, "rodízio: o teto por ciclo não pode conferir sempre os mesmos valores"


def test_controle_busca_que_nao_respondeu_nao_cura_a_divergencia_do_indice(cz, monkeypatch):
    monkeypatch.setattr(config, "TETO_BUSCAS_CEREBRO", 2)
    _muitos_superados(cz)
    sup = {"cerebro": {"busca": True}}
    v = citacoes.varrer(cz, sup, buscar=_velho, agora=1000.0)
    citacoes.conciliar(cz, v["divergencias"], v["conferidas"], 1000.0)

    def fora(q, k):
        raise OSError("cérebro fora do ar")
    for ciclo in range(1, 4):
        v = citacoes.varrer(cz, sup, buscar=fora, agora=1000.0 + ciclo)
        r = citacoes.conciliar(cz, v["divergencias"], v["conferidas"], 1000.0 + ciclo)
    assert r["abertas"] == 2 and v["indisponiveis"]


def test_indice_respeita_a_pasta_ignorada_do_vault_o_alarme_nao_se_realimenta(tres_versoes):
    sup = {"vault": {"pasta": "/nao/existe", "ignorar": ["aprendizados/automelhoria"]}, "cerebro": {"busca": True}}
    eco = [{"source": "vault", "path": "aprendizados/automelhoria/2026-11-20.md", "heading": "",
            "snippet": "cerebro_indice: jfn/sinais-criticos.md diz R$ 21.824.089,12, vigente R$"}]
    assert citacoes.varrer(tres_versoes, sup, buscar=lambda q, k: eco)["divergencias"] == []
    nota = [{**eco[0], "path": "jfn/sinais-criticos.md"}]                                   # controle positivo
    d = citacoes.varrer(tres_versoes, sup, buscar=lambda q, k: nota)["divergencias"]
    assert d and {x["tipo"] for x in d} == {"indice_do_cerebro_serve_valor_superado"}
