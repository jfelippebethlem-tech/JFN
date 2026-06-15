import { NextRequest, NextResponse } from 'next/server'
import { listarAcoes, executarAcao } from '@/lib/acoes'

// GET /api/acoes            → lista o catálogo de ações (introspecção p/ Hermes)
// GET /api/acoes?nome=X&... → executa a ação X (params via querystring)
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const nome = searchParams.get('nome')
  if (!nome) {
    return NextResponse.json({ acoes: listarAcoes() })
  }
  const params: Record<string, string> = {}
  searchParams.forEach((v, k) => { if (k !== 'nome') params[k] = v })
  const origem = (searchParams.get('origem') as 'hermes' | 'humano' | 'sistema') ?? 'humano'
  const r = await executarAcao(nome, params, origem)
  return NextResponse.json(r)
}

// POST /api/acoes  { nome, params, origem }
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  const { nome, params = {}, origem = 'humano' } = body
  if (!nome) return NextResponse.json({ ok: false, erro: 'Informe "nome" da ação' }, { status: 400 })
  const r = await executarAcao(nome, params, origem)
  return NextResponse.json(r)
}
