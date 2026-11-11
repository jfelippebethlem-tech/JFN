"""
Ciclo de inteligência progressiva — o loop completo, num comando só.

    python -m compliance_agent.nucleo.ciclo            # roda um ciclo
    python -m compliance_agent.nucleo.ciclo --status   # só mostra o estado

Cada execução:

  1. PERICIA  — se houver banco, varre as OBs do SIAFE (contabilizadas) ainda não
                periciadas, por cursor, e registra cada laudo na memória pericial.
                (cada perícia torna as referências de preço mais precisas)
  2. AVALIA   — mede o desempenho no conjunto-ouro (placar F1).
  3. APRIMORA — roda o loop de autoaprimoramento: testa calibrações e mantém
                só as que comprovadamente melhoram o placar.
  4. RELATA   — devolve um relatório JSON/texto do que aprendeu e mudou.

Ideal para rodar no systemd timer (ex.: diário, junto do jfn-tfe.timer) ou no
ciclo do Auditor 24h. É o "sono REM" do sistema: consolida o que viu de dia e
acorda mais calibrado.
"""

from __future__ import annotations

import json
import sys

from compliance_agent.nucleo import aprendizado, memoria_pericial
from compliance_agent.nucleo.autoaprimoramento import executar_loop, historico_evolucao
from compliance_agent.nucleo.avaliacao import avaliar_sistema


_PAGINA = 500


