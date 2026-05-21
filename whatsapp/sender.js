/**
 * JFN WhatsApp Sender
 * Usage: node sender.js <phone> <message>
 *   phone — international format without +, e.g. 5511999999999
 *
 * First run: a QR code appears in the terminal. Scan it with WhatsApp
 * on your phone once. The session is saved in .wwebjs_auth/ so subsequent
 * runs authenticate automatically without a new QR scan.
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const path = require("path");

const phone = process.argv[2];
const message = process.argv[3];

if (!phone || !message) {
  console.error("Usage: node sender.js <phone> <message>");
  process.exit(1);
}

const AUTH_DIR = path.join(__dirname, ".wwebjs_auth");

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
    ],
  },
});

client.on("qr", (qr) => {
  console.log("\n📱 Escaneie o QR Code abaixo com o WhatsApp do seu celular:\n");
  qrcode.generate(qr, { small: true });
  console.log("\n(Aguardando autenticação...)\n");
});

client.on("authenticated", () => {
  console.log("[whatsapp] Autenticado com sucesso.");
});

client.on("ready", async () => {
  try {
    const chatId = `${phone}@c.us`;
    await client.sendMessage(chatId, message);
    console.log(`[whatsapp] ✓ Mensagem enviada para ${phone}`);
    await client.destroy();
    process.exit(0);
  } catch (err) {
    console.error("[whatsapp] ✗ Erro ao enviar mensagem:", err.message);
    await client.destroy();
    process.exit(1);
  }
});

client.on("auth_failure", (msg) => {
  console.error("[whatsapp] ✗ Falha na autenticação:", msg);
  process.exit(1);
});

client.on("disconnected", (reason) => {
  console.error("[whatsapp] Desconectado:", reason);
  process.exit(1);
});

client.initialize();
