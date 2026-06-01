import TelegramBot from 'node-telegram-bot-api'
import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient()
const token = process.env.TELEGRAM_BOT_TOKEN

if (!token) {
  console.error('TELEGRAM_BOT_TOKEN não configurado no .env')
  process.exit(1)
}

const bot = new TelegramBot(token, { polling: true })

console.log('Bot do Telegram iniciado...')

bot.on('message', async (msg) => {
  if (!msg.text) return

  const chatId = String(msg.chat.id)
  const userId = msg.from?.id ? String(msg.from.id) : null
  const username = msg.from?.username ?? null
  const nome = msg.from
    ? [msg.from.first_name, msg.from.last_name].filter(Boolean).join(' ')
    : null

  try {
    await prisma.telegramMensagem.create({
      data: {
        chatId,
        userId,
        username,
        nome,
        mensagem: msg.text,
      },
    })

    await bot.sendMessage(
      chatId,
      `✅ Sua mensagem foi recebida pelo gabinete!\n\nRespondemos em breve. Obrigado pelo contato.`
    )

    console.log(`[${new Date().toISOString()}] Mensagem de ${nome ?? username ?? chatId}: ${msg.text}`)
  } catch (err) {
    console.error('Erro ao salvar mensagem:', err)
    await bot.sendMessage(chatId, 'Ocorreu um erro. Por favor, tente novamente mais tarde.')
  }
})

bot.on('polling_error', (err) => {
  console.error('Polling error:', err)
})
