/**
 * Métricas avançadas de apoiadores — Influencer Score, Consistency, Velocity, Heat Map.
 * Todas as funções têm nomes e retornos explícitos para que o Hermes (IA fraca)
 * consiga captar e usar os dados sem ambiguidade.
 */
import { prisma } from './db'

// ── Influencer Score (ROI real do apoiador) ──────────────────────────────────
// Cada compartilhamento expõe o post aos seguidores do apoiador; comentário pesa
// menos; curtida menos ainda. Resultado em "centenas de impressões potenciais".
export function influencerScore(p: {
  totalShares: number
  totalComents: number
  totalLikes: number
  seguidores: number
}): number {
  const seg = p.seguidores || 0
  const alcance = p.totalShares * seg + p.totalComents * seg * 0.2 + p.totalLikes * seg * 0.05
  return Math.round(alcance / 100)
}

// Alcance estimado real gerado pelos compartilhamentos do apoiador
export function alcanceEstimado(totalShares: number, seguidores: number): number {
  return totalShares * (seguidores || 0)
}

// ── Métricas que dependem do banco ───────────────────────────────────────────

export type MetricaApoiador = {
  pessoaId: string
  nome: string
  tipo: string
  telefone: string | null
  seguidores: number
  totalLikes: number
  totalComents: number
  totalShares: number
  score: number
  influencerScore: number
  alcanceEstimado: number
  consistencia: number      // 0-1: % dos posts em que engajou (30d)
  consistenciaPct: number   // 0-100
  velocidadeMin: number | null // minutos médios até engajar (null se sem dados)
  postsEngajados: number
  totalPostsPeriodo: number
  streak: number
}

/**
 * Calcula Consistency Score e Engagement Velocity de todos os apoiadores,
 * cruzando BondInteracao (por externalId das contas vinculadas) com BondPost.
 * Janela: últimos `dias` dias (padrão 30).
 */
export async function calcularMetricasApoiadores(dias = 30): Promise<MetricaApoiador[]> {
  const desde = new Date(Date.now() - dias * 24 * 60 * 60 * 1000)

  // Posts do período (publicações próprias)
  const posts = await prisma.bondPost.findMany({
    where: { publicadoEm: { gte: desde } },
    select: { postId: true, plataforma: true, publicadoEm: true },
  })
  const totalPostsPeriodo = posts.length
  const postPubMap = new Map<string, Date>() // `${plataforma}:${postId}` -> publicadoEm
  for (const p of posts) postPubMap.set(`${p.plataforma}:${p.postId}`, p.publicadoEm)
  const postIdsValidos = new Set(posts.map(p => `${p.plataforma}:${p.postId}`))

  // Interações do período
  const interacoes = await prisma.bondInteracao.findMany({
    where: { criadoEm: { gte: desde } },
    select: { plataforma: true, externalId: true, postId: true, criadoEm: true },
  })

  // Agrupa por externalId
  const porFa = new Map<string, { postsEngajados: Set<string>; somaMinutos: number; nVel: number }>()
  for (const i of interacoes) {
    const chavePost = `${i.plataforma}:${i.postId}`
    if (!postIdsValidos.has(chavePost)) continue
    const key = `${i.plataforma}:${i.externalId}`
    const entry = porFa.get(key) ?? { postsEngajados: new Set<string>(), somaMinutos: 0, nVel: 0 }
    entry.postsEngajados.add(chavePost)
    const pub = postPubMap.get(chavePost)
    if (pub) {
      const min = (new Date(i.criadoEm).getTime() - new Date(pub).getTime()) / 60000
      if (min >= 0 && min < 60 * 48) { entry.somaMinutos += min; entry.nVel++ }
    }
    porFa.set(key, entry)
  }

  // Apoiadores
  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true },
    include: {
      bondFas: { select: { plataforma: true, externalId: true, totalLikes: true, totalComents: true, totalShares: true } },
    },
  })

  return apoiadores.map(p => {
    const totalLikes = p.bondFas.reduce((s, f) => s + f.totalLikes, 0)
    const totalComents = p.bondFas.reduce((s, f) => s + f.totalComents, 0)
    const totalShares = p.bondFas.reduce((s, f) => s + f.totalShares, 0)
    const score = totalLikes + totalComents * 2 + totalShares * 3

    // une métricas de todas as contas do apoiador
    const postsEngajadosSet = new Set<string>()
    let somaMin = 0, nVel = 0
    for (const f of p.bondFas) {
      const e = porFa.get(`${f.plataforma}:${f.externalId}`)
      if (e) {
        e.postsEngajados.forEach(x => postsEngajadosSet.add(x))
        somaMin += e.somaMinutos; nVel += e.nVel
      }
    }
    const postsEngajados = postsEngajadosSet.size
    const consistencia = totalPostsPeriodo > 0 ? postsEngajados / totalPostsPeriodo : 0
    const velocidadeMin = nVel > 0 ? Math.round(somaMin / nVel) : null

    return {
      pessoaId: p.id,
      nome: p.nome,
      tipo: p.tipo,
      telefone: p.telefone,
      seguidores: p.seguidores,
      totalLikes, totalComents, totalShares, score,
      influencerScore: influencerScore({ totalShares, totalComents, totalLikes, seguidores: p.seguidores }),
      alcanceEstimado: alcanceEstimado(totalShares, p.seguidores),
      consistencia: parseFloat(consistencia.toFixed(2)),
      consistenciaPct: Math.round(consistencia * 100),
      velocidadeMin,
      postsEngajados,
      totalPostsPeriodo,
      streak: p.streak,
    }
  }).sort((a, b) => b.score - a.score)
}

