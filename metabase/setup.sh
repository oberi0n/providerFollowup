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
    -d "{\"token\":\"${SETUP_TOKEN}\",\"user\":{\"first_name\":\"Provider\",\"last_name\":\"Admin\",\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"},\"prefs\":{\"site_name\":\"Provider Follow-up\",\"site_locale\":\"fr\"},\"database\":null}")
  SESSION_ID=$(printf '%s' "$SETUP_RESPONSE" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
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
    -d "{\"engine\":\"postgres\",\"name\":\"Provider Follow-up PostgreSQL\",\"details\":{\"host\":\"${DB_HOST}\",\"port\":${DB_PORT},\"dbname\":\"${DB_NAME}\",\"user\":\"${DB_USER}\",\"password\":\"${DB_PASSWORD}\",\"ssl\":false}}")
  DB_ID=$(printf '%s' "$DB_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
fi

DASH_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/dashboard" \
  -H "Content-Type: application/json" \
  -H "X-Metabase-Session: ${SESSION_ID}" \
  -d '{"name":"Provider Follow-up - Budget invoices","description":"Dashboard auto-configured by docker compose."}')
DASH_ID=$(printf '%s' "$DASH_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')

create_card() {
  NAME="$1"
  SQL="$2"
  CARD_RESPONSE=$(curl -fsS -X POST "${METABASE_URL}/api/card" \
    -H "Content-Type: application/json" \
    -H "X-Metabase-Session: ${SESSION_ID}" \
    -d "{\"name\":\"${NAME}\",\"dataset_query\":{\"database\":${DB_ID},\"type\":\"native\",\"native\":{\"query\":\"${SQL}\"}},\"display\":\"table\",\"visualization_settings\":{}}")
  CARD_ID=$(printf '%s' "$CARD_RESPONSE" | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p')
  if [ -n "$CARD_ID" ] && [ -n "$DASH_ID" ]; then
    curl -fsS -X POST "${METABASE_URL}/api/dashboard/${DASH_ID}/cards" \
      -H "Content-Type: application/json" \
      -H "X-Metabase-Session: ${SESSION_ID}" \
      -d "{\"cardId\":${CARD_ID}}" >/dev/null || true
  fi
}

create_card "Total TTC par mois" "select to_char(invoice_date, 'YYYY-MM') as mois, sum(amount_ttc) as total_ttc from invoices where invoice_date is not null group by 1 order by 1"
create_card "Dépenses par fournisseur" "select coalesce(supplier_name, 'Fournisseur inconnu') as fournisseur, sum(amount_ttc) as total_ttc from invoices group by 1 order by 2 desc"
create_card "Factures récentes" "select invoice_date, supplier_name, invoice_number, amount_ttc, currency from invoices order by created_at desc limit 25"
create_card "Total année courante" "select extract(year from invoice_date) as annee, sum(amount_ttc) as total_ttc from invoices where invoice_date is not null group by 1 order by 1 desc"

echo "Metabase configured: ${METABASE_URL} (${ADMIN_EMAIL} / ${ADMIN_PASSWORD})"
