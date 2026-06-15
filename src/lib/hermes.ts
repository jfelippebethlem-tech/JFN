import { prisma } from './db'
import { GoogleGenerativeAI } from '@google/generative-ai'

// ─── AI client: OpenRouter (Hermes 3 405B free) com fallback Gemini ────────────

async function callAI(
  messages: { role: 'system' | 'user' | 'assistant'; content: string }[],
  maxTokens = 1024
): Promise<string> {
  // Tenta OpenRouter (Hermes 3 405B gratuito)
  if (process.env.OPENROUTER_API_KEY) {
    const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000',
        'X-Title': 'PolitiMonitor Hermes',
      },
      body: JSON.stringify({
        model: 'nousresearch/hermes-3-llama-3.1-405b:free',
        messages,
        max_tokens: maxTokens,
      }),
    })
    const data = await res.json()
    const text = data?.choices?.[0]?.message?.content
    if (text) return text
  }

  // Fallback: Gemini 2.0 Flash
  if (process.env.GEMINI_API_KEY) {
    const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY)
    const model = genAI.getGenerativeModel({
      model: 'gemini-2.0-flash',
      systemInstruction: messages.find((m) => m.role === 'system')?.content,
      generationConfig: { maxOutputTokens: maxTokens },
    })
    const userMessages = messages.filter((m) => m.role !== 'system')
    const last = userMessages.at(-1)?.content ?? ''
    const history = userMessages.slice(0, -1).map((m) => ({
      role: m.role === 'user' ? 'user' : 'model',
      parts: [{ text: m.content }],
    }))
    const chat = model.startChat({ history })
    const result = await chat.sendMessage(last)
    return result.response.text()
  }

  return 'Configure OPENROUTER_API_KEY ou GEMINI_API_KEY no .env para ativar o Hermes.'
}

// ─── Memória ────────────────────────────────────────────────────────────────────

export async function lembrar(tipo: string, chave: string, conteudo: string, relevancia = 1.0) {
  await prisma.hermesMemoria.upsert({
    where: { tipo_chave: { tipo, chave } },
    update: { conteudo, relevancia, atualizadoEm: new Date() },
    create: { tipo, chave, conteudo, relevancia },
  })
}

export async function buscarMemoria(tipo?: string, limite = 20): Promise<string> {
  const memorias = await prisma.hermesMemoria.findMany({
    where: tipo ? { tipo } : undefined,
    orderBy: [{ relevancia: 'desc' }, { atualizadoEm: 'desc' }],
    take: limite,
  })
  if (!memorias.length) return ''
  return memorias.map((m) => `[${m.tipo}] ${m.chave}: ${m.conteudo}`).join('\n')
}

// ─── System prompt ─────────────────────────────────────────────────────────────

async function buildSystemPrompt(): Promise<string> {
  const [memorias, cfgNome, cfgPartido, cfgEstado] = await Promise.all([
    buscarMemoria(undefined, 30),
    prisma.configuracao.findUnique({ where: { chave: 'deputado_nome' } }),
    prisma.configuracao.findUnique({ where: { chave: 'deputado_partido' } }),
    prisma.configuracao.findUnique({ where: { chave: 'deputado_estado' } }),
  ])
  const nomeDeputado = cfgNome?.valor ?? 'Deputado(a)'
  const partido = cfgPartido?.valor ?? ''
  const estado = cfgEstado?.valor ?? ''
  const identidade = [nomeDeputado, partido && `${partido}/${estado}`].filter(Boolean).join(' — ')

  return `Você é Hermes, agente de inteligência política autônomo do PolitiMonitor.
Você trabalha para ${identidade}, Deputado Estadual, aprendendo continuamente sobre o gabinete e as redes sociais.

IDENTIDADE DO DEPUTADO:
Nome: ${nomeDeputado}
Partido/Estado: ${partido}/${estado}
Mandato: Deputado Estadual — ALERJ (Assembleia Legislativa do Estado do Rio de Janeiro)

SUAS RESPONSABILIDADES:
- Analisar demandas de cidadãos e sugerir respostas e prioridades
- Identificar padrões em posts de redes sociais e tendências de sentimento
- Monitorar mensagens do Telegram e recomendar respostas
- Gerar insights estratégicos e alertas proativos
- Aprender com cada interação para melhorar suas análises

MEMÓRIA ACUMULADA:
${memorias || '(sem memórias ainda — começando a aprender)'}

Responda sempre em português. Seja direto, analítico e politicamente perspicaz.
Ao final de análises, indique o que aprendeu e o que deve ser memorizado.`
}

