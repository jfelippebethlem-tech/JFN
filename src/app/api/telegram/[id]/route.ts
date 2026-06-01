import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()

  const mensagem = await prisma.telegramMensagem.update({
    where: { id: params.id },
    data: {
      respondida: body.respondida ?? true,
      resposta: body.resposta || null,
    },
  })

  return NextResponse.json(mensagem)
}
