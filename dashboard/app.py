"""PumpGuard Streamlit dashboard. Talks to the API only (never to the DB directly)."""

import os
from typing import Any

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
DISCLAIMER = (
    "PumpGuard outputs statistical anomaly risk scores for research and education only. "
    "A high score is not an accusation of wrongdoing and is not investment advice "
    "or a buy/sell signal."
)

st.set_page_config(page_title="PumpGuard", layout="wide")


@st.cache_data(ttl=60)
def api_get(path: str, **params: Any) -> dict[str, Any]:
    r = httpx.get(
        f"{API_URL}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=60
    )
    body: dict[str, Any] = r.json()
    if r.status_code >= 400:
        raise RuntimeError(body.get("error", {}).get("message", r.text))
    return body


@st.cache_data(ttl=300)
def api_backtest(source: str, mode: str) -> dict[str, Any]:
    r = httpx.post(
        f"{API_URL}/evaluate/backtest",
        json={"source": source, "mode": mode, "n_bootstrap": 500, "include_periods": False},
        timeout=300,
    )
    body: dict[str, Any] = r.json()
    if r.status_code >= 400:
        raise RuntimeError(body.get("error", {}).get("message", r.text))
    return body["result"]


def gauge(score: float, threshold: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#d62728" if score >= threshold else "#1f77b4"},
                "steps": [{"range": [threshold, 100], "color": "#fde0dd"}],
                "threshold": {"line": {"color": "black", "width": 3}, "value": threshold},
            },
            title={"text": "Anomaly risk score"},
        )
    )
    fig.update_layout(height=260, margin={"t": 40, "b": 10, "l": 20, "r": 20})
    return fig


def price_volume_chart(
    df: pd.DataFrame, threshold: float, window: tuple[str, str] | None = None
) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.03
    )
    fig.add_trace(
        go.Scatter(x=df["date"], y=df["close"], name="Close", line={"color": "#333"}), 1, 1
    )
    flags = df[df["score"].fillna(0) >= threshold]
    fig.add_trace(
        go.Scatter(
            x=flags["date"],
            y=flags["close"],
            mode="markers",
            name=f"Score ≥ {threshold:g}",
            marker={"color": "#d62728", "size": 8, "symbol": "triangle-up"},
        ),
        1,
        1,
    )
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color="#9ecae1"), 2, 1)
    fig.add_trace(
        go.Scatter(x=df["date"], y=df["score"], name="Score", line={"color": "#d62728"}), 3, 1
    )
    fig.add_hline(y=threshold, line_dash="dash", line_color="black", row=3, col=1)
    if window:
        fig.add_vrect(x0=window[0], x1=window[1], fillcolor="orange", opacity=0.15, line_width=0)
    fig.update_yaxes(title_text="Close", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="Score", range=[0, 100], row=3, col=1)
    fig.update_layout(height=620, margin={"t": 20, "b": 20}, legend={"orientation": "h"})
    return fig


def page_stock() -> None:
    st.header("Stock anomaly score")
    stocks = [s["symbol"] for s in api_get("/stocks")["stocks"]]
    if not stocks:
        st.warning("No stocks loaded yet. Run `make seed` (synthetic demo) or the ingestion job.")
        return
    default = stocks.index("SYNTH_09") if "SYNTH_09" in stocks else 0
    symbol = st.selectbox("Symbol", stocks, index=default)
    try:
        score = api_get(f"/stocks/{symbol}/score")
        hist = api_get(f"/stocks/{symbol}/history")
    except RuntimeError as exc:
        st.error(str(exc))
        return
    c1, c2 = st.columns([1, 2])
    with c1:
        st.plotly_chart(gauge(score["score"], score["threshold"]), width="stretch")
        st.caption(f"As of {score['as_of_date']} · model {score['model_version']}")
    with c2:
        st.subheader("Why this score?")
        st.write(score["explanation"])
        st.caption(f"Explanation source: {score['explanation_path']}")
        st.dataframe(pd.DataFrame(score["top_features"]), hide_index=True, width="stretch")
    df = pd.DataFrame(hist["points"])
    st.plotly_chart(price_volume_chart(df, hist["threshold"]), width="stretch")
    if symbol.startswith("SYNTH_"):
        st.info("SYNTH_ symbols are generated demo data, not real companies.")


