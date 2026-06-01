import { prisma } from '@/lib/db'
import {
  Users,
  FileText,
  Radio,
  Send,
  TrendingUp,
  AlertCircle,
  CheckCircle,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { ptBR } from 'date-fns/locale'

async function getDashboardData() {
  const [
    totalPessoas,
    totalFuncionarios,
    totalApoiadores,
    demandasAbertas,
    demandasAlta,
    demandasResolvidas,
    totalAtividades,
    recentePosts,
    recentedemandas,
    recenteTelegram,
  ] = await Promise.all([
    prisma.pessoa.count({ where: { ativo: true } }),
    prisma.pessoa.count({ where: { tipo: 'funcionario', ativo: true } }),
    prisma.pessoa.count({ where: { tipo: 'apoiador', ativo: true } }),
    prisma.demanda.count({ where: { status: 'aberta' } }),
    prisma.demanda.count({ where: { status: 'aberta', prioridade: 'alta' } }),
    prisma.demanda.count({ where: { status: 'resolvida' } }),
    prisma.atividade.count(),
    prisma.post.findMany({ take: 5, orderBy: { criadoEm: 'desc' } }),
    prisma.demanda.findMany({
      take: 5,
      orderBy: { criadoEm: 'desc' },
      include: { pessoa: true },
    }),
    prisma.telegramMensagem.findMany({
      take: 5,
      orderBy: { criadoEm: 'desc' },
    }),
  ])

  return {
    totalPessoas,
    totalFuncionarios,
    totalApoiadores,
    demandasAbertas,
    demandasAlta,
    demandasResolvidas,
    totalAtividades,
    recentePosts,
    recentedemandas,
    recenteTelegram,
  }
}

export default async function DashboardPage() {
  const data = await getDashboardData()

  const stats = [
    {
      label: 'Total de Pessoas',
      value: data.totalPessoas,
      sub: `${data.totalFuncionarios} func. | ${data.totalApoiadores} apoia.`,
      icon: Users,
      color: 'bg-blue-500',
    },
    {
      label: 'Demandas Abertas',
      value: data.demandasAbertas,
      sub: `${data.demandasAlta} de alta prioridade`,
      icon: AlertCircle,
      color: 'bg-red-500',
    },
    {
      label: 'Demandas Resolvidas',
      value: data.demandasResolvidas,
      sub: 'total histórico',
      icon: CheckCircle,
      color: 'bg-green-500',
    },
    {
      label: 'Atividades Registradas',
      value: data.totalAtividades,
      sub: 'votos, projetos, reuniões',
      icon: TrendingUp,
      color: 'bg-purple-500',
    },
  ]

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">Visão geral do gabinete</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {stats.map((stat) => (
          <div key={stat.label} className="card">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm text-gray-500">{stat.label}</p>
                <p className="text-3xl font-bold text-gray-900 mt-1">{stat.value}</p>
                <p className="text-xs text-gray-400 mt-1">{stat.sub}</p>
              </div>
              <div className={`${stat.color} p-3 rounded-lg`}>
                <stat.icon className="w-5 h-5 text-white" />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card lg:col-span-2">
          <div className="flex items-center gap-2 mb-4">
            <FileText className="w-5 h-5 text-gray-400" />
            <h2 className="font-semibold text-gray-900">Demandas Recentes</h2>
          </div>
          {data.recentedemandas.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-6">Nenhuma demanda ainda</p>
          ) : (
            <div className="space-y-3">
              {data.recentedemandas.map((d) => (
                <div key={d.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                  <div
                    className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                      d.prioridade === 'alta'
                        ? 'bg-red-500'
                        : d.prioridade === 'media'
                        ? 'bg-yellow-500'
                        : 'bg-blue-500'
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{d.titulo}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {d.pessoa?.nome ?? 'Anônimo'} ·{' '}
                      {formatDistanceToNow(new Date(d.criadoEm), {
                        addSuffix: true,
                        locale: ptBR,
                      })}
                    </p>
                  </div>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      d.status === 'aberta'
                        ? 'bg-red-100 text-red-700'
                        : d.status === 'em_andamento'
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-green-100 text-green-700'
                    }`}
                  >
                    {d.status === 'aberta'
                      ? 'Aberta'
                      : d.status === 'em_andamento'
                      ? 'Em andamento'
                      : 'Resolvida'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Send className="w-5 h-5 text-gray-400" />
            <h2 className="font-semibold text-gray-900">Telegram Recente</h2>
          </div>
          {data.recenteTelegram.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-6">Nenhuma mensagem ainda</p>
          ) : (
            <div className="space-y-3">
              {data.recenteTelegram.map((msg) => (
                <div key={msg.id} className="p-3 bg-gray-50 rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-gray-700">
                      {msg.nome ?? msg.username ?? msg.chatId}
                    </span>
                    {!msg.respondida && (
                      <span className="w-2 h-2 rounded-full bg-blue-500" />
                    )}
                  </div>
                  <p className="text-xs text-gray-500 truncate">{msg.mensagem}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {data.recentePosts.length > 0 && (
        <div className="card mt-6">
          <div className="flex items-center gap-2 mb-4">
            <Radio className="w-5 h-5 text-gray-400" />
            <h2 className="font-semibold text-gray-900">Monitoramento Recente</h2>
          </div>
          <div className="space-y-2">
            {data.recentePosts.map((post) => (
              <div
                key={post.id}
                className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg"
              >
                <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium capitalize">
                  {post.plataforma}
                </span>
                <p className="text-sm text-gray-700 flex-1 line-clamp-2">{post.conteudo}</p>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    post.sentimento === 'positivo'
                      ? 'bg-green-100 text-green-700'
                      : post.sentimento === 'negativo'
                      ? 'bg-red-100 text-red-700'
                      : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {post.sentimento ?? 'neutro'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
