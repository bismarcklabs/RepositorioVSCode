"""News intelligence observacional por token.

Recopila noticias, clasifica eventos con reglas transparentes y genera una
prediccion alcista/bajista/neutral. No modifica el score principal ni abre
posiciones; primero permite medir si las noticias anticipan el movimiento real.
"""
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from app import database
from app.config import (
    CRYPTOPANIC_AUTH_TOKEN,
    NEWS_GDELT_ENABLED,
    NEWS_GOOGLE_RSS_ENABLED,
    NEWS_LOOKBACK_HOURS,
    NEWS_MAX_SYMBOLS,
    NEWS_MIN_ABS_SCORE,
    NEWS_OUTCOME_HORIZON_MINUTES,
    NEWS_RSS_FEEDS,
    NEWS_WATCH_SYMBOLS,
    SECURITY_ALERTS_ENABLED,
    SECURITY_GITHUB_REPOS,
)

logger = logging.getLogger("news_intelligence")

_POSITIVE_EVENTS = {
    "partnership": (8, ("partnership", "partners with", "collaboration", "integrates with")),
    "listing": (10, (
        "listing", "listed on", "will list", "to list", "launchpool", "launchpad",
        "support the krw market", "support the usd market",
    )),
    "upgrade": (6, ("mainnet", "upgrade", "launches", "release", "roadmap")),
    "adoption": (8, ("adoption", "institutional", "payment integration", "treasury")),
    "funding_raise": (5, ("raises", "funding round", "investment")),
    "product_launch": (10, (
        "goes live", "is now live", "launches lending", "launches borrowing",
        "launches bitcoin-backed lending", "launches btc-backed lending",
    )),
    "defi_integration": (8, ("bitcoin-backed lending", "btc-backed lending", "native bitcoin collateral")),
    "testnet_launch": (6, (
        "public testnet", "testnet launch", "launches on testnet",
        "lending on aave v4 testnet", "borrowing on aave v4 testnet",
    )),
}
_NEGATIVE_EVENTS = {
    "hack": (-25, ("hack", "hacked", "exploit", "drained", "security breach")),
    "critical_protocol_bug": (-30, (
        "critical vulnerability", "critical soundness vulnerability",
        "counterfeiting vulnerability", "undetectable counterfeit",
        "invalid state transitions", "double-spending",
    )),
    "emergency_security_response": (-18, (
        "emergency soft fork", "emergency hard fork", "time-critical upgrade",
        "temporarily disables", "temporarily disabled", "transactions temporarily suspended",
    )),
    "delisting": (-20, ("delist", "delisting")),
    "large_sale": (-12, ("sell-off", "whale sells", "large sale", "dump")),
    "token_unlock": (-10, ("token unlock", "unlocking tokens", "vesting unlock")),
    "regulatory": (-8, ("lawsuit", "investigation", "regulatory action", "charged")),
    "outage": (-8, ("outage", "halted", "network down", "suspended withdrawals")),
}
_BULLISH_MARKET_LANGUAGE = {
    "strong_rally": (14, ("surges", "soars", "skyrockets", "jumps", "rallies", "breaks above", "breakout")),
    "positive_flow": (10, ("record inflows", "inflow streak", "accumulation", "buying pressure")),
    "recovery": (8, ("rises", "gains", "rebounds", "recovers", "bounces", "bullish")),
    "bearish_flow_ends": (8, ("outflow streak ends", "end outflow streak", "ends outflow streak")),
}
_BEARISH_MARKET_LANGUAGE = {
    "strong_drop": (-16, ("plunges", "crashes", "collapses", "tumbles", "sinks", "gets demolished", "wipe out")),
    "negative_flow": (-10, ("record outflows", "outflow streak", "selling pressure", "liquidation cascade")),
    "decline": (-8, ("falls", "drops", "declines", "slides", "slumps", "bearish")),
    "downside_risk": (-10, ("could crash", "danger of dropping", "breaks below", "risk of falling")),
}
_ALIASES = {
    "BTC": ("bitcoin",),
    "ETH": ("ethereum",),
    "SOL": ("solana",),
    "BNB": ("bnb chain", "binance coin"),
    "XRP": ("ripple",),
    "DOGE": ("dogecoin",),
    "ADA": ("cardano",),
    "AVAX": ("avalanche",),
    "LINK": ("chainlink",),
    "TON": ("toncoin", "the open network"),
    "NEAR": ("near protocol",),
    "HOME": ("defi app", "home token"),
    "BABY": ("babylon", "babylon labs"),
    "AAVE": ("aave",),
    "ZEC": ("zcash",),
}
_AMBIGUOUS_SYMBOLS = {"GAS", "HOME", "LINK", "MASK", "NEAR", "ONE"}


