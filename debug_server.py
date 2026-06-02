from pathlib import Path

path = Path(r"C:/JFN/jfn/server.py")
text = path.read_text(encoding="utf-8", errors="ignore")
lines = text.splitlines()

for i in range(100, 120):
    prefix = f"{i+1:4}|"
    print(f"{prefix}{lines[i] if i < len(lines) else '<EOF>'}")
