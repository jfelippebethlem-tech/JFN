const TWITTER_BASE = 'https://api.twitter.com/2'

function headers() {
  return {
    Authorization: `Bearer ${process.env.TWITTER_BEARER_TOKEN}`,
    'Content-Type': 'application/json',
  }
}

export async function getTwitterUser(username: string) {
  if (!process.env.TWITTER_BEARER_TOKEN) return null
  const res = await fetch(
    `${TWITTER_BASE}/users/by/username/${username}?user.fields=public_metrics,description,profile_image_url`,
    { headers: headers() }
  )
  if (!res.ok) return null
  const data = await res.json()
  return data.data ?? null
}

export async function getTwitterTweets(userId: string, maxResults = 20) {
  if (!process.env.TWITTER_BEARER_TOKEN) return []
  const res = await fetch(
    `${TWITTER_BASE}/users/${userId}/tweets?max_results=${maxResults}&tweet.fields=public_metrics,created_at,attachments&expansions=attachments.media_keys&media.fields=url,preview_image_url`,
    { headers: headers() }
  )
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

export async function getTwitterLikers(tweetId: string) {
  if (!process.env.TWITTER_BEARER_TOKEN) return []
  const res = await fetch(
    `${TWITTER_BASE}/tweets/${tweetId}/liking_users?user.fields=name,username,profile_image_url`,
    { headers: headers() }
  )
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}

export async function getTwitterRetweeters(tweetId: string) {
  if (!process.env.TWITTER_BEARER_TOKEN) return []
  const res = await fetch(
    `${TWITTER_BASE}/tweets/${tweetId}/retweeted_by?user.fields=name,username,profile_image_url`,
    { headers: headers() }
  )
  if (!res.ok) return []
  const data = await res.json()
  return data.data ?? []
}
