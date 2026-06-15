const IG_BASE = 'https://graph.facebook.com/v19.0'

function igUrl(path: string, extra = '') {
  const token = process.env.FACEBOOK_PAGE_TOKEN // Instagram uses same Facebook token
  return `${IG_BASE}${path}?access_token=${token}${extra ? '&' + extra : ''}`
}

export async function getInstagramAccountId() {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return null
  const res = await fetch(igUrl('/me', 'fields=instagram_business_account'))
  if (!res.ok) return null
  const data = await res.json()
  return data.instagram_business_account?.id ?? null
}

export async function getInstagramProfile(igUserId: string) {
  const res = await fetch(
    igUrl(`/${igUserId}`, 'fields=id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url')
  )
  if (!res.ok) return null
  return res.json()
}

export async function getInstagramPosts(igUserId: string, limit = 20) {
  const fields = 'id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count'
  const res = await fetch(igUrl(`/${igUserId}/media`, `fields=${fields}&limit=${limit}`))
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

export async function getInstagramPostInsights(mediaId: string) {
  const metrics = 'reach,impressions,engagement,saved,video_views'
  const res = await fetch(igUrl(`/${mediaId}/insights`, `metric=${metrics}`))
  if (!res.ok) return null
  const data = await res.json()
  if (!data.data) return null
  return Object.fromEntries(data.data.map((m: { name: string; values: { value: number }[] }) => [m.name, m.values?.[0]?.value ?? 0]))
}

export async function getInstagramComments(mediaId: string) {
  const res = await fetch(igUrl(`/${mediaId}/comments`, 'fields=id,username,text,timestamp&limit=100'))
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

// Business Discovery: dados PÚBLICOS de outra conta Business (adversários).
// Usa a própria conta IG como "lente" para consultar perfis públicos.
export async function getInstagramBusinessDiscovery(meuIgId: string, username: string, limitPosts = 12) {
  const sub = `business_discovery.username(${username}){followers_count,media_count,username,name,profile_picture_url,media.limit(${limitPosts}){id,caption,media_type,permalink,timestamp,like_count,comments_count}}`
  const res = await fetch(igUrl(`/${meuIgId}`, `fields=${sub}`))
  if (!res.ok) return null
  const data = await res.json()
  return data.business_discovery ?? null
}