def _base_symbol(symbol: str) -> str:
    value = symbol.upper()
    for suffix in ("USDT", "USDC", "BUSD", "USD"):
        if value.endswith(suffix):
            return value[:-len(suffix)]
    return value


def _event_id(source: str, url: str, title: str) -> str:
    raw = f"{source}|{url}|{title}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _published_iso(value: Any) -> str:
    if isinstance(value, str) and value:
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            pass
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _focused_title(title: str, symbol: str = "") -> str:
    """Reduce titulares multi-token a las clausulas que mencionan el token."""
    if not symbol:
        return title.lower()
    base = _base_symbol(symbol)
    names = (base.lower(), *[alias.lower() for alias in _ALIASES.get(base, ())])
    clauses = re.split(r"[,;]|\bwhile\b|\bwhereas\b", title.lower())
    focused = [clause for clause in clauses if any(re.search(rf"\b{re.escape(name)}\b", clause) for name in names)]
    return " ".join(focused) if focused else title.lower()


def _score_language(text: str, language: Dict[str, tuple]) -> tuple:
    score = 0.0
    labels: List[str] = []
    for label, (weight, phrases) in language.items():
        if any(phrase in text for phrase in phrases):
            score += weight
            labels.append(label)
    return score, labels


def classify_news(title: str, summary: str = "", symbol: str = "") -> Dict[str, Any]:
    focused_title = _focused_title(title, symbol)
    summary_text = summary.lower()
    fundamental_score = 0.0
    events: List[str] = []
    for name, (weight, keywords) in {**_POSITIVE_EVENTS, **_NEGATIVE_EVENTS}.items():
        title_match = any(keyword in focused_title for keyword in keywords)
        summary_match = any(keyword in summary_text for keyword in keywords)
        if title_match or summary_match:
            fundamental_score += weight if title_match else weight * 0.4
            events.append(name)

    bullish_score, bullish_labels = _score_language(focused_title, _BULLISH_MARKET_LANGUAGE)
    bearish_score, bearish_labels = _score_language(focused_title, _BEARISH_MARKET_LANGUAGE)
    outflow_ended = bool(re.search(r"\b(?:end|ends|ended|ending)\b.{0,40}\boutflow streak\b", focused_title))
    if outflow_ended:
        if "bearish_flow_ends" not in bullish_labels:
            bullish_score += 8
            bullish_labels.append("bearish_flow_ends")
        if "negative_flow" in bearish_labels:
            bearish_score -= _BEARISH_MARKET_LANGUAGE["negative_flow"][0]
            bearish_labels.remove("negative_flow")
    market_score = bullish_score + bearish_score
    events.extend(f"market_{label}" for label in bullish_labels + bearish_labels)

    # El titular describe el movimiento inmediato; el cuerpo aporta contexto
    # fundamental, pero no debe invertir una direccion clara del titular.
    score = fundamental_score + market_score
    if market_score >= NEWS_MIN_ABS_SCORE and -NEWS_MIN_ABS_SCORE < score < NEWS_MIN_ABS_SCORE:
        score = market_score
    elif market_score <= -NEWS_MIN_ABS_SCORE and -NEWS_MIN_ABS_SCORE < score < NEWS_MIN_ABS_SCORE:
        score = market_score

    if score >= NEWS_MIN_ABS_SCORE:
        prediction = "BULLISH"
    elif score <= -NEWS_MIN_ABS_SCORE:
        prediction = "BEARISH"
    else:
        prediction = "NEUTRAL"
    return {
        "event_type": events[0] if len(events) == 1 else "mixed" if events else "general",
        "event_types": events,
        "fundamental_score": round(fundamental_score, 2),
        "market_sentiment_score": round(market_score, 2),
        "sentiment_score": round(max(-100, min(100, score)), 2),
        "prediction": prediction,
    }


_CRYPTO_CONTEXT_WORDS = ("crypto", "token", "blockchain", "coin", "defi", "exchange", "onchain", "on-chain")


