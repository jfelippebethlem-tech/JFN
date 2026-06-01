import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const tipo = searchParams.get('tipo') ?? ''

  const atividades = await prisma.atividade.findMany({
    where: {
      ...(tipo ? { tipo } : {}),
    },
    orderBy: { data: 'desc' },
  })

  return NextResponse.json(atividades)
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const atividade = await prisma.atividade.create({
    data: {
      tipo: body.tipo,
      titulo: body.titulo,
      descricao: body.descricao || null,
      data: new Date(body.data),
      resultado: body.resultado || null,
    },
  })

  return NextResponse.json(atividade, { status: 201 })
}
