# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse


def parse_count(value) -> int:
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0
    match = re.search(r"([\d.]+)\s*([KMB万億亿]?)", raw, re.IGNORECASE)
    if not match:
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else 0
    number = float(match.group(1))
    suffix = match.group(2).lower()
    factor = 1
    if suffix == "k":
        factor = 1000
    elif suffix == "m":
        factor = 1000000
    elif suffix == "b":
        factor = 1000000000
    elif suffix == "万":
        factor = 10000
    elif suffix in {"亿", "億"}:
        factor = 100000000
    return int(number * factor)


def extract_username_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
        for part in path.split("/"):
            if part.startswith("@"):
                return part.lstrip("@")
    except Exception:
        pass
    return ""


def extract_video_id(url: str) -> str:
    try:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if "video" in parts:
            idx = parts.index("video")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return parts[-1] if parts else ""
    except Exception:
        return ""


def absolute_tiktok_url(href: str) -> str:
    href = str(href or "").strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.tiktok.com" + href
    return href


def normalize_tiktok_username(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "tiktok.com" in raw or "/@" in raw:
        extracted = extract_username_from_url(raw)
        if extracted:
            raw = extracted
    raw = raw.splitlines()[0].strip().lstrip("@")
    raw = raw.split("?")[0].split("#")[0].strip("/")
    raw = re.sub(r"\s+", "", raw)
    raw = re.sub(r"[^A-Za-z0-9._-]", "", raw)
    return raw[:80]


def normalize_comment_text(value: str, max_length: int = 800) -> str:
    text = str(value or "").replace("\u200b", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_length:
        return text[:max_length].rstrip()
    return text


def is_placeholder_comment_text(value: str) -> bool:
    text = normalize_comment_text(value).strip(" .。…").lower()
    if not text:
        return True
    if re.fullmatch(
        r"[·.\-\s]*(\d+\s*)?(s|min|m|h|d|w|sem|semanas?|dia|dias|hora|horas)?\s*(atr[aá]s|ago)?[·.\-\s]*",
        text,
    ) and re.search(r"\d|atr[aá]s|ago", text):
        return True
    if re.fullmatch(r"[·.\-\s]*\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?[·.\-\s]*", text):
        return True
    if re.fullmatch(r"[·.\-\s]*\d+\s*(s|min|m|h|d|w)[·.\-\s]*", text):
        return True
    placeholders = {
        "add comment",
        "add a comment",
        "write a comment",
        "start the conversation",
        "comment",
        "adicionar comentario",
        "adicionar comentário",
        "escreva um comentario",
        "escreva um comentário",
        "añadir comentario",
        "añadir un comentario",
        "agregar comentario",
        "escribe un comentario",
        "添加评论",
        "发表评论",
        "写评论",
        "for you",
        "foryou",
        "para voce",
        "para você",
        "following",
        "seguindo",
        "friends",
        "amigos",
        "explore",
        "explorar",
    }
    return text in placeholders


def is_comment_noise_text(value: str) -> bool:
    text = normalize_comment_text(value).strip(" .。…")
    lowered = text.lower()
    if is_placeholder_comment_text(text):
        return True
    if len(text) < 3:
        return True
    if not re.search(r"[A-Za-z0-9\u00c0-\u024f\u0400-\u04ff\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        return True
    if re.fullmatch(r"[\d,.]+\s*([kmb]|mil|mi|万|亿|億)?", lowered, re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}", lowered):
        return True
    if re.fullmatch(r"#\S+", text):
        return True
    if re.fullmatch(r"[@#\w.\-]+\s*(followers?|following|likes?|views?|comments?)?", lowered):
        return True
    chrome_exact = {
        "capcut editing made easy",
        "editing made easy",
        "original sound",
        "watch full video",
        "view more",
        "see more",
        "shop now",
        "learn more",
        "download tiktok",
        "get the app",
        "promoted",
        "sponsored",
    }
    if lowered in chrome_exact:
        return True
    chrome_contains = [
        "the blueprint self-paced course",
        "join us in celebrating",
        "companyprogramterms",
        "terms & policies",
        "terms and policies",
        "editing made easy",
        "limited time offer",
        "sale live",
        "don't miss out",
        "download the app",
        "open in app",
        "log in to comment",
        "sign up for tiktok",
    ]
    if any(token in lowered for token in chrome_contains):
        return True
    ui_tokens = [
        "follow",
        "following",
        "reply",
        "replies",
        "view replies",
        "like",
        "share",
        "comment",
        "for you",
        "profile",
        "search",
    ]
    token_hits = sum(1 for token in ui_tokens if token in lowered)
    if token_hits >= 5 and len(text) > 60:
        return True
    if lowered.count("tiktok") >= 3 and len(text) > 120:
        return True
    return False


def normalize_source_type(source_type: str) -> str:
    aliases = {
        "tag": "hashtag",
        "shop_keyword": "keyword",
        "live": "live_room_url",
        "live_url": "live_room_url",
    }
    return aliases.get(str(source_type or "").strip(), str(source_type or "").strip())


def classify_vertical(source_type: str, value: str = "") -> str:
    text = f"{source_type} {value}".lower()
    if "product" in text or "shop" in text:
        return "ecommerce"
    return "general"


def normalize_language_text(text: str) -> str:
    value = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def detect_text_language(text: str) -> str:
    value = str(text or "").strip().lower()
    if not value:
        return "unknown"
    if re.search(r"[\u4e00-\u9fff]", value):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", value):
        return "ko"
    if re.search(r"[\u0e00-\u0e7f]", value):
        return "th"
    if re.search(r"[\u0600-\u06ff]", value):
        return "ar"
    if re.search(r"[\u0400-\u04ff]", value):
        return "ru"
    plain = normalize_language_text(value)
    dictionaries = {
        "pt": {"onde", "link", "baixar", "app", "responder", "preco", "comprar", "gratis", "assistir", "nome", "episodio"},
        "es": {"donde", "enlace", "descargar", "precio", "comprar", "gratis", "responder", "nombre", "episodio", "ver"},
        "en": {"where", "link", "download", "price", "buy", "free", "watch", "name", "episode", "app"},
        "fr": {"ou", "lien", "telecharger", "prix", "acheter", "gratuit", "regarder", "nom", "episode", "appli"},
        "de": {"wo", "link", "herunterladen", "preis", "kaufen", "kostenlos", "ansehen", "name", "folge", "app"},
        "it": {"dove", "link", "scaricare", "prezzo", "comprare", "gratis", "guardare", "nome", "episodio", "app"},
        "id": {"dimana", "tautan", "unduh", "harga", "beli", "gratis", "nonton", "nama", "episode", "aplikasi"},
        "vi": {"dau", "link", "tai", "gia", "mua", "mien", "phi", "xem", "ten", "tap", "ung", "dung"},
    }
    words = set(re.findall(r"[a-z]+", plain))
    scores = {language: len(words & keywords) for language, keywords in dictionaries.items()}
    language, score = max(scores.items(), key=lambda item: item[1])
    if score > 0:
        return language
    if re.search(r"[a-z]", value):
        return "latin"
    return "unknown"
