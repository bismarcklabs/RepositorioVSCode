from app.news_intelligence import (
    _matches_symbol,
    aggregate_prediction,
    classify_news,
    fetch_google_news_batch,
    fetch_rss_news_batch,
    score_event,
)


def test_classifies_confirmed_hack_as_bearish():
    result = classify_news("Protocol hacked after critical exploit")
    assert result["prediction"] == "BEARISH"
    assert result["sentiment_score"] <= -20
    assert "hack" in result["event_types"]


def test_classifies_partnership_as_bullish():
    result = classify_news("Project announces partnership and payment integration")
    assert result["prediction"] == "BULLISH"
    assert result["sentiment_score"] > 0


def test_classifies_babylon_aave_testnet_launch_as_bullish():
    result = classify_news(
        "Babylon launches Bitcoin-backed lending on Aave V4 testnet",
        symbol="BABYUSDT",
    )
    assert result["prediction"] == "BULLISH"
    assert result["sentiment_score"] >= 20
    assert "defi_integration" in result["event_types"]
    assert "testnet_launch" in result["event_types"]


def test_classifies_future_exchange_listing_as_bullish():
    result = classify_news("UPBIT will list Babylon (BABY) and support the KRW market", symbol="BABYUSDT")
    assert result["prediction"] == "BULLISH"
    assert "listing" in result["event_types"]


def test_classifies_zcash_orchard_vulnerability_as_strong_bearish():
    result = classify_news(
        "Zcash Orchard critical soundness vulnerability triggers emergency soft fork",
        symbol="ZECUSDT",
    )
    assert result["prediction"] == "BEARISH"
    assert result["sentiment_score"] <= -40
    assert "critical_protocol_bug" in result["event_types"]
    assert "emergency_security_response" in result["event_types"]


def test_classifies_market_drop_as_bearish_even_with_positive_summary():
    result = classify_news(
        "Ripple-linked XRP sinks 7% to four-month lows",
        "Institutional adoption remains part of the long-term thesis",
        "XRPUSDT",
    )
    assert result["prediction"] == "BEARISH"
    assert result["market_sentiment_score"] < 0
    assert result["sentiment_score"] < 0


def test_classifies_downside_risk_language_as_bearish():
    result = classify_news("Bitcoin in danger of dropping to $60,000", symbol="BTCUSDT")
    assert result["prediction"] == "BEARISH"


def test_classifies_ending_outflow_streak_as_bullish():
    result = classify_news("Bitcoin ETFs end outflow streak", symbol="BTCUSDT")
    assert result["prediction"] == "BULLISH"


def test_focuses_on_requested_token_in_multi_asset_title():
    btc = classify_news(
        "Bitcoin bounces, HYPE falls, NEAR gets demolished",
        symbol="BTCUSDT",
    )
    near = classify_news(
        "Bitcoin bounces, HYPE falls, NEAR gets demolished",
        symbol="NEARUSDT",
    )
    assert btc["prediction"] == "BULLISH"
    assert near["prediction"] == "BEARISH"


def test_does_not_match_ambiguous_ticker_as_common_word():
    assert not _matches_symbol("NEARUSDT", "Bitcoin plunges to near $62,000")
    assert _matches_symbol("NEARUSDT", "NEAR gets demolished as crypto falls")
    assert _matches_symbol("NEARUSDT", "Near Protocol announces an upgrade")
    assert _matches_symbol("ZECUSDT", "Zcash Orchard vulnerability remediated")


def test_one_letter_ticker_needs_explicit_notation():
    # Falsos positivos reales del diagnóstico 2026-07-17: "A" matcheaba todo
    assert not _matches_symbol("AUSDT", "A Guide to Crypto Wallets for Beginners")
    assert not _matches_symbol("AUSDT", "More Than Bitcoin: 5 Types of Crypto Projects Explained Simply")
    assert not _matches_symbol("TUSDT", "Inside Bonzo Lend's $9M exploit - why secure smart contracts couldn't stop it")
    # Con notación explícita sí
    assert _matches_symbol("AUSDT", "$A rallies 20% after exchange listing")
    assert _matches_symbol("AUSDT", "AUSDT volume spikes on Binance")
    assert _matches_symbol("TUSDT", "T/USDT breaks resistance")


