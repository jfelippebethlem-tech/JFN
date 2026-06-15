export type Nivel = {
  nivel: number
  nome: string
  cor: string
  bg: string
  minPts: number
  maxPts: number
}

export const NIVEIS: Nivel[] = [
  { nivel: 0, nome: 'Observador',        cor: 'text-slate-400', bg: 'bg-slate-700',  minPts: 0,    maxPts: 49 },
  { nivel: 1, nome: 'Apoiador Ativo',    cor: 'text-green-400', bg: 'bg-green-900',  minPts: 50,   maxPts: 199 },
  { nivel: 2, nome: 'Militante',         cor: 'text-blue-400',  bg: 'bg-blue-900',   minPts: 200,  maxPts: 499 },
  { nivel: 3, nome: 'Ativista',          cor: 'text-purple-400',bg: 'bg-purple-900', minPts: 500,  maxPts: 999 },
  { nivel: 4, nome: 'Líder Comunitário', cor: 'text-orange-400',bg: 'bg-orange-900', minPts: 1000, maxPts: 2499 },
  { nivel: 5, nome: 'Referência',        cor: 'text-yellow-400',bg: 'bg-yellow-900', minPts: 2500, maxPts: Infinity },
]

export type Badge = {
  id: string
  emoji: string
  nome: string
  descricao: string
}

export function getNivel(score: number): Nivel {
  for (let i = NIVEIS.length - 1; i >= 0; i--) {
    if (score >= NIVEIS[i].minPts) return NIVEIS[i]
  }
  return NIVEIS[0]
}

export function getProgressoNivel(score: number): number {
  const n = getNivel(score)
  if (n.maxPts === Infinity) return 100
  const range = n.maxPts - n.minPts + 1
  const progresso = score - n.minPts
  return Math.min(100, Math.floor((progresso / range) * 100))
}

export function getBadges(p: {
  totalLikes: number
  totalComents: number
  totalShares: number
  score: number
  plataformasVinculadas: string[]
  posicaoRanking?: number
  streak?: number
}): Badge[] {
  const badges: Badge[] = []

  if (p.score > 0) {
    badges.push({ id: 'primeiro_passo', emoji: '🌟', nome: 'Primeiro Passo', descricao: 'Primeiro engajamento registrado' })
  }
  if ((p.streak ?? 0) >= 3) {
    badges.push({ id: 'streak3', emoji: '🔥', nome: 'Em Chamas', descricao: `Engajou em ${p.streak} posts seguidos` })
  }
  if ((p.streak ?? 0) >= 7) {
    badges.push({ id: 'streak7', emoji: '⚡', nome: 'Imparável', descricao: `Sequência de ${p.streak} posts!` })
  }
  if (p.totalLikes >= 10) {
    badges.push({ id: 'fa_dedicado', emoji: '❤️', nome: 'Fã Dedicado', descricao: '10+ curtidas' })
  }
  if (p.totalComents >= 5) {
    badges.push({ id: 'comentarista', emoji: '💬', nome: 'Comentarista', descricao: '5+ comentários' })
  }
  if (p.totalShares >= 3) {
    badges.push({ id: 'compartilhador', emoji: '🔄', nome: 'Compartilhador', descricao: '3+ compartilhamentos' })
  }
  if (p.totalShares >= 10) {
    badges.push({ id: 'megafone', emoji: '📣', nome: 'Megafone', descricao: '10+ compartilhamentos' })
  }
  if (p.totalLikes > 0 && p.totalComents > 0 && p.totalShares > 0) {
    badges.push({ id: 'completo', emoji: '🎯', nome: 'Engajado Total', descricao: 'Curtiu, comentou e compartilhou' })
  }
  if (p.plataformasVinculadas.length >= 2) {
    badges.push({ id: 'multi_plat', emoji: '🌐', nome: 'Multi-Plataforma', descricao: '2+ redes sociais vinculadas' })
  }
  if (p.score >= 500) {
    badges.push({ id: 'superstar', emoji: '⭐', nome: 'Superstar', descricao: '500+ pontos' })
  }
  if (p.posicaoRanking !== undefined && p.posicaoRanking >= 1 && p.posicaoRanking <= 3) {
    const emojis = ['🥇', '🥈', '🥉']
    badges.push({ id: 'top3', emoji: emojis[p.posicaoRanking - 1], nome: `Top ${p.posicaoRanking}`, descricao: `#${p.posicaoRanking} no ranking geral` })
  }

  return badges
}
