"""Smoke MANUAL do modo /goal (não é teste do pytest: não tem test_*).

25/11/2026: rodava `asyncio.run(main())` no IMPORT, então toda coleta do pytest (portão, CI, VM-2, it-campo) executava o
HermesGoalAgent de verdade sobre o banco (init_db, definir_missao, ações que podem chamar LLM). Agora só roda à mão:
    python tests/test_goal_modes_smoke.py
"""
import traceback
import asyncio
from compliance_agent.database.models import get_session, init_db
from compliance_agent.hermes_goal import HermesGoalAgent

async def main():
    try:
        init_db()
        session = get_session()
        ag = HermesGoalAgent(session=session)
        ag.definir_missao("Identificar irregularidades em OBs de obras e serviços de engenharia.")
        r1 = await ag.executar_acao("analisar_dados", {"tipo": "sem_sei"})
        r2 = await ag.executar_acao("identificar_padroes", {})
        r3 = await ag.executar_acao("desenvolver_hipoteses", {})
        r4 = await ag.executar_acao("testar_hipoteses", {})
        print("analisar_dados:", r1)
        print("identificar_padroes:", r2)
        print("desenvolver_hipoteses:", r3)
        print("testar_hipoteses:", r4)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
