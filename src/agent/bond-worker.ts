/**
 * Bond Worker — agente de redes sociais rodando em paralelo
 * Execute: npx tsx src/agent/bond-worker.ts  ou  npm run bond
 */
import { syncAll, analisarTopPosts, analisarAudiencia, gerarRelatorioSemanal } from '../lib/bond'

const INTERVAL_SYNC = 30 * 60_000      // sync a cada 30min
const INTERVAL_ANALISE = 60 * 60_000   // análise a cada 1h
const INTERVAL_RELATORIO = 24 * 60 * 60_000 // relatório diário

console.log('🔗 Bond Agent iniciando...')
console.log(`   Sync de posts: a cada 30min`)
console.log(`   Análise IA: a cada 1h`)
console.log(`   Relatório: diário`)
console.log('─'.repeat(50))

async function runSync() {
  console.log('[Bond] Sincronizando redes sociais...')
  try {
    const result = await syncAll()
    for (const [plat, res] of Object.entries(result)) {
      if ('error' in (res as object) && (res as { error: string }).error) {
        console.log(`[Bond] ${plat}: ${(res as { error: string }).error}`)
      } else {
        console.log(`[Bond] ✓ ${plat}: ${(res as { synced: number }).synced} posts sincronizados`)
      }
    }
  } catch (err) {
    console.error('[Bond] Erro no sync:', err)
  }
}

async function runAnalise() {
  console.log('[Bond] Rodando análises IA...')
  try {
    await Promise.allSettled([analisarTopPosts(), analisarAudiencia()])
    console.log('[Bond] ✓ Análises concluídas')
  } catch (err) {
    console.error('[Bond] Erro na análise:', err)
  }
}

async function runRelatorio() {
  console.log('[Bond] Gerando relatório semanal...')
  try {
    await gerarRelatorioSemanal()
    console.log('[Bond] ✓ Relatório gerado')
  } catch (err) {
    console.error('[Bond] Erro no relatório:', err)
  }
}

async function main() {
  // Executa imediatamente ao iniciar
  await runSync()
  setTimeout(runAnalise, 10_000)

  setInterval(runSync, INTERVAL_SYNC)
  setInterval(runAnalise, INTERVAL_ANALISE)
  setInterval(runRelatorio, INTERVAL_RELATORIO)

  console.log('[Bond] ✓ Rodando. Próximo sync em 30min.\n')
}

main().catch(err => {
  console.error('[Bond] Erro fatal:', err)
  process.exit(1)
})
