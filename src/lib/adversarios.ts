/**
 * Monitoramento de adversários — Share of Voice.
 * Reutiliza BondPerfil (categoria="adversario") e BondPost (via perfilId).
 * Sincroniza dados PÚBLICOS via Instagram Business Discovery e Twitter público.
 */
import { prisma } from './db'
import { getInstagramAccountId, getInstagramBusinessDiscovery } from './social/instagram'
import { getTwitterUser, getTwitterTweets } from './social/twitter'

// Adiciona/atualiza um adversário a monitorar
export async function adicionarAdversario(plataforma: string, handle: string, nome?: string) {
  const h = handle.replace(/^@/, '').trim().toLowerCase()
  const perfil = await prisma.bondPerfil.upsert({
    where: { plataforma_handle: { plataforma, handle: h } },
    update: { categoria: 'adversario', nomeCompleto: nome ?? undefined },
    create: { plataforma, handle: h, categoria: 'adversario', nomeCompleto: nome ?? h },
  })
  return perfil
}

export async function removerAdversario(perfilId: string) {
  // Soft remove: marca inativo
  await prisma.bondPerfil.update({ where: { id: perfilId }, data: { ativo: false } })
  return { ok: true }
}

// Sincroniza posts/engajamento dos adversários (dados públicos)
export async function sincronizarAdversarios() {
  const adversarios = await prisma.bondPerfil.findMany({
    where: { categoria: 'adversario', ativo: true },
  })
  if (adversarios.length === 0) return { sincronizados: 0, detalhes: ['Nenhum adversário cadastrado'] }

  const meuIgId = await getInstagramAccountId()
  const detalhes: string[] = []
  let sincronizados = 0

  for (const adv of adversarios) {
    try {
      if (adv.plataforma === 'instagram' && meuIgId) {
        const bd = await getInstagramBusinessDiscovery(meuIgId, adv.handle, 12)
        if (!bd) { detalhes.push(`${adv.handle}: sem dados (conta privada ou inexistente)`); continue }
        await prisma.bondPerfil.update({
          where: { id: adv.id },
          data: { seguidores: bd.followers_count ?? 0, totalPosts: bd.media_count ?? 0, nomeCompleto: bd.name ?? adv.handle, fotoUrl: bd.profile_picture_url, ultimaSync: new Date() },
        })
        for (const m of bd.media?.data ?? []) {
          await prisma.bondPost.upsert({
            where: { plataforma_postId: { plataforma: 'instagram', postId: m.id } },
            update: { likes: m.like_count ?? 0, comentarios: m.comments_count ?? 0, sincronizadoEm: new Date() },
            create: {
              plataforma: 'instagram', postId: m.id, conteudo: m.caption ?? '',
              tipo: m.media_type === 'VIDEO' ? 'video' : 'foto', url: m.permalink,
              likes: m.like_count ?? 0, comentarios: m.comments_count ?? 0,
              publicadoEm: new Date(m.timestamp), perfilId: adv.id,
            },
          })
        }
        sincronizados++
        detalhes.push(`${adv.handle}: ${bd.media?.data?.length ?? 0} posts, ${bd.followers_count} seguidores`)
      } else if (adv.plataforma === 'twitter') {
        const user = await getTwitterUser(adv.handle)
        if (!user) { detalhes.push(`${adv.handle}: usuário Twitter não encontrado`); continue }
        await prisma.bondPerfil.update({
          where: { id: adv.id },
          data: { seguidores: user.public_metrics?.followers_count ?? 0, nomeCompleto: user.name, ultimaSync: new Date() },
        })
        const tweets = await getTwitterTweets(user.id, 12)
        for (const t of tweets) {
          await prisma.bondPost.upsert({
            where: { plataforma_postId: { plataforma: 'twitter', postId: t.id } },
            update: {
              likes: t.public_metrics?.like_count ?? 0,
              comentarios: t.public_metrics?.reply_count ?? 0,
              compartilhos: t.public_metrics?.retweet_count ?? 0,
              sincronizadoEm: new Date(),
            },
            create: {
              plataforma: 'twitter', postId: t.id, conteudo: t.text ?? '', tipo: 'texto',
              likes: t.public_metrics?.like_count ?? 0,
              comentarios: t.public_metrics?.reply_count ?? 0,
              compartilhos: t.public_metrics?.retweet_count ?? 0,
              publicadoEm: t.created_at ? new Date(t.created_at) : new Date(),
              perfilId: adv.id,
            },
          })
        }
        sincronizados++
        detalhes.push(`${adv.handle}: ${tweets.length} tweets`)
      }
    } catch (e) {
      detalhes.push(`${adv.handle}: erro — ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return { sincronizados, detalhes }
}

// Comparativo: meu engajamento vs adversários (Share of Voice)
export async function compararShareOfVoice(dias = 30) {
  const desde = new Date(Date.now() - dias * 24 * 60 * 60 * 1000)

  async function metricasPerfil(categoria: string) {
    const perfis = await prisma.bondPerfil.findMany({
      where: { categoria, ativo: true },
      include: { postagens: { where: { publicadoEm: { gte: desde } } } },
    })
    return perfis.map(p => {
      const likes = p.postagens.reduce((s, x) => s + x.likes, 0)
      const comments = p.postagens.reduce((s, x) => s + x.comentarios, 0)
      const shares = p.postagens.reduce((s, x) => s + x.compartilhos, 0)
      const engajamentoTotal = likes + comments + shares
      return {
        perfilId: p.id,
        plataforma: p.plataforma,
        handle: p.handle,
        nome: p.nomeCompleto ?? p.handle,
        seguidores: p.seguidores,
        posts: p.postagens.length,
        likes, comments, shares,
        engajamentoTotal,
        engajamentoMedio: p.postagens.length ? Math.round(engajamentoTotal / p.postagens.length) : 0,
      }
    })
  }

  const [proprios, adversarios] = await Promise.all([
    metricasPerfil('proprio'),
    metricasPerfil('adversario'),
  ])

  const meuTotal = proprios.reduce((s, p) => s + p.engajamentoTotal, 0)
  const advTotal = adversarios.reduce((s, p) => s + p.engajamentoTotal, 0)
  const total = meuTotal + advTotal
  const shareOfVoice = total > 0 ? Math.round((meuTotal / total) * 100) : 0

  return {
    proprios,
    adversarios,
    meuEngajamento: meuTotal,
    engajamentoAdversarios: advTotal,
    shareOfVoicePct: shareOfVoice, // % do engajamento total que é meu
    periodoDias: dias,
  }
}