// ─── Criação de insights ────────────────────────────────────────────────────────

export async function criarInsight(
  titulo: string,
  descricao: string,
  tipo: string,
  prioridade: 'alta' | 'media' | 'baixa' = 'media'
) {
  return prisma.hermesInsight.create({ data: { titulo, descricao, tipo, prioridade } })
}

// ─── Jobs ───────────────────────────────────────────────────────────────────────

export async function enqueueJob(tipo: string, payload: object) {
  return prisma.hermesJob.create({
    data: { tipo, payload: JSON.stringify(payload) },
  })
}

export async function processarJob(job: { id: string; tipo: string; payload: string }) {
  await prisma.hermesJob.update({
    where: { id: job.id },
    data: { status: 'processando' },
  })

  try {
    const payload = JSON.parse(job.payload)
    let resultado = ''

    const system = await buildSystemPrompt()

    if (job.tipo === 'analise_demanda') {
      resultado = await analisarDemanda(system, payload)
    } else if (job.tipo === 'analise_post') {
      resultado = await analisarPost(system, payload)
    } else if (job.tipo === 'analise_telegram') {
      resultado = await analisarTelegram(system, payload)
    } else if (job.tipo === 'resumo_diario') {
      resultado = await gerarResumoDiario(system)
    } else if (job.tipo === 'chat') {
      resultado = await chatHermes(system, payload.mensagem, payload.historico)
    }

    await prisma.hermesJob.update({
      where: { id: job.id },
      data: { status: 'concluido', resultado, processadoEm: new Date() },
    })

    return resultado
  } catch (err) {
    const erro = err instanceof Error ? err.message : String(err)
    await prisma.hermesJob.update({
      where: { id: job.id },
      data: { status: 'erro', erro, processadoEm: new Date() },
    })
    throw err
  }
}

// ─── Análises específicas ────────────────────────────────────────────────────────

async function analisarDemanda(
  system: string,
  payload: { id: string; titulo: string; descricao: string; origem?: string }
) {
  const resposta = await callAI(
    [
      { role: 'system', content: system },
      {
        role: 'user',
        content: `Analise esta demanda do gabinete:

TÍTULO: ${payload.titulo}
DESCRIÇÃO: ${payload.descricao}
ORIGEM: ${payload.origem || 'não informada'}

Forneça:
1. CLASSIFICAÇÃO: tema principal (saúde/educação/infraestrutura/segurança/outro)
2. URGÊNCIA: alta/média/baixa + justificativa
3. RESPOSTA SUGERIDA: rascunho de resposta profissional
4. APRENDIZADO: o que memorizar sobre este tipo de demanda`,
      },
    ],
    1200
  )

  // Atualiza memória com padrão aprendido
  const tema = extrairTema(resposta)
  if (tema) {
    const memoriaAtual = await prisma.hermesMemoria.findUnique({
      where: { tipo_chave: { tipo: 'estatistica', chave: `demanda_tema_${tema}` } },
    })
    const count = memoriaAtual ? parseInt(memoriaAtual.conteudo) + 1 : 1
    await lembrar('estatistica', `demanda_tema_${tema}`, String(count))
  }

  await criarInsight(
    `Nova demanda analisada: ${payload.titulo}`,
    resposta.slice(0, 400),
    'sugestao',
    extrairUrgencia(resposta)
  )

  return resposta
}

