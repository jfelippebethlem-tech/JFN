import { prisma } from './db'
import { GoogleGenerativeAI } from '@google/generative-ai'
import { getTwitterUser, getTwitterTweets, getTwitterLikers, getTwitterRetweeters } from './social/twitter'
import { getFacebookPageInfo, getFacebookPosts, getFacebookPostInsights, getFacebookPostLikers, getFacebookPostComments } from './social/facebook'
import { getInstagramAccountId, getInstagramProfile, getInstagramPosts, getInstagramPostInsights, getInstagramComments } from './social/instagram'

// ── AI client ─────────────────────────────────────────────────────────────────

async function bondAI(prompt: string, maxTokens = 1024): Promise<string> {
  if (!process.env.GEMINI_API_KEY) return 'Configure GEMINI_API_KEY para usar a IA do Bond.'
  const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY)
  const model = genAI.getGenerativeModel({
    model: 'gemini-2.0-flash',
    systemInstruction: `Você é Bond. Função: analisar redes sociais de um deputado estadual brasileiro e gerar respostas úteis.

REGRAS — SIGA TODAS SEM EXCEÇÃO:
1. Responda SEMPRE em português do Brasil.
2. Siga EXATAMENTE o formato solicitado no prompt — use os mesmos títulos em maiúsculas.
3. NÃO comece com "Olá", "Claro", "Com prazer" ou qualquer saudação.
4. NÃO use markdown com asteriscos (* ou **) — escreva apenas texto simples.
5. Se faltar dado para uma seção, escreva: [SEM DADOS SUFICIENTES]
6. Seja direto e objetivo. Não repita o que foi pedido como introdução.`,
    generationConfig: { maxOutputTokens: maxTokens },
  })
  const result = await model.generateContent(prompt)
  return result.response.text() ?? ''
}

// ── Sincronização Twitter ─────────────────────────────────────────────────────

export async function syncTwitter() {
  const handle = process.env.TWITTER_USERNAME
  if (!handle || !process.env.TWITTER_BEARER_TOKEN) return { synced: 0, error: 'Twitter não configurado' }

  const user = await getTwitterUser(handle)
  if (!user) return { synced: 0, error: 'Usuário Twitter não encontrado' }

  const perfil = await prisma.bondPerfil.upsert({
    where: { plataforma_handle: { plataforma: 'twitter', handle } },
    update: {
      nomeCompleto: user.name,
      seguidores: user.public_metrics?.followers_count ?? 0,
      seguindo: user.public_metrics?.following_count ?? 0,
      totalPosts: user.public_metrics?.tweet_count ?? 0,
      bio: user.description,
      fotoUrl: user.profile_image_url,
      ultimaSync: new Date(),
    },
    create: {
      plataforma: 'twitter',
      handle,
      nomeCompleto: user.name,
      seguidores: user.public_metrics?.followers_count ?? 0,
      seguindo: user.public_metrics?.following_count ?? 0,
      totalPosts: user.public_metrics?.tweet_count ?? 0,
      bio: user.description,
      fotoUrl: user.profile_image_url,
      ultimaSync: new Date(),
    },
  })

  const tweets = await getTwitterTweets(user.id, 20)
  let synced = 0

  for (const tweet of tweets) {
    const metrics = tweet.public_metrics ?? {}
    const likers = await getTwitterLikers(tweet.id)
    const retweeters = await getTwitterRetweeters(tweet.id)
    const allEngagers = [...likers, ...retweeters].map((u: { id: string; name: string; username: string }) => ({
      id: u.id, nome: u.name, username: u.username,
    }))

    await prisma.bondPost.upsert({
      where: { plataforma_postId: { plataforma: 'twitter', postId: tweet.id } },
      update: {
        likes: metrics.like_count ?? 0,
        comentarios: metrics.reply_count ?? 0,
        compartilhos: metrics.retweet_count ?? 0,
        impressoes: metrics.impression_count ?? 0,
        engajamento: calcEngagement(metrics.like_count, metrics.reply_count, metrics.retweet_count, metrics.impression_count),
        fasJson: JSON.stringify(allEngagers),
        sincronizadoEm: new Date(),
      },
      create: {
        plataforma: 'twitter',
        postId: tweet.id,
        conteudo: tweet.text,
        tipo: tweet.attachments ? 'foto' : 'texto',
        likes: metrics.like_count ?? 0,
        comentarios: metrics.reply_count ?? 0,
        compartilhos: metrics.retweet_count ?? 0,
        impressoes: metrics.impression_count ?? 0,
        engajamento: calcEngagement(metrics.like_count, metrics.reply_count, metrics.retweet_count, metrics.impression_count),
        publicadoEm: new Date(tweet.created_at),
        fasJson: JSON.stringify(allEngagers),
        perfilId: perfil.id,
      },
    })

    // Atualiza fãs
    for (const engager of allEngagers) {
      await upsertFa('twitter', engager.id, engager.nome, engager.username, likers.some((l: { id: string }) => l.id === engager.id))
    }
    synced++
  }

  return { synced, perfilId: perfil.id }
}