def _data_siafe(txt):
    """`data_emissao` do SIAFE é TEXTO 'dd/mm/aaaa' — vira date (a régua de sanção vigente compara ISO)."""
    from datetime import datetime
    try:
        return datetime.strptime((txt or "").strip()[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def _ob_siafe(row):
    """Linha de `ob_orcamentaria_siafe` → objeto que `periciar_ob` lê por getattr. Chave = (numero_ob, UG,
    exercício): `numero_ob` sozinho NÃO é único entre UGs (cada UG numera as suas)."""
    from types import SimpleNamespace
    numero_ob, ug, exercicio, data, credor, nome, processo, valor = row
    return SimpleNamespace(
        numero_ob=numero_ob, ug_codigo=ug, ug_nome=ug or "", exercicio=exercicio,
        referencia_pericia=f"siafe:{numero_ob}:{ug}:{exercicio}", fonte_pericia="siafe_ob",
        favorecido_cpf=credor or "", favorecido_nome=nome or "", valor=valor,
        data_emissao=_data_siafe(data), observacao=f"OB {numero_ob} · processo {processo or '—'}",
        categoria="", tipo_ob="")


def _paginar(session, filtro: str, params: dict):
    """Cursor por (valor desc, rowid desc) — página a página, SEM teto: quem para é o consumidor, ao achar
    `limite` OBs novas. O teto fixo (`.limit(limite*3)`) cortava ANTES do filtro do já periciado."""
    from sqlalchemy import text
    ultimo = None
    while True:
        cond = "" if ultimo is None else " AND (valor < :uv OR (valor = :uv AND rowid < :ur))"
        rows = session.execute(text(
            "SELECT rowid, numero_ob, ug_emitente, exercicio, data_emissao, credor, nome_credor, processo, valor "
            "FROM ob_orcamentaria_siafe WHERE status LIKE 'contabiliz%' AND valor IS NOT NULL AND "
            + filtro + cond + " ORDER BY valor DESC, rowid DESC LIMIT :pag"),
            {**params, "pag": _PAGINA, **({} if ultimo is None else {"uv": ultimo[0], "ur": ultimo[1]})}).fetchall()
        if not rows:
            return
        for r in rows:
            yield _ob_siafe(tuple(r)[1:])
        ultimo = (rows[-1][8], rows[-1][0])


def _obs_alvo(session, limite: int):
    """
    Duas miras, na ordem: (1) OBs de favorecidos SANCIONADOS (CEIS/CNEP local)
    — alto rendimento, qualquer valor relevante; (2) maiores OBs da base.
    Só as maiores re-encontraria sempre transferências estruturais.

    11/11/2026: fonte = `ob_orcamentaria_siafe`, só OB Contabilizada (regra "OB → sempre SIAFE"; anulada e
    excluída não são pagamento). Antes lia o espelho TFE `ordens_bancarias` e só as 600 maiores — esgotadas,
    `pericias_novas: 0` todo dia de 25/10 a 11/11. Agora é cursor: segue até o consumidor parar.
    """
    from sqlalchemy import text
    try:
        tem_sancao = session.execute(text("SELECT 1 FROM sancoes_federais LIMIT 1")).fetchone() is not None
    except Exception:
        tem_sancao = False
    if tem_sancao:
        yield from _paginar(session, "valor >= 10000 AND credor IN (SELECT cpf_cnpj FROM sancoes_federais)", {})
    yield from _paginar(session, "valor >= 100000", {})


def _periciar_base(session, limite: int = 200) -> dict:
    """
    Varre OBs ainda não periciadas (sancionados primeiro, depois as maiores)
    e alimenta a memória. Retorna contadores. Falha de banco não derruba o ciclo.
    """
    novos = com_achados = 0
    try:
        from compliance_agent.nucleo.adaptador_db import periciar_ob
        from compliance_agent.nucleo.memoria_pericial import _conectar

        con = _conectar()
        try:
            ja = {r for (r,) in con.execute(
                "SELECT DISTINCT referencia FROM pericias").fetchall()}
        finally:
            con.close()

        for ob in _obs_alvo(session, limite):
            ref = ob.referencia_pericia  # siafe:<numero_ob>:<ug>:<exercício>
            if ref in ja:
                continue
            ja.add(ref)  # as duas miras podem trazer a mesma OB
            # periciar_ob já registra na memória (usar_memoria=True)
            laudo = periciar_ob(session, ob)
            novos += 1
            if laudo.veredito.achados:
                com_achados += 1
            if novos >= limite:
                break
    except Exception as e:
        return {"pericias_novas": novos, "com_achados": com_achados,
                "aviso": f"varredura parcial: {e}"}
    return {"pericias_novas": novos, "com_achados": com_achados}


def rodar_ciclo(session=None, limite_pericias: int = 200) -> dict:
    """Executa um ciclo completo e devolve o relatório estruturado."""
    relatorio: dict = {}

    # 1. Perícia em lote (opcional — precisa de session do banco).
    if session is not None:
        relatorio["varredura"] = _periciar_base(session, limite_pericias)

    # 2+3. Avaliação + autoaprimoramento (sempre rodam; offline-safe).
    evolucao = executar_loop()
    relatorio["placar"] = {
        "f1_inicial": evolucao.placar_inicial.f1_global,
        "f1_final": evolucao.placar_final.f1_global,
        "falsos_alarmes": evolucao.placar_final.falsos_alarmes,
        "cobertura": evolucao.placar_final.cobertura,
    }
    relatorio["calibracoes_mantidas"] = evolucao.mantidos
    relatorio["calibracoes_revertidas"] = evolucao.revertidos
    relatorio["red_flags_propostas"] = evolucao.red_flags_propostas
    relatorio["sinal"] = {"saturado": evolucao.saturado,
                          "sem_caso_real": evolucao.sem_caso_real,
                          "casos_reais": evolucao.casos_reais,
                          "motivo": evolucao.motivo}

    # 4. Estado da memória e do feedback.
    relatorio["memoria"] = memoria_pericial.estatisticas()
    relatorio["precisao_indicadores"] = [
        {"indicador": p.indicador_id, "precisao": p.precisao, "amostra": p.amostra}
        for p in aprendizado.precisao_por_indicador()
    ]
    return relatorio


def status() -> dict:
    """Estado atual sem executar nada (para painel/telegram)."""
    placar = avaliar_sistema()
    return {
        "placar_ouro": {"f1": placar.f1_global, "precisao": placar.precisao,
                        "cobertura": placar.cobertura,
                        "falsos_alarmes": placar.falsos_alarmes},
        "memoria": memoria_pericial.estatisticas(),
        "evolucoes_registradas": len(historico_evolucao()),
    }


def _main() -> int:
    if "--status" in sys.argv:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    # Tenta abrir a sessão do banco do projeto; sem ela, roda offline.
    session = None
    try:
        from compliance_agent.database.models import get_session  # type: ignore
        session = get_session()
    except Exception:
        pass
    rel = rodar_ciclo(session)
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