def test_english_word_tickers_need_crypto_evidence():
    # Falsos positivos reales: POWER (Anker), TRUMP (política), BEAT, HYPE, SAMSUNG
    assert not _matches_symbol("POWERUSDT", "This Compact Anker Portable Power Station Is 50% Off Right Now")
    assert not _matches_symbol("POWERUSDT", "Severe storms down power lines across Hackensack")
    assert not _matches_symbol("TRUMPUSDT", "Trump blames vandals for Reflecting Pool problems")
    assert not _matches_symbol("BEATUSDT", "Hacks and The Comeback Beat the Odds - Filmmaker Magazine")
    assert not _matches_symbol("HYPEUSDT", "Hackers are capitalizing on AI hype to ramp up social engineering attacks")
    assert not _matches_symbol("SAMSUNGUSDT", "Samsung Galaxy Z Fold 8 Price Leak Reveals Ultra Tier")
    # Con evidencia cripto explícita sí
    assert _matches_symbol("POWERUSDT", "$POWER surges after Aragon DAO exploit recovery")
    assert _matches_symbol("POWERUSDT", "Attacker cleans out $1.6M from POWER in Aragon DAO exploit, token crashes")
    assert _matches_symbol("HYPEUSDT", "HYPE token hits new all-time high")
    assert _matches_symbol("TRUMPUSDT", "TRUMP coin crashes 30% after unlock")


def test_uppercase_ticker_requires_crypto_context():
    # MAYÚSCULAS sin contexto cripto no basta (siglas de otra industria)
    assert not _matches_symbol("POWERUSDT", "POWER outage hits the East Coast grid")
    assert _matches_symbol("POWERUSDT", "POWER leads token gainers on DeFi exchange")


def test_aggregate_marks_contradictory_news():
    positive = score_event({
        "symbol": "HOMEUSDT",
        "source": "gdelt",
        "title": "HOME token announces partnership",
    })
    negative = score_event({
        "symbol": "HOMEUSDT",
        "source": "gdelt",
        "title": "HOME token exploit reported",
    })
    result = aggregate_prediction("HOMEUSDT", [positive, negative])
    assert result["contradictory"] is True
    assert result["positive_count"] == 1
    assert result["negative_count"] == 1


def test_aggregate_ignores_other_symbols():
    event = score_event({
        "symbol": "BTCUSDT",
        "source": "gdelt",
        "title": "Bitcoin partnership announced",
    })
    result = aggregate_prediction("ETHUSDT", [event])
    assert result["news_count"] == 0
    assert result["prediction"] == "NEUTRAL"


def test_rss_maps_same_article_to_each_matching_token(monkeypatch):
    payload = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>Bitcoin and Ethereum announce crypto partnership</title>
      <description>BTC and ETH adoption grows</description>
      <link>https://example.com/story</link>
      <pubDate>Fri, 05 Jun 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>"""

    class Response:
        content = payload

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("app.news_intelligence.NEWS_RSS_FEEDS", ["https://example.com/rss"])
    monkeypatch.setattr("app.news_intelligence.requests.get", lambda *args, **kwargs: Response())

    events = fetch_rss_news_batch(["BTCUSDT", "ETHUSDT"])

    assert {event["symbol"] for event in events} == {"BTCUSDT", "ETHUSDT"}
    assert len({event["event_id"] for event in events}) == 2
    assert all(event["published_at"] == "2026-06-05T12:00:00" for event in events)


def test_google_news_maps_babylon_name_to_baby(monkeypatch):
    payload = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>Babylon launches Bitcoin-backed lending on Aave V4 testnet</title>
      <description>Babylon Labs product launch</description>
      <link>https://news.google.com/story</link>
      <pubDate>Fri, 05 Jun 2026 09:00:00 GMT</pubDate>
      <source>Binance News</source>
    </item></channel></rss>"""

    class Response:
        content = payload

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("app.news_intelligence.requests.get", lambda *args, **kwargs: Response())
    events = fetch_google_news_batch(["BABYUSDT"])

    assert len(events) == 1
    assert events[0]["symbol"] == "BABYUSDT"
    assert events[0]["source_domain"] == "Binance News"
