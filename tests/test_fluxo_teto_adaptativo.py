"""26/11/2026: quantos logins simultâneos o SEI-RJ aguenta não é chute — o motor mede. AIMD sobre a taxa de falha de
CONEXÃO dos jobs do SEI (árvore e captura): < 2 % sobe 1 (até o teto do yaml), > 5 % corta pela metade (mín. 1); com
amostra pequena não mexe. Medido na janela 1: serial 0 conexão fechada em 74; 6 com login novo, 10 em 45 (22 %)."""
import json

from compliance_agent.fluxo import teto_adaptativo as T
from tests.fluxo_pg import con, esquema_tmp, precisa_pg  # noqa: F401 — fixtures


def test_decidir_aimd():
    assert T.decidir(2, 40, 0, maximo=6)[0] == 3                  # saudável: +1
    assert T.decidir(6, 40, 0, maximo=6)[0] == 6                  # já no teto do yaml
    assert T.decidir(6, 45, 10, maximo=6)[0] == 3                 # 22 % de conexão fechada: metade
    assert T.decidir(1, 45, 10, maximo=6)[0] == 1                 # nunca abaixo de 1
    assert T.decidir(3, 40, 1, maximo=6)[0] == 3                  # 2,5 %: zona morta, mantém
    assert T.decidir(3, 5, 0, maximo=6)[0] == 3                   # amostra pequena: não SOBE
    # 26/11 17h15: 3 sessões derrubaram os logins e a vazão caiu a 9 jobs na janela — a amostra mínima travava a
    # DESCIDA. Falha em massa não espera amostra: 3+ falhas de conexão acima de 5 % cortam já.
    assert T.decidir(3, 9, 5, maximo=6)[0] == 1
    assert T.decidir(3, 4, 2, maximo=6)[0] == 3                   # 2 falhas soltas em amostra pequena: mantém


def test_erro_de_conexao_reconhecido():
    assert T.e_erro_de_conexao("RuntimeError: login no SEI falhou — Page.goto: net::ERR_CONNECTION_CLOSED at https://")
    assert T.e_erro_de_conexao("TimeoutError: Page.goto: Timeout 30000ms exceeded")
    assert not T.e_erro_de_conexao("[fora_de_alcance] SEI respondeu RESTRITO")
    assert not T.e_erro_de_conexao("árvore vazia (via 'campo de pesquisa não apareceu')")


@precisa_pg
def test_medir_e_vigente(con):
    for i in range(30):
        con.execute("INSERT INTO jobs(tipo, chave, estado, payload, concluido_em) VALUES ('arvore', %s, 'feito', %s, now())",
                    (f"arvore:{i}", json.dumps({})))
    con.execute("INSERT INTO jobs(tipo, chave, estado, payload, erro_resumo, iniciado_em) VALUES ('capturar', 'c:x', 'fila', "
                "%s, 'login no SEI falhou — net::ERR_CONNECTION_CLOSED', now())", (json.dumps({}),))
    m = T.medir(con)
    assert m["n"] == 31 and m["erros"] == 1
    assert T.vigente(con, maximo=6) is None
    r = T.rodar(con, maximo=6, atual_padrao=2)
    assert r["novo"] == 2 and T.vigente(con, maximo=6) == 2       # 1/31 = 3,2 %: zona morta, mantém o 2


@precisa_pg
def test_nao_volta_ao_nivel_que_falhou(con):
    """Sem memória o controle oscilava 2→3→corte→2→3 a cada ~45 min, derrubando os logins a cada subida. O nível que
    sofreu corte nas últimas 6 h vira teto: sobe até ele − 1."""
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'teto_adaptativo', 1, %s)",
                (json.dumps({"etiqueta": "sei_rj_ip", "corte_de": 3}),))
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'teto_adaptativo', 2, %s)",
                (json.dumps({"etiqueta": "sei_rj_ip"}),))
    for i in range(30):
        con.execute("INSERT INTO jobs(tipo, chave, estado, payload, concluido_em) VALUES ('arvore', %s, 'feito', '{}', "
                    "now())", (f"arvore:m{i}",))
    r = T.rodar(con, maximo=6)
    assert r["novo"] == 2 and "falhou" in r["motivo"]
