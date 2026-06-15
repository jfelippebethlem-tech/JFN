/**
 * Hermes Worker — agente paralelo autônomo
 * Execute com: npx tsx src/agent/hermes-worker.ts
 * Ou: npm run hermes
 */

import { PrismaClient } from '@prisma/client'
import { processarJob, enqueueJob, lembrar, cicloAutonomo } from '../lib/hermes'

const prisma = new PrismaClient()

const INTERVAL_JOBS = 30_000       // verifica jobs a cada 30s
const INTERVAL_SCAN = 2 * 60_000   // escaneia novos dados a cada 2min
const INTERVAL_DAILY = 60 * 60_000 // resumo diário a cada 1h
const INTERVAL_AUTONOMO = 45 * 60_000 // ciclo autônomo (capta estado + age) a cada 45min

let lastScanDemandas: Date = new Date(0)
let lastScanPosts: Date = new Date(0)
let lastScanTelegram: Date = new Date(0)
let lastDailyResume: Date = new Date(0)

console.log('🪽  Hermes Agent iniciando...')
console.log(`   Jobs: a cada ${INTERVAL_JOBS / 1000}s`)
console.log(`   Scan: a cada ${INTERVAL_SCAN / 1000}s`)
console.log(`   Resumo diário: a cada ${INTERVAL_DAILY / 60000}min`)
console.log('─'.repeat(50))

// ─── Loop principal de processamento de jobs ────────────────────────────────────

async function processarJobsPendentes() {
  const jobs = await prisma.hermesJob.findMany({
    where: { status: 'pendente' },
    orderBy: { criadoEm: 'asc' },
    take: 3,
  })

  for (const job of jobs) {
    console.log(`[Hermes] Processando job: ${job.tipo} (${job.id.slice(-6)})`)
    try {
      const resultado = await processarJob(job)
      console.log(`[Hermes] ✓ ${job.tipo} concluído`)
      if (process.env.HERMES_VERBOSE === 'true') {
        console.log('   Resultado:', resultado?.slice(0, 200))
      }
    } catch (err) {
      console.error(`[Hermes] ✗ Erro no job ${job.tipo}:`, err)
    }
  }
}

// ─── Scan de novos dados para enfileirar análises ───────────────────────────────

async function escanearNovosDados() {
  // Demandas abertas sem análise do Hermes (jobs concluídos para esse item)
  const demandasRecentes = await prisma.demanda.findMany({
    where: {
      criadoEm: { gt: lastScanDemandas },
      status: 'aberta',
    },
    take: 5,
    orderBy: { criadoEm: 'asc' },
  })

  for (const d of demandasRecentes) {
    const jaEnfileirado = await prisma.hermesJob.findFirst({
      where: {
        tipo: 'analise_demanda',
        payload: { contains: d.id },
        status: { in: ['pendente', 'processando', 'concluido'] },
      },
    })
    if (!jaEnfileirado) {
      await enqueueJob('analise_demanda', {
        id: d.id,
        titulo: d.titulo,
        descricao: d.descricao,
        origem: d.origem,
      })
      console.log(`[Hermes] Nova demanda enfileirada: "${d.titulo.slice(0, 40)}"`)
    }
  }
  if (demandasRecentes.length) lastScanDemandas = new Date()

  // Posts recentes sem análise
  const postsRecentes = await prisma.post.findMany({
    where: {
      criadoEm: { gt: lastScanPosts },
      sentimento: null,
    },
    take: 5,
    orderBy: { criadoEm: 'asc' },
  })

  for (const p of postsRecentes) {
    const jaEnfileirado = await prisma.hermesJob.findFirst({
      where: {
        tipo: 'analise_post',
        payload: { contains: p.id },
        status: { in: ['pendente', 'processando', 'concluido'] },
      },
    })
    if (!jaEnfileirado) {
      await enqueueJob('analise_post', {
        id: p.id,
        conteudo: p.conteudo,
        plataforma: p.plataforma,
        palavra: p.palavra,
      })
      console.log(`[Hermes] Novo post enfileirado para análise`)
    }
  }
  if (postsRecentes.length) lastScanPosts = new Date()

  // Mensagens Telegram não respondidas
  const telegramRecentes = await prisma.telegramMensagem.findMany({
    where: {
      criadoEm: { gt: lastScanTelegram },
      respondida: false,
    },
    take: 5,
    orderBy: { criadoEm: 'asc' },
  })

  for (const msg of telegramRecentes) {
    const jaEnfileirado = await prisma.hermesJob.findFirst({
      where: {
        tipo: 'analise_telegram',
        payload: { contains: msg.id },
        status: { in: ['pendente', 'processando', 'concluido'] },
      },
    })
    if (!jaEnfileirado) {
      await enqueueJob('analise_telegram', {
        id: msg.id,
        nome: msg.nome,
        mensagem: msg.mensagem,
      })
      console.log(`[Hermes] Nova mensagem Telegram enfileirada`)
    }
  }
  if (telegramRecentes.length) lastScanTelegram = new Date()
}

// ─── Resumo diário ──────────────────────────────────────────────────────────────

async function verificarResumoDiario() {
  const agora = Date.now()
  if (agora - lastDailyResume.getTime() < INTERVAL_DAILY) return

  console.log('[Hermes] Gerando resumo diário...')
  await enqueueJob('resumo_diario', { timestamp: new Date().toISOString() })
  await lembrar('contexto', 'hermes_ativo_desde', new Date().toISOString())
  lastDailyResume = new Date()
}

// ─── Inicialização ──────────────────────────────────────────────────────────────

async function inicializar() {
  await lembrar('contexto', 'hermes_status', 'ativo')
  await lembrar('contexto', 'hermes_iniciado', new Date().toISOString())

  // Resumo imediato na primeira inicialização
  await enqueueJob('resumo_diario', {
    timestamp: new Date().toISOString(),
    motivo: 'inicializacao',
  })
  lastDailyResume = new Date()

  console.log('[Hermes] ✓ Inicializado. Aguardando dados...\n')
}

// ─── Entry point ────────────────────────────────────────────────────────────────

// ─── Ciclo autônomo: capta o estado completo e decide UMA ação via catálogo ─────

async function rodarCicloAutonomo() {
  console.log('[Hermes] 🤖 Ciclo autônomo: captando estado e decidindo ação...')
  try {
    const resumo = await cicloAutonomo()
    console.log(`[Hermes] ✓ ${resumo}`)
  } catch (err) {
    console.error('[Hermes] Erro no ciclo autônomo:', err)
  }
}

async function main() {
  await inicializar()

  setInterval(processarJobsPendentes, INTERVAL_JOBS)
  setInterval(escanearNovosDados, INTERVAL_SCAN)
  setInterval(verificarResumoDiario, INTERVAL_DAILY)
  setInterval(rodarCicloAutonomo, INTERVAL_AUTONOMO)

  // Executa imediatamente na inicialização
  await escanearNovosDados()
  setTimeout(processarJobsPendentes, 5000)
  setTimeout(rodarCicloAutonomo, 120_000) // primeiro ciclo após 2min
}

main().catch((err) => {
  console.error('[Hermes] Erro fatal:', err)
  process.exit(1)
})
