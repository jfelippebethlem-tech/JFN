import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { statusWhatsapp, estatisticasFila, enfileirarBroadcast, enfileirarWhatsapp } from '@/lib/whatsapp'
import { registrarNps } from '@/lib/nps'

// GET /api/whatsapp?tipo=status|fila
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo') ?? 'status'

  if (tipo === 'fila') {
    const itens = await prisma.whatsappFila.findMany({ orderBy: { criadoEm: 'desc' }, take: 50 })
    const stats = await estatisticasFila()
    return NextResponse.json({ stats, itens })
  }

  const [status, stats] = await Promise.all([statusWhatsapp(), estatisticasFila()])
  return NextResponse.json({ ...status, fila: stats })
}

// POST /api/whatsapp  { acao: 'broadcast'|'enviar'|'nps', ... }
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  const { acao } = body

  if (acao === 'broadcast') {
    if (!body.mensagem?.trim()) return NextResponse.json({ error: 'Mensagem obrigatória' }, { status: 400 })
    return NextResponse.json(await enfileirarBroadcast(body.mensagem, 'broadcast'))
  }

  if (acao === 'enviar') {
    if (!body.telefone || !body.mensagem) return NextResponse.json({ error: 'telefone e mensagem obrigatórios' }, { status: 400 })
    return NextResponse.json(await enfileirarWhatsapp({ telefone: body.telefone, mensagem: body.mensagem, pessoaId: body.pessoaId }))
  }

  if (acao === 'nps') {
    if (!body.pessoaId || body.nota == null) return NextResponse.json({ error: 'pessoaId e nota obrigatórios' }, { status: 400 })
    return NextResponse.json(await registrarNps(body.pessoaId, Number(body.nota), body.comentario))
  }

  return NextResponse.json({ error: 'Ação inválida' }, { status: 400 })
}
