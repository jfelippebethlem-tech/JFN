/**
 * WhatsApp Worker — conexão GRATUITA via Baileys (WhatsApp Web).
 * Execute: npx tsx src/agent/whatsapp-worker.ts  ou  npm run whatsapp
 *
 * Como conectar (uma vez):
 *  1. Inicie o worker.
 *  2. Abra a página /whatsapp no app — um QR Code aparece.
 *  3. No celular: WhatsApp > Aparelhos conectados > Conectar aparelho > escaneie.
 *  4. A sessão fica salva em ./.whatsapp-auth (não commitar).
 *
 * Sem custo de API. Envia as mensagens pendentes da tabela WhatsappFila com
 * intervalo seguro entre mensagens para evitar bloqueio.
 */
import { prisma } from '../lib/db'
import { setConfig } from '../lib/whatsapp'
import qrcode from 'qrcode'
import path from 'path'

const AUTH_DIR = path.resolve(process.cwd(), '.whatsapp-auth')
const INTERVALO_ENVIO = 4000   // 4s entre mensagens (anti-bloqueio)
const INTERVALO_FILA = 15_000  // verifica a fila a cada 15s
const MAX_TENTATIVAS = 3

console.log('📱 WhatsApp Worker iniciando (Baileys — grátis)...')

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let sock: any = null
let conectado = false

async function iniciarBaileys() {
  // Import dinâmico: nunca entra no build do Next.js
  const baileys = await import('@whiskeysockets/baileys')
  const makeWASocket = baileys.default
  const { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = baileys

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()

  sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    // logger silencioso
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    logger: { level: 'silent', child: () => ({ level: 'silent', error() {}, warn() {}, info() {}, debug() {}, trace() {}, fatal() {} }), error() {}, warn() {}, info() {}, debug() {}, trace() {}, fatal() {} } as any,
  })

  sock.ev.on('creds.update', saveCreds)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sock.ev.on('connection.update', async (update: any) => {
    const { connection, lastDisconnect, qr } = update

    if (qr) {
      // Gera QR como data URL para exibir na página /whatsapp
      try {
        const dataUrl = await qrcode.toDataURL(qr)
        await setConfig('whatsapp_qr', dataUrl)
        await setConfig('whatsapp_status', 'aguardando_qr')
        await setConfig('whatsapp_status_em', new Date().toISOString())
        console.log('[WhatsApp] 📷 QR Code gerado — escaneie em /whatsapp')
      } catch (e) {
        console.error('[WhatsApp] erro ao gerar QR:', e)
      }
    }

    if (connection === 'open') {
      conectado = true
      await setConfig('whatsapp_status', 'conectado')
      await setConfig('whatsapp_qr', '')
      await setConfig('whatsapp_status_em', new Date().toISOString())
      console.log('[WhatsApp] ✓ Conectado!')
    }

    if (connection === 'close') {
      conectado = false
      const code = lastDisconnect?.error?.output?.statusCode
      const deveReconectar = code !== DisconnectReason.loggedOut
      await setConfig('whatsapp_status', deveReconectar ? 'reconectando' : 'desconectado')
      await setConfig('whatsapp_status_em', new Date().toISOString())
      console.log(`[WhatsApp] conexão fechada (code ${code}). Reconectar: ${deveReconectar}`)
      if (deveReconectar) {
        setTimeout(() => iniciarBaileys().catch(e => console.error('[WhatsApp] erro reconexão:', e)), 5000)
      } else {
        // Logout: limpa credenciais para permitir novo pareamento
        await setConfig('whatsapp_qr', '')
      }
    }
  })
}

async function enviarMensagem(telefone: string, mensagem: string): Promise<boolean> {
  if (!sock || !conectado) return false
  const jid = `${telefone}@s.whatsapp.net`
  try {
    await sock.sendMessage(jid, { text: mensagem })
    return true
  } catch (e) {
    console.error(`[WhatsApp] erro ao enviar p/ ${telefone}:`, e)
    return false
  }
}

async function drenarFila() {
  if (!conectado) return

  const agora = new Date()
  const pendentes = await prisma.whatsappFila.findMany({
    where: {
      status: 'pendente',
      tentativas: { lt: MAX_TENTATIVAS },
      OR: [{ agendadoPara: null }, { agendadoPara: { lte: agora } }],
    },
    orderBy: { criadoEm: 'asc' },
    take: 20,
  })

  for (const msg of pendentes) {
    const ok = await enviarMensagem(msg.telefone, msg.mensagem)
    if (ok) {
      await prisma.whatsappFila.update({
        where: { id: msg.id },
        data: { status: 'enviado', enviadoEm: new Date() },
      })
      console.log(`[WhatsApp] ✓ enviado p/ ${msg.telefone} (${msg.tipo})`)
    } else {
      const tentativas = msg.tentativas + 1
      await prisma.whatsappFila.update({
        where: { id: msg.id },
        data: {
          tentativas,
          status: tentativas >= MAX_TENTATIVAS ? 'erro' : 'pendente',
          erro: 'falha no envio',
        },
      })
    }
    // intervalo anti-bloqueio entre mensagens
    await new Promise(r => setTimeout(r, INTERVALO_ENVIO))
  }
}

async function main() {
  await setConfig('whatsapp_status', 'iniciando')
  await iniciarBaileys()
  setInterval(() => { drenarFila().catch(e => console.error('[WhatsApp] erro fila:', e)) }, INTERVALO_FILA)
  console.log('[WhatsApp] ✓ Rodando. Verificando fila a cada 15s.\n')
}

main().catch(err => {
  console.error('[WhatsApp] Erro fatal:', err)
  process.exit(1)
})
