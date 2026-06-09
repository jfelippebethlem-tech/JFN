"""
checar.py — Saude do sistema JFN em UM disparo.

Testa cada parte UMA vez e imprime [OK] / [X] claro, sem esperar os
loops de 15 min. Mostra exatamente onde esta o problema.

Uso:
    python checar.py
"""

import asyncio
import os
import platform
from datetime import date


# ── Carrega credenciais (.env e/ou .env.txt) ──────────────────────────────────
def _load_env():
    try:
        from compliance_agent.envfile import carregar_env
        lidos = carregar_env()
        if not lidos:
            print("  [X] Nenhum .env / .env.txt encontrado na pasta do projeto.")
    except Exception as e:
        print(f"  [X] Falha ao carregar .env: {e}")


_load_env()


def _mask(v: str) -> str:
    if not v:
        return "(VAZIO)"
    if len(v) <= 4:
        return "****"
    return v[:4] + "..." + v[-3:]


def ok(m):
    print(f"  [OK] {m}")


def bad(m):
    print(f"  [X]  {m}")


async def main():
    print("\n" + "=" * 60)
    print("  JFN — CHECAGEM DE SAUDE DO SISTEMA")
    print("=" * 60)

    # 1. Credenciais ----------------------------------------------------------
    print("\n=== 1. Credenciais (.env) ===")
    obrigatorias = {
        "SIAFE_USER": "login SIAFE2",
        "SIAFE_PASS": "senha SIAFE2",
        "GROQ_API_KEY": "analise rapida (Groq)",
        "OPENROUTER_API_KEY": "Hermes-3 (aprendizado)",
        "TELEGRAM_BOT_TOKEN": "avisos no celular",
        "TELEGRAM_CHAT_ID": "seu chat no Telegram",
    }
    for key, desc in obrigatorias.items():
        v = os.environ.get(key, "")
        (ok if v else bad)(f"{key} = {_mask(v)}   ({desc})")

    # 2. Chrome 9222 ----------------------------------------------------------
    print("\n=== 2. Chrome modo debug (porta 9222) ===")
    print("  (SIAFE2 e DOERJ SO funcionam pelo Chrome aberto na porta 9222)")
    import httpx
    chrome_ok = False
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get("http://127.0.0.1:9222/json/version")
            if r.status_code == 200:
                chrome_ok = True
                ok(f"Chrome no ar: {r.json().get('Browser', '?')}")
            else:
                bad(f"Chrome respondeu HTTP {r.status_code}")
    except Exception as e:
        bad(f"Chrome 9222 inacessivel: {e}")

        if platform.system() == "Windows":
            perfil = os.path.join(os.environ.get("LOCALAPPDATA", ""), "JFN", "ChromeDebug")
            print("       -> Rode HERMES.bat — o passo 4 abre o Chrome no modo debug.")
            print(f"          Perfil que sera usado: {perfil}")
        else:
            print("       -> Rode HERMES.bat — o passo 4 abre o Chrome no modo debug.")

    # 3. DOERJ ----------------------------------------------------------------
    print("\n=== 3. DOERJ (diario oficial - publico) ===")
    if chrome_ok:
        try:
            from compliance_agent.database.models import get_session, init_db
            from compliance_agent.collectors.doerj import DOERJCollector
            init_db()
            s = get_session()
            try:
                pubs = await DOERJCollector(s).coletar_hoje()
                if pubs:
                    ok(f"DOERJ coletou {len(pubs)} publicacoes hoje")
                else:
                    bad("DOERJ retornou 0 publicacoes")
                    print("       -> Normal se for fim de semana/feriado (sem edicao).")
            finally:
                s.close()
        except Exception as e:
            bad(f"DOERJ falhou: {type(e).__name__}: {e}")
    else:
        bad("pulado (Chrome 9222 off)")

    # 4. SIAFE2 ---------------------------------------------------------------
    print("\n=== 4. SIAFE2 (rede do governo) ===")
    if chrome_ok:
        try:
            from compliance_agent.collectors.siafe_ob import run_daily_collection
            r = await run_daily_collection(date.today(), collect_details=False)
            n = r.get("records_saved", 0)
            errs = r.get("errors", [])
            if n:
                ok(f"SIAFE leu e salvou {n} OBs hoje")
            else:
                bad("SIAFE leu 0 OBs")
                for e in errs[:3]:
                    print(f"       -> {e}")
                print("       -> Se aparece 'login'/'autenticacao': cheque a rede do")
                print("          governo (VPN) e SIAFE_USER / SIAFE_PASS no .env.")
        except Exception as e:
            bad(f"SIAFE falhou: {type(e).__name__}: {e}")
    else:
        bad("pulado (Chrome 9222 off)")

    # 5. Groq -----------------------------------------------------------------
    print("\n=== 5. Groq (analise rapida das OBs) ===")
    try:
        from compliance_agent.llm.free_llm import groq_available, groq_chat_async
        if not groq_available():
            bad("GROQ_API_KEY ausente — analise por IA desligada")
            print("       -> Pegue chave gratis em https://console.groq.com e ponha no .env")
        else:
            resp = await groq_chat_async("Responda apenas: OK", system="Teste.")
            ok(f"Groq respondeu: {resp[:40].strip()}")
    except Exception as e:
        bad(f"Groq falhou: {type(e).__name__}: {e}")

    # 6. Hermes (cascata de modelos) ------------------------------------------
    print("\n=== 6. Hermes (OpenRouter - aprendizado) ===")
    try:
        from compliance_agent.llm.free_llm import openrouter_available
        from compliance_agent.llm import hermes_agent as _ha

        if not openrouter_available():
            bad("OPENROUTER_API_KEY ausente — Hermes NAO roda")
            print("       -> Pegue uma chave gratis em https://openrouter.ai e ponha no .env")
        else:
            # Testa a cascata completa: _hermes() tenta 405B, faz fallback automatico se der 429
            import time
            _ha._ultima_chamada = 0.0  # reseta rate-limit interno para o teste
            t0 = time.time()
            resp = await _ha._hermes(
                "Voce e um assistente de teste.",
                "Responda apenas com a palavra: OK",
                max_tokens=10,
            )
            dt = time.time() - t0
            # Detecta qual modelo foi usado (modelo de fallback imprime no console)
            if resp.strip():
                ok(f"Hermes respondeu em {dt:.1f}s: {resp.strip()[:60]}")
            else:
                bad("Hermes retornou resposta vazia")
    except Exception as e:
        errmsg = str(e)
        bad(f"Hermes falhou: {errmsg[:120]}")
        if "429" in errmsg:
            print("       -> Todos os modelos :free com cota esgotada.")
            print("          Aguarde alguns minutos e rode checar.py de novo.")
            print("          Com GROQ_API_KEY no .env, Groq serve de fallback.")
        elif "OPENROUTER_API_KEY" in errmsg:
            print("       -> Configure OPENROUTER_API_KEY no .env")

    # 7. Telegram -------------------------------------------------------------
    print("\n=== 7. Telegram ===")
    try:
        from compliance_agent.notifications.telegram import enviar_mensagem, BOT_TOKEN
        if not BOT_TOKEN:
            bad("TELEGRAM_BOT_TOKEN ausente")
        else:
            r = await enviar_mensagem("Checagem JFN: teste de conexao OK.")
            if r.get("ok"):
                ok("Telegram enviou mensagem de teste (veja seu celular)")
            else:
                desc = str(r.get("description", r))
                bad(f"Telegram recusou: {desc}")
                if "chat not found" in desc.lower():
                    print("       -> Abra o Telegram e mande /start para o bot uma vez.")
    except Exception as e:
        bad(f"Telegram falhou: {type(e).__name__}: {e}")

    # 8. Banco de dados -------------------------------------------------------
    print("\n=== 8. Banco de dados (o que ja foi coletado) ===")
    try:
        from compliance_agent.database.models import get_session, init_db, OrdemBancaria, Alerta
        init_db()
        s = get_session()
        try:
            n_obs = s.query(OrdemBancaria).count()
            n_alertas = s.query(Alerta).count()
            ok(f"{n_obs} OBs e {n_alertas} alertas no banco")
            if n_obs == 0:
                print("       -> Banco vazio: por isso o Hermes nao tem o que aprender.")
                print("          Resolva a coleta (passos 2/3/4 acima) primeiro.")
        finally:
            s.close()
    except Exception as e:
        bad(f"Banco falhou: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("  FIM. As linhas [X] mostram o que precisa de atencao.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    try:
        input("\nPressione ENTER para fechar...")
    except (EOFError, KeyboardInterrupt):
        pass
