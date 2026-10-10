from app.ingestion.synthetic import CLEAN_SYMBOLS, PUMPS, generate_synthetic_universe


def test_deterministic(synth) -> None:  # type: ignore[no-untyped-def]
    again = generate_synthetic_universe(seed=42)
    for s in synth.prices:
        assert synth.prices[s].equals(again.prices[s])


def test_all_symbols_synthetic_and_valid(synth) -> None:  # type: ignore[no-untyped-def]
    assert len(synth.prices) == len(PUMPS) + len(CLEAN_SYMBOLS)
    for symbol, df in synth.prices.items():
        assert symbol.startswith("SYNTH_")
        assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
        assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
        assert (df["volume"] > 0).all()


def test_pump_raises_volume(synth) -> None:  # type: ignore[no-untyped-def]
    p = PUMPS[0]
    df = synth.prices[p.symbol]
    i = df.index[df["date"] == p.start][0]
    before = df["volume"].iloc[i - 60 : i - 10].median()
    during = df["volume"].iloc[i : i + p.length].median()
    assert during > 3 * before
