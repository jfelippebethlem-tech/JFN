import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()

  const pessoa = await prisma.pessoa.update({
    where: { id: params.id },
    data: {
      nome: body.nome,
      tipo: body.tipo,
      cargo: body.cargo || null,
      email: body.email || null,
      telefone: body.telefone || null,
      twitter: body.twitter || null,
      instagram: body.instagram || null,
      telegramUser: body.telegramUser || null,
      observacoes: body.observacoes || null,
    },
  })

  return NextResponse.json(pessoa)
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  await prisma.pessoa.update({
    where: { id: params.id },
    data: { ativo: false },
  })

  return NextResponse.json({ ok: true })
}
