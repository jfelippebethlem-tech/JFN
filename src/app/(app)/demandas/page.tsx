'use client'

import { useEffect, useState } from 'react'
import { FileText, Plus, Search, Edit2, Trash2, Loader2, X, Bot } from 'lucide-react'

type Pessoa = { id: string; nome: string }

type Demanda = {
  id: string
  titulo: string
  descricao: string
  status: string
  prioridade: string
  origem: string | null
  pessoaId: string | null
  pessoa: Pessoa | null
  resposta: string | null
  criadoEm: string
}

const statusLabel: Record<string, string> = {
  aberta: 'Aberta',
  em_andamento: 'Em andamento',
  resolvida: 'Resolvida',
}

const statusColor: Record<string, string> = {
  aberta: 'bg-red-100 text-red-700',
  em_andamento: 'bg-yellow-100 text-yellow-700',
  resolvida: 'bg-green-100 text-green-700',
}

const prioridadeColor: Record<string, string> = {
  alta: 'bg-red-100 text-red-700',
  media: 'bg-yellow-100 text-yellow-700',
  baixa: 'bg-blue-100 text-blue-700',
}

const emptyForm = {
  titulo: '',
  descricao: '',
  status: 'aberta',
  prioridade: 'media',
  origem: '',
  pessoaId: '',
  resposta: '',
}

export default function DemandasPage() {
  const [demandas, setDemandas] = useState<Demanda[]>([])
  const [pessoas, setPessoas] = useState<Pessoa[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [prioridadeFilter, setPrioridadeFilter] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Demanda | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)

  async function load() {
    setLoading(true)
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (statusFilter) params.set('status', statusFilter)
    if (prioridadeFilter) params.set('prioridade', prioridadeFilter)
    const res = await fetch(`/api/demandas?${params}`)
    const data = await res.json()
    setDemandas(data)
    setLoading(false)
  }

  async function loadPessoas() {
    const res = await fetch('/api/pessoas')
    const data = await res.json()
    setPessoas(data)
  }

  useEffect(() => {
    load()
    loadPessoas()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, statusFilter, prioridadeFilter])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm)
    setShowModal(true)
  }

  function openEdit(d: Demanda) {
    setEditing(d)
    setForm({
      titulo: d.titulo,
      descricao: d.descricao,
      status: d.status,
      prioridade: d.prioridade,
      origem: d.origem ?? '',
      pessoaId: d.pessoaId ?? '',
      resposta: d.resposta ?? '',
    })
    setShowModal(true)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    const method = editing ? 'PUT' : 'POST'
    const url = editing ? `/api/demandas/${editing.id}` : '/api/demandas'
    await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setSaving(false)
    setShowModal(false)
    load()
  }

  async function handleDelete(id: string) {
    if (!confirm('Deseja excluir esta demanda?')) return
    await fetch(`/api/demandas/${id}`, { method: 'DELETE' })
    load()
  }

  async function gerarRespostaIA() {
    if (!form.descricao) return
    setAiLoading(true)
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'resposta', demanda: form.titulo + ': ' + form.descricao }),
    })
    const data = await res.json()
    if (data.texto) {
      setForm({ ...form, resposta: data.texto })
    }
    setAiLoading(false)
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Demandas</h1>
          <p className="text-gray-500 text-sm mt-1">Solicitações e demandas da população</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> Nova Demanda
        </button>
      </div>

      <div className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar demandas..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input w-40"
        >
          <option value="">Todos os status</option>
          <option value="aberta">Aberta</option>
          <option value="em_andamento">Em andamento</option>
          <option value="resolvida">Resolvida</option>
        </select>
        <select
          value={prioridadeFilter}
          onChange={(e) => setPrioridadeFilter(e.target.value)}
          className="input w-40"
        >
          <option value="">Todas as prioridades</option>
          <option value="alta">Alta</option>
          <option value="media">Média</option>
          <option value="baixa">Baixa</option>
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : demandas.length === 0 ? (
        <div className="card text-center py-12">
          <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhuma demanda encontrada</p>
        </div>
      ) : (
        <div className="space-y-3">
          {demandas.map((d) => (
            <div key={d.id} className="card p-4">
              <div className="flex items-start gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColor[d.status] ?? ''}`}
                    >
                      {statusLabel[d.status] ?? d.status}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${prioridadeColor[d.prioridade] ?? ''}`}
                    >
                      {d.prioridade === 'alta'
                        ? 'Alta'
                        : d.prioridade === 'media'
                        ? 'Média'
                        : 'Baixa'}
                    </span>
                    {d.origem && (
                      <span className="text-xs text-gray-400">via {d.origem}</span>
                    )}
                  </div>
                  <h3 className="font-medium text-gray-900">{d.titulo}</h3>
                  <p className="text-sm text-gray-500 mt-1 line-clamp-2">{d.descricao}</p>
                  {d.pessoa && (
                    <p className="text-xs text-blue-600 mt-1">Solicitante: {d.pessoa.nome}</p>
                  )}
                  {d.resposta && (
                    <div className="mt-2 p-2 bg-green-50 rounded-lg border border-green-100">
                      <p className="text-xs text-green-700 font-medium">Resposta:</p>
                      <p className="text-xs text-green-600 mt-0.5 line-clamp-2">{d.resposta}</p>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => openEdit(d)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(d.id)}
                    className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-2xl shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b sticky top-0 bg-white">
              <h2 className="font-semibold text-gray-900">
                {editing ? 'Editar Demanda' : 'Nova Demanda'}
              </h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Título *</label>
                <input
                  required
                  value={form.titulo}
                  onChange={(e) => setForm({ ...form, titulo: e.target.value })}
                  className="input"
                  placeholder="Resumo da demanda"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Descrição *</label>
                <textarea
                  required
                  value={form.descricao}
                  onChange={(e) => setForm({ ...form, descricao: e.target.value })}
                  className="input"
                  rows={3}
                  placeholder="Detalhes da demanda..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
                  <select
                    value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="input"
                  >
                    <option value="aberta">Aberta</option>
                    <option value="em_andamento">Em andamento</option>
                    <option value="resolvida">Resolvida</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Prioridade
                  </label>
                  <select
                    value={form.prioridade}
                    onChange={(e) => setForm({ ...form, prioridade: e.target.value })}
                    className="input"
                  >
                    <option value="alta">Alta</option>
                    <option value="media">Média</option>
                    <option value="baixa">Baixa</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Origem</label>
                  <input
                    value={form.origem}
                    onChange={(e) => setForm({ ...form, origem: e.target.value })}
                    className="input"
                    placeholder="Ex: WhatsApp, email..."
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Solicitante
                  </label>
                  <select
                    value={form.pessoaId}
                    onChange={(e) => setForm({ ...form, pessoaId: e.target.value })}
                    className="input"
                  >
                    <option value="">Anônimo</option>
                    {pessoas.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.nome}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700">Resposta</label>
                  <button
                    type="button"
                    onClick={gerarRespostaIA}
                    disabled={aiLoading || !form.descricao}
                    className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 disabled:opacity-40"
                  >
                    {aiLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Bot className="w-3 h-3" />
                    )}
                    Gerar com IA
                  </button>
                </div>
                <textarea
                  value={form.resposta}
                  onChange={(e) => setForm({ ...form, resposta: e.target.value })}
                  className="input"
                  rows={4}
                  placeholder="Resposta ao cidadão..."
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary flex-1"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {editing ? 'Salvar' : 'Criar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
