import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Keycloak from 'keycloak-js'
import { BarChart3, Calendar, Database, FileText, Trash2, Upload, Wand2 } from 'lucide-react'
import './index.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8080'
const MINIO_CONSOLE_URL = import.meta.env.VITE_MINIO_CONSOLE_URL || 'http://localhost:9001'
const METABASE_URL = import.meta.env.VITE_METABASE_URL || 'http://localhost:3001'
const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8081',
  realm: import.meta.env.VITE_KEYCLOAK_REALM || 'provider-followup',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'provider-followup-frontend',
})
const currentYear = new Date().getFullYear()
const emptyInvoice = {
  supplierName: '',
  invoiceNumber: '',
  invoiceDate: '',
  amountHt: '',
  vatAmount: '',
  amountTtc: '',
  currency: 'EUR',
  budgetType: '',
  comment: '',
}
const suggestionFields = ['supplierName', 'invoiceNumber', 'invoiceDate', 'amountHt', 'vatAmount', 'amountTtc', 'currency']

function App() {
  const [invoices, setInvoices] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [selected, setSelected] = useState(null)
  const [draftInvoiceId, setDraftInvoiceId] = useState(null)
  const [form, setForm] = useState(emptyInvoice)
  const [file, setFile] = useState(null)
  const [ocrResult, setOcrResult] = useState(null)
  const [message, setMessage] = useState('')
  const [loadingOcr, setLoadingOcr] = useState(false)
  const [fiscalYear, setFiscalYear] = useState(currentYear)
  const [opexBudget, setOpexBudget] = useState(80000)
  const [capexBudget, setCapexBudget] = useState(40000)
  const [authenticated, setAuthenticated] = useState(false)
  const [authReady, setAuthReady] = useState(false)
  const [userProfile, setUserProfile] = useState(null)

  useEffect(() => {
    keycloak.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false })
      .then(isAuthenticated => {
        setAuthenticated(isAuthenticated)
        setAuthReady(true)
        if (isAuthenticated) {
          keycloak.loadUserProfile().then(setUserProfile).catch(() => setUserProfile({ username: keycloak.tokenParsed?.preferred_username }))
        }
      })
      .catch(error => {
        setMessage(`Erreur Keycloak : ${error}`)
        setAuthReady(true)
      })
  }, [])

  useEffect(() => {
    if (authenticated) {
      refresh().catch(error => setMessage(`Erreur chargement : ${error.message}`))
    }
  }, [authenticated, fiscalYear, opexBudget, capexBudget])

  async function authFetch(url, options = {}) {
    await keycloak.updateToken(30).catch(() => keycloak.login().then(() => Promise.reject(new Error('Session Keycloak expirée'))))
    const headers = new Headers(options.headers || {})
    headers.set('Authorization', `Bearer ${keycloak.token}`)
    return fetch(url, { ...options, headers })
  }

  async function refresh() {
    const params = new URLSearchParams({ year: String(fiscalYear), opexBudget: String(opexBudget || 0), capexBudget: String(capexBudget || 0) })
    const [invoiceRes, dashRes] = await Promise.all([authFetch(`${API}/api/invoices`), authFetch(`${API}/api/dashboard?${params}`)])
    if (!invoiceRes.ok) throw new Error(await invoiceRes.text())
    if (!dashRes.ok) throw new Error(await dashRes.text())
    setInvoices(await invoiceRes.json())
    setDashboard(await dashRes.json())
  }

  function resetWorkflow(successMessage = '') {
    setSelected(null)
    setDraftInvoiceId(null)
    setForm(emptyInvoice)
    setFile(null)
    setOcrResult(null)
    setMessage(successMessage)
  }

  function selectInvoice(invoice) {
    setSelected(invoice)
    setDraftInvoiceId(null)
    const { category, status, ...editableInvoice } = invoice
    setForm({ ...emptyInvoice, ...editableInvoice, invoiceDate: invoice.invoiceDate || '' })
    setOcrResult(invoice.ocrRawText ? { rawText: invoice.ocrRawText, suggestions: JSON.parse(invoice.ocrSuggestionsJson || '{}') } : null)
    setFile(null)
    setMessage('')
  }

  async function persistInvoice(invoiceForm = form, invoiceId = selected?.id, draft = false) {
    const payload = normalizeForm(invoiceForm)
    const draftQuery = draft ? '?draft=true' : ''
    const res = await authFetch(invoiceId ? `${API}/api/invoices/${invoiceId}${draftQuery}` : `${API}/api/invoices${draftQuery}`, {
      method: invoiceId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  }

  async function saveInvoice(event) {
    event.preventDefault()
    try {
      await persistInvoice()
      setDraftInvoiceId(null)
      resetWorkflow('Facture enregistrée. Vous pouvez démarrer une nouvelle facture ou lancer un nouvel OCR.')
      await refresh()
    } catch (error) {
      setMessage(`Erreur enregistrement : ${error.message}`)
    }
  }

  async function uploadAndOcr() {
    if (!file) return setMessage('Choisissez un fichier JPG, PNG ou PDF avant de lancer l’OCR.')
    setLoadingOcr(true)
    setMessage('OCR en cours : création de la facture, upload du fichier puis extraction locale…')
    try {
      const invoice = await persistInvoice(form, selected?.id, true)
      setSelected(invoice)
      setDraftInvoiceId(invoice.id)
      const body = new FormData()
      body.append('file', file)

      const uploadRes = await authFetch(`${API}/api/invoices/${invoice.id}/upload`, { method: 'POST', body })
      if (!uploadRes.ok) throw new Error(await uploadRes.text())

      const ocrRes = await authFetch(`${API}/api/invoices/${invoice.id}/ocr`, { method: 'POST' })
      if (!ocrRes.ok) throw new Error(await ocrRes.text())
      const result = await ocrRes.json()
      const prefilled = prefilledForm(form, result.suggestions || {})

      setOcrResult(result)
      setForm(prefilled)
      const savedWithOcrDate = await persistInvoice(prefilled, invoice.id, true)
      setSelected(savedWithOcrDate)
      setMessage('OCR terminé : les champs vides ont été préremplis et le fichier a été rangé selon la date de facture détectée. Vérifiez/corrigez puis cliquez sur “Valider / enregistrer”.')
      await refresh()
    } catch (error) {
      setMessage(`Erreur OCR : ${error.message}`)
    } finally {
      setLoadingOcr(false)
    }
  }


  async function abandonCurrentDraft() {
    if (!draftInvoiceId || selected?.id !== draftInvoiceId) {
      resetWorkflow('Saisie abandonnée. Aucun fichier temporaire à supprimer.')
      return
    }
    try {
      const res = await authFetch(`${API}/api/invoices/${draftInvoiceId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      resetWorkflow('Saisie abandonnée : la facture brouillon et son fichier MinIO ont été supprimés.')
      await refresh()
    } catch (error) {
      setMessage(`Erreur abandon de saisie : ${error.message}`)
    }
  }

  async function startNewInvoice() {
    if (draftInvoiceId && selected?.id === draftInvoiceId) {
      await abandonCurrentDraft()
      return
    }
    resetWorkflow('Nouvelle facture prête.')
  }

  function applySuggestion(key, value) {
    setForm(current => ({ ...current, [key]: value ?? '' }))
  }

  const budgetYears = useMemo(() => Array.from({ length: 5 }, (_, index) => currentYear - 2 + index), [])
  const invoicesForYear = useMemo(() => invoices.filter(invoice => !invoice.invoiceDate || new Date(invoice.invoiceDate).getFullYear() === fiscalYear), [invoices, fiscalYear])
  const cards = useMemo(() => dashboard ? [
    ['OPEX consommé', dashboard.opexConsumed],
    ['OPEX restant', dashboard.opexAvailable],
    ['CAPEX consommé', dashboard.capexConsumed],
    ['CAPEX restant', dashboard.capexAvailable],
    ['Engagé non payé', dashboard.committedUnpaid],
  ] : [], [dashboard])

  if (!authReady) {
    return <main className="mx-auto max-w-3xl p-6"><div className="rounded-xl bg-white p-6 shadow">Connexion à Keycloak en cours…</div></main>
  }

  return <main className="mx-auto max-w-7xl p-6 space-y-6">
    <header className="rounded-2xl bg-white p-5 shadow">
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <nav className="flex w-fit flex-wrap items-center gap-1 rounded-2xl border border-slate-200 bg-slate-50 p-1 shadow-sm">
          <a href={MINIO_CONSOLE_URL} target="_blank" rel="noreferrer" className="rounded-xl px-4 py-2 text-sm font-bold text-blue-700 transition hover:bg-white hover:shadow-sm"><Database className="inline" size={16}/> MinIO</a>
          <a href={METABASE_URL} target="_blank" rel="noreferrer" className="rounded-xl px-4 py-2 text-sm font-bold text-purple-700 transition hover:bg-white hover:shadow-sm"><BarChart3 className="inline" size={16}/> Metabase</a>
        </nav>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-slate-100 px-3 py-2 text-sm text-slate-700">Connecté : {userProfile?.username || userProfile?.email || 'admin'}</span>
          <button onClick={startNewInvoice} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white">Nouvelle facture</button>
          <button onClick={() => keycloak.logout({ redirectUri: window.location.origin })} className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700">Déconnexion</button>
        </div>
      </div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-bold">Provider Follow-up</h1>
          <p className="text-slate-600">Suivi factures fournisseurs avec OCR OCR.space et fallback local.</p>
        </div>
      </div>
    </header>

    {message && <div className="rounded border border-blue-200 bg-blue-50 p-3 text-blue-900">{message}</div>}

    <section>
      <form onSubmit={saveInvoice} className="rounded-xl bg-white p-4 shadow">
        <h2 className="mb-2 text-xl font-semibold">{selected ? `Facture #${selected.id}` : 'Formulaire facture'}</h2>
        <div className="mb-5 rounded-xl border border-purple-100 bg-purple-50 p-4">
          <h3 className="mb-2 flex items-center gap-2 text-lg font-semibold text-purple-950"><Upload size={20}/>OCR facture</h3>
          <p className="mb-4 text-sm text-purple-900">1. Sélectionnez l’image/PDF, lancez l’OCR, puis validez ou corrigez les champs du formulaire ci-dessous.</p>
          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <input type="file" accept="image/png,image/jpeg,application/pdf" onChange={e => setFile(e.target.files?.[0] || null)} className="rounded border bg-white p-2"/>
            <button type="button" disabled={loadingOcr} onClick={uploadAndOcr} className="rounded bg-purple-600 px-4 py-2 text-white disabled:cursor-not-allowed disabled:bg-purple-300"><Wand2 className="inline" size={16}/> {loadingOcr ? 'OCR en cours…' : 'Lancer OCR et préremplir'}</button>
          </div>
          {ocrResult && <OcrPanel result={ocrResult} applySuggestion={applySuggestion}/>}
        </div>
        <p className="mb-4 text-sm text-slate-600">2. Les champs fournisseur, date, montant TTC et CAPEX/OPEX sont obligatoires avant validation.</p>
        <InvoiceFields form={form} setForm={setForm}/>
        <div className="mt-4 flex flex-wrap gap-3"><button className="rounded bg-emerald-600 px-4 py-2 text-white">Valider / enregistrer</button>{draftInvoiceId && selected?.id === draftInvoiceId && <button type="button" onClick={abandonCurrentDraft} className="rounded border border-red-200 bg-red-50 px-4 py-2 font-semibold text-red-700"><Trash2 className="inline" size={16}/> Abandonner et supprimer le fichier</button>}</div>
      </form>
    </section>

    <section className="rounded-xl bg-white p-4 shadow">
      <div className="mb-3 flex items-center gap-2 text-xl font-semibold"><Calendar size={20}/>Année budgétaire</div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="mb-2 text-sm text-slate-600">3. Paramétrez les lignes OPEX/CAPEX, puis consultez la synthèse globale.</p>
          <div className="flex flex-wrap gap-2">
            {budgetYears.map(year => <button key={year} type="button" onClick={() => setFiscalYear(year)} className={`rounded-full px-4 py-2 text-sm font-semibold ${fiscalYear === year ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>{year}</button>)}
            <input type="number" value={fiscalYear} onChange={e => setFiscalYear(Number(e.target.value || currentYear))} className="w-28 rounded-full border px-4 py-2 text-sm" aria-label="Année budgétaire personnalisée"/>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium">Budget OPEX
            <input type="number" step="0.01" value={opexBudget} onChange={e => setOpexBudget(Number(e.target.value || 0))} className="mt-1 w-full rounded border p-2 lg:w-44"/>
          </label>
          <label className="text-sm font-medium">Budget CAPEX
            <input type="number" step="0.01" value={capexBudget} onChange={e => setCapexBudget(Number(e.target.value || 0))} className="mt-1 w-full rounded border p-2 lg:w-44"/>
          </label>
        </div>
      </div>
    </section>

    {dashboard && <section className="rounded-xl bg-white p-4 shadow">
      <h2 className="mb-3 text-xl font-semibold">Synthèse globale CAPEX + OPEX</h2>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded bg-slate-50 p-3"><p className="text-sm text-slate-500">Budget global</p><p className="text-2xl font-bold">{money(dashboard.annualBudget)}</p></div>
        <div className="rounded bg-slate-50 p-3"><p className="text-sm text-slate-500">Consommé global</p><p className="text-2xl font-bold">{money(dashboard.consumed)}</p></div>
        <div className="rounded bg-slate-50 p-3"><p className="text-sm text-slate-500">Reste global</p><p className="text-2xl font-bold">{money(dashboard.available)}</p></div>
      </div>
    </section>}

    <section className="grid grid-cols-1 gap-4 md:grid-cols-5">
      {cards.map(([label, value]) => <div key={label} className="rounded-xl bg-white p-4 shadow"><p className="text-sm text-slate-500">{label}</p><p className="text-2xl font-bold">{money(value)}</p></div>)}
    </section>

    {dashboard && <section className="grid grid-cols-1 gap-4 md:grid-cols-2"><Chart title="Par mois" data={dashboard.expensesByMonth} moneyValues/><Chart title="Par fournisseur" data={dashboard.expensesBySupplier} moneyValues/></section>}

    <section className="overflow-hidden rounded-xl bg-white shadow">
      <div className="border-b p-4">
        <h2 className="flex items-center gap-2 text-xl font-semibold"><FileText size={20}/>Factures {fiscalYear}</h2>
        <p className="text-sm text-slate-500">4. Liste des factures de l’année sélectionnée. Cliquez une ligne pour la reprendre dans le formulaire.</p>
      </div>
      <div className="max-h-[520px] overflow-auto">
        {invoicesForYear.length === 0 && <p className="p-4 text-sm text-slate-500">Aucune facture pour cette année.</p>}
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Date</th><th className="p-3">Fournisseur</th><th className="p-3">Budget</th><th className="p-3 text-right">TTC</th></tr></thead>
          <tbody>{invoicesForYear.map(invoice => <tr key={invoice.id} onClick={() => selectInvoice(invoice)} className={`cursor-pointer border-t hover:bg-blue-50 ${selected?.id === invoice.id ? 'bg-blue-50' : ''}`}><td className="p-3 whitespace-nowrap">{invoice.invoiceDate || '—'}</td><td className="p-3"><div className="font-semibold text-slate-900">{invoice.supplierName || 'Sans fournisseur'}</div><div className="text-xs text-slate-500">{invoice.invoiceNumber || 'N° ?'}</div></td><td className="p-3"><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold">{invoice.budgetType || '—'}</span></td><td className="p-3 text-right font-semibold">{money(invoice.amountTtc)}</td></tr>)}</tbody>
        </table>
      </div>
    </section>
  </main>
}

function InvoiceFields({ form, setForm }) {
  const update = e => setForm({ ...form, [e.target.name]: e.target.value })
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
    {[
      ['supplierName','Fournisseur'],
      ['invoiceNumber','N° facture'],
      ['invoiceDate','Date facture','date'],
      ['amountHt','Montant HT','number'],
      ['vatAmount','TVA','number'],
      ['amountTtc','Montant TTC','number'],
      ['currency','Devise'],
    ].map(([name,label,type='text']) => <label key={name} className="text-sm font-medium">{label}{['supplierName','invoiceDate','amountTtc'].includes(name) && <span className="text-red-600"> *</span>}<input name={name} type={type} step="0.01" required={['supplierName','invoiceDate','amountTtc'].includes(name)} value={form[name] ?? ''} onChange={update} className="mt-1 w-full rounded border p-2"/></label>)}
    <label className="text-sm font-medium">Budget <span className="text-red-600">*</span><select name="budgetType" required value={form.budgetType ?? ''} onChange={update} className="mt-1 w-full rounded border p-2"><option value="">Sélectionner</option><option value="OPEX">OPEX</option><option value="CAPEX">CAPEX</option></select></label>
    <label className="text-sm font-medium md:col-span-2">Commentaire<textarea name="comment" value={form.comment ?? ''} onChange={update} className="mt-1 w-full rounded border p-2"/></label>
  </div>
}

function OcrPanel({ result, applySuggestion }) {
  const s = result.suggestions || {}
  return <div className="mt-6 grid gap-4 md:grid-cols-2">
    <div className="rounded bg-slate-50 p-4">
      <h3 className="font-semibold">Suggestions OCR ({result.confidence || 'LOW'})</h3>
      {Object.entries(s).map(([k,v]) => <div key={k} className="mt-2 flex items-center justify-between gap-2 text-sm"><span>{k}: <b>{String(v ?? '')}</b></span><button type="button" onClick={() => applySuggestion(k, v)} className="rounded bg-slate-800 px-2 py-1 text-white">Remplacer</button></div>)}
    </div>
    <div className="rounded bg-black p-4 text-green-200">
      <h3 className="mb-2 font-semibold text-white">Texte OCR brut (debug)</h3>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{result.rawText}</pre>
    </div>
  </div>
}

function Chart({ title, data, moneyValues }) {
  return <div className="rounded-xl bg-white p-4 shadow"><h3 className="font-semibold">{title}</h3>{Object.entries(data || {}).map(([k,v]) => <div key={k} className="mt-2 flex justify-between border-b pb-1 text-sm"><span>{k}</span><span>{moneyValues ? money(v) : v}</span></div>)}</div>
}

function prefilledForm(current, suggestions) {
  const next = { ...current }
  for (const key of suggestionFields) {
    const value = suggestions[key]
    if (value !== undefined && value !== null && value !== '' && (next[key] === undefined || next[key] === null || next[key] === '')) {
      next[key] = String(value)
    }
  }
  return next
}

function normalizeForm(form) {
  return Object.fromEntries(Object.entries(form)
    .filter(([k]) => k !== 'category' && k !== 'status')
    .map(([k,v]) => [k, ['amountHt','vatAmount','amountTtc'].includes(k) && v !== '' ? Number(v) : (v === '' ? null : v)]))
}

function money(value) {
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(value || 0))
}

createRoot(document.getElementById('root')).render(<App />)
