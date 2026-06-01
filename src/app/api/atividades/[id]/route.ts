import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()

  const atividade = await prisma.atividade.update({
    where: { id: params.id },
    data: {
      tipo: body.tipo,
      titulo: body.titulo,
      descricao: body.descricao || null,
      data: new Date(body.data),
      resultado: body.resultado || null,
    },
  })

  return NextResponse.json(atividade)
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  await prisma.atividade.delete({ where: { id: params.id } })
  return NextResponse.json({ ok: true })
}
