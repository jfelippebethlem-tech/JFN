'use client'

import { useEffect, useState } from 'react'
import { Users, Plus, Search, Edit2, Trash2, Loader2, X } from 'lucide-react'

type Pessoa = {
  id: string
  nome: string
  tipo: string
  cargo: string | null
  email: string | null
  telefone: string | null
  twitter: string | null
  instagram: string | null
  telegramUser: string | null
  ativo: boolean
  observacoes: string | null
}

const tipoLabel: Record<string, string> = {
  funcionario: 'Funcionário',
  apoiador: 'Apoiador',
  contato: 'Contato',
}

const tipoColor: Record<string, string> = {
  funcionario: 'bg-blue-100 text-blue-700',
  apoiador: 'bg-green-100 text-green-700',
  contato: 'bg-gray-100 text-gray-700',
}

const emptyForm = {
  nome: '',
  tipo: 'funcionario',
  cargo: '',
  email: '',
  telefone: '',
  twitter: '',
  instagram: '',
  telegramUser: '',
  observacoes: '',
}

export default function PessoasPage() {
  const [pessoas, setPessoas] = useState<Pessoa[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [tipoFilter, setTipoFilter] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Pessoa | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)

  async function load() {
    setLoading(true)
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (tipoFilter) params.set('tipo', tipoFilter)
    const res = await fetch(`/api/pessoas?${params}`)
    const data = await res.json()
    setPessoas(data)
    setLoading(false)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tipoFilter])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm)
    setShowModal(true)
  }

  function openEdit(p: Pessoa) {
    setEditing(p)
    setForm({
      nome: p.nome,
      tipo: p.tipo,
      cargo: p.cargo ?? '',
      email: p.email ?? '',
      telefone: p.telefone ?? '',
      twitter: p.twitter ?? '',
      instagram: p.instagram ?? '',
      telegramUser: p.telegramUser ?? '',
      observacoes: p.observacoes ?? '',
    })
    setShowModal(true)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    const method = editing ? 'PUT' : 'POST'
    const url = editing ? `/api/pessoas/${editing.id}` : '/api/pessoas'
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
    if (!confirm('Deseja remover esta pessoa?')) return
    await fetch(`/api/pessoas/${id}`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pessoas</h1>
          <p className="text-gray-500 text-sm mt-1">Funcionários, apoiadores e contatos</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> Nova Pessoa
        </button>
      </div>

      <div className="flex gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar por nome..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-9"
          />
        </div>
        <select
          value={tipoFilter}
          onChange={(e) => setTipoFilter(e.target.value)}
          className="input w-40"
        >
          <option value="">Todos os tipos</option>
          <option value="funcionario">Funcionários</option>
          <option value="apoiador">Apoiadores</option>
          <option value="contato">Contatos</option>
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : pessoas.length === 0 ? (
        <div className="card text-center py-12">
          <Users className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhuma pessoa encontrada</p>
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-6 py-3 font-medium text-gray-500">Nome</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Tipo</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Cargo</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Contato</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Redes</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {pessoas.map((p) => (
                <tr key={p.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="font-medium text-gray-900">{p.nome}</div>
                    {p.observacoes && (
                      <div className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">
                        {p.observacoes}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${tipoColor[p.tipo] ?? 'bg-gray-100 text-gray-700'}`}>
                      {tipoLabel[p.tipo] ?? p.tipo}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-600">{p.cargo ?? '—'}</td>
                  <td className="px-6 py-4 text-gray-600">
                    <div>{p.email ?? ''}</div>
                    <div className="text-xs text-gray-400">{p.telefone ?? ''}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-2 text-xs text-gray-500">
                      {p.twitter && <span>@{p.twitter}</span>}
                      {p.instagram && <span>📷{p.instagram}</span>}
                      {p.telegramUser && <span>✈️{p.telegramUser}</span>}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => openEdit(p)}
                        className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(p.id)}
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="font-semibold text-gray-900">
                {editing ? 'Editar Pessoa' : 'Nova Pessoa'}
              </h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Nome *</label>
                  <input
                    required
                    value={form.nome}
                    onChange={(e) => setForm({ ...form, nome: e.target.value })}
                    className="input"
                    placeholder="Nome completo"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tipo *</label>
                  <select
                    value={form.tipo}
                    onChange={(e) => setForm({ ...form, tipo: e.target.value })}
                    className="input"
                  >
                    <option value="funcionario">Funcionário</option>
                    <option value="apoiador">Apoiador</option>
                    <option value="contato">Contato</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Cargo</label>
                  <input
                    value={form.cargo}
                    onChange={(e) => setForm({ ...form, cargo: e.target.value })}
                    className="input"
                    placeholder="Ex: Assessor"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    className="input"
                    placeholder="email@exemplo.com"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Telefone</label>
                  <input
                    value={form.telefone}
                    onChange={(e) => setForm({ ...form, telefone: e.target.value })}
                    className="input"
                    placeholder="(11) 99999-9999"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Twitter/X</label>
                  <input
                    value={form.twitter}
                    onChange={(e) => setForm({ ...form, twitter: e.target.value })}
                    className="input"
                    placeholder="usuario (sem @)"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Instagram</label>
                  <input
                    value={form.instagram}
                    onChange={(e) => setForm({ ...form, instagram: e.target.value })}
                    className="input"
                    placeholder="usuario (sem @)"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Telegram Username
                  </label>
                  <input
                    value={form.telegramUser}
                    onChange={(e) => setForm({ ...form, telegramUser: e.target.value })}
                    className="input"
                    placeholder="usuario (sem @)"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Observações
                  </label>
                  <textarea
                    value={form.observacoes}
                    onChange={(e) => setForm({ ...form, observacoes: e.target.value })}
                    className="input"
                    rows={2}
                    placeholder="Anotações internas..."
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary flex-1"
                >
                  Cancelar
                </button>
                <button type="submit" className="btn-primary flex-1 flex items-center justify-center gap-2">
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
