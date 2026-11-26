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
    assert T.decidir(3, 5, 0, maximo=6)[0] == 3                   # amostra pequena: não mexe


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
