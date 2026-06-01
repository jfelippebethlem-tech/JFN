import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const demanda = await prisma.demanda.findUnique({
    where: { id: params.id },
    include: { pessoa: true },
  })

  if (!demanda) {
    return NextResponse.json({ error: 'Não encontrada' }, { status: 404 })
  }

  return NextResponse.json(demanda)
}

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()

  const demanda = await prisma.demanda.update({
    where: { id: params.id },
    data: {
      titulo: body.titulo,
      descricao: body.descricao,
      status: body.status,
      prioridade: body.prioridade,
      origem: body.origem || null,
      pessoaId: body.pessoaId || null,
      resposta: body.resposta || null,
    },
    include: { pessoa: true },
  })

  return NextResponse.json(demanda)
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  await prisma.demanda.delete({ where: { id: params.id } })
  return NextResponse.json({ ok: true })
}
