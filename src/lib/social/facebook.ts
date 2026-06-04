const FB_BASE = 'https://graph.facebook.com/v19.0'

function fbUrl(path: string, extra = '') {
  const token = process.env.FACEBOOK_PAGE_TOKEN
  return `${FB_BASE}${path}?access_token=${token}${extra ? '&' + extra : ''}`
}

export async function getFacebookPageInfo() {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return null
  const res = await fetch(
    fbUrl('/me', 'fields=id,name,fan_count,followers_count,about,picture')
  )
  if (!res.ok) return null
  return res.json()
}

export async function getFacebookPosts(limit = 20) {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return []
  const fields = 'id,message,story,created_time,full_picture,permalink_url,likes.summary(true),comments.summary(true),shares'
  const res = await fetch(fbUrl('/me/posts', `fields=${fields}&limit=${limit}`))
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

export async function getFacebookPostInsights(postId: string) {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return null
  const metrics = 'post_impressions,post_impressions_unique,post_engaged_users,post_clicks'
  const res = await fetch(fbUrl(`/${postId}/insights`, `metric=${metrics}`))
  if (!res.ok) return null
  return res.json()
}

export async function getFacebookPostLikers(postId: string) {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return []
  const res = await fetch(fbUrl(`/${postId}/likes`, 'fields=id,name,pic_square&limit=100'))
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

export async function getFacebookPostComments(postId: string) {
  if (!process.env.FACEBOOK_PAGE_TOKEN) return []
  const res = await fetch(fbUrl(`/${postId}/comments`, 'fields=id,from,message,created_time&limit=100'))
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}
