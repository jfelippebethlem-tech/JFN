import { prisma } from './db'
import { GoogleGenerativeAI } from '@google/generative-ai'

async function campanhaAI(prompt: string, maxTokens = 1200): Promise<string> {
  if (!process.env.GEMINI_API_KEY) return 'Configure GEMINI_API_KEY.'
  const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY)
  const model = genAI.getGenerativeModel({
    model: 'gemini-2.0-flash',
    systemInstruction: `Você é um estrategista digital especialista em campanhas eleitorais brasileiras.
Analisa dados reais de redes sociais para dar diagnósticos precisos e acionáveis.
Seja direto, use números quando disponíveis, e foque em ações práticas.
Responda SEMPRE em português do Brasil. Nunca use markdown com asteriscos.`,
    generationConfig: { maxOutputTokens: maxTokens },
  })
  const result = await model.generateContent(prompt)
  return result.response.text() ?? ''
}

// Score de potencial viral de um post (0-100)
function calcularPotencialViral(likes: number, comentarios: number, compartilhos: number, impressoes: number): number {
  if (!impressoes) return 0
  const engRate = ((likes + comentarios + compartilhos) / impressoes) * 100
  // Compartilhos têm peso triplo no viral — são o maior multiplicador de alcance
  const viralScore = (compartilhos * 3 + comentarios * 2 + likes) / impressoes * 100
  return Math.min(100, Math.round(viralScore * 10))
}

// Analisa qual horário/dia tende a gerar mais engajamento
export async function analisarMelhoresHorarios() {
  const posts = await prisma.bondPost.findMany({
    where: { impressoes: { gt: 0 } },
    select: { publicadoEm: true, likes: true, comentarios: true, compartilhos: true, impressoes: true, plataforma: true },
  })

  if (posts.length < 3) return null

  const porHora: Record<number, { total: number; count: number }> = {}
  const porDia: Record<number, { total: number; count: number }> = {}

  for (const p of posts) {
    const d = new Date(p.publicadoEm)
    const hora = d.getHours()
    const dia = d.getDay() // 0=Dom, 6=Sáb
    const eng = ((p.likes + p.comentarios + p.compartilhos) / p.impressoes) * 100

    porHora[hora] = porHora[hora] ?? { total: 0, count: 0 }
    porHora[hora].total += eng
    porHora[hora].count++

    porDia[dia] = porDia[dia] ?? { total: 0, count: 0 }
    porDia[dia].total += eng
    porDia[dia].count++
  }

  const topHoras = Object.entries(porHora)
    .map(([h, v]) => ({ hora: parseInt(h), mediaEng: v.total / v.count }))
    .sort((a, b) => b.mediaEng - a.mediaEng)
    .slice(0, 3)

  const diasNome = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']
  const topDias = Object.entries(porDia)
    .map(([d, v]) => ({ dia: diasNome[parseInt(d)], mediaEng: v.total / v.count }))
    .sort((a, b) => b.mediaEng - a.mediaEng)
    .slice(0, 3)

  return { topHoras, topDias }
}