// ── Sincronização Facebook ────────────────────────────────────────────────────

export async function syncFacebook() {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return { synced: 0, error: 'Facebook não configurado' }

  const page = await getFacebookPageInfo()
  if (!page) return { synced: 0, error: 'Página Facebook não encontrada' }

  const handle = page.id ?? 'page'
  const perfil = await prisma.bondPerfil.upsert({
    where: { plataforma_handle: { plataforma: 'facebook', handle } },
    update: {
      nomeCompleto: page.name,
      seguidores: page.followers_count ?? page.fan_count ?? 0,
      bio: page.about,
      fotoUrl: page.picture?.data?.url,
      ultimaSync: new Date(),
    },
    create: {
      plataforma: 'facebook',
      handle,
      nomeCompleto: page.name,
      seguidores: page.followers_count ?? page.fan_count ?? 0,
      bio: page.about,
      fotoUrl: page.picture?.data?.url,
      ultimaSync: new Date(),
    },
  })

  const posts = await getFacebookPosts(20)
  let synced = 0

  for (const post of posts) {
    const insights = await getFacebookPostInsights(post.id)
    const likers = await getFacebookPostLikers(post.id)
    const comments = await getFacebookPostComments(post.id)
    const insightMap: Record<string, number> = {}
    for (const ins of insights?.data ?? []) insightMap[ins.name] = ins.values?.[0]?.value ?? 0

    const allEngagers = likers.map((l: { id: string; name: string }) => ({ id: l.id, nome: l.name, username: null }))
    for (const c of comments) {
      if (c.from?.id && !allEngagers.some((e: { id: string }) => e.id === c.from.id)) {
        allEngagers.push({ id: c.from.id, nome: c.from.name, username: null })
      }
    }

    await prisma.bondPost.upsert({
      where: { plataforma_postId: { plataforma: 'facebook', postId: post.id } },
      update: {
        likes: post.likes?.summary?.total_count ?? 0,
        comentarios: post.comments?.summary?.total_count ?? 0,
        compartilhos: post.shares?.count ?? 0,
        alcance: insightMap['post_impressions_unique'] ?? 0,
        impressoes: insightMap['post_impressions'] ?? 0,
        fasJson: JSON.stringify(allEngagers),
        sincronizadoEm: new Date(),
      },
      create: {
        plataforma: 'facebook',
        postId: post.id,
        conteudo: post.message ?? post.story ?? '',
        tipo: post.full_picture ? 'foto' : 'texto',
        url: post.permalink_url,
        imagemUrl: post.full_picture,
        likes: post.likes?.summary?.total_count ?? 0,
        comentarios: post.comments?.summary?.total_count ?? 0,
        compartilhos: post.shares?.count ?? 0,
        alcance: insightMap['post_impressions_unique'] ?? 0,
        impressoes: insightMap['post_impressions'] ?? 0,
        engajamento: calcEngagement(post.likes?.summary?.total_count, post.comments?.summary?.total_count, post.shares?.count, insightMap['post_impressions']),
        publicadoEm: new Date(post.created_time),
        fasJson: JSON.stringify(allEngagers),
        perfilId: perfil.id,
      },
    })

    for (const e of allEngagers) await upsertFa('facebook', e.id, e.nome, e.username)
    synced++
  }

  return { synced, perfilId: perfil.id }
}

