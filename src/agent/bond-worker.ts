/**
 * Bond Worker — agente de redes sociais rodando em paralelo
 * Execute: npx tsx src/agent/bond-worker.ts  ou  npm run bond
 */
import { syncAll, analisarTopPosts, analisarAudiencia, gerarRelatorioSemanal, gerarRankingCabos } from '../lib/bond'
import { prisma } from '../lib/db'
import { quemCobrar, recomputarStreaks } from '../lib/metricas'
import { enfileirarBroadcast } from '../lib/whatsapp'
import { sincronizarAdversarios } from '../lib/adversarios'

const INTERVAL_SYNC      = 30 * 60_000           // sync a cada 30min
const INTERVAL_ANALISE   = 60 * 60_000            // análise a cada 1h
const INTERVAL_RELATORIO = 24 * 60 * 60_000       // relatório diário
const INTERVAL_CHECKLIST = 30 * 60_000            // checklist 6h a cada 30min
const INTERVAL_NOTIFICA  = 10 * 60_000            // avisar apoiadores de novos posts a cada 10min
const INTERVAL_ADVERSARIO = 6 * 60 * 60_000       // sincronizar adversários a cada 6h

console.log('🔗 Bond Agent iniciando...')
console.log(`   Sync de posts: a cada 30min`)
console.log(`   Análise IA: a cada 1h`)
console.log(`   Notificar apoiadores (WhatsApp): a cada 10min`)
console.log(`   Checklist 6h: a cada 30min`)
console.log(`   Adversários: a cada 6h`)
console.log(`   Relatório semanal + quem cobrar: diário`)
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

// Gera checklist 6h após cada post e relatório semanal de ranking
async function runChecklistReports() {
  try {
    const agora = Date.now()
    const limite_inf = new Date(agora - 7 * 60 * 60 * 1000)   // posts até 7h atrás
    const limite_sup = new Date(agora - 5.5 * 60 * 60 * 1000) // posts há pelo menos 5,5h

    const postsAlvo = await prisma.bondPost.findMany({
      where: { publicadoEm: { gte: limite_inf, lte: limite_sup } },
    })

    for (const post of postsAlvo) {
      // Verifica se já foi gerado
      const jaGerado = await prisma.bondInsight.findFirst({
        where: { tipo: 'relatorio_post', dados: { contains: post.id } },
      })
      if (jaGerado) continue

      // Coleta interações do post
      const interacoes = await prisma.bondInteracao.findMany({
        where: { postId: post.postId, plataforma: post.plataforma },
      })

      const interacaoPorFa = new Map<string, string[]>()
      for (const inter of interacoes) {
        const tipos = interacaoPorFa.get(inter.externalId) ?? []
        tipos.push(inter.tipo)
        interacaoPorFa.set(inter.externalId, tipos)
      }

      // Busca todos os apoiadores e verifica quem interagiu
      const apoiadores = await prisma.pessoa.findMany({
        where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true },
        include: {
          bondFas: { where: { plataforma: post.plataforma }, select: { externalId: true } },
        },
      })

      const interagiram: string[] = []
      const naoInteragiram: string[] = []

      for (const p of apoiadores) {
        const fa = p.bondFas[0]
        const tipos = fa ? (interacaoPorFa.get(fa.externalId) ?? []) : []
        if (tipos.length > 0) {
          interagiram.push(`${p.nome} (${tipos.join(', ')})`)
        } else {
          naoInteragiram.push(p.nome)
        }
      }

      const conteudoPreview = post.conteudo?.slice(0, 80) ?? 'sem texto'
      const titulo = `Relatório 6h — ${post.plataforma}: "${conteudoPreview}..."`
      const descricao = [
        `📊 Post publicado em: ${new Date(post.publicadoEm).toLocaleString('pt-BR')}`,
        `❤️ Likes: ${post.likes} | 💬 Comentários: ${post.comentarios} | 🔄 Compartilhos: ${post.compartilhos}`,
        ``,
        `✅ Apoiadores que interagiram (${interagiram.length}):`,
        interagiram.length > 0 ? interagiram.map(n => `  • ${n}`).join('\n') : '  Nenhum',
        ``,
        `❌ Apoiadores sem interação (${naoInteragiram.length}):`,
        naoInteragiram.length > 0 ? naoInteragiram.map(n => `  • ${n}`).join('\n') : '  Todos interagiram!',
      ].join('\n')

      await prisma.bondInsight.create({
        data: {
          titulo,
          descricao,
          tipo: 'relatorio_post',
          plataforma: post.plataforma,
          dados: JSON.stringify({
            postId: post.id,
            postExternalId: post.postId,
            plataforma: post.plataforma,
            interagiram: interagiram.length,
            naoInteragiram: naoInteragiram.length,
            total: apoiadores.length,
          }),
        },
      })

      console.log(`[Bond] ✓ Relatório 6h gerado para post ${post.id} (${interagiram.length}/${apoiadores.length} apoiadores)`)
    }
  } catch (err) {
    console.error('[Bond] Erro no checklist 6h:', err)
  }
}

