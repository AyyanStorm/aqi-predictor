"""
accuracy.py — Streamlit UI for the AQI tracking & accuracy section.

grill-me decisions implemented here:
  - OPTION C accuracy: MAPE-based headline %, ±15 tolerance hit-rate,
    EPA category-match % as supporting stats.
  - AUTOMATIC tracking: every generated prediction is saved (per-browser
    user_id via localStorage), actuals fetched retroactively from
    Open-Meteo at view time — the graph fills in as time passes.
  - "Track My City" reuses the EXISTING location picker (GPS/IP/search)
    — no duplicate location system. Selecting a city = tracking it.
  - Per-browser identity: anonymous uuid in localStorage (Q4 option a).

Design keeps the existing dark AQI Predictor language: #0e1117 cards,
accent-colored values, Plotly dark theme. Everything here is defensive —
any failure degrades to an info/warning message and NEVER breaks the
existing forecast UI.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_js_eval import get_local_storage, set_local_storage

from src.tracking import accuracy as acc
from src.tracking.store import (
    ParquetPredictionStore,
    get_prediction_store,
    new_prediction_id,
)
from src.utils.local_time import tz_display_name
from src.utils.logger import get_logger

logger = get_logger(__name__)

USER_ID_KEY = "aqi_user_id"
STORE_KEY = "aqi_tracking_store"

# Chart colours — distinguishable on the dark theme:
#   predicted = amber, actual = light blue (colourblind-safe pairing).
PRED_COLOR = "#ffb74d"
ACTUAL_COLOR = "#4fc3f7"


# ---------------------------------------------------------------
# Store resolution (resilient: Hopsworks -> Parquet fallback)
# ---------------------------------------------------------------
def _resolve_store():
    """
    One store per session, cached in session_state so save and load
    ALWAYS hit the same backend. Prefers Hopsworks when configured and
    installed; falls back to Parquet on any failure.
    """
    if STORE_KEY in st.session_state:
        return st.session_state[STORE_KEY]
    store = get_prediction_store()
    st.session_state[STORE_KEY] = store
    return store


def _fallback_to_parquet():
    """Force the local Parquet store and remember it for this session."""
    store = ParquetPredictionStore()
    st.session_state[STORE_KEY] = store
    return store


# ---------------------------------------------------------------
# Per-browser identity (Q4: per-browser, private)
# ---------------------------------------------------------------
def get_user_id():
    """
    Stable anonymous id per browser (Q4: per-browser, private).

    Stored in localStorage via streamlit-js-eval, mirrored in
    session_state so it survives reruns.

    FIX (16:17 bug): on a FRESH page load the JS bridge hasn't rendered
    yet, so the first get_local_storage() returns None EVEN IF an id is
    already stored. The old code then generated a new id and overwrote
    localStorage — orphaning every previous prediction, which is why the
    user saw "No tracked predictions" on the next visit after seeing the
    graph the first time.

    Fix: rerun once so the component value arrives, then ADOPT the
    stored id. Only create a new id when a second read still returns
    None (genuinely fresh browser).
    """
    if USER_ID_KEY in st.session_state:
        return st.session_state[USER_ID_KEY]
    try:
        stored = get_local_storage(USER_ID_KEY)
    except Exception as e:
        logger.warning(f"localStorage read failed: {e}")
        stored = None
    if stored:
        st.session_state[USER_ID_KEY] = stored
        return stored
    if not st.session_state.get("_user_id_retried"):
        # First render of this page load: None may mean "JS not ready
        # yet", not "no id". Rerun once so the bridge delivers the real
        # stored value instead of us clobbering it with a fresh uuid.
        st.session_state["_user_id_retried"] = True
        st.rerun()
    # Second read also empty -> genuinely new browser: create + persist.
    uid = str(uuid.uuid4())
    st.session_state[USER_ID_KEY] = uid
    try:
        set_local_storage(USER_ID_KEY, uid)
    except Exception as e:
        logger.warning(f"localStorage write failed: {e}")
    return uid


# ---------------------------------------------------------------
# Automatic save (Q3: automatic tracking)
# ---------------------------------------------------------------
def maybe_save_prediction(user_id, loc, result):
    """
    Save the just-generated prediction once. Idempotent: if a prediction
    for the same city + base hour already exists, skip (avoids spamming
    the store on every rerun).

    Resilient: if the preferred (Hopsworks) store fails to write — e.g.
    the pyjks/twofish wall on Windows — we FALL BACK to the local
    Parquet store and warn the user, so a write failure can never look
    like "no tracked predictions".
    """
    try:
        store = _resolve_store()
        base = pd.Timestamp(result["fetched_at"]).floor("h")
        existing = store.load(user_id=user_id, city=loc.get("name"))
        if not existing.empty and "base_ts" in existing.columns:
            if (pd.to_datetime(existing["base_ts"]) == base).any():
                return  # already tracked this forecast
        record = acc.build_record(user_id, loc, result)
        record["prediction_id"] = new_prediction_id()
        try:
            store.save(record)
        except Exception as e:
            logger.warning(
                f"Tracking store write failed ({e}) — falling back to "
                f"local Parquet store"
            )
            _fallback_to_parquet().save(record)
            st.warning(
                "⚠️ Could not write this prediction to the remote store, "
                "so it was saved locally instead. Tracking still works."
            )
    except Exception as e:
        logger.warning(f"maybe_save_prediction failed (tracking skipped): {e}")
        st.warning(f"⚠️ Tracking save failed: {e}")


# ---------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------
def _to_local(ts_utc, tz_name):
    """UTC timestamp -> naive local datetime for plotting."""
    ts = pd.Timestamp(ts_utc)
    if tz_name:
        try:
            ts = ts.tz_convert(ZoneInfo(tz_name))
        except Exception:
            ts = ts.tz_convert("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.tz_localize(None)


def _prediction_chart(record, actuals_df, tz_name, city):
    """
    Plotly figure: Predicted AQI (amber, markers+line at current/+24h/
    +48h/+72h) vs Actual AQI (light blue hourly line, progressively
    available). Covers the 72h tracking window.
    """
    fig = go.Figure()

    base = pd.Timestamp(record["base_ts"])
    x_pred, y_pred = [], []
    x_pred.append(_to_local(base, tz_name))
    y_pred.append(int(record["current_aqi"]))
    for h, ts_utc, pred in acc.horizon_values(record):
        x_pred.append(_to_local(ts_utc, tz_name))
        y_pred.append(pred)

    fig.add_trace(go.Scatter(
        x=x_pred, y=y_pred,
        mode="lines+markers",
        name="Predicted AQI",
        line=dict(color=PRED_COLOR, width=2.5, dash="dash"),
        marker=dict(size=8, color=PRED_COLOR),
    ))

    if actuals_df is not None and not actuals_df.empty:
        x_act = [_to_local(t, tz_name) for t in actuals_df["date"]]
        fig.add_trace(go.Scatter(
            x=x_act, y=actuals_df["us_aqi"],
            mode="lines",
            name="Actual AQI",
            line=dict(color=ACTUAL_COLOR, width=2),
        ))

    tz_label = tz_display_name(tz_name) if tz_name else "UTC"
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#e6e6e6"),
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(title=f"Local time ({city})", gridcolor="#262b36"),
        yaxis=dict(title="AQI (US EPA)", gridcolor="#262b36"),
        hovermode="x unified",
    )
    return fig


def _metric_card(title, value, subtitle, accent):
    """Metric card matching the existing forecast-card language."""
    return f"""
    <div style="
        border: 2px solid {accent};
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 8px;
        background: #0e1117;">
      <div style="font-size: 0.85rem; color: #aaa;">{title}</div>
      <div style="font-size: 2.2rem; font-weight: 700; color: {accent};">
        {value}
      </div>
      <div style="font-size: 0.8rem; color: #9aa4b2;">{subtitle}</div>
    </div>
    """


def _render_summary_cards(summary, per_city=False):
    """Row of Option-C metric cards from a summarize() dict."""
    if summary is None:
        return
    c1, c2, c3 = st.columns(3)
    scope = city_label = ""
    with c1:
        st.markdown(_metric_card(
            "Average Prediction Accuracy",
            f"{summary['avg_accuracy']:.1f}%",
            f"MAPE-based · {summary['n_horizons']} horizon(s) evaluated",
            "#66bb6a",
        ), unsafe_allow_html=True)
    with c2:
        st.markdown(_metric_card(
            "±15 AQI Hit Rate",
            f"{summary['hit_rate']:.0f}%",
            f"{summary['n_correct']}/{summary['n_horizons']} within ±15 points",
            PRED_COLOR,
        ), unsafe_allow_html=True)
    with c3:
        st.markdown(_metric_card(
            "EPA Category Match",
            f"{summary['category_rate']:.0f}%",
            "predicted band == actual band",
            ACTUAL_COLOR,
        ), unsafe_allow_html=True)


# ---------------------------------------------------------------
# Main render
# ---------------------------------------------------------------
def render_accuracy(user_id, loc):
    """
    The "Prediction vs Actual AQI" section: chart + Option-C cards for
    the selected city, then the global "Your Average Accuracy" section.
    Every block is defensive — never breaks the rest of the app.
    """
    tz_name = loc.get("timezone")
    city = loc.get("name", "selected city")

    st.divider()
    st.subheader("📊 Prediction vs Actual AQI")

    store = _resolve_store()
    try:
        records = store.load(user_id=user_id, city=city)
    except Exception as e:
        logger.warning(f"load predictions failed: {e}")
        records = pd.DataFrame()

    if records.empty:
        st.info(
            "No tracked predictions for this city yet. Every forecast you "
            "generate is saved automatically — come back after a few hours "
            "and the actual AQI line will appear here."
        )
    else:
        # Latest tracking window for this city.
        record = records.sort_values("created_at").iloc[-1].to_dict()
        end = pd.Timestamp(record["base_ts"]) + pd.Timedelta(hours=72)
        actuals = acc.fetch_actuals(record.get("lat"), record.get("lon"),
                                    record["base_ts"], end)
        fig = _prediction_chart(record, actuals, tz_name, city)
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})

        # Per-city Option-C cards (evaluated horizons for this city).
        all_rows = []
        for _, r in store.load(user_id=user_id, city=city).iterrows():
            rec = r.to_dict()
            results, _ = acc.evaluate_record(rec, acc.fetch_actuals(
                rec.get("lat"), rec.get("lon"), rec["base_ts"],
                pd.Timestamp(rec["base_ts"]) + pd.Timedelta(hours=72)))
            all_rows.extend(results)
        city_summary = acc.summarize(all_rows)

        if city_summary is None:
            st.caption(
                "⏳ Tracking in progress — actual AQI data will appear here "
                "as the +24h/+48h/+72h timestamps pass."
            )
        else:
            _render_summary_cards(city_summary, per_city=True)
            if loc.get("source") in ("browser", "ip"):
                st.caption(f"📍 Tracking your current city: **{city}**")
            else:
                st.caption(
                    "🎯 Tracking your own city? Use **'Use my location'** in "
                    "the sidebar — it's tracked automatically, no extra setup."
                )

    # ---- Your Average Accuracy (global, across all tracked cities) ----
    st.divider()
    st.subheader("🎯 Your Average Accuracy")
    try:
        all_records = _resolve_store().load(user_id=user_id)
    except Exception as e:
        logger.warning(f"load all predictions failed: {e}")
        all_records = pd.DataFrame()

    if all_records.empty:
        st.info(
            "No tracked predictions yet. Generate a forecast for any city "
            "(including your own via 'Use my location') and your average "
            "accuracy will build up automatically as the 72h windows complete."
        )
        return

    global_rows = []
    cities_seen = set()
    periods = []
    for _, r in all_records.iterrows():
        rec = r.to_dict()
        try:
            aq = acc.fetch_actuals(
                rec.get("lat"), rec.get("lon"), rec["base_ts"],
                pd.Timestamp(rec["base_ts"]) + pd.Timedelta(hours=72))
            results, _ = acc.evaluate_record(rec, aq)
        except Exception as e:
            logger.warning(f"evaluate {rec.get('prediction_id')} failed: {e}")
            continue
        if results:
            cities_seen.add(rec.get("city"))
            periods.append(pd.Timestamp(rec["base_ts"]))
        global_rows.extend(results)

    summary = acc.summarize(global_rows)
    if summary is None:
        st.caption(
            "⏳ Tracking in progress — accuracy appears once any +24h/+48h/"
            "+72h window has completed and actuals are available."
        )
        return

    # Headline number + supporting stats.
    c_head, c_sup = st.columns([1, 2])
    with c_head:
        st.markdown(_metric_card(
            "Average Prediction Accuracy",
            f"{summary['avg_accuracy']:.1f}%",
            f"across {summary['n_horizons']} evaluated horizon(s)",
            "#66bb6a",
        ), unsafe_allow_html=True)
    with c_sup:
        n_pred = len(all_records)
        st.markdown(_metric_card(
            "Tracking Summary",
            f"{len(cities_seen)}",
            f"cities tracked · {n_pred} prediction(s) saved",
            "#9aa4b2",
        ), unsafe_allow_html=True)

    if periods:
        first, last = min(periods), max(periods)
        st.caption(
            f"📅 Tracking period: {first.strftime('%b %d, %Y')} → "
            f"{last.strftime('%b %d, %Y')} · "
            f"✅ {summary['n_correct']} within ±15 AQI · "
            f"📊 {summary['n_horizons']} horizons evaluated"
        )