def page_replay() -> None:
    st.header("Benchmark case replay")
    st.write(
        "Replays what the detector would have said each day **before and during** a known case "
        "window, using a model fitted only on data before the evaluation period."
    )
    cases = api_get("/cases")["cases"]
    if not cases:
        st.warning("No benchmark cases loaded. See docs/RUNBOOK.md → Adding SEBI cases.")
        return
    labels = {
        f"{c['case_id']} · {c['symbol']} · {c['split']}{' · SYNTHETIC' if c['synthetic'] else ''}": c
        for c in cases
    }
    case = labels[st.selectbox("Case", list(labels))]
    detector = st.radio(
        "Detector", ["isolation_forest", "zscore_rule", "logistic_regression"], horizontal=True
    )
    try:
        rep = api_get(f"/cases/{case['case_id']}/replay", detector=detector)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    if case["synthetic"]:
        st.warning("Synthetic fixture: dry-run only, not a real SEBI case.")
    elif case["order_url"]:
        st.markdown(f"SEBI order: [{case['order_reference'] or 'link'}]({case['order_url']})")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Detected", "Yes" if rep["detected"] else "No")
    m2.metric("Threshold (dev-tuned)", f"{rep['threshold']:.1f}")
    m3.metric("First flag", rep["first_flag_date"] or "—")
    m4.metric(
        "Lead time (trading days)",
        rep["lead_time_days"] if rep["lead_time_days"] is not None else "—",
    )
    df = pd.DataFrame(rep["series"])
    st.plotly_chart(
        price_volume_chart(df, rep["threshold"], (rep["window_start"], rep["window_end"])),
        width="stretch",
    )
    st.caption("Orange band = case window. Red triangles = days the score crossed the threshold.")


def page_metrics() -> None:
    st.header("Backtest metrics")
    c1, c2 = st.columns(2)
    source = c1.selectbox("Source", ["synthetic", "db"])
    mode = c2.selectbox("Mode", ["dry-run", "official"])
    try:
        res = api_backtest(source, mode)
    except RuntimeError as exc:
        st.error(str(exc))
        return
    for w in res.get("warnings", []):
        st.warning(w)
    st.caption(
        f"Mode: {res['mode']} · fit cutoff {res['fit_cutoff']} · verified cases: {res['verified_cases']}"
    )
    rows = []
    for d in res["detectors"]:
        t = d["test_metrics"]
        ci = d.get("test_ci", {})

        def fmt(k: str, t: dict[str, Any] = t, ci: dict[str, Any] = ci) -> str:
            v = t.get(k)
            if v is None:
                return "—"
            c = ci.get(k)
            return f"{v:.2f}" + (f" [{c[0]:.2f}, {c[1]:.2f}]" if c else "")

        rows.append(
            {
                "detector": d["detector"],
                "threshold (dev)": d["threshold"],
                "precision": fmt("precision"),
                "recall": fmt("recall"),
                "F1": fmt("f1"),
                "FPR": fmt("false_positive_rate"),
                "median lead (days)": d.get("median_lead_time_days"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Test-split metrics with 95% bootstrap confidence intervals. Thresholds tuned on dev only."
    )


def page_alerts() -> None:
    st.header("Recent alerts")
    alerts = api_get("/alerts")["alerts"]
    if not alerts:
        st.info("No alerts.")
        return
    st.dataframe(pd.DataFrame(alerts), hide_index=True, width="stretch")


PAGES = {
    "Stock score": page_stock,
    "Case replay": page_replay,
    "Backtest metrics": page_metrics,
    "Alerts": page_alerts,
}

st.sidebar.title("PumpGuard")
choice = st.sidebar.radio("Page", list(PAGES))
st.sidebar.caption(f"API: {API_URL}")
st.warning(DISCLAIMER)
try:
    PAGES[choice]()
except httpx.HTTPError as exc:
    st.error(f"Cannot reach the API at {API_URL}: {exc}")
