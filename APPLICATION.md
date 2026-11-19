# PowerGrid Full Application

PowerGrid is now runnable as a Streamlit application combining the existing PostgreSQL billing model, MongoDB telemetry model, CSV fallback data, analytics, and payment workflows.

## Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

The application works immediately in **CSV demo mode**. Configure `.env` and select PostgreSQL from the sidebar to read the billing summary view. If MongoDB is available, the telemetry page automatically reads MongoDB documents; otherwise it uses `data/meter_readings.csv`.

## Features

- Operations dashboard with consumption, revenue, collection-rate, and anomaly KPIs.
- Monthly and area-level charts plus tariff revenue analysis.
- Bill search/filtering and outstanding-balance views.
- Demo payment recording in the current Streamlit session.
- Consumer directory and individual billing history.
- Peak-hour demand and abnormal-reading monitoring.
- Tariff management and system setup guide.
- Optional PostgreSQL and MongoDB integrations with graceful CSV fallback.

For permanent payments, use the PostgreSQL `payments` table and the existing schema constraints; demo payments are intentionally session-local so the application cannot alter production data accidentally.
