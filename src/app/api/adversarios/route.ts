import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { adicionarAdversario, removerAdversario, sincronizarAdversarios, compararShareOfVoice } from '@/lib/adversarios'
import { calcularNps } from '@/lib/nps'

// GET /api/adversarios?tipo=sov|lista|nps
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo') ?? 'sov'

  if (tipo === 'nps') return NextResponse.json(await calcularNps())

  if (tipo === 'lista') {
    const lista = await prisma.bondPerfil.findMany({
      where: { categoria: 'adversario', ativo: true },
      orderBy: { seguidores: 'desc' },
    })
    return NextResponse.json(lista)
  }

  const dias = parseInt(searchParams.get('dias') ?? '30')
  return NextResponse.json(await compararShareOfVoice(dias))
}

// POST /api/adversarios  { acao: 'adicionar'|'sincronizar'|'remover', ... }
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  const { acao } = body

  if (acao === 'adicionar') {
    if (!body.plataforma || !body.handle) return NextResponse.json({ error: 'plataforma e handle obrigatórios' }, { status: 400 })
    return NextResponse.json(await adicionarAdversario(body.plataforma, body.handle, body.nome))
  }
  if (acao === 'sincronizar') {
    return NextResponse.json(await sincronizarAdversarios())
  }
  if (acao === 'remover') {
    if (!body.perfilId) return NextResponse.json({ error: 'perfilId obrigatório' }, { status: 400 })
    return NextResponse.json(await removerAdversario(body.perfilId))
  }
  return NextResponse.json({ error: 'Ação inválida' }, { status: 400 })
}
