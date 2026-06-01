import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const plataforma = searchParams.get('plataforma') ?? ''
  const sentimento = searchParams.get('sentimento') ?? ''

  const posts = await prisma.post.findMany({
    where: {
      ...(plataforma ? { plataforma } : {}),
      ...(sentimento ? { sentimento } : {}),
    },
    include: { pessoa: true },
    orderBy: { criadoEm: 'desc' },
    take: 50,
  })

  return NextResponse.json(posts)
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const post = await prisma.post.create({
    data: {
      plataforma: body.plataforma,
      conteudo: body.conteudo,
      url: body.url || null,
      likes: body.likes ?? 0,
      shares: body.shares ?? 0,
      sentimento: body.sentimento || null,
      pessoaId: body.pessoaId || null,
      palavra: body.palavra || null,
    },
    include: { pessoa: true },
  })

  return NextResponse.json(post, { status: 201 })
}