// ── Sincronização Instagram ───────────────────────────────────────────────────

export async function syncInstagram() {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return { synced: 0, error: 'Instagram não configurado' }

  const igId = await getInstagramAccountId()
  if (!igId) return { synced: 0, error: 'Conta Instagram Business não encontrada' }

  const profile = await getInstagramProfile(igId)
  if (!profile) return { synced: 0, error: 'Perfil Instagram não carregado' }

  const handle = profile.username ?? igId
  const perfil = await prisma.bondPerfil.upsert({
    where: { plataforma_handle: { plataforma: 'instagram', handle } },
    update: {
      nomeCompleto: profile.name,
      seguidores: profile.followers_count ?? 0,
      seguindo: profile.follows_count ?? 0,
      totalPosts: profile.media_count ?? 0,
      bio: profile.biography,
      fotoUrl: profile.profile_picture_url,
      ultimaSync: new Date(),
    },
    create: {
      plataforma: 'instagram',
      handle,
      nomeCompleto: profile.name,
      seguidores: profile.followers_count ?? 0,
      seguindo: profile.follows_count ?? 0,
      totalPosts: profile.media_count ?? 0,
      bio: profile.biography,
      fotoUrl: profile.profile_picture_url,
      ultimaSync: new Date(),
    },
  })

  const posts = await getInstagramPosts(igId, 20)
  let synced = 0

  for (const post of posts) {
    const insights = await getInstagramPostInsights(post.id)
    const comments = await getInstagramComments(post.id)
    const commenters = comments.map((c: { id: string; username: string }) => ({ id: c.id, nome: c.username, username: c.username }))

    await prisma.bondPost.upsert({
      where: { plataforma_postId: { plataforma: 'instagram', postId: post.id } },
      update: {
        likes: post.like_count ?? 0,
        comentarios: post.comments_count ?? 0,
        alcance: insights?.reach ?? 0,
        impressoes: insights?.impressions ?? 0,
        engajamento: insights?.engagement ?? calcEngagement(post.like_count, post.comments_count, 0, insights?.impressions),
        fasJson: JSON.stringify(commenters),
        sincronizadoEm: new Date(),
      },
      create: {
        plataforma: 'instagram',
        postId: post.id,
        conteudo: post.caption ?? '',
        tipo: post.media_type === 'VIDEO' ? 'video' : post.media_type === 'CAROUSEL_ALBUM' ? 'foto' : 'foto',
        url: post.permalink,
        imagemUrl: post.media_url ?? post.thumbnail_url,
        likes: post.like_count ?? 0,
        comentarios: post.comments_count ?? 0,
        alcance: insights?.reach ?? 0,
        impressoes: insights?.impressions ?? 0,
        engajamento: insights?.engagement ?? calcEngagement(post.like_count, post.comments_count, 0, insights?.impressions),
        publicadoEm: new Date(post.timestamp),
        fasJson: JSON.stringify(commenters),
        perfilId: perfil.id,
      },
    })

    for (const c of commenters) await upsertFa('instagram', c.id, c.nome, c.username)
    synced++
  }

  return { synced, perfilId: perfil.id }
}

// ── Sync all platforms ────────────────────────────────────────────────────────

export async function syncAll() {
  const [tw, fb, ig] = await Promise.allSettled([syncTwitter(), syncFacebook(), syncInstagram()])
  return {
    twitter: tw.status === 'fulfilled' ? tw.value : { error: String(tw.reason) },
    facebook: fb.status === 'fulfilled' ? fb.value : { error: String(fb.reason) },
    instagram: ig.status === 'fulfilled' ? ig.value : { error: String(ig.reason) },
  }
}

// ── Análises AI ───────────────────────────────────────────────────────────────

