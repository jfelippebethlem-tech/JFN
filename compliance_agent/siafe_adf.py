# -*- coding: utf-8 -*-
"""
siafe_adf — helpers de sincronização com o Oracle ADF (SIAFE-Rio 2).

Causa-raiz da fragilidade da automação SIAFE (confirmada na doc Oracle):
- O PPR (Partial Page Rendering) é disparado por um `valueChangeEvent` REAL vindo do
  autoSubmit do componente. Por isso `fill()`/`dispatchEvent` falham (mudam o DOM sem
  gerar o evento que o ADF escuta) e `keyboard.type` funciona (gera eventos nativos).
- Usar `sleep(2.5)` fixo é frágil: lento quando o PPR termina antes, e quebra quando
  demora mais → causa "context destroyed"/StaleElement.

SOLUÇÃO CANÔNICA: esperar o método interno `AdfPage.PAGE.isSynchronizedWithServer()`,
que diz exatamente quando o PPR terminou e o browser está pronto. (Red Heap/White Horses;
existe desde ADF 11g.) Substitui todos os sleeps fixos.

Fontes: docs/APRENDIZADOS-SESSAO-2026-06-07.md (matriz de abordagens SIAFE).
"""
from __future__ import annotations

# JS que retorna True só quando o ADF terminou o PPR e está sincronizado com o servidor.
SYNC_JS = (
    "() => (typeof AdfPage !== 'undefined' "
    "&& AdfPage.PAGE "
    "&& typeof AdfPage.PAGE.isSynchronizedWithServer === 'function' "
    "&& AdfPage.PAGE.isSynchronizedWithServer())"
)


async def wait_adf_sync(page, timeout: int = 30000, settle_ms: int = 120) -> bool:
    """Espera o ADF concluir o PPR (em vez de sleep fixo). Retorna True se sincronizou.

    Faz fallback gracioso: se o AdfPage não estiver disponível (tela não-ADF ou ainda
    carregando) ou estourar o timeout, NÃO levanta — devolve False para o chamador
    decidir (mantém compatibilidade com o fluxo atual)."""
    try:
        await page.wait_for_function(SYNC_JS, timeout=timeout)
        if settle_ms:
            await page.wait_for_timeout(settle_ms)  # micro-assentamento pós-render
        return True
    except Exception:
        return False


async def disable_animations(page) -> None:
    """Desliga as animações do ADF (acelera o sync). Best-effort."""
    try:
        await page.evaluate(
            "() => { try { if (typeof AdfPage!=='undefined' && AdfPage.PAGE "
            "&& AdfPage.PAGE.setAnimationEnabled) AdfPage.PAGE.setAnimationEnabled(false); } catch(e){} }"
        )
    except Exception:
        pass


async def adf_settle(page, timeout: int = 30000) -> bool:
    """Atalho: desliga animação + espera sync. Use após cada ação que dispara PPR
    (clique de menu, filtro, ordenação, expand) no lugar de `wait_for_timeout` fixo."""
    ok = await wait_adf_sync(page, timeout=timeout)
    return ok


_WHY_JS = ("() => { try { return (AdfPage.PAGE && AdfPage.PAGE.whyIsNotSynchronizedWithServer) "
           "? AdfPage.PAGE.whyIsNotSynchronizedWithServer() : '(sem whyIs nesta build)'; } "
           "catch (e) { return 'AdfPage.PAGE indisponível'; } }")


class AdfSync:
    """Wrapper operacional do sync ADF (verificado: AdfPage existe no SIAFE 4.167.12;
    AdfPage.PAGE popula nas views da aplicação, não no launcher acessoRapido.jsp).

    Encapsula a RECEITA JÁ VALIDADA (siafe_contratos: MGS=41): abrir disclosure por
    clique REAL, Propriedade/Operador por select_option, e o VALOR por keyboard.type+Enter
    (fill NÃO gera o valueChangeEvent que dispara o PPR). Cada passo espera o sync real.
    Fallback gracioso (settle por tempo) quando isSynchronizedWithServer não responde —
    NÃO levanta, para não quebrar fluxos que já funcionam."""

    def __init__(self, page, default_timeout: int = 30000):
        self.page = page
        self.timeout = default_timeout

    async def boot(self) -> None:
        await wait_adf_sync(self.page, timeout=self.timeout)
        await disable_animations(self.page)

    async def wait(self, timeout: int | None = None) -> bool:
        ok = await wait_adf_sync(self.page, timeout=timeout or self.timeout)
        if not ok:
            await self.page.wait_for_timeout(1500)  # fallback: settle por tempo (não quebra)
        return ok

    def _loc(self, element_id: str):
        return self.page.locator(f"#{element_id.replace(':', r'\\:')}")

    async def click_real(self, element_id: str) -> None:
        """Clique de MOUSE real (ADF ignora el.click() de JS em disclosure/popup) + sync."""
        await self._loc(element_id).click()
        await self.wait()

    async def select_option(self, select_id: str, value: str) -> None:
        await self._loc(select_id).select_option(value)
        await self.wait()

    async def type_filter(self, value_field_id: str, valor: str, *, delay: int = 80,
                          clear_first: bool = True) -> None:
        """Campo VALOR do filtro: keystrokes reais + Enter (o que dispara o PPR) + sync."""
        f = self._loc(value_field_id)
        await f.click()
        if clear_first:
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Delete")
        await self.page.keyboard.type(valor, delay=delay)
        await self.page.keyboard.press("Enter")
        await self.wait()

    async def why(self) -> str:
        try:
            return await self.page.evaluate(_WHY_JS)
        except Exception:
            return "(indisponível)"
