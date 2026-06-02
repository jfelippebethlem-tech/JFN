import { GoogleGenerativeAI } from '@google/generative-ai'

let client: GoogleGenerativeAI | null = null

function getClient() {
  if (!process.env.GEMINI_API_KEY) return null
  if (!client) {
    client = new GoogleGenerativeAI(process.env.GEMINI_API_KEY)
  }
  return client
}

const MODEL = 'gemini-2.0-flash'

async function chat(prompt: string, maxTokens = 1024): Promise<string> {
  const genAI = getClient()
  if (!genAI) return ''

  const model = genAI.getGenerativeModel({
    model: MODEL,
    generationConfig: { maxOutputTokens: maxTokens },
  })

  const result = await model.generateContent(prompt)
  return result.response.text() ?? ''
}

export async function gerarResposta(demanda: string, contexto?: string): Promise<string> {
  if (!getClient()) {
    return 'Configure GEMINI_API_KEY no .env para usar o assistente de IA (gratuito em aistudio.google.com).'
  }

  const prompt = `Você é um assistente de um deputado estadual brasileiro.
Ajude a redigir uma resposta profissional, empática e eficiente para a seguinte demanda de cidadão:

DEMANDA: ${demanda}
${contexto ? `\nCONTEXTO ADICIONAL: ${contexto}` : ''}

Responda de forma profissional, em português, com tom respeitoso e solucionador.`

  const result = await chat(prompt, 1024)
  return result || 'Erro ao gerar resposta.'
}

export async function analisarSentimento(texto: string): Promise<string> {
  if (!getClient()) return 'neutro'

  const prompt = `Classifique o sentimento deste texto como exatamente uma palavra: "positivo", "negativo" ou "neutro".
Texto: "${texto}"
Resposta (apenas uma palavra):`

  const result = await chat(prompt, 5)
  const s = result.toLowerCase().trim()
  if (s.includes('positivo')) return 'positivo'
  if (s.includes('negativo')) return 'negativo'
  return 'neutro'
}

export async function gerarPostRedeSocial(
  tema: string,
  plataforma: string,
  tom: string
): Promise<string> {
  if (!getClient()) {
    return 'Configure GEMINI_API_KEY no .env para usar o assistente de IA (gratuito em aistudio.google.com).'
  }

  const limits: Record<string, number> = {
    twitter: 280,
    instagram: 2200,
    facebook: 63206,
  }
  const limit = limits[plataforma.toLowerCase()] || 500

  const prompt = `Crie um post para ${plataforma} sobre: ${tema}
Tom: ${tom}
Limite de caracteres: ${limit}
Escreva apenas o texto do post, sem explicações adicionais.`

  const result = await chat(prompt, 512)
  return result || 'Erro ao gerar post.'
}
