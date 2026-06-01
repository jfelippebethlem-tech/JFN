"""
Groq-powered autonomous SIAFE2 explorer.

Uses a Groq LLM (llama3 / mixtral) to observe the current state of the SIAFE2
browser and decide what to click/fill next — essentially an LLM agent that
drives Chrome the same way a human would, but faster and persistently.

The loop:
    1. Capture page state (visible text, inputs, clickable elements, screenshot)
    2. Send state to Groq with a task description
    3. Groq responds with a JSON action: {type, target, value, reason}
    4. Execute the action in the browser
    5. Repeat until task is complete or max_steps reached

Usage:
    from siafe_agent.llm.groq_explorer import SIAFEGroqExplorer
    explorer = SIAFEGroqExplorer()
    await explorer.run_task("Map all fields in the OB Orçamentária detail screen")

Or standalone:
    python -m siafe_agent.llm.groq_explorer
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

GROQ_API_KEY = os.environ.get(
    "GROQ_API_KEY",
    "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",
)
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SCREENSHOTS = Path("diagnostic_screenshots")
SCREENSHOTS.mkdir(exist_ok=True)

_SYSTEM_PROMPT = """
You are an expert at navigating Oracle ADF Fusion web applications, specifically the
SIAFE2 government financial system used by the Rio de Janeiro state (Brazil).

SIAFE2 uses minified CSS class names:
- a.xyo  — top-level main menu items
- a.xgh  — second-level menu (submenu bar)
- a.xgg  — third-level dropdown items (e.g. "OB Orçamentária")
- a.xg8  — left panel navigation links
- a.xyp  — detail page tabs (Detalhamento, Itens, Pagamentos, Processo, etc.)
- a.x7j  — action buttons (Ok, Sim, Não, Consultar, etc.)
- a.xg2  — modal buttons

CRITICAL RULES:
- NEVER click a.xyo "Execução" — it navigates away to a different system (FlexVision)
- To navigate to OB Orçamentária: click a.xgg "OB Orçamentária" (always in DOM)
- All DOM interactions must specify exact CSS selector + text
- ADF uses Partial Page Refresh (PPR) — always wait after clicks

You respond ONLY with a valid JSON object (no markdown, no explanation outside JSON):
{
  "action": "click" | "fill" | "wait" | "done" | "navigate",
  "selector": "CSS selector string",
  "text": "exact element text to match (for click)",
  "value": "value to fill (for fill action)",
  "url": "URL to navigate to (for navigate action)",
  "reason": "brief explanation of why this action advances the task",
  "task_complete": false
}

