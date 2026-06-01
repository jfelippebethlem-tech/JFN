import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const respondida = searchParams.get('respondida')

  const mensagens = await prisma.telegramMensagem.findMany({
    where: {
      ...(respondida !== null ? { respondida: respondida === 'true' } : {}),
    },
    orderBy: { criadoEm: 'desc' },
    take: 50,
  })

  return NextResponse.json(mensagens)
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const mensagem = await prisma.telegramMensagem.create({
    data: {
      chatId: body.chatId,
      userId: body.userId || null,
      username: body.username || null,
      nome: body.nome || null,
      mensagem: body.mensagem,
    },
  })

  return NextResponse.json(mensagem, { status: 201 })
}
