import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET() {
  const configs = await prisma.configuracao.findMany()
  const result: Record<string, string> = {}
  configs.forEach((c) => {
    result[c.chave] = c.valor
  })
  return NextResponse.json(result)
}

export async function POST(req: NextRequest) {
  const body = await req.json()

  const promises = Object.entries(body).map(([chave, valor]) =>
    prisma.configuracao.upsert({
      where: { chave },
      update: { valor: String(valor) },
      create: { chave, valor: String(valor) },
    })
  )

  await Promise.all(promises)
  return NextResponse.json({ ok: true })
}
