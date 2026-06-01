'use client'

import { useEffect, useState } from 'react'
import { Radio, Plus, Search, Trash2, Loader2, X, Tag, ExternalLink } from 'lucide-react'

type Post = {
  id: string
  plataforma: string
  conteudo: string
  url: string | null
  likes: number
  shares: number
  sentimento: string | null
  palavra: string | null
  pessoa: { nome: string } | null
  criadoEm: string
}

type PalavraChave = {
  id: string
  palavra: string
  ativa: boolean
}

const sentimentoColor: Record<string, string> = {
  positivo: 'bg-green-100 text-green-700',
  negativo: 'bg-red-100 text-red-700',
  neutro: 'bg-gray-100 text-gray-700',
}

const plataformaColor: Record<string, string> = {
  twitter: 'bg-sky-100 text-sky-700',
  instagram: 'bg-pink-100 text-pink-700',
  facebook: 'bg-blue-100 text-blue-700',
  youtube: 'bg-red-100 text-red-700',
  outro: 'bg-gray-100 text-gray-700',
}

export default function MonitoramentoPage() {
  const [posts, setPosts] = useState<Post[]>([])
  const [palavras, setPalavras] = useState<PalavraChave[]>([])
  const [loading, setLoading] = useState(true)
  const [sentFilter, setSentFilter] = useState('')
  const [platFilter, setPlatFilter] = useState('')
  const [showAddPost, setShowAddPost] = useState(false)
  const [showAddPalavra, setShowAddPalavra] = useState(false)
  const [novaPalavra, setNovaPalavra] = useState('')
  const [saving, setSaving] = useState(false)
  const [aiLoading, setAiLoading] = useState<string | null>(null)
  const [postForm, setPostForm] = useState({
    plataforma: 'twitter',
    conteudo: '',
    url: '',
    likes: '0',
    shares: '0',
    palavra: '',
  })

  async function loadPosts() {
    setLoading(true)
    const params = new URLSearchParams()
    if (sentFilter) params.set('sentimento', sentFilter)
    if (platFilter) params.set('plataforma', platFilter)
    const res = await fetch(`/api/posts?${params}`)
    const data = await res.json()
    setPosts(data)
    setLoading(false)
  }

  async function loadPalavras() {
    const res = await fetch('/api/palavras-chave')
    const data = await res.json()
    setPalavras(data)
  }

  useEffect(() => {
    loadPosts()
    loadPalavras()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sentFilter, platFilter])

  async function handleAddPost(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    await fetch('/api/posts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...postForm,
        likes: parseInt(postForm.likes) || 0,
        shares: parseInt(postForm.shares) || 0,
      }),
    })
    setSaving(false)
    setShowAddPost(false)
    setPostForm({ plataforma: 'twitter', conteudo: '', url: '', likes: '0', shares: '0', palavra: '' })
    loadPosts()
  }

  async function handleAddPalavra(e: React.FormEvent) {
    e.preventDefault()
    if (!novaPalavra.trim()) return
    await fetch('/api/palavras-chave', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ palavra: novaPalavra.trim().toLowerCase() }),
    })
    setNovaPalavra('')
    setShowAddPalavra(false)
    loadPalavras()
  }

  async function togglePalavra(id: string, ativa: boolean) {
    await fetch(`/api/palavras-chave/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ativa: !ativa }),
    })
    loadPalavras()
  }

  async function deletePalavra(id: string) {
    await fetch(`/api/palavras-chave/${id}`, { method: 'DELETE' })
    loadPalavras()
  }

  async function analisarSentimento(postId: string, conteudo: string) {
    setAiLoading(postId)
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sentimento', texto: conteudo }),
    })
    const data = await res.json()
    if (data.sentimento) {
      setPosts((prev) =>
        prev.map((p) => (p.id === postId ? { ...p, sentimento: data.sentimento } : p))
      )
    }
    setAiLoading(null)
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Monitoramento</h1>
          <p className="text-gray-500 text-sm mt-1">Acompanhe menções e posts nas redes sociais</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowAddPalavra(true)}
            className="btn-secondary flex items-center gap-2"
          >
            <Tag className="w-4 h-4" /> Palavras-chave
          </button>
          <button
            onClick={() => setShowAddPost(true)}
            className="btn-primary flex items-center gap-2"
          >
            <Plus className="w-4 h-4" /> Adicionar Post
          </button>
        </div>
      </div>

      {palavras.length > 0 && (
        <div className="card mb-6 p-4">
          <p className="text-xs font-medium text-gray-500 mb-2">Palavras monitoradas:</p>
          <div className="flex flex-wrap gap-2">
            {palavras.map((p) => (
              <span
                key={p.id}
                className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium cursor-pointer transition-colors ${
                  p.ativa
                    ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                    : 'bg-gray-100 text-gray-400 line-through'
                }`}
                onClick={() => togglePalavra(p.id, p.ativa)}
              >
                {p.palavra}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    deletePalavra(p.id)
                  }}
                  className="hover:text-red-500 ml-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <div className="input pl-9 bg-white text-gray-400 cursor-default">Filtrar posts...</div>
        </div>
        <select
          value={platFilter}
          onChange={(e) => setPlatFilter(e.target.value)}
          className="input w-40"
        >
          <option value="">Todas as plataformas</option>
          <option value="twitter">Twitter/X</option>
          <option value="instagram">Instagram</option>
          <option value="facebook">Facebook</option>
          <option value="youtube">YouTube</option>
          <option value="outro">Outro</option>
        </select>
        <select
          value={sentFilter}
          onChange={(e) => setSentFilter(e.target.value)}
          className="input w-40"
        >
          <option value="">Todos sentimentos</option>
          <option value="positivo">Positivo</option>
          <option value="neutro">Neutro</option>
          <option value="negativo">Negativo</option>
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : posts.length === 0 ? (
        <div className="card text-center py-12">
          <Radio className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhum post monitorado ainda</p>
          <p className="text-gray-400 text-sm mt-1">
            Adicione posts manualmente ou configure integração com APIs
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {posts.map((post) => (
            <div key={post.id} className="card p-4">
              <div className="flex items-start gap-3">
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize shrink-0 ${
                    plataformaColor[post.plataforma] ?? 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {post.plataforma}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800">{post.conteudo}</p>
                  <div className="flex items-center gap-3 mt-2">
                    {post.pessoa && (
                      <span className="text-xs text-blue-600">{post.pessoa.nome}</span>
                    )}
                    {post.palavra && (
                      <span className="text-xs text-gray-400">#{post.palavra}</span>
                    )}
                    <span className="text-xs text-gray-400">
                      ❤️ {post.likes} · 🔁 {post.shares}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {post.sentimento ? (
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        sentimentoColor[post.sentimento] ?? ''
                      }`}
                    >
                      {post.sentimento}
                    </span>
                  ) : (
                    <button
                      onClick={() => analisarSentimento(post.id, post.conteudo)}
                      disabled={!!aiLoading}
                      className="text-xs text-blue-600 hover:text-blue-700 disabled:opacity-40 flex items-center gap-1"
                    >
                      {aiLoading === post.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : null}
                      Analisar
                    </button>
                  )}
                  {post.url && (
                    <a
                      href={post.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1 text-gray-400 hover:text-blue-600"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAddPost && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="font-semibold text-gray-900">Adicionar Post</h2>
              <button onClick={() => setShowAddPost(false)} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleAddPost} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Plataforma</label>
                <select value={postForm.plataforma} onChange={(e) => setPostForm({ ...postForm, plataforma: e.target.value })} className="input">
                  <option value="twitter">Twitter/X</option>
                  <option value="instagram">Instagram</option>
                  <option value="facebook">Facebook</option>
                  <option value="youtube">YouTube</option>
                  <option value="outro">Outro</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Conteúdo *</label>
                <textarea required value={postForm.conteudo} onChange={(e) => setPostForm({ ...postForm, conteudo: e.target.value })} className="input" rows={3} placeholder="Texto do post..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">URL</label>
                <input value={postForm.url} onChange={(e) => setPostForm({ ...postForm, url: e.target.value })} className="input" placeholder="https://..." />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Likes</label>
                  <input type="number" value={postForm.likes} onChange={(e) => setPostForm({ ...postForm, likes: e.target.value })} className="input" min="0" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Shares</label>
                  <input type="number" value={postForm.shares} onChange={(e) => setPostForm({ ...postForm, shares: e.target.value })} className="input" min="0" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Palavra</label>
                  <input value={postForm.palavra} onChange={(e) => setPostForm({ ...postForm, palavra: e.target.value })} className="input" placeholder="tag..." />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowAddPost(false)} className="btn-secondary flex-1">Cancelar</button>
                <button type="submit" className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Adicionar
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showAddPalavra && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="font-semibold text-gray-900">Nova Palavra-chave</h2>
              <button onClick={() => setShowAddPalavra(false)} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleAddPalavra} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Palavra *</label>
                <input required value={novaPalavra} onChange={(e) => setNovaPalavra(e.target.value)} className="input" placeholder="Ex: assembleia" autoFocus />
              </div>
              <div className="flex gap-3">
                <button type="button" onClick={() => setShowAddPalavra(false)} className="btn-secondary flex-1">Cancelar</button>
                <button type="submit" className="btn-primary flex-1">Adicionar</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
