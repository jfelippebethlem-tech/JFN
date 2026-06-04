import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { syncAll, syncTwitter, syncFacebook, syncInstagram, gerarSugestaoConteudo, chatComBond, analisarTopPosts, analisarAudiencia } from '@/lib/bond'

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
    })
    return NextResponse.json(fas)
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
  const [perfis, totalPosts, totalFas, insightsNaoLidos, stats] = await Promise.all([
    prisma.bondPerfil.findMany({ where: { ativo: true } }),
    prisma.bondPost.count(),
    prisma.bondFa.count(),
    prisma.bondInsight.count({ where: { lido: false } }),
    prisma.bondPost.aggregate({
      _sum: { likes: true, comentarios: true, compartilhos: true, alcance: true },
      _avg: { engajamento: true },
    }),
  ])

  return NextResponse.json({ perfis, totalPosts, totalFas, insightsNaoLidos, stats })
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
