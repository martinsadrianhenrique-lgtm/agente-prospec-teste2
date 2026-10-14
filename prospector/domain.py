from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlencode, quote
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
STAGES = ["Novo", "Contatado", "Em conversa", "Interessado", "Reunião marcada", "Proposta enviada", "Ganho", "Perdido", "Encerrado sem resposta"]
STOP_STAGES = {"Reunião marcada", "Proposta enviada", "Ganho", "Perdido", "Encerrado sem resposta"}
CITIES = ["Apucarana", "Arapongas", "Maringá", "Londrina", "Califórnia", "Mandaguari", "Cambira", "Jandaia do Sul"]
NICHES = ["Oficina mecânica", "Autopeças", "Pet shop", "Dentista", "Estética/Harmonização"]
CRITERIA = {
    "conversao": ("Contato e agendamento", {0: "Sem lacuna observada", 15: "Site oficial confirmado sem vínculo no perfil", 30: "Link de contato/agendamento com falha reproduzível"}),
    "cadastro": ("Informações essenciais", {0: "Sem lacuna observada", 10: "Campo essencial aplicável não preenchido", 25: "Divergência material confirmada pela empresa"}),
    "avaliacoes": ("Avaliações no contexto local", {0: "Na mediana ou acima dos concorrentes comparáveis", 10: "Abaixo da mediana", 20: "Abaixo de metade da mediana"}),
    "respostas": ("Respostas às avaliações", {0: "Sem lacuna observada", 5: "Algumas avaliações sem resposta", 15: "Três ou mais sem resposta e pelo menos metade da amostra"}),
    "visual": ("Apresentação visual", {0: "Categorias visuais representadas", 5: "Uma categoria visual aplicável ausente", 10: "Duas categorias visuais aplicáveis ausentes"}),
}
SOURCE_TYPES = ["Google Maps", "Site oficial", "Rede social oficial", "Conversa com a empresa", "Diretório", "Outro"]
OBS_STATES = ["A validar", "Verificado", "Inferido", "Não encontrado no escopo", "Inacessível", "Conflitante"]


class DomainError(ValueError):
    pass


class ConflictError(DomainError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None = None) -> str:
    return (value or now_utc()).astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def local_time(value: str | None) -> str:
    return parse_time(value).astimezone(TZ).strftime("%d/%m/%Y %H:%M") if value else "—"


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def clean_text(value: object, limit: int = 5000) -> str:
    return str(value or "").strip()[:limit]


def safe_url(value: object) -> str:
    text = clean_text(value, 2048)
    if not text:
        return ""
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    try:
        p = urlparse(text)
        valid = p.scheme in {"http", "https"} and p.hostname and "." in p.hostname and not p.username and not p.password
        valid = valid and not any(c.isspace() for c in text) and p.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise DomainError("Informe uma URL pública válida, começando com https://.")
    return text


def maps_query(company: str, city: str) -> str:
    return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": f"{company} {city} PR"})


def next_business_day(value: datetime, days: int) -> datetime:
    local = value.astimezone(TZ)
    count = 0
    while count < days:
        local += timedelta(days=1)
        if local.weekday() < 5:
            count += 1
    if local.hour < 9:
        local = local.replace(hour=9, minute=0, second=0, microsecond=0)
    elif local.hour >= 18:
        return next_business_day(local.replace(hour=9, minute=0, second=0, microsecond=0), 1)
    return local.astimezone(timezone.utc)


def current_evidence(row: dict, at: datetime | None = None) -> bool:
    if row.get("state") != "Verificado" or not row.get("observed_at"):
        return False
    age = (at or now_utc()) - parse_time(row["observed_at"])
    return timedelta(0) <= age <= timedelta(days=30)


def score_evidence(rows: list[dict]) -> dict:
    latest = {}
    for row in sorted(rows, key=lambda r: (r["created_at"], r.get("id", ""))):
        latest[row["criterion"]] = row
    values = {k: latest[k]["points"] for k in CRITERIA if k in latest and current_evidence(latest[k]) and latest[k]["points"] in CRITERIA[k][1]}
    total = sum(values.values()) if len(values) == len(CRITERIA) else None
    priority = "A validar" if total is None else "Alta" if total >= 60 else "Média" if total >= 30 else "Baixa"
    return {"score": total, "priority": priority, "coverage": len(values), "criteria": values}


def whatsapp_url(e164: str, message: str) -> str:
    digits = e164.lstrip("+")
    if not re.fullmatch(r"55\d{10,11}", digits):
        raise DomainError("Número inválido para o link do WhatsApp.")
    return f"https://wa.me/{digits}?text={quote(message, safe='')}"


def is_optout(text: str) -> bool:
    value = normalized(text)
    # Conservative exact/short matching; ambiguous long replies are left to the operator.
    phrases = ["nao tenho interesse", "nao temos interesse", "pare de mandar", "pare de enviar", "nao me chame", "remova meu contato", "remover contato", "nao quero receber", "nao entre mais em contato"]
    if any(value == p or value.startswith(p + " ") for p in phrases):
        return True
    return value in {"nao quero", "sem interesse", "pare", "remover"}
