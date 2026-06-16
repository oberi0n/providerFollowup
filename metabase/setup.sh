#!/bin/sh
set -eu

METABASE_URL="${METABASE_URL:-http://metabase:3000}"
ADMIN_EMAIL="${MB_ADMIN_EMAIL:-admin@providerfollowup.local}"
ADMIN_PASSWORD="${MB_ADMIN_PASSWORD:-ProviderFollowup!2026}"
DB_HOST="${APP_DB_HOST:-postgres}"
DB_PORT="${APP_DB_PORT:-5432}"
DB_NAME="${APP_DB_NAME:-providerfollowup}"
DB_USER="${APP_DB_USER:-provider}"
DB_PASSWORD="${APP_DB_PASSWORD:-provider}"

echo "Waiting for Metabase at ${METABASE_URL}..."
until curl -fsS "${METABASE_URL}/api/health" >/dev/null 2>&1; do
  sleep 5
done

PROPS=$(curl -fsS "${METABASE_URL}/api/session/properties")
SETUP_TOKEN=$(printf '%s' "$PROPS" | sed -n 's/.*"setup-token":"\([^"]*\)".*/\1/p')

if [ -n "$SETUP_TOKEN" ]; then
  echo "Initialising Metabase admin and Provider Follow-up database..."
  SETUP_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/setup" \
    -H "Content-Type: application/json" \
    -d "{\"token\":\"${SETUP_TOKEN}\",\"user\":{\"first_name\":\"Provider\",\"last_name\":\"Admin\",\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"},\"prefs\":{\"site_name\":\"Provider Follow-up\",\"site_locale\":\"fr\"},\"database\":null}" || true)
  SESSION_ID=$(printf '%s' "$SETUP_RESPONSE" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  if [ -z "$SESSION_ID" ]; then
    echo "Metabase setup endpoint refused initialisation; trying to log in with the existing admin."
    LOGIN_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/session" \
      -H "Content-Type: application/json" \
      -d "{\"username\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" || true)
    SESSION_ID=$(printf '%s' "$LOGIN_RESPONSE" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  fi
else
  echo "Metabase is already initialised; logging in."
  LOGIN_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/session" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" || true)
  SESSION_ID=$(printf '%s' "$LOGIN_RESPONSE" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
fi

if [ -z "${SESSION_ID:-}" ]; then
  echo "Cannot obtain Metabase session; setup may already be configured with different credentials."
  exit 0
fi

DATABASES=$(curl -fsS "${METABASE_URL}/api/database" -H "X-Metabase-Session: ${SESSION_ID}")
DB_ID=$(printf '%s' "$DATABASES" | sed -n 's/.*"id":\([0-9][0-9]*\),"name":"Provider Follow-up PostgreSQL".*/\1/p')
if [ -z "$DB_ID" ]; then
  DB_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/database" \
    -H "Content-Type: application/json" \
    -H "X-Metabase-Session: ${SESSION_ID}" \
    -d "{\"engine\":\"postgres\",\"name\":\"Provider Follow-up PostgreSQL\",\"details\":{\"host\":\"${DB_HOST}\",\"port\":${DB_PORT},\"dbname\":\"${DB_NAME}\",\"user\":\"${DB_USER}\",\"password\":\"${DB_PASSWORD}\",\"ssl\":false,\"ssl-mode\":\"disable\",\"additional-options\":\"sslmode=disable\"}}")
  DB_ID=$(printf '%s' "$DB_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
fi

DASH_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/dashboard" \
  -H "Content-Type: application/json" \
  -H "X-Metabase-Session: ${SESSION_ID}" \
  -d '{"name":"Provider Follow-up - Budget invoices","description":"Dashboard auto-configured by docker compose."}')
DASH_ID=$(printf '%s' "$DASH_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
DASH_CARDS=""
CARD_INDEX=0

create_card() {
  NAME="$1"
  SQL="$2"
  DISPLAY="${3:-table}"
  CARD_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/card" \
    -H "Content-Type: application/json" \
    -H "X-Metabase-Session: ${SESSION_ID}" \
    -d "{\"name\":\"${NAME}\",\"dataset_query\":{\"database\":${DB_ID},\"type\":\"native\",\"native\":{\"query\":\"${SQL}\"}},\"display\":\"${DISPLAY}\",\"visualization_settings\":{}}")
  CARD_ID=$(printf '%s' "$CARD_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
  if [ -n "$CARD_ID" ] && [ -n "$DASH_ID" ]; then
    ROW=$((CARD_INDEX * 4))
    DASHCARD="{\"id\":-$((CARD_INDEX + 1)),\"card_id\":${CARD_ID},\"row\":${ROW},\"col\":0,\"size_x\":24,\"size_y\":4,\"series\":[],\"visualization_settings\":{},\"parameter_mappings\":[]}"
    if [ -z "$DASH_CARDS" ]; then
      DASH_CARDS="$DASHCARD"
    else
      DASH_CARDS="${DASH_CARDS},${DASHCARD}"
    fi
    CARD_INDEX=$((CARD_INDEX + 1))
    curl -fsS -X PUT "${METABASE_URL}/api/dashboard/${DASH_ID}/cards" \
      -H "Content-Type: application/json" \
      -H "X-Metabase-Session: ${SESSION_ID}" \
      -d "{\"cards\":[${DASH_CARDS}]}" >/dev/null || true
  fi
}

create_card "Total TTC par mois" "select to_char(invoice_date, 'YYYY-MM') as mois, sum(amount_ttc) as total_ttc from invoices where invoice_date is not null group by 1 order by 1"
create_card "Dépenses par fournisseur" "select coalesce(supplier_name, 'Fournisseur inconnu') as fournisseur, sum(amount_ttc) as total_ttc from invoices group by 1 order by 2 desc"
create_card "Factures récentes" "select invoice_date, supplier_name, invoice_number, amount_ttc, currency from invoices order by created_at desc limit 25"
create_card "Total année courante" "select extract(year from invoice_date) as annee, sum(amount_ttc) as total_ttc from invoices where invoice_date is not null group by 1 order by 1 desc"
create_card "Progression cumulée par année budgétaire" "with years as (select generate_series(extract(year from now())::int - 2, extract(year from now())::int + 2) as annee_budgetaire), months as (select generate_series(1, 12) as mois_num), monthly as (select extract(year from invoice_date)::int as annee_budgetaire, extract(month from invoice_date)::int as mois_num, sum(amount_ttc) as total_ttc from invoices where invoice_date is not null group by 1, 2) select y.annee_budgetaire, m.mois_num, to_char(make_date(y.annee_budgetaire, m.mois_num, 1), 'TMMonth') as mois, sum(coalesce(monthly.total_ttc, 0)) over (partition by y.annee_budgetaire order by m.mois_num rows between unbounded preceding and current row) as cumul_ttc from years y cross join months m left join monthly on monthly.annee_budgetaire = y.annee_budgetaire and monthly.mois_num = m.mois_num order by y.annee_budgetaire, m.mois_num" "line"

echo "Metabase configured: ${METABASE_URL} (${ADMIN_EMAIL} / ${ADMIN_PASSWORD})"