async function analisarPost(
  system: string,
  payload: { conteudo: string; plataforma: string; palavra?: string }
) {
  const resposta = await callAI(
    [
      { role: 'system', content: system },
      {
        role: 'user',
        content: `Analise este post monitorado:

PLATAFORMA: ${payload.plataforma}
PALAVRA-CHAVE: ${payload.palavra || 'n/a'}
CONTEÚDO: ${payload.conteudo}

Forneça:
1. SENTIMENTO: positivo/negativo/neutro
2. RELEVÂNCIA: alta/média/baixa para o gabinete
3. AÇÃO RECOMENDADA: o que o gabinete deve fazer
4. APRENDIZADO: padrão identificado`,
      },
    ],
    600
  )

  const sentimento = resposta.toLowerCase().includes('negativo')
    ? 'negativo'
    : resposta.toLowerCase().includes('positivo')
    ? 'positivo'
    : 'neutro'

  if (sentimento === 'negativo') {
    await criarInsight(
      `Post negativo detectado em ${payload.plataforma}`,
      `"${payload.conteudo.slice(0, 150)}..." — ${resposta.slice(0, 200)}`,
      'alerta',
      'alta'
    )
  }

  await lembrar('padrao', `sentimento_${payload.plataforma}_recente`, sentimento)
  return resposta
}

async function analisarTelegram(
  system: string,
  payload: { id: string; nome?: string; mensagem: string }
) {
  const resposta = await callAI(
    [
      { role: 'system', content: system },
      {
        role: 'user',
        content: `Analise esta mensagem recebida no Telegram do gabinete:

DE: ${payload.nome || 'Cidadão'}
MENSAGEM: ${payload.mensagem}

Forneça:
1. INTENÇÃO: o que o cidadão quer
2. URGÊNCIA: alta/média/baixa
3. RESPOSTA SUGERIDA: resposta pronta para enviar
4. PERFIL: características deste tipo de solicitante`,
      },
    ],
    800
  )

  await lembrar('padrao', 'telegram_ultimo_tema', payload.mensagem.slice(0, 100))
  return resposta
}

async function gerarResumoDiario(system: string) {
  const [totalDemandas, demandasAbertas, totalPosts, semResposta] = await Promise.all([
    prisma.demanda.count(),
    prisma.demanda.count({ where: { status: 'aberta' } }),
    prisma.post.count(),
    prisma.telegramMensagem.count({ where: { respondida: false } }),
  ])

  const memorias = await buscarMemoria('estatistica', 10)

  const resumo = await callAI(
    [
      { role: 'system', content: system },
      {
        role: 'user',
        content: `Gere um resumo diário executivo do gabinete:

DADOS ATUAIS:
- Total de demandas: ${totalDemandas} (${demandasAbertas} abertas)
- Posts monitorados: ${totalPosts}
- Mensagens Telegram sem resposta: ${semResposta}

ESTATÍSTICAS APRENDIDAS:
${memorias || 'em coleta'}

Forneça:
1. RESUMO EXECUTIVO (3-4 linhas)
2. PRIORIDADES DO DIA (top 3)
3. ALERTAS (se houver)
4. RECOMENDAÇÃO ESTRATÉGICA`,
      },
    ],
    800
  )

  await criarInsight('Resumo Diário do Gabinete', resumo.slice(0, 600), 'resumo', 'media')
  await lembrar('contexto', 'ultimo_resumo_diario', new Date().toLocaleDateString('pt-BR'))
  return resumo
}

export async function chatHermes(
  system: string,
  mensagem: string,
  historico: { role: string; content: string }[] = []
) {
  const messages: { role: 'system' | 'user' | 'assistant'; content: string }[] = [
    { role: 'system', content: system },
    ...historico.map((h) => ({
      role: h.role as 'user' | 'assistant',
      content: h.content,
    })),
    { role: 'user', content: mensagem },
  ]
  return callAI(messages, 1024)
}

// ─── Chat direto (com sistema já construído) ────────────────────────────────────

