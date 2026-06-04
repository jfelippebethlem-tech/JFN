' Hermes Gateway - launcher sem janela visivel
' Executa o .cmd com argumento RUN (que entao roda python.exe com console valido) em janela oculta (0)
Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c ""C:\Users\socah\AppData\Local\hermes\gateway-service\Hermes_Gateway.cmd"" RUN", 0, False
