import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import {
  syncAll, syncTwitter, syncFacebook, syncInstagram,
  gerarSugestaoConteudo, chatComBond, analisarTopPosts, analisarAudiencia,
  gerarRankingGeral, gerarRankingSemanal, gerarRankingCabos,
  buscarComentariosPendentes, sugerirResposta, aprovarResposta, rejeitarComentario,
} from '@/lib/bond'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo')

  if (tipo === 'posts') {
    const plataforma = searchParams.get('plataforma')
    const posts = await prisma.bondPost.findMany({
      where: plataforma ? { plataforma } : undefined,
      orderBy: [{ publicadoEm: 'desc' }],
      take: 50,
      include: { perfil: true },
    })
    return NextResponse.json(posts)
  }

  if (tipo === 'fas') {
    const plataforma = searchParams.get('plataforma')
    const fas = await prisma.bondFa.findMany({
      where: plataforma ? { plataforma } : undefined,
      orderBy: [{ totalLikes: 'desc' }, { totalComents: 'desc' }],
      take: 50,
      include: { pessoa: { select: { id: true, nome: true, tipo: true } } },
    })
    return NextResponse.json(fas)
  }

  if (tipo === 'ranking_geral') {
    return NextResponse.json(await gerarRankingGeral())
  }

  if (tipo === 'ranking_semanal') {
    return NextResponse.json(await gerarRankingSemanal())
  }

  if (tipo === 'ranking_cabos') {
    return NextResponse.json(await gerarRankingCabos())
  }

  if (tipo === 'comentarios') {
    return NextResponse.json(await buscarComentariosPendentes())
  }

  if (tipo === 'insights') {
    const insights = await prisma.bondInsight.findMany({
      orderBy: { criadoEm: 'desc' },
      take: 20,
    })
    return NextResponse.json(insights)
  }

  if (tipo === 'rascunhos') {
    const rascunhos = await prisma.bondRascunho.findMany({
      orderBy: { criadoEm: 'desc' },
    })
    return NextResponse.json(rascunhos)
  }

  // Default: overview
  const [perfis, totalPosts, totalFas, insightsNaoLidos, comentariosPendentes, stats] = await Promise.all([
    prisma.bondPerfil.findMany({ where: { ativo: true } }),
    prisma.bondPost.count(),
    prisma.bondFa.count(),
    prisma.bondInsight.count({ where: { lido: false } }),
    prisma.bondComentario.count({ where: { respondido: false } }),
    prisma.bondPost.aggregate({
      _sum: { likes: true, comentarios: true, compartilhos: true, alcance: true },
      _avg: { engajamento: true },
    }),
  ])

  return NextResponse.json({ perfis, totalPosts, totalFas, insightsNaoLidos, comentariosPendentes, stats })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const { acao } = body

  if (acao === 'sync') {
    const plat = body.plataforma
    let result
    if (plat === 'twitter') result = await syncTwitter()
    else if (plat === 'facebook') result = await syncFacebook()
    else if (plat === 'instagram') result = await syncInstagram()
    else result = await syncAll()
    return NextResponse.json(result)
  }

  if (acao === 'chat') {
    const { mensagem, historico = [] } = body
    const resposta = await chatComBond(mensagem, historico)
    return NextResponse.json({ resposta })
  }

  if (acao === 'sugerir_conteudo') {
    const { tema, plataforma } = body
    const sugestao = await gerarSugestaoConteudo(tema, plataforma)
    return NextResponse.json({ sugestao })
  }

  if (acao === 'analisar') {
    const [posts, audiencia] = await Promise.allSettled([analisarTopPosts(), analisarAudiencia()])
    return NextResponse.json({
      posts: posts.status === 'fulfilled' ? posts.value : null,
      audiencia: audiencia.status === 'fulfilled' ? audiencia.value : null,
    })
  }

  if (acao === 'sugerir_resposta') {
    const { comentarioId, plataforma } = body
    const sugestao = await sugerirResposta(comentarioId, plataforma)
    return NextResponse.json({ sugestao })
  }

  if (acao === 'aprovar_resposta') {
    const { comentarioId, plataforma, texto } = body
    await aprovarResposta(comentarioId, plataforma, texto)
    return NextResponse.json({ ok: true })
  }

  if (acao === 'rejeitar_comentario') {
    const { comentarioId, plataforma } = body
    await rejeitarComentario(comentarioId, plataforma)
    return NextResponse.json({ ok: true })
  }

  if (acao === 'salvar_rascunho') {
    const { titulo, texto, plataformas, tipo, hashtags } = body
    const r = await prisma.bondRascunho.create({
      data: { titulo, texto, plataformas: plataformas ?? 'todas', tipo: tipo ?? 'post', hashtags },
    })
    return NextResponse.json(r)
  }

  if (acao === 'marcar_insight_lido') {
    await prisma.bondInsight.update({ where: { id: body.id }, data: { lido: true } })
    return NextResponse.json({ ok: true })
  }

  if (acao === 'deletar_rascunho') {
    await prisma.bondRascunho.delete({ where: { id: body.id } })
    return NextResponse.json({ ok: true })
  }

  return NextResponse.json({ error: 'Ação inválida' }, { status: 400 })
}