export async function analisarTopPosts() {
  const posts = await prisma.bondPost.findMany({
    orderBy: { engajamento: 'desc' },
    take: 10,
    include: { perfil: true },
  })
  if (!posts.length) return null

  const resumo = posts.map(p =>
    `[${p.plataforma}] ${p.conteudo.slice(0, 100)} — ❤️${p.likes} 💬${p.comentarios} 🔁${p.compartilhos} 📊${p.engajamento.toFixed(1)}%`
  ).join('\n')

  const analise = await bondAI(`Você recebeu dados dos posts com maior engajamento de um deputado estadual.
Tarefa: analisar os dados abaixo e identificar padrões. Siga o formato EXATO da resposta.

DADOS DOS POSTS (formato: [plataforma] texto — curtidas comentários compartilhamentos engajamento%):
${resumo}

RESPONDA EXATAMENTE NESTE FORMATO — use estes títulos em maiúsculas, sem introdução:

PADRÕES DE CONTEÚDO:
[2 a 3 frases descrevendo o que os posts mais engajados têm em comum — tema, tom, linguagem]

TEMAS COM MAIS INTERAÇÃO:
- Tema 1: [nome do tema e por que engaja]
- Tema 2: [nome do tema e por que engaja]
- Tema 3: [nome do tema e por que engaja]

FORMATOS MAIS EFICAZES:
[Diga qual formato (texto, foto ou vídeo) teve melhor desempenho e 1 frase explicando por quê]

RECOMENDAÇÕES PRÁTICAS:
- Recomendação 1: [ação específica que o deputado deve tomar]
- Recomendação 2: [ação específica que o deputado deve tomar]
- Recomendação 3: [ação específica que o deputado deve tomar]`, 800)

  await prisma.bondInsight.create({
    data: {
      titulo: 'Análise dos Posts de Maior Engajamento',
      descricao: analise,
      tipo: 'performance',
    },
  })

  return analise
}

export async function analisarAudiencia() {
  const fas = await prisma.bondFa.findMany({
    orderBy: [{ totalLikes: 'desc' }, { totalComents: 'desc' }],
    take: 20,
  })
  if (!fas.length) return null

  const resumo = fas.map(f =>
    `${f.nome ?? f.username ?? f.externalId} (${f.plataforma}): ❤️${f.totalLikes} 💬${f.totalComents} 🔁${f.totalShares}`
  ).join('\n')

  const analise = await bondAI(`Você recebeu dados dos seguidores que mais interagiram com as redes sociais de um deputado estadual.
Tarefa: analisar o perfil da audiência. Siga o formato EXATO da resposta.

DADOS DOS ENGAJADORES (formato: nome (plataforma): curtidas comentários compartilhamentos):
${resumo}

RESPONDA EXATAMENTE NESTE FORMATO — use estes títulos em maiúsculas, sem introdução:

PERFIL DOS FÃS MAIS FIÉIS:
[2 frases descrevendo quem são as pessoas que mais interagem — tipo de perfil, comportamento]

PLATAFORMA MAIS ATIVA:
[Escreva o nome de UMA plataforma e 1 frase curta dizendo por que ela é a mais ativa]

ESTRATÉGIAS DE RELACIONAMENTO:
- Estratégia 1: [ação específica para engajar os fãs mais fiéis]
- Estratégia 2: [ação específica para engajar os fãs mais fiéis]
- Estratégia 3: [ação específica para engajar os fãs mais fiéis]

COMO TRANSFORMAR FÃS EM MULTIPLICADORES:
- Ação 1: [o que fazer para que os fãs compartilhem o conteúdo com outras pessoas]
- Ação 2: [o que fazer para que os fãs compartilhem o conteúdo com outras pessoas]`, 600)

  await prisma.bondInsight.create({
    data: {
      titulo: 'Análise da Audiência — Top Engajadores',
      descricao: analise,
      tipo: 'audiencia',
    },
  })

  return analise
}

