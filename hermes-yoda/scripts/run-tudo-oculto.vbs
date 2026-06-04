' Sobe Yoda (bot) + Painel (Web UI) em SEGUNDO PLANO (janelas ocultas, com auto-retry).
' O Chrome do painel ainda abre visivel. Para parar: use bot-control.ps1 stop / Gerenciador de Tarefas.
Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c ""C:\Users\socah\hermes-webui\run-yoda.cmd""", 0, False
WScript.Sleep 5000
sh.Run "cmd /c ""C:\Users\socah\hermes-webui\run-webui.cmd""", 0, False