// ── Heat Map: engajamento dos apoiadores por hora e dia da semana ────────────
export type HeatMap = {
  porHora: { hora: number; total: number }[]      // 0-23
  porDia: { dia: number; nome: string; total: number }[] // 0=Dom
  matriz: number[][]                                // [dia][hora]
  melhorHora: number
  melhorDia: { dia: number; nome: string }
  totalInteracoes: number
}

const DIAS_SEMANA = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']

export async function calcularHeatMap(dias = 30): Promise<HeatMap> {
  const desde = new Date(Date.now() - dias * 24 * 60 * 60 * 1000)
  const interacoes = await prisma.bondInteracao.findMany({
    where: { criadoEm: { gte: desde } },
    select: { criadoEm: true },
  })

  const porHora = Array.from({ length: 24 }, (_, h) => ({ hora: h, total: 0 }))
  const porDia = DIAS_SEMANA.map((nome, dia) => ({ dia, nome, total: 0 }))
  const matriz: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0))

  for (const i of interacoes) {
    const d = new Date(i.criadoEm)
    const h = d.getHours()
    const dia = d.getDay()
    porHora[h].total++
    porDia[dia].total++
    matriz[dia][h]++
  }

  const melhorHora = porHora.reduce((max, x) => (x.total > max.total ? x : max), porHora[0]).hora
  const melhorDiaObj = porDia.reduce((max, x) => (x.total > max.total ? x : max), porDia[0])

  return {
    porHora,
    porDia,
    matriz,
    melhorHora,
    melhorDia: { dia: melhorDiaObj.dia, nome: melhorDiaObj.nome },
    totalInteracoes: interacoes.length,
  }
}

// ── "Quem cobrar": apoiadores valiosos que NÃO engajaram nos posts recentes ──
export type AlvoCobranca = {
  pessoaId: string
  nome: string
  tipo: string
  telefone: string | null
  consistenciaPct: number
  influencerScore: number
  score: number
  postsRecentesSemEngajar: number
  prioridade: number // quanto maior, mais importante cobrar
}

