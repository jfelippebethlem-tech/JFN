"""Configuration for the JFN Brazilian stock market agent."""

# B3 stock universe — IBOVESPA
IBOVESPA_TICKERS = [
    "VALE3", "PETR4", "ITUB4", "BBDC4", "ABEV3", "WEGE3", "RDOR3",
    "RENT3", "GGBR4", "PRIO3", "BPAC11", "HAPV3", "SBSP3",
    "ENEV3", "CPFE3", "EGIE3", "TAEE11", "CMIG4", "VIVT3", "TIMS3",
    "FLRY3", "QUAL3", "ENBR3", "CPLE6", "TRPL4", "SAPR11",
    "BBSE3", "CSAN3", "MDIA3", "BRFS3", "JBSS3", "CCRO3",
    "TOTS3", "SUZB3", "KLBN11", "DXCO3", "CMIN3", "CSNA3",
    "UGPA3", "HYPE3", "RADL3", "PCAR3", "ASAI3", "CRFB3",
    "NTCO3", "SOMA3", "ARZZ3", "GRND3",
]

# B3 stock universe — SMLL (small caps, perennial focus)
SMLL_TICKERS = [
    "ODPV3", "POSI3", "TUPY3", "KEPL3", "ROMI3", "LEVE3",
    "FRAS3", "MYPK3", "LPSB3", "JHSF3", "BRSR6", "BPAN4",
    "IRBR3", "SLCE3", "SOJA3", "BEEF3", "TASA4", "TGMA3",
    "VULC3", "LOGG3", "STBP3", "BLAU3", "CBAV3", "CEAB3",
    "EUCA4", "HBSA3", "LAVV3", "MBRE3", "NGRD3", "ONCO3",
    "ORVR3", "PETZ3", "SEQL3", "SMFT3", "SYNE3", "UCAS3",
    "VAMO3", "VIVA3", "VLID3", "YDUQ3", "CLSA3", "CSED3",
]

# Analysis thresholds
SIGNAL_THRESHOLD = 65           # Minimum score (0–100) to send alert
STRONG_SIGNAL_THRESHOLD = 80    # High conviction threshold
COOLDOWN_HOURS = 24             # Hours before re-alerting same ticker
MAX_SIGNALS_PER_SCAN = 5        # Cap alerts per scan run

# Technical indicator thresholds
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
VOLUME_SPIKE_MULTIPLIER = 1.5   # Volume > 1.5x average = spike

# Market hours (Brasilia time, BRT = UTC-3)
MARKET_OPEN_HOUR = 10           # 10:00 BRT
MARKET_CLOSE_HOUR = 17          # 17:00 BRT (pre-close scan)
CHECK_INTERVAL_MINUTES = 30     # How often to scan during market hours

# brapi.dev API (free tier — set BRAPI_TOKEN in .env for higher limits)
BRAPI_BASE_URL = "https://brapi.dev/api"
