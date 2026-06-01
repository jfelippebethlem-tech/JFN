import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function PUT(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json()

  const palavra = await prisma.palavraChave.update({
    where: { id: params.id },
    data: { ativa: body.ativa },
  })

  return NextResponse.json(palavra)
}

export async function DELETE(_req: NextRequest, { params }: { params: { id: string } }) {
  await prisma.palavraChave.delete({ where: { id: params.id } })
  return NextResponse.json({ ok: true })
}