export async function chatComHermes(
  mensagem: string,
  historico: { role: string; content: string }[] = []
) {
  const system = await buildSystemPrompt()
  return chatHermes(system, mensagem, historico)
}

// ─── Ciclo autônomo: Hermes capta o estado e age via catálogo de ações ──────────
//
// Pensado para um modelo FRACO: damos o estado resumido + uma lista curta e clara
// de ações seguras, e pedimos UMA decisão em JSON estrito. Ações sensíveis viram
// recomendação (não executam sozinhas — ver trava em executarAcao).

export async function cicloAutonomo(): Promise<string> {
  // import dinâmico evita qualquer ciclo de dependência
  const { listarAcoes, executarAcao } = await import('./acoes')
  const { captarEstadoCompleto } = await import('./estado')

  const estado = await captarEstadoCompleto()
  const acoesAuto = listarAcoes().filter(a => a.seguranca === 'auto')

  const listaAcoes = acoesAuto
    .map(a => `- ${a.nome}: ${a.descricao}${Object.keys(a.parametros).length ? ` | params: ${Object.keys(a.parametros).join(', ')}` : ''}`)
    .join('\n')

  const system = await buildSystemPrompt()
  const resposta = await callAI(
    [
      { role: 'system', content: system },
      {
        role: 'user',
        content: `Você é um agente autônomo. Olhe o ESTADO ATUAL e escolha UMA ação útil agora.

ESTADO ATUAL (resumo):
${JSON.stringify(estado, null, 2).slice(0, 3500)}

AÇÕES DISPONÍVEIS (apenas estas, todas seguras):
${listaAcoes}

REGRAS:
- Responda APENAS com um JSON válido, nada antes ou depois.
- Formato: {"acao": "nome_da_acao", "params": {}, "motivo": "por que agora"}
- Se nada for necessário neste momento, use {"acao": "nenhuma", "params": {}, "motivo": "..."}
- Escolha algo que gere valor: se há alertas, investigue; se há cobranças pendentes, calcule; se faltam análises, analise.`,
      },
    ],
    400
  )

  // Extrai JSON de forma defensiva (modelo fraco pode adicionar texto)
  let decisao: { acao?: string; params?: object; motivo?: string } = {}
  try {
    const match = resposta.match(/\{[\s\S]*\}/)
    if (match) decisao = JSON.parse(match[0])
  } catch {
    await lembrar('contexto', 'hermes_ultimo_ciclo', `JSON inválido: ${resposta.slice(0, 100)}`)
    return `Decisão inválida: ${resposta.slice(0, 120)}`
  }

  if (!decisao.acao || decisao.acao === 'nenhuma') {
    await lembrar('contexto', 'hermes_ultimo_ciclo', `Sem ação. Motivo: ${decisao.motivo ?? '—'}`)
    return `Nenhuma ação tomada. ${decisao.motivo ?? ''}`
  }

  const r = await executarAcao(decisao.acao, decisao.params ?? {}, 'hermes')
  await lembrar('contexto', 'hermes_ultimo_ciclo', `Ação: ${decisao.acao} | ${r.ok ? 'ok' : 'falhou'} | ${decisao.motivo ?? ''}`)
  return `Ação "${decisao.acao}": ${r.ok ? 'executada' : (r.requerAprovacao ? 'recomendada (precisa aprovação)' : 'erro')}. Motivo: ${decisao.motivo ?? ''}`
}

// ─── Utilitários ────────────────────────────────────────────────────────────────

function extrairTema(texto: string): string {
  const temas = ['saude', 'educacao', 'infraestrutura', 'seguranca', 'habitacao', 'social']
  const lower = texto.toLowerCase()
  return temas.find((t) => lower.includes(t)) ?? 'outros'
}

function extrairUrgencia(texto: string): 'alta' | 'media' | 'baixa' {
  const lower = texto.toLowerCase()
  if (lower.includes('alta') || lower.includes('urgente')) return 'alta'
  if (lower.includes('baixa')) return 'baixa'
  return 'media'
}