def _matches_symbol(symbol: str, title: str, summary: str = "") -> bool:
    """Asocia una noticia a un símbolo solo con evidencia explícita.

    Jerarquía de reglas (cualquiera basta):
      1. Alias del proyecto (word-boundary) — "zcash" → ZEC.
      2. Notación de mercado: $POWER, POWER/USDT, POWERUSDT, POWER-USD.
      3. Ticker en MAYÚSCULAS exactas + contexto cripto (solo len>=3): los
         titulares en Title Case producen "Power", no "POWER" — es el filtro
         contra tickers que son palabras comunes en inglés.
      4. Bigrama cripto adyacente (solo len>=3): "power token", "hype coin".

    Tickers de 1-2 letras (A, T, US, IN...) solo matchean por reglas 1-2 —
    sin alias registrado ni notación explícita no hay asociación posible.
    """
    base = _base_symbol(symbol)
    if not base:
        return False
    original_text = f" {title} {summary} "
    text = original_text.lower()
    base_lower = base.lower()
    base_esc = re.escape(base_lower)

    # 1. Alias del proyecto (multi-palabra como frase; palabra sola con boundary)
    for alias in _ALIASES.get(base, ()):
        alias_lower = alias.lower()
        if " " in alias_lower:
            if alias_lower in text:
                return True
        elif re.search(rf"\b{re.escape(alias_lower)}\b", text):
            return True

    # 2. Notación de mercado explícita
    if re.search(rf"(?:\${base_esc}|\b{base_esc}/usdt?\b|\b{base_esc}usdt?\b|\b{base_esc}-usdt?\b)", text):
        return True

    if len(base) < 3:
        return False

    # 3. Ticker en mayúsculas exactas + contexto cripto en el texto
    if re.search(rf"\b{re.escape(base)}\b", original_text) and any(
        word in text for word in _CRYPTO_CONTEXT_WORDS
    ):
        return True

    # 4. Bigrama cripto inmediatamente después del ticker
    return bool(re.search(rf"\b{base_esc}\s+(?:token|coin|price|crypto)\b", text))


def fetch_gdelt_news_batch(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    if not NEWS_GDELT_ENABLED:
        return []
    tracked = list(dict.fromkeys(symbols))
    terms: List[str] = []
    for symbol in tracked:
        base = _base_symbol(symbol)
        aliases = _ALIASES.get(base, ())
        # Sin alias, el ticker pelado solo sirve como término si tiene >=3 letras
        # ("A crypto" o "T crypto" traen puro ruido).
        selected = aliases or ((base,) if len(base) >= 3 else ())
        terms.extend(f'"{alias}"' if " " in alias else alias for alias in selected)
    if not terms:
        return []

    query = f"({' OR '.join(dict.fromkeys(terms))}) (crypto OR token OR blockchain)"
    articles: List[Dict[str, Any]] = []
    for attempt in range(2):
        try:
            response = requests.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "sort": "DateDesc",
                    "maxrecords": 100,
                    "timespan": f"{max(1, int(NEWS_LOOKBACK_HOURS))}h",
                },
                timeout=15,
            )
            if response.status_code == 429 and attempt == 0:
                time.sleep(3)
                continue
            response.raise_for_status()
            articles = response.json().get("articles", [])
            break
        except Exception as exc:
            if attempt == 1:
                logger.warning("GDELT no disponible: %s", exc)
    if not articles:
        return []

    results = []
    for article in articles:
        title = article.get("title", "")
        for symbol in tracked:
            if not _matches_symbol(symbol, title):
                continue
            results.append({
                "event_id": _event_id("gdelt", f"{article.get('url', '')}|{symbol}", title),
                "symbol": symbol,
                "source": "gdelt",
                "source_domain": article.get("domain", ""),
                "title": title,
                "summary": "",
                "url": article.get("url", ""),
                "published_at": _published_iso(article.get("seendate")),
            })
    return results


def fetch_gdelt_news(symbol: str) -> List[Dict[str, Any]]:
    return fetch_gdelt_news_batch([symbol])


