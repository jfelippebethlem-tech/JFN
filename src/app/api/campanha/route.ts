import { NextRequest, NextResponse } from 'next/server'
import { analisarPadroesCampanha, sugerirConteudoViral, buscarInsightsCampanha, analisarMelhoresHorarios } from '@/lib/campanha'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo')

  if (tipo === 'insights') {
    return NextResponse.json(await buscarInsightsCampanha())
  }

  if (tipo === 'horarios') {
    return NextResponse.json(await analisarMelhoresHorarios())
  }

  return NextResponse.json({ error: 'tipo inválido' }, { status: 400 })
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const { acao } = body

  if (acao === 'analisar') {
    const resultado = await analisarPadroesCampanha()
    return NextResponse.json(resultado)
  }

  if (acao === 'sugerir_viral') {
    const { tema } = body
    const sugestao = await sugerirConteudoViral(tema)
    return NextResponse.json({ sugestao })
  }

  return NextResponse.json({ error: 'Ação inválida' }, { status: 400 })
}
