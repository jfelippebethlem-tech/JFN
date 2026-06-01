import { NextRequest, NextResponse } from 'next/server'
import { gerarResposta, gerarPostRedeSocial, analisarSentimento } from '@/lib/ai'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const { acao } = body

  try {
    if (acao === 'resposta') {
      const texto = await gerarResposta(body.demanda, body.contexto)
      return NextResponse.json({ texto })
    }

    if (acao === 'post') {
      const texto = await gerarPostRedeSocial(body.tema, body.plataforma, body.tom)
      return NextResponse.json({ texto })
    }

    if (acao === 'sentimento') {
      const sentimento = await analisarSentimento(body.texto)
      return NextResponse.json({ sentimento })
    }

    return NextResponse.json({ error: 'Ação inválida' }, { status: 400 })
  } catch (err) {
    console.error(err)
    return NextResponse.json({ error: 'Erro ao processar' }, { status: 500 })
  }
}
