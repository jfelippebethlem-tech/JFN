import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET() {
  const palavras = await prisma.palavraChave.findMany({
    orderBy: { palavra: 'asc' },
  })
  return NextResponse.json(palavras)
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const palavra = await prisma.palavraChave.create({
    data: { palavra: body.palavra },
  })

  return NextResponse.json(palavra, { status: 201 })
}