When the task is fully complete, set "task_complete": true and "action": "done".
"""


async def _get_page_state(page) -> dict:
    """Capture minimal page state for LLM consumption."""
    url = page.url
    title = await page.title()

    visible_text = ""
    try:
        body = await page.inner_text("body")
        visible_text = body[:2000]
    except Exception:
        pass

    elements = await page.evaluate("""
        () => {
            const results = [];
            const sels = ['a.xyo', 'a.xgh', 'a.xgg', 'a.xg8', 'a.xyp', 'a.x7j', 'a.xg2'];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0) continue;
                    const t = el.textContent.trim();
                    if (!t || t.length > 100) continue;
                    results.push({
                        sel, text: t,
                        disabled: el.className.includes('p_AFDisabled'),
                        selected: el.className.includes('p_AFSelected'),
                    });
                }
            }
            return results;
        }
    """)

    inputs = await page.evaluate("""
        () => {
            const results = [];
            for (const el of document.querySelectorAll('input, select, textarea')) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0) continue;
                results.push({
                    tag: el.tagName,
                    id: el.id || '',
                    type: el.type || '',
                    value: (el.value || '').substring(0, 60),
                });
            }
            return results;
        }
    """)

    return {
        "url": url,
        "title": title,
        "visible_text_excerpt": visible_text,
        "clickable_elements": elements[:60],
        "inputs": inputs[:30],
    }


async def _call_groq(messages: list[dict], max_tokens: int = 500) -> str | None:
    """Call Groq API and return the assistant message text."""
    try:
        import httpx
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
        import httpx

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GROQ_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _execute_action(page, action: dict) -> str:
    """Execute a single LLM-decided action in the browser."""
    act = action.get("action", "")
    reason = action.get("reason", "")
    print(f"  → {act}: {reason}")

    if act == "done":
        return "done"

    if act == "wait":
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        return "waited"

    if act == "navigate":
        url = action.get("url", "")
        if url:
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(2)
        return f"navigated to {url}"

    if act == "click":
        selector = action.get("selector", "")
        text = action.get("text", "")
        text_js = text.replace("'", "\\'")
        sel_js = selector.replace("'", "\\'")

        result = await page.evaluate(f"""
            () => {{
                const els = document.querySelectorAll('{sel_js}');
                for (const el of els) {{
                    const t = el.textContent.trim();
                    const r = el.getBoundingClientRect();
                    if (('{text_js}' === '' || t === '{text_js}' || t.includes('{text_js[:15]}'))
                        && r.width > 0 && !el.className.includes('p_AFDisabled')) {{
                        el.click();
                        return 'clicked: ' + t;
                    }}
                }}
                return null;
            }}
        """)
        if result:
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await asyncio.sleep(1)
            return result
        return f"element not found: {selector} / {text}"

    if act == "fill":
        selector = action.get("selector", "")
        value = action.get("value", "")
        sel_js = selector.replace("'", "\\'")
        val_js = value.replace("'", "\\'")

        result = await page.evaluate(f"""
            () => {{
                const el = document.querySelector('{sel_js}');
                if (el && el.getBoundingClientRect().width > 0) {{
                    el.value = '{val_js}';
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    el.dispatchEvent(new Event('blur', {{bubbles: true}}));
                    return 'filled: ' + el.id;
                }}
                return null;
            }}
        """)
        await asyncio.sleep(0.5)
        return result or f"input not found: {selector}"

    return f"unknown action: {act}"


class SIAFEGroqExplorer:
    """
    LLM-driven autonomous SIAFE2 browser agent.

    The explorer maintains conversation history so the LLM has full context
    of what it has already done in each session.
    """

    def __init__(self, model: str = GROQ_MODEL, max_steps: int = 30):
        self.model = model
        self.max_steps = max_steps
        self._history: list[dict] = []
        self._log: list[str] = []

    def _lprint(self, msg: str):
        print(msg)
        self._log.append(msg)

    async def run_task(self, task: str, page=None) -> dict:
        """
        Run an autonomous task on a SIAFE2 page.

        If page is None, connects to Chrome via CDP on port 9222.
        Returns {steps, actions, log, success}.
        """
        from playwright.async_api import async_playwright

        own_browser = page is None
        p = browser = None

        if own_browser:
            p = await async_playwright().start()
            try:
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            except Exception as e:
                return {"success": False, "error": str(e), "log": self._log}

            page = None
            for ctx in browser.contexts:
                for pg in ctx.pages:
                    url = pg.url.lower()
                    if "siafe2.fazenda" in url and "flexvision" not in url:
                        page = pg
                        break
                if page:
                    break
            if not page and browser.contexts and browser.contexts[0].pages:
                page = browser.contexts[0].pages[0]

            if not page:
                await p.stop()
                return {"success": False, "error": "No SIAFE2 page found", "log": self._log}

        self._lprint(f"\n🤖 Groq Explorer — tarefa: {task}")
        self._lprint(f"   Modelo: {self.model} | max_steps: {self.max_steps}")

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        actions_taken = []

        for step in range(self.max_steps):
            self._lprint(f"\n── Passo {step + 1}/{self.max_steps} ──")

            state = await _get_page_state(page)
            self._lprint(f"   URL: {state['url']}")
            self._lprint(f"   Elementos clicáveis: {len(state['clickable_elements'])}")

            state_summary = (
                f"URL: {state['url']}\n"
                f"Title: {state['title']}\n"
                f"Visible text (excerpt):\n{state['visible_text_excerpt'][:800]}\n\n"
                f"Clickable elements:\n"
                + "\n".join(
                    f"  [{e['sel']}] {e['text']!r}"
                    + (" [DISABLED]" if e['disabled'] else "")
                    + (" [SELECTED]" if e['selected'] else "")
                    for e in state['clickable_elements'][:40]
                )
                + f"\n\nInputs:\n"
                + "\n".join(
                    f"  <{i['tag']}> id={i['id']!r} type={i['type']!r} value={i['value']!r}"
                    for i in state['inputs'][:20]
                )
            )

            user_msg = (
                f"TASK: {task}\n\n"
                f"CURRENT STATE:\n{state_summary}\n\n"
                f"Steps taken so far: {step}\n"
                "What is your next action?"
            )
            messages.append({"role": "user", "content": user_msg})

            try:
                raw_response = await _call_groq(messages, max_tokens=400)
            except Exception as e:
                self._lprint(f"   Groq API error: {e}")
                break

            self._lprint(f"   Groq → {raw_response[:200]}")
            messages.append({"role": "assistant", "content": raw_response})

            # Parse JSON action
            try:
                clean = raw_response.strip()
                if "```" in clean:
                    clean = clean.split("```")[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                action = json.loads(clean)
            except (json.JSONDecodeError, IndexError) as e:
                self._lprint(f"   JSON parse error: {e} — raw: {raw_response[:200]}")
                continue

            result = await _execute_action(page, action)
            self._lprint(f"   Result: {result}")
            actions_taken.append({
                "step": step + 1,
                "action": action,
                "result": result,
            })

            if action.get("task_complete") or action.get("action") == "done":
                self._lprint(f"\n✅ Task complete after {step + 1} steps")
                break

        if own_browser and p:
            await p.stop()

        return {
            "success": True,
            "steps": len(actions_taken),
            "actions": actions_taken,
            "log": self._log,
        }


async def explore_ob_screen():
    """Standalone: use Groq to autonomously map the OB Orçamentária screen."""
    explorer = SIAFEGroqExplorer(max_steps=25)
    result = await explorer.run_task(
        "Navigate to OB Orçamentária (click a.xgg 'OB Orçamentária'), "
        "then execute a search for the current month, open the first result row, "
        "and map ALL tabs (Detalhamento, Itens, Pagamentos, Processo, Observação, "
        "Espelho Contábil, Registro de Envio, Histórico) by clicking each one. "
        "Report the full content of the Processo tab — especially the SEI process number."
    )
    print(f"\nResult: {result['steps']} steps, success={result['success']}")
    return result


if __name__ == "__main__":
    asyncio.run(explore_ob_screen())