// Analisa padrões de conteúdo — o que funciona vs. o que não funciona
export async function analisarPadroesCampanha() {
  const [posts, totalFas, totalApoiadores] = await Promise.all([
    prisma.bondPost.findMany({
      orderBy: { publicadoEm: 'desc' },
      take: 30,
      include: { perfil: true },
    }),
    prisma.bondFa.count(),
    prisma.pessoa.count({ where: { tipo: { in: ['apoiador', 'cabo_eleitoral', 'coordenador'] }, ativo: true } }),
  ])

  if (!posts.length) return null

  // Calcula potencial viral de cada post
  const postsComScore = posts.map(p => ({
    ...p,
    potencialViral: calcularPotencialViral(p.likes, p.comentarios, p.compartilhos, p.impressoes),
    score: p.likes + p.comentarios * 2 + p.compartilhos * 3,
  }))

  const topPosts = [...postsComScore].sort((a, b) => b.score - a.score).slice(0, 5)
  const flopPosts = [...postsComScore].sort((a, b) => a.score - b.score).slice(0, 3)
  const viralPotential = [...postsComScore].sort((a, b) => b.potencialViral - a.potencialViral).slice(0, 3)

  const totalLikes = posts.reduce((s, p) => s + p.likes, 0)
  const totalComents = posts.reduce((s, p) => s + p.comentarios, 0)
  const totalShares = posts.reduce((s, p) => s + p.compartilhos, 0)
  const mediaEng = posts.reduce((s, p) => s + p.engajamento, 0) / posts.length

  const analise = await campanhaAI(`Você é o estrategista digital do Dep. Jorge Felippe Neto (PL/RJ, Deputado Estadual).
Analise os dados abaixo e gere um diagnóstico COMPLETO e HONESTO da campanha nas redes sociais.

DADOS DOS ÚLTIMOS 30 POSTS:
- Total de posts analisados: ${posts.length}
- Total curtidas acumuladas: ${totalLikes}
- Total comentários: ${totalComents}
- Total compartilhos: ${totalShares}
- Taxa de engajamento média: ${mediaEng.toFixed(2)}%
- Apoiadores mapeados (BondFas): ${totalFas}
- Apoiadores cadastrados: ${totalApoiadores}

TOP 5 POSTS (mais engajamento):
${topPosts.map((p, i) => `${i + 1}. [${p.plataforma}] ${p.conteudo.slice(0, 120)} | ❤${p.likes} 💬${p.comentarios} 🔁${p.compartilhos} | Potencial viral: ${p.potencialViral}/100`).join('\n')}

3 POSTS COM PIOR DESEMPENHO:
${flopPosts.map((p, i) => `${i + 1}. [${p.plataforma}] ${p.conteudo.slice(0, 100)} | ❤${p.likes} 💬${p.comentarios} 🔁${p.compartilhos}`).join('\n')}

POSTS COM MAIOR POTENCIAL VIRAL (ainda não explorados):
${viralPotential.map((p, i) => `${i + 1}. [${p.plataforma}] ${p.conteudo.slice(0, 100)} | Score viral: ${p.potencialViral}/100`).join('\n')}

RESPONDA EXATAMENTE NESTE FORMATO (sem asteriscos, sem markdown):

DIAGNÓSTICO GERAL:
[2-3 frases honestas sobre a situação atual da campanha nas redes — o que está bom e o que está ruim]

ONDE ESTÁ ERRANDO:
- Erro 1: [nome do problema] — [explicação com dados]
- Erro 2: [nome do problema] — [explicação com dados]
- Erro 3: [nome do problema] — [explicação com dados]

O QUE ESTÁ FUNCIONANDO:
- Acerto 1: [o que está gerando resultado e por quê]
- Acerto 2: [o que está gerando resultado e por quê]

PADRÃO DO CONTEÚDO VIRAL (baseado nos top posts):
[2 frases descrevendo o que os posts mais engajados têm em comum — tema, tom, formato]

AÇÕES IMEDIATAS (próximos 7 dias):
- Ação 1: [ação específica e prática]
- Ação 2: [ação específica e prática]
- Ação 3: [ação específica e prática]

META SUGERIDA PARA 30 DIAS:
[Um objetivo concreto e mensurável para melhorar o engajamento]`, 1400)

  await prisma.bondInsight.create({
    data: {
      titulo: `Análise de Campanha — ${new Date().toLocaleDateString('pt-BR')}`,
      descricao: analise,
      tipo: 'performance',
    },
  })

  return {
    analise,
    stats: { totalLikes, totalComents, totalShares, mediaEng, totalFas, totalApoiadores },
    topPosts: topPosts.map(p => ({ id: p.id, plataforma: p.plataforma, conteudo: p.conteudo.slice(0, 150), likes: p.likes, comentarios: p.comentarios, compartilhos: p.compartilhos, potencialViral: p.potencialViral, score: p.score })),
    flopPosts: flopPosts.map(p => ({ id: p.id, plataforma: p.plataforma, conteudo: p.conteudo.slice(0, 150), likes: p.likes, comentarios: p.comentarios, compartilhos: p.compartilhos })),
    viralPotential: viralPotential.map(p => ({ id: p.id, plataforma: p.plataforma, conteudo: p.conteudo.slice(0, 150), potencialViral: p.potencialViral })),
  }
}

// Gera sugestão de conteúdo viral baseado nos padrões identificados
export async function sugerirConteudoViral(tema?: string) {
  const topPosts = await prisma.bondPost.findMany({
    where: { engajamento: { gt: 0 } },
    orderBy: { engajamento: 'desc' },
    take: 5,
  })

  const horarios = await analisarMelhoresHorarios()

  const prompt = `Crie 3 sugestões de post viral para o Dep. Jorge Felippe Neto (PL/RJ)${tema ? ` sobre o tema: "${tema}"` : ''}.

PADRÃO DOS POSTS QUE MAIS ENGAJARAM:
${topPosts.map(p => `[${p.plataforma}] ${p.conteudo.slice(0, 150)} (${p.engajamento.toFixed(1)}% engajamento)`).join('\n') || 'Sem histórico ainda'}

MELHOR HORÁRIO DE PUBLICAÇÃO:
${horarios ? `Melhores horas: ${horarios.topHoras.map(h => `${h.hora}h`).join(', ')} | Melhores dias: ${horarios.topDias.map(d => d.dia).join(', ')}` : 'Sem dados suficientes'}

REGRAS PARA POSTS VIRAIS:
- Linguagem: direta, próxima, como conversa entre amigos — não parlamentar
- Deve provocar resposta emocional: indignação, orgulho, esperança, ou humor (escolha um)
- Terminar com pergunta OU chamada para comentar
- Para Instagram/Facebook: 2-3 parágrafos curtos + hashtags
- Para Twitter/X: máximo 280 caracteres, impacto imediato

RESPONDA EXATAMENTE NESTE FORMATO — repita 3 vezes:

POST 1:
PLATAFORMA: [Instagram / Facebook / Twitter]
TEXTO: [texto completo pronto para copiar]
HASHTAGS: [3-5 hashtags]
PUBLICAR EM: [dia e horário recomendado]
POR QUE VAI VIRALIZAR: [1 frase]

POST 2:
[mesmo formato]

POST 3:
[mesmo formato]`

  return campanhaAI(prompt, 1200)
}

// Busca últimos insights de campanha
export async function buscarInsightsCampanha() {
  return prisma.bondInsight.findMany({
    where: { tipo: 'performance' },
    orderBy: { criadoEm: 'desc' },
    take: 10,
  })
}