export async function gerarSugestaoConteudo(tema?: string, plataforma = 'todas') {
  const topPosts = await prisma.bondPost.findMany({
    where: plataforma !== 'todas' ? { plataforma } : undefined,
    orderBy: { engajamento: 'desc' },
    take: 5,
  })

  const historico = topPosts.map(p => p.conteudo.slice(0, 150)).join('\n---\n')

  const prompt = `Tarefa: criar 3 sugestões de post${tema ? ` sobre o tema "${tema}"` : ''} para ${plataforma === 'todas' ? 'redes sociais em geral' : plataforma} de um deputado estadual brasileiro.

HISTÓRICO DOS POSTS QUE MAIS ENGAJARAM (use como referência de tom e estilo):
${historico || 'Sem histórico — use linguagem direta, próxima do cidadão, sem jargão político.'}

REGRAS PARA OS POSTS:
- O texto deve estar COMPLETO e pronto para copiar e publicar — não use "[...]" ou resumos
- Linguagem: direta, humana, sem jargão jurídico ou político
- Tamanho por plataforma: Twitter até 280 caracteres, Facebook e Instagram de 1 a 3 parágrafos curtos

RESPONDA EXATAMENTE NESTE FORMATO — repita o bloco 3 vezes com os títulos exatos:

POST 1:
TÍTULO: [assunto do post em até 8 palavras]
TEXTO: [texto completo pronto para publicar]
HASHTAGS: [3 a 5 hashtags começando com #, separadas por espaço]
HORÁRIO: [melhor horário do dia para publicar, ex: "18h às 21h"]
POR QUÊ FUNCIONA: [1 frase explicando por que esse post vai engajar]

POST 2:
TÍTULO: [assunto do post em até 8 palavras]
TEXTO: [texto completo pronto para publicar]
HASHTAGS: [3 a 5 hashtags começando com #, separadas por espaço]
HORÁRIO: [melhor horário do dia para publicar]
POR QUÊ FUNCIONA: [1 frase explicando por que esse post vai engajar]

POST 3:
TÍTULO: [assunto do post em até 8 palavras]
TEXTO: [texto completo pronto para publicar]
HASHTAGS: [3 a 5 hashtags começando com #, separadas por espaço]
HORÁRIO: [melhor horário do dia para publicar]
POR QUÊ FUNCIONA: [1 frase explicando por que esse post vai engajar]`

  return bondAI(prompt, 1200)
}

export async function gerarRelatorioSemanal() {
  const umaSemanaAtras = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
  const [perfis, postsRecentes, totalFas] = await Promise.all([
    prisma.bondPerfil.findMany({ where: { ativo: true } }),
    prisma.bondPost.findMany({
      where: { publicadoEm: { gte: umaSemanaAtras } },
      orderBy: { engajamento: 'desc' },
    }),
    prisma.bondFa.count(),
  ])

  const totalLikes = postsRecentes.reduce((s, p) => s + p.likes, 0)
  const totalComents = postsRecentes.reduce((s, p) => s + p.comentarios, 0)
  const totalShares = postsRecentes.reduce((s, p) => s + p.compartilhos, 0)

  const relatorio = await bondAI(`Tarefa: gerar um relatório semanal de redes sociais de um deputado estadual. Use os dados abaixo. Siga o formato EXATO.

DADOS DA SEMANA:
- Plataformas ativas: ${perfis.map(p => p.plataforma).join(', ') || 'nenhuma'}
- Posts publicados: ${postsRecentes.length}
- Total de curtidas: ${totalLikes}
- Total de comentários: ${totalComents}
- Total de compartilhamentos: ${totalShares}
- Total de fãs/engajadores mapeados: ${totalFas}

TOP 3 POSTS DA SEMANA:
${postsRecentes.slice(0, 3).map(p => `- [${p.plataforma}] ${p.conteudo.slice(0, 100)} (curtidas: ${p.likes})`).join('\n') || '- Sem posts nessa semana'}

RESPONDA EXATAMENTE NESTE FORMATO — use estes títulos em maiúsculas, sem introdução:

RESUMO DA SEMANA:
[2 a 3 frases resumindo como foi o desempenho geral nas redes sociais]

MELHOR DESEMPENHO:
[Cite qual plataforma ou post se destacou e 1 frase explicando por quê]

PIOR DESEMPENHO:
[Cite o que não funcionou bem e 1 frase explicando o motivo]

RECOMENDAÇÕES PARA A PRÓXIMA SEMANA:
- Recomendação 1: [ação específica]
- Recomendação 2: [ação específica]
- Recomendação 3: [ação específica]

META DE ENGAJAMENTO SUGERIDA:
[Um número ou percentual concreto de melhoria, ex: "Aumentar curtidas em 20%", com 1 frase justificando]`, 800)

  await prisma.bondInsight.create({
    data: {
      titulo: `Relatório Semanal — ${new Date().toLocaleDateString('pt-BR')}`,
      descricao: relatorio,
      tipo: 'performance',
    },
  })

  return relatorio
}

