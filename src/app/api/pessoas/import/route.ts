import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import Papa from 'papaparse'

interface RowData {
  nome?: string
  instagram?: string
  twitter?: string
  facebook?: string
  telefone?: string
  cargo?: string
  observacoes?: string
  tipo?: string
  [key: string]: string | undefined
}

// Normaliza handle: remove @, espaços, transforma em minúsculas
function normalizeHandle(h?: string): string {
  if (!h) return ''
  return h.replace(/^@/, '').trim().toLowerCase()
}

// Após criar/atualizar Pessoa, vincula BondFa existentes que tiverem o mesmo handle
async function vincularBondFas(pessoaId: string, instagram?: string, twitter?: string, facebook?: string) {
  const links: Promise<unknown>[] = []

  if (instagram) {
    const ig = normalizeHandle(instagram)
    links.push(
      prisma.bondFa.updateMany({
        where: { plataforma: 'instagram', username: { contains: ig }, pessoaId: null },
        data: { pessoaId },
      })
    )
  }
  if (twitter) {
    const tw = normalizeHandle(twitter)
    links.push(
      prisma.bondFa.updateMany({
        where: { plataforma: 'twitter', username: { contains: tw }, pessoaId: null },
        data: { pessoaId },
      })
    )
  }
  if (facebook) {
    const fb = normalizeHandle(facebook)
    links.push(
      prisma.bondFa.updateMany({
        where: { plataforma: 'facebook', username: { contains: fb }, pessoaId: null },
        data: { pessoaId },
      })
    )
  }

  await Promise.allSettled(links)
}

export async function POST(req: NextRequest) {
  const contentType = req.headers.get('content-type') ?? ''

  // ── Importação CSV ────────────────────────────────────────────────────────
  if (contentType.includes('text/csv') || contentType.includes('text/plain')) {
    const text = await req.text()
    const { data, errors } = Papa.parse<RowData>(text, {
      header: true,
      skipEmptyLines: true,
      transformHeader: h => h.trim().toLowerCase().replace(/\s+/g, '_'),
    })

    if (errors.length > 0 && data.length === 0) {
      return NextResponse.json({ error: 'CSV inválido', details: errors }, { status: 400 })
    }

    const results = { criados: 0, atualizados: 0, erros: 0, detalhes: [] as string[] }

    for (const row of data) {
      const nome = (row['nome'] ?? row['name'] ?? '').trim()
      if (!nome) continue

      const instagram = normalizeHandle(row['instagram'] ?? row['instagram_handle'])
      const twitter = normalizeHandle(row['twitter'] ?? row['twitter_handle'] ?? row['x'])
      const facebook = normalizeHandle(row['facebook'] ?? row['facebook_handle'])
      const tipo = (row['tipo'] ?? 'cabo_eleitoral').trim()
      const cargo = (row['cargo'] ?? '').trim() || undefined
      const telefone = (row['telefone'] ?? row['telefone_celular'] ?? '').trim() || undefined
      const observacoes = (row['observacoes'] ?? row['observação'] ?? row['obs'] ?? '').trim() || undefined

      try {
        // Tenta encontrar por instagram, twitter ou facebook
        const existente = await prisma.pessoa.findFirst({
          where: {
            OR: [
              instagram ? { instagram: { contains: instagram } } : {},
              twitter ? { twitter: { contains: twitter } } : {},
              facebook ? { facebook: { contains: facebook } } : {},
              { nome: { equals: nome } },
            ].filter(w => Object.keys(w).length > 0),
          },
        })

        if (existente) {
          await prisma.pessoa.update({
            where: { id: existente.id },
            data: {
              nome,
              tipo,
              cargo,
              telefone,
              observacoes,
              instagram: instagram || existente.instagram || undefined,
              twitter: twitter || existente.twitter || undefined,
              facebook: facebook || existente.facebook || undefined,
            },
          })
          await vincularBondFas(existente.id, instagram, twitter, facebook)
          results.atualizados++
        } else {
          const pessoa = await prisma.pessoa.create({
            data: {
              nome,
              tipo,
              cargo,
              telefone,
              observacoes,
              instagram: instagram || undefined,
              twitter: twitter || undefined,
              facebook: facebook || undefined,
            },
          })
          await vincularBondFas(pessoa.id, instagram, twitter, facebook)
          results.criados++
        }
      } catch (e) {
        results.erros++
        results.detalhes.push(`Erro ao processar "${nome}": ${e}`)
      }
    }

    return NextResponse.json(results)
  }

  // ── Criação/atualização manual de um cabo ─────────────────────────────────
  if (contentType.includes('application/json')) {
    const body = await req.json()
    const { nome, instagram, twitter, facebook, telefone, cargo, observacoes, tipo = 'cabo_eleitoral', pessoaId } = body

    if (!nome?.trim()) {
      return NextResponse.json({ error: 'Nome é obrigatório' }, { status: 400 })
    }

    const ig = normalizeHandle(instagram)
    const tw = normalizeHandle(twitter)
    const fb = normalizeHandle(facebook)

    if (pessoaId) {
      // Atualiza existente
      const pessoa = await prisma.pessoa.update({
        where: { id: pessoaId },
        data: { nome: nome.trim(), tipo, cargo: cargo || undefined, telefone: telefone || undefined, observacoes: observacoes || undefined, instagram: ig || undefined, twitter: tw || undefined, facebook: fb || undefined },
      })
      await vincularBondFas(pessoa.id, ig, tw, fb)
      return NextResponse.json(pessoa)
    } else {
      const pessoa = await prisma.pessoa.create({
        data: { nome: nome.trim(), tipo, cargo: cargo || undefined, telefone: telefone || undefined, observacoes: observacoes || undefined, instagram: ig || undefined, twitter: tw || undefined, facebook: fb || undefined },
      })
      await vincularBondFas(pessoa.id, ig, tw, fb)
      return NextResponse.json(pessoa)
    }
  }

  return NextResponse.json({ error: 'Content-Type não suportado. Use text/csv ou application/json.' }, { status: 415 })
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo')
  const search = searchParams.get('q') ?? ''

  const where = {
    ...(tipo ? { tipo } : { tipo: { in: ['cabo_eleitoral', 'coordenador'] } }),
    ...(search ? { nome: { contains: search } } : {}),
    ativo: true,
  }

  const cabos = await prisma.pessoa.findMany({
    where,
    orderBy: { nome: 'asc' },
    include: {
      bondFas: {
        select: { id: true, plataforma: true, totalLikes: true, totalComents: true, totalShares: true },
      },
    },
  })

  return NextResponse.json(cabos.map(c => ({
    ...c,
    score: c.bondFas.reduce((s, f) => s + f.totalLikes + f.totalComents * 2 + f.totalShares * 3, 0),
    plataformasVinculadas: Array.from(new Set(c.bondFas.map(f => f.plataforma))),
  })))
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const id = searchParams.get('id')
  if (!id) return NextResponse.json({ error: 'ID obrigatório' }, { status: 400 })

  await prisma.pessoa.update({ where: { id }, data: { ativo: false } })
  return NextResponse.json({ ok: true })
}
