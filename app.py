"""PowerGrid full-stack Streamlit application.

Runs in CSV demo mode by default and can use PostgreSQL/MongoDB when configured.
Start with: streamlit run app.py
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

st.set_page_config(page_title="PowerGrid | Smart Meter Analytics", page_icon="⚡", layout="wide")


def load_csv(name: str) -> pd.DataFrame:
    path = DATA / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data
 def load_data():
    consumers = load_csv("consumers.csv")
    tariffs = load_csv("tariffs.csv")
    connections = load_csv("connections.csv")
    meters = load_csv("meters.csv")
    bills = load_csv("bills.csv")
    payments = load_csv("payments.csv")
    readings = load_csv("meter_readings.csv")
    for frame, cols in [(bills, ["units_consumed", "total_amount"]), (payments, ["amount_paid"]), (readings, ["kwh_consumed", "voltage"])]:
        for col in cols:
            if col in frame:
                frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0)
    if "billing_month" in bills:
        bills["billing_month"] = pd.to_datetime(bills["billing_month"])
    if "reading_timestamp" in readings:
        readings["reading_timestamp"] = pd.to_datetime(readings["reading_timestamp"])
    return consumers, tariffs, connections, meters, bills, payments, readings


# Optional PostgreSQL reader. CSV mode remains usable without a database.
def postgres_connection():
    try:
        import psycopg2
        return psycopg2.connect(
            host=os.getenv("PG_HOST", "localhost"), port=int(os.getenv("PG_PORT", "5432")),
            dbname=os.getenv("PG_DATABASE", "powergrid_db"), user=os.getenv("PG_USER", "postgres"),
            password=os.getenv("PG_PASSWORD", ""), connect_timeout=3,
        )
    except Exception:
        return None


def postgres_billing():
    conn = postgres_connection()
    if conn is None:
        return None
    try:
        return pd.read_sql("SELECT * FROM vw_consumer_billing_summary", conn)
    except Exception:
        return None
    finally:
        conn.close()


def mongo_readings():
    try:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"), serverSelectionTimeoutMS=1500)
        db = client[os.getenv("MONGO_DATABASE", "powergrid_nosql")]
        docs = list(db.meter_readings.find({}, {"_id": 0}).limit(10000))
        client.close()
        if not docs:
            return None
        rows = []
        for doc in docs:
            telemetry, location = doc.get("telemetry", {}), doc.get("location", {})
            rows.append({**doc, "voltage": telemetry.get("voltage"), "is_peak_hour": telemetry.get("is_peak_hour", False), "is_abnormal": telemetry.get("is_abnormal", False), "area": location.get("area", "Unknown")})
        return pd.DataFrame(rows)
    except Exception:
        return None


def money(value):
    return f"₹{value:,.2f}"


@st.cache_data
 def make_billing(consumers, tariffs, connections, bills, payments):
    if bills.empty:
        return pd.DataFrame()
    paid = payments.groupby("bill_id", as_index=False)["amount_paid"].sum().rename(columns={"amount_paid": "total_paid"}) if not payments.empty else pd.DataFrame(columns=["bill_id", "total_paid"])
    result = (bills.merge(connections, on="connection_id", suffixes=("", "_connection"))
              .merge(consumers[["consumer_id", "full_name", "category", "area"]], on="consumer_id")
              .merge(tariffs[["tariff_id", "tariff_code", "tariff_name"]], on="tariff_id")
              .merge(paid, on="bill_id", how="left"))
    result["total_paid"] = result["total_paid"].fillna(0)
    result["balance_due"] = (result["total_amount"] - result["total_paid"]).round(2)
    return result


def add_payment_csv(bill_id, amount, method):
    """Record a demo payment in session state; PostgreSQL users should use the SQL schema."""
    payment = pd.DataFrame([{"payment_id": int(st.session_state.next_payment_id), "bill_id": int(bill_id), "payment_date": str(date.today()), "amount_paid": float(amount), "payment_method": method, "transaction_ref": f"DEMO-{st.session_state.next_payment_id}"}])
    st.session_state.payments = pd.concat([st.session_state.payments, payment], ignore_index=True)
    st.session_state.next_payment_id += 1
    st.cache_data.clear()
    st.rerun()


consumers, tariffs, connections, bills, payments, readings = (None,) * 6
consumers, tariffs, connections, meters, bills, payments, readings = load_data()
if "payments" not in st.session_state:
    st.session_state.payments = payments.copy()
    st.session_state.next_payment_id = int(payments["payment_id"].max() + 1) if not payments.empty else 1
else:
    payments = st.session_state.payments

billing = make_billing(consumers, tariffs, connections, bills, payments)

with st.sidebar:
    st.title("⚡ PowerGrid")
    st.caption("Smart-meter billing and analytics platform")
    mode = st.radio("Data source", ["CSV demo mode", "PostgreSQL (if available)"], index=0)
    page = st.radio("Navigate", ["Dashboard", "Bills & Payments", "Consumers", "Meter Telemetry", "Tariffs", "System Guide"])
    st.divider()
    st.info("CSV mode works immediately. Copy .env.example to .env to enable PostgreSQL and MongoDB integrations.")

if mode.startswith("PostgreSQL"):
    db_billing = postgres_billing()
    if db_billing is not None:
        billing = db_billing
        st.sidebar.success("PostgreSQL connected")
    else:
        st.sidebar.warning("PostgreSQL unavailable; using CSV data")

if page == "Dashboard":
    st.title("PowerGrid Operations Dashboard")
    st.caption("Bengaluru smart-meter network | January–June 2026")
    total_kwh = float(billing["units_consumed"].sum()) if not billing.empty else 0
    billed = float(billing["total_amount"].sum()) if not billing.empty else 0
    collected = float(billing["total_paid"].sum()) if not billing.empty else 0
    abnormal = int(readings["is_abnormal"].sum()) if "is_abnormal" in readings else 0
    a, b, c, d = st.columns(4)
    a.metric("Total consumption", f"{total_kwh:,.0f} kWh")
    b.metric("Billed revenue", money(billed))
    c.metric("Collection rate", f"{(collected / billed * 100 if billed else 0):.2f}%")
    d.metric("Abnormal readings", f"{abnormal:,}")
    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Monthly consumption")
        monthly = billing.groupby(billing["billing_month"].dt.strftime("%b %Y"), sort=False)["units_consumed"].sum()
        st.line_chart(monthly)
    with right:
        st.subheader("Consumption by area")
        st.bar_chart(billing.groupby("area")["units_consumed"].sum().sort_values(ascending=False))
    st.subheader("Revenue by tariff")
    tariff_view = billing.groupby(["tariff_code", "consumer_category"], as_index=False).agg(total_revenue_inr=("total_amount", "sum"), total_kwh=("units_consumed", "sum"))
    st.dataframe(tariff_view.sort_values("total_revenue_inr", ascending=False).style.format({"total_revenue_inr": money, "total_kwh": "{:,.2f}"}), use_container_width=True, hide_index=True)

elif page == "Bills & Payments":
    st.title("Bills and Payments")
    if billing.empty:
        st.warning("No billing data found."); st.stop()
    c1, c2, c3 = st.columns(3)
    status = c1.multiselect("Bill status", sorted(billing.bill_status.unique()), default=sorted(billing.bill_status.unique()))
    area = c2.multiselect("Area", sorted(billing.area.unique()), default=sorted(billing.area.unique()))
    search = c3.text_input("Search consumer")
    view = billing[billing.bill_status.isin(status) & billing.area.isin(area)].copy()
    if search:
        view = view[view.full_name.str.contains(search, case=False, na=False)]
    st.dataframe(view[["bill_id", "full_name", "area", "tariff_code", "billing_month", "total_amount", "total_paid", "balance_due", "bill_status"]].sort_values("balance_due", ascending=False).style.format({"total_amount": money, "total_paid": money, "balance_due": money}), use_container_width=True, hide_index=True)
    st.divider(); st.subheader("Record demo payment")
    unpaid = view[view.balance_due > 0]
    if unpaid.empty:
        st.success("No outstanding bills in the selected filter.")
    else:
        with st.form("payment_form"):
            selected = st.selectbox("Bill", unpaid.bill_id.tolist(), format_func=lambda x: f"Bill {x} — {unpaid.loc[unpaid.bill_id == x, 'full_name'].iloc[0]}")
            max_due = float(unpaid.loc[unpaid.bill_id == selected, "balance_due"].iloc[0])
            amount = st.number_input("Amount (INR)", min_value=1.0, max_value=max_due, value=max_due, step=1.0)
            method = st.selectbox("Payment method", ["UPI", "NetBanking", "Credit Card", "Debit Card", "Auto-Debit", "Cash"])
            if st.form_submit_button("Record payment"):
                add_payment_csv(selected, amount, method)

elif page == "Consumers":
    st.title("Consumer Directory")
    st.dataframe(consumers, use_container_width=True, hide_index=True)
    selected_id = st.number_input("Consumer ID for detail", min_value=1, max_value=int(consumers.consumer_id.max()), value=1, step=1)
    detail = billing[billing.consumer_id == selected_id]
    if not detail.empty:
        st.subheader(detail.full_name.iloc[0])
        x, y, z = st.columns(3)
        x.metric("6-month consumption", f"{detail.units_consumed.sum():,.2f} kWh")
        y.metric("Billed", money(detail.total_amount.sum()))
        z.metric("Outstanding", money(detail.balance_due.sum()))
        st.dataframe(detail[["billing_month", "units_consumed", "total_amount", "total_paid", "balance_due", "bill_status"]], use_container_width=True, hide_index=True)

elif page == "Meter Telemetry":
    st.title("Smart Meter Telemetry")
    mongo = mongo_readings()
    telemetry = mongo if mongo is not None else readings.copy()
    st.caption("MongoDB data is used when available; otherwise the CSV telemetry dataset is displayed.")
    if telemetry.empty:
        st.warning("No telemetry data found."); st.stop()
    telemetry["hour"] = pd.to_datetime(telemetry.reading_timestamp).dt.hour
    h1, h2 = st.columns(2)
    with h1:
        st.subheader("Average hourly demand")
        st.line_chart(telemetry.groupby("hour")["kwh_consumed"].mean())
    with h2:
        st.subheader("Peak demand by area")
        peak = telemetry[telemetry.is_peak_hour.astype(bool)].groupby("area")["kwh_consumed"].sum().sort_values(ascending=False)
        st.bar_chart(peak)
    st.subheader("Latest abnormal readings")
    abnormal_view = telemetry[telemetry.is_abnormal.astype(bool)].sort_values("kwh_consumed", ascending=False)
    st.dataframe(abnormal_view.head(25), use_container_width=True, hide_index=True)

elif page == "Tariffs":
    st.title("Tariff Management")
    st.dataframe(tariffs, use_container_width=True, hide_index=True)
    tariff_summary = billing.groupby("tariff_code", as_index=False).agg(bills=("bill_id", "count"), kwh=("units_consumed", "sum"), revenue=("total_amount", "sum"))
    st.dataframe(tariff_summary.style.format({"kwh": "{:,.2f}", "revenue": money}), use_container_width=True, hide_index=True)

else:
    st.title("System Guide")
    st.markdown("""### Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

### Production mode
1. Run `database/schema.sql` and `database/data.sql` in PostgreSQL.
2. Set PostgreSQL values in `.env`; choose PostgreSQL in the sidebar.
3. Run `mongodb/crud_operations.py`, then the MongoDB index and aggregation scripts.
4. Keep credentials in `.env`; never commit them.

The application provides dashboard analytics, bill filtering, demo payment recording, consumer drill-down, telemetry anomaly monitoring, tariff summaries, and optional PostgreSQL/MongoDB connectivity.")
