import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

function makePrisma() {
  const client = new PrismaClient({
    log: process.env.NODE_ENV === 'development' ? ['error', 'warn'] : ['error'],
  })
  // WAL mode: required for PM2 cluster (multiple workers, single SQLite file)
  client.$executeRawUnsafe('PRAGMA journal_mode = WAL').catch(() => {})
  client.$executeRawUnsafe('PRAGMA synchronous = NORMAL').catch(() => {})
  client.$executeRawUnsafe('PRAGMA busy_timeout = 5000').catch(() => {})
  return client
}

export const prisma = globalForPrisma.prisma ?? makePrisma()

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
