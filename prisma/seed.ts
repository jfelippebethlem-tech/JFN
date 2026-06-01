import { PrismaClient } from '@prisma/client'

const prisma = new PrismaClient()

async function main() {
  await prisma.configuracao.upsert({
    where: { chave: 'deputado_nome' },
    update: {},
    create: { chave: 'deputado_nome', valor: 'Deputado(a)' },
  })

  const palavras = ['deputado', 'gabinete', 'vereador', 'assembleia']
  for (const palavra of palavras) {
    await prisma.palavraChave.upsert({
      where: { palavra },
      update: {},
      create: { palavra },
    })
  }

  console.log('Seed concluído!')
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect())