// ── Chat com Bond ─────────────────────────────────────────────────────────────

export async function chatComBond(
  mensagem: string,
  historico: { role: string; content: string }[] = []
): Promise<string> {
  const [topPosts, topFas, perfis] = await Promise.all([
    prisma.bondPost.findMany({ orderBy: { engajamento: 'desc' }, take: 5 }),
    prisma.bondFa.findMany({ orderBy: { totalLikes: 'desc' }, take: 10 }),
    prisma.bondPerfil.findMany({ where: { ativo: true } }),
  ])

  const contexto = `
PLATAFORMAS CONECTADAS: ${perfis.map(p => `${p.plataforma} (@${p.handle}, ${p.seguidores} seguidores)`).join(' | ') || 'nenhuma'}
TOP POSTS: ${topPosts.map(p => `[${p.plataforma}] ${p.conteudo.slice(0, 80)} (❤️${p.likes})`).join(' | ') || 'sem dados'}
TOP FÃS: ${topFas.map(f => `${f.nome ?? f.username} (${f.plataforma})`).join(', ') || 'sem dados'}
`

  const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY ?? '')
  const model = genAI.getGenerativeModel({
    model: 'gemini-2.0-flash',
    systemInstruction: `Você é Bond, o agente de redes sociais de um deputado estadual brasileiro.

DADOS ATUAIS DAS REDES SOCIAIS DO DEPUTADO:
${contexto}

REGRAS — SIGA TODAS SEM EXCEÇÃO:
1. Responda SEMPRE em português do Brasil.
2. Responda APENAS o que foi perguntado. Não adicione informações extras não solicitadas.
3. Se pedirem texto para publicar: forneça o texto COMPLETO, pronto para copiar — sem resumos ou "[...]".
4. Se pedirem análise: use SOMENTE os dados acima. NÃO invente números ou nomes.
5. Se não tiver dados para responder: diga exatamente "Ainda não tenho dados suficientes. Faça uma sincronização primeiro em Configurações."
6. NÃO comece respostas com "Olá", "Claro!", "Com prazer" ou qualquer saudação.
7. Máximo de 5 parágrafos por resposta, salvo se pedirem texto longo para publicar.`,
    generationConfig: { maxOutputTokens: 1024 },
  })

  const hist = historico.slice(-8).map(h => ({
    role: h.role === 'user' ? 'user' : 'model',
    parts: [{ text: h.content }],
  }))

  const chat = model.startChat({ history: hist })
  const result = await chat.sendMessage(mensagem)
  return result.response.text()
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function calcEngagement(likes = 0, comments = 0, shares = 0, impressions = 0): number {
  if (!impressions) return 0
  return parseFloat((((likes + comments + shares) / impressions) * 100).toFixed(2))
}

async function upsertFa(plataforma: string, externalId: string, nome: string | null, username: string | null, liked = true) {
  await prisma.bondFa.upsert({
    where: { plataforma_externalId: { plataforma, externalId } },
    update: {
      nome: nome ?? undefined,
      username: username ?? undefined,
      totalLikes: liked ? { increment: 1 } : undefined,
      ultimaInter: new Date(),
    },
    create: {
      plataforma,
      externalId,
      nome,
      username,
      totalLikes: liked ? 1 : 0,
      ultimaInter: new Date(),
    },
  })
}
