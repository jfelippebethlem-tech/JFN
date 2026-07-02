"""
Ciclo de inteligência progressiva — o loop completo, num comando só.

    python -m compliance_agent.nucleo.ciclo            # roda um ciclo
    python -m compliance_agent.nucleo.ciclo --status   # só mostra o estado

Cada execução:

  1. PERICIA  — se houver banco, varre as maiores OBs/contratos ainda não
                periciados e registra cada laudo na memória pericial.
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


def _periciar_base(session, limite: int = 200) -> dict:
    """
    Varre as maiores OBs ainda não periciadas e alimenta a memória.
    Retorna contadores. Falha de banco não derruba o ciclo.
    """
    novos = com_achados = 0
    try:
        from compliance_agent.database.models import OrdemBancaria
        from compliance_agent.nucleo.adaptador_db import periciar_ob
        from compliance_agent.nucleo.memoria_pericial import _conectar

        con = _conectar()
        try:
            ja = {r for (r,) in con.execute(
                "SELECT DISTINCT referencia FROM pericias").fetchall()}
        finally:
            con.close()

        q = (session.query(OrdemBancaria)
             .filter(OrdemBancaria.valor.isnot(None),
                     OrdemBancaria.valor >= 100_000)
             .order_by(OrdemBancaria.valor.desc())
             .limit(limite * 3))
        for ob in q:
            ref = ob.numero_ob or f"ob:{ob.id}"
            if ref in ja:
                continue
            laudo = periciar_ob(session, ob)
            memoria_pericial.registrar_laudo(laudo, referencia=ref)
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