def fetch_rss_news_batch(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    """Obtiene noticias RSS como respaldo cuando los agregadores no responden."""
    tracked = list(dict.fromkeys(symbols))
    results: List[Dict[str, Any]] = []
    for feed_url in NEWS_RSS_FEEDS:
        try:
            response = requests.get(
                feed_url,
                timeout=12,
                headers={"User-Agent": "crypto-dashboard/2.0"},
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except Exception as exc:
            logger.warning("RSS no disponible (%s): %s", feed_url, exc)
            continue

        source_domain = urlparse(feed_url).netloc
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            summary = (item.findtext("description") or "").strip()
            url = (item.findtext("link") or "").strip()
            published_at = _published_iso(item.findtext("pubDate"))
            for symbol in tracked:
                if not _matches_symbol(symbol, title, summary):
                    continue
                results.append({
                    "event_id": _event_id("rss", f"{url}|{symbol}", title),
                    "symbol": symbol,
                    "source": "rss",
                    "source_domain": source_domain,
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "published_at": published_at,
                })
    return results


def fetch_google_news_batch(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    """Busca noticias recientes por proyecto mediante el RSS publico de Google News."""
    if not NEWS_GOOGLE_RSS_ENABLED:
        return []
    tracked = list(dict.fromkeys(symbols))
    terms: List[str] = []
    for symbol in tracked:
        base = _base_symbol(symbol)
        aliases = _ALIASES.get(base, ())
        # Para tickers ambiguos o cortos se consulta el nombre del proyecto, no el ticker.
        selected = aliases or (
            (base,) if len(base) >= 3 and base not in _AMBIGUOUS_SYMBOLS else ()
        )
        terms.extend(f'"{term}"' if " " in term else term for term in selected)
    if not terms:
        return []

    try:
        response = requests.get(
            "https://news.google.com/rss/search",
            params={
                "q": f"({' OR '.join(dict.fromkeys(terms))}) crypto when:1d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            timeout=15,
            headers={"User-Agent": "crypto-dashboard/2.0"},
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except Exception as exc:
        logger.warning("Google News RSS no disponible: %s", exc)
        return []

    results: List[Dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        summary = (item.findtext("description") or "").strip()
        url = (item.findtext("link") or "").strip()
        source_node = item.find("source")
        source_domain = (source_node.text or "").strip() if source_node is not None else "Google News"
        published_at = _published_iso(item.findtext("pubDate"))
        for symbol in tracked:
            if not _matches_symbol(symbol, title, summary):
                continue
            results.append({
                "event_id": _event_id("google_news", f"{url}|{symbol}", title),
                "symbol": symbol,
                "source": "google_news",
                "source_domain": source_domain,
                "title": title,
                "summary": summary,
                "url": url,
                "published_at": published_at,
            })
    return results


def fetch_cryptopanic_news(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    if not CRYPTOPANIC_AUTH_TOKEN:
        return []
    currencies = ",".join(_base_symbol(s) for s in symbols)
    try:
        response = requests.get(
            "https://cryptopanic.com/api/developer/v2/posts/",
            params={"auth_token": CRYPTOPANIC_AUTH_TOKEN, "currencies": currencies, "public": "true"},
            timeout=12,
        )
        response.raise_for_status()
        posts = response.json().get("results", [])
    except Exception as exc:
        logger.warning("CryptoPanic no disponible: %s", exc)
        return []

    results: List[Dict[str, Any]] = []
    for post in posts:
        title = post.get("title", "")
        for currency in post.get("currencies") or []:
            symbol = f"{currency.get('code', '').upper()}USDT"
            if not symbol or not _matches_symbol(symbol, title):
                continue
            results.append({
                "event_id": _event_id("cryptopanic", f"{post.get('url', '')}|{symbol}", title),
                "symbol": symbol,
                "source": "cryptopanic",
                "source_domain": (post.get("source") or {}).get("domain", ""),
                "title": title,
                "summary": "",
                "url": post.get("url", ""),
                "published_at": _published_iso(post.get("published_at")),
            })
    return results


def fetch_github_security_news(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    """Consulta releases y advisories oficiales, normalmente antes que los medios."""
    tracked = set(symbols)
    results: List[Dict[str, Any]] = []
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "crypto-dashboard/2.0"}
    for repo, symbol in SECURITY_GITHUB_REPOS:
        if symbol not in tracked:
            continue
        endpoints = (
            ("github_release", f"https://api.github.com/repos/{repo}/releases?per_page=10"),
            ("github_advisory", f"https://api.github.com/repos/{repo}/security-advisories?per_page=10"),
        )
        for source, endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=15, headers=headers)
                response.raise_for_status()
                items = response.json()
            except Exception as exc:
                logger.warning("GitHub security source no disponible (%s): %s", repo, exc)
                continue
            for item in items if isinstance(items, list) else []:
                title = item.get("name") or item.get("summary") or item.get("ghsa_id") or ""
                summary = item.get("body") or item.get("description") or ""
                published = item.get("published_at") or item.get("created_at")
                if not title or not published:
                    continue
                event_url = item.get("html_url") or item.get("url") or ""
                results.append({
                    "event_id": _event_id(source, f"{event_url}|{symbol}", title),
                    "symbol": symbol,
                    "source": source,
                    "source_domain": f"github.com/{repo}",
                    "title": title,
                    "summary": summary[:4000],
                    "url": event_url,
                    "published_at": _published_iso(published),
                })
    return results


def score_event(event: Dict[str, Any]) -> Dict[str, Any]:
    classification = classify_news(
        event.get("title", ""),
        event.get("summary", ""),
        event.get("symbol", ""),
    )
    credibility = {
        "cryptopanic": 0.85, "rss": 0.75, "google_news": 0.70,
        "github_release": 0.95, "github_advisory": 1.0,
    }.get(event.get("source"), 0.65)
    score = round(classification["sentiment_score"] * credibility, 2)
    return {
        **event,
        **classification,
        "credibility": credibility,
        "weighted_score": score,
    }


def aggregate_prediction(symbol: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    relevant = [event for event in events if event.get("symbol") == symbol]
    weighted = sum(float(event.get("weighted_score") or 0.0) for event in relevant)
    positive = sum(1 for event in relevant if event.get("prediction") == "BULLISH")
    negative = sum(1 for event in relevant if event.get("prediction") == "BEARISH")
    contradictory = positive > 0 and negative > 0
    score = max(-100.0, min(100.0, weighted))
    if score >= NEWS_MIN_ABS_SCORE:
        prediction = "BULLISH"
    elif score <= -NEWS_MIN_ABS_SCORE:
        prediction = "BEARISH"
    else:
        prediction = "NEUTRAL"
    confidence = min(100, int(abs(score) + min(30, len(relevant) * 5)))
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "symbol": symbol,
        "prediction": prediction,
        "sentiment_score": round(score, 2),
        "confidence": confidence,
        "news_count": len(relevant),
        "positive_count": positive,
        "negative_count": negative,
        "contradictory": contradictory,
        "top_events": sorted(relevant, key=lambda event: abs(event.get("weighted_score", 0)), reverse=True)[:3],
    }


def run_news_collection(symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    discovered = symbols or database.get_recent_symbols(limit=NEWS_MAX_SYMBOLS)
    tracked = list(dict.fromkeys([*NEWS_WATCH_SYMBOLS, *discovered]))[:NEWS_MAX_SYMBOLS]
    events: List[Dict[str, Any]] = []
    events.extend(fetch_cryptopanic_news(tracked))
    events.extend(fetch_gdelt_news_batch(tracked))
    events.extend(fetch_rss_news_batch(tracked))
    events.extend(fetch_google_news_batch(tracked))
    events.extend(fetch_github_security_news(tracked))

    scored = [score_event(event) for event in events]
    if scored:
        database.insert_news_events(scored)
        if SECURITY_ALERTS_ENABLED:
            from app.security_intelligence import process_security_events
            process_security_events(scored)

    predictions = [aggregate_prediction(symbol, scored) for symbol in tracked]
    predictions = [item for item in predictions if item["news_count"] > 0]
    for prediction in predictions:
        prediction["price_at_prediction"] = database.get_latest_symbol_price(prediction["symbol"])
        prediction["horizon_minutes"] = NEWS_OUTCOME_HORIZON_MINUTES
        database.insert_news_prediction(prediction)
    return predictions


def run_security_collection(symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Ciclo rapido: solo fuentes oficiales/RSS y GitHub para incidentes criticos."""
    discovered = symbols or []
    tracked = list(dict.fromkeys([*NEWS_WATCH_SYMBOLS, *discovered]))[:NEWS_MAX_SYMBOLS]
    events = [*fetch_rss_news_batch(tracked), *fetch_github_security_news(tracked)]
    scored = [score_event(event) for event in events]
    if scored:
        database.insert_news_events(scored)
        from app.security_intelligence import process_security_events
        return process_security_events(scored)
    return []


def evaluate_news_predictions(horizon_minutes: int = 60) -> int:
    return database.evaluate_open_news_predictions(horizon_minutes=horizon_minutes)