// Relatório semanal de ranking de apoiadores
async function runRankingSemanal() {
  const hoje = new Date()
  if (hoje.getDay() !== 0) return // Só na segunda-feira (0=domingo)

  try {
    const ranking = await gerarRankingCabos()
    if (ranking.length === 0) return

    const top5 = ranking.slice(0, 5).map((r, i) => {
      const medal = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'][i]
      return `${medal} ${r.nome}: ${r.score} pts (❤️${r.totalLikes} 💬${r.totalComents} 🔄${r.totalShares})`
    }).join('\n')

    const descricao = [
      `📅 Semana de ${new Date(Date.now() - 7 * 86400000).toLocaleDateString('pt-BR')} a ${hoje.toLocaleDateString('pt-BR')}`,
      ``,
      `🏆 Top 5 Apoiadores da Semana:`,
      top5,
      ``,
      `Total de apoiadores ativos: ${ranking.filter(r => r.score > 0).length}/${ranking.length}`,
    ].join('\n')

    await prisma.bondInsight.create({
      data: {
        titulo: `Ranking Semanal — ${hoje.toLocaleDateString('pt-BR')}`,
        descricao,
        tipo: 'relatorio_semanal',
        dados: JSON.stringify({ ranking: ranking.slice(0, 20), geradoEm: hoje.toISOString() }),
      },
    })

    console.log('[Bond] ✓ Ranking semanal de apoiadores gerado')
  } catch (err) {
    console.error('[Bond] Erro no ranking semanal:', err)
  }
}

// Avisa apoiadores via WhatsApp quando há post novo (janela crítica das 2h)
async function runNotificarNovosPosts() {
  try {
    const limite = new Date(Date.now() - 12 * 60 * 60 * 1000) // posts das últimas 12h
    const novos = await prisma.bondPost.findMany({
      where: { notificado: false, publicadoEm: { gte: limite }, perfil: { categoria: 'proprio' } },
      orderBy: { publicadoEm: 'desc' },
    })
    for (const post of novos) {
      const link = post.url ? `\n👉 ${post.url}` : ''
      const resumo = (post.conteudo ?? '').slice(0, 100)
      const msg = `🔔 Nova publicação no ${post.plataforma}!\n\n"${resumo}${resumo.length >= 100 ? '...' : ''}"${link}\n\n⏰ As primeiras 2 horas definem o alcance! Curta, comente e compartilhe AGORA. 💪`
      const r = await enfileirarBroadcast(msg, 'notificacao', post.id)
      await prisma.bondPost.update({ where: { id: post.id }, data: { notificado: true } })
      console.log(`[Bond] 📱 Apoiadores notificados sobre post ${post.id}: ${r.enfileirados} mensagens`)
    }
  } catch (err) {
    console.error('[Bond] Erro ao notificar novos posts:', err)
  }
}

// Recalcula streaks e gera relatório diário "quem cobrar"
async function runQuemCobrar() {
  const hoje = new Date()
  try {
    await recomputarStreaks()
    const alvos = await quemCobrar(3)
    if (alvos.length === 0) return

    const top = alvos.slice(0, 15).map((a, i) =>
      `${i + 1}. ${a.nome}${a.telefone ? ` (${a.telefone})` : ''} — faltou em ${a.postsRecentesSemEngajar} post(s), consistência ${a.consistenciaPct}%`
    ).join('\n')

    await prisma.bondInsight.create({
      data: {
        titulo: `📋 Quem cobrar hoje — ${hoje.toLocaleDateString('pt-BR')}`,
        descricao: `${alvos.length} apoiadores não engajaram nos posts recentes. Prioridade de cobrança:\n\n${top}`,
        tipo: 'cobranca',
        dados: JSON.stringify({ alvos: alvos.slice(0, 30) }),
      },
    })
    console.log(`[Bond] ✓ Relatório "quem cobrar" gerado (${alvos.length} alvos)`)
  } catch (err) {
    console.error('[Bond] Erro no quem cobrar:', err)
  }
}

async function runSincronizarAdversarios() {
  try {
    const r = await sincronizarAdversarios()
    console.log(`[Bond] ✓ Adversários sincronizados: ${r.sincronizados}`)
  } catch (err) {
    console.error('[Bond] Erro ao sincronizar adversários:', err)
  }
}

async function main() {
  await runSync()
  setTimeout(runAnalise, 10_000)
  setTimeout(runChecklistReports, 60_000)
  setTimeout(runNotificarNovosPosts, 30_000)
  setTimeout(runQuemCobrar, 90_000)

  setInterval(runSync, INTERVAL_SYNC)
  setInterval(runAnalise, INTERVAL_ANALISE)
  setInterval(runRelatorio, INTERVAL_RELATORIO)
  setInterval(runChecklistReports, INTERVAL_CHECKLIST)
  setInterval(runRankingSemanal, INTERVAL_RELATORIO)
  setInterval(runNotificarNovosPosts, INTERVAL_NOTIFICA)
  setInterval(runQuemCobrar, INTERVAL_RELATORIO)
  setInterval(runSincronizarAdversarios, INTERVAL_ADVERSARIO)

  console.log('[Bond] ✓ Rodando. Próximo sync em 30min.\n')
}

main().catch(err => {
  console.error('[Bond] Erro fatal:', err)
  process.exit(1)
})