export async function quemCobrar(nPostsRecentes = 3): Promise<AlvoCobranca[]> {
  const postsRecentes = await prisma.bondPost.findMany({
    orderBy: { publicadoEm: 'desc' },
    take: nPostsRecentes,
    select: { postId: true, plataforma: true },
  })
  if (postsRecentes.length === 0) return []

  const chavesPosts = postsRecentes.map(p => ({ plataforma: p.plataforma, postId: p.postId }))

  // interações nesses posts
  const interacoes = await prisma.bondInteracao.findMany({
    where: { OR: chavesPosts.map(p => ({ plataforma: p.plataforma, postId: p.postId })) },
    select: { plataforma: true, externalId: true, postId: true },
  })
  const engajou = new Set<string>() // `${plataforma}:${externalId}:${postId}`
  for (const i of interacoes) engajou.add(`${i.plataforma}:${i.externalId}:${i.postId}`)

  const metricas = await calcularMetricasApoiadores(30)
  const metricaMap = new Map(metricas.map(m => [m.pessoaId, m]))

  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true },
    include: { bondFas: { select: { plataforma: true, externalId: true } } },
  })

  const alvos: AlvoCobranca[] = []
  for (const p of apoiadores) {
    if (p.bondFas.length === 0) continue // sem conta vinculada não dá para medir
    let semEngajar = 0
    for (const post of postsRecentes) {
      const engajouEntePost = p.bondFas.some(f =>
        engajou.has(`${post.plataforma}:${f.externalId}:${post.postId}`))
      if (!engajouEntePost) semEngajar++
    }
    if (semEngajar === 0) continue // engajou em todos, não precisa cobrar

    const m = metricaMap.get(p.id)
    const consistenciaPct = m?.consistenciaPct ?? 0
    const infl = m?.influencerScore ?? 0
    const score = m?.score ?? 0
    // prioridade: quem é consistente normalmente + influente + faltou = mais urgente
    const prioridade = Math.round(consistenciaPct * 1.5 + infl * 0.5 + semEngajar * 10)
    alvos.push({
      pessoaId: p.id,
      nome: p.nome,
      tipo: p.tipo,
      telefone: p.telefone,
      consistenciaPct,
      influencerScore: infl,
      score,
      postsRecentesSemEngajar: semEngajar,
      prioridade,
    })
  }

  return alvos.sort((a, b) => b.prioridade - a.prioridade)
}

// ── Recalcula o streak (posts consecutivos engajados) de cada apoiador ───────
// Streak = nº de posts mais recentes (em ordem) em que o apoiador engajou,
// contando do mais novo até o primeiro que ele "furou".
export async function recomputarStreaks(nPosts = 15) {
  const posts = await prisma.bondPost.findMany({
    where: { perfil: { categoria: 'proprio' } },
    orderBy: { publicadoEm: 'desc' },
    take: nPosts,
    select: { postId: true, plataforma: true },
  })
  if (posts.length === 0) return { atualizados: 0 }

  const interacoes = await prisma.bondInteracao.findMany({
    where: { OR: posts.map(p => ({ plataforma: p.plataforma, postId: p.postId })) },
    select: { plataforma: true, externalId: true, postId: true },
  })
  const engajou = new Set<string>() // `${plataforma}:${externalId}:${postId}`
  for (const i of interacoes) engajou.add(`${i.plataforma}:${i.externalId}:${i.postId}`)

  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true },
    include: { bondFas: { select: { plataforma: true, externalId: true } } },
  })

  let atualizados = 0
  for (const p of apoiadores) {
    let streak = 0
    for (const post of posts) { // do mais recente ao mais antigo
      const engajouNesse = p.bondFas.some(f => engajou.has(`${post.plataforma}:${f.externalId}:${post.postId}`))
      if (engajouNesse) streak++
      else break
    }
    if (streak !== p.streak) {
      await prisma.pessoa.update({ where: { id: p.id }, data: { streak } })
      atualizados++
    }
  }
  return { atualizados }
}
