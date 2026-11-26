# JFN - supervisor do motor de fluxo no it-campo (jfn-fluxo@itcampo), SUBIDO NO BOOT, sem logon (O1.10).
# Tarefa: JFN-Fluxo-Boot (gatilho: inicializacao; "executar estando o usuario conectado ou nao"; conta do usuario).
# Criada DESABILITADA na parada de obras (24/11/2026); habilita na O9.0:  schtasks /change /tn JFN-Fluxo-Boot /enable
# A captura SEI visivel (JFN-SEI-Paralelo) continua no LOGON - esta tarefa nao abre janela.
# Passos: (1) sobe o WSL e confere/monta o D: (montar_d.sh, como root do WSL, sem sudo);
#         (2) roda o supervisor em ~/JFN-worker e o religa se sair (o wsl.exe vivo segura a VM do WSL acordada).
# Ambiente (O9.0): deploy/fluxo/producao.env da arvore do worker; JFN_ASSINATURA_ESCOPO sempre fora (so do ensaio).
# DSN do PG: o supervisor ACHA pelo resolvedor (compliance_agent.credenciais, VM-1 por ssh); nada copiado para ca.
# Instalar/atualizar: tools/religar_o90.py passo R2 copia este arquivo da arvore para C:\JFN-Fluxo\ (md5 conferido).
# Log: C:\JFN-Fluxo\boot.log    Pausar sem desabilitar: criar C:\JFN-Fluxo\PAUSA
$ErrorActionPreference = 'Continue'
$Base = 'C:\JFN-Fluxo'
$Log  = Join-Path $Base 'boot.log'
function Diga($m) { Add-Content -Path $Log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) }
Diga "boot: subindo o WSL (Ubuntu)"
& wsl.exe -d Ubuntu -u root -e bash /mnt/c/JFN-Fluxo/montar_d.sh 2>&1 | ForEach-Object { Diga "montar_d: $_" }
Diga "montar_d saiu com $LASTEXITCODE (0 = D: montado e conferido; 3 = D: ausente, segue sem o HD)"
while ($true) {
  if (Test-Path (Join-Path $Base 'PAUSA')) { Diga "PAUSA presente - espero 60 s"; Start-Sleep -Seconds 60; continue }
  Diga "supervisor: subindo (no itcampo, ~/JFN-worker)"
  # 26/11/2026: o vLLM do Surya (GPU) sobe NESTA mesma chamada do wsl.exe, antes do supervisor: processo lancado por
  # uma chamada curta do wsl.exe morre quando ela termina (SIGTERM medido as 15h27). O E5 (ExecutorGPU) e so o
  # CLIENTE dele; sem o servidor a GPU fica parada e o OCR cai na CPU. vllm_surya.sh nao religa se a 8790 responde.
  & wsl.exe -d Ubuntu --cd /home/iterj/JFN-worker -e bash -lc 'bash deploy/itcampo/ocr_gpu/vllm_surya.sh | grep -E "PRONTO|checkpoint"; set -a; . deploy/fluxo/producao.env || exit 3; set +a; unset JFN_ASSINATURA_ESCOPO; PYTHONPATH=. exec .venv/bin/python -m compliance_agent.fluxo supervisor --no itcampo' 2>&1 | ForEach-Object { Diga "sup: $_" }
  Diga "supervisor saiu (codigo $LASTEXITCODE) - religo em 30 s"
  Start-Sleep -Seconds 30
}
