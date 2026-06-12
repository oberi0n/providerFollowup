import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FileText, Upload, Wand2 } from 'lucide-react'
import './index.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8080'
const emptyInvoice = { supplierName: '', invoiceNumber: '', invoiceDate: '', amountHt: '', vatAmount: '', amountTtc: '', currency: 'EUR', category: '', status: 'RECEIVED', comment: '' }
const statuses = ['RECEIVED', 'TO_SIGN', 'SIGNED', 'SENT_TO_FINANCE', 'PAID', 'REJECTED']

function App() {
  const [invoices, setInvoices] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [selected, setSelected] = useState(null)
  const [form, setForm] = useState(emptyInvoice)
  const [file, setFile] = useState(null)
  const [ocrResult, setOcrResult] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => { refresh() }, [])
  async function refresh() {
    const [invoiceRes, dashRes] = await Promise.all([fetch(`${API}/api/invoices`), fetch(`${API}/api/dashboard`)])
    setInvoices(await invoiceRes.json())
    setDashboard(await dashRes.json())
  }

  function selectInvoice(invoice) {
    setSelected(invoice)
    setForm({ ...emptyInvoice, ...invoice, invoiceDate: invoice.invoiceDate || '' })
    setOcrResult(invoice.ocrRawText ? { rawText: invoice.ocrRawText, suggestions: JSON.parse(invoice.ocrSuggestionsJson || '{}') } : null)
    setMessage('')
  }

  async function saveInvoice(event) {
    event.preventDefault()
    const payload = normalizeForm(form)
    const res = await fetch(selected ? `${API}/api/invoices/${selected.id}` : `${API}/api/invoices`, {
      method: selected ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    })
    const saved = await res.json()
    setSelected(saved)
    setMessage('Facture enregistrée. Les suggestions OCR ne remplacent jamais automatiquement ces champs validés.')
    await refresh()
  }

  async function uploadAndOcr() {
    if (!selected?.id || !file) return setMessage('Créez la facture et choisissez un fichier avant OCR.')
    const body = new FormData(); body.append('file', file)
    await fetch(`${API}/api/invoices/${selected.id}/upload`, { method: 'POST', body })
    const result = await (await fetch(`${API}/api/invoices/${selected.id}/ocr`, { method: 'POST' })).json()
    setOcrResult(result)
    setMessage('OCR terminé. Vérifiez les suggestions puis copiez/validez manuellement les champs souhaités.')
    await refresh()
  }

  function applySuggestion(key, value) { setForm(current => ({ ...current, [key]: value ?? '' })) }
  const cards = useMemo(() => dashboard ? [
    ['Budget annuel', dashboard.annualBudget], ['Consommé', dashboard.consumed], ['Engagé non payé', dashboard.committedUnpaid], ['Reste disponible', dashboard.available]
  ] : [], [dashboard])

  return <main className="mx-auto max-w-7xl p-6 space-y-6">
    <header className="flex items-center justify-between"><div><h1 className="text-3xl font-bold">Provider Follow-up</h1><p className="text-slate-600">Suivi factures fournisseurs avec OCR local Tesseract (fra + eng).</p></div><button onClick={() => { setSelected(null); setForm(emptyInvoice); setOcrResult(null) }} className="rounded bg-blue-600 px-4 py-2 text-white">Nouvelle facture</button></header>
    {message && <div className="rounded border border-blue-200 bg-blue-50 p-3 text-blue-900">{message}</div>}
    <section className="grid grid-cols-1 gap-4 md:grid-cols-4">{cards.map(([label, value]) => <div key={label} className="rounded-xl bg-white p-4 shadow"><p className="text-sm text-slate-500">{label}</p><p className="text-2xl font-bold">{money(value)}</p></div>)}</section>
    <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="rounded-xl bg-white p-4 shadow lg:col-span-1"><h2 className="mb-3 flex items-center gap-2 text-xl font-semibold"><FileText size={20}/>Factures</h2><div className="space-y-2">{invoices.map(invoice => <button key={invoice.id} onClick={() => selectInvoice(invoice)} className={`w-full rounded border p-3 text-left hover:bg-slate-50 ${selected?.id === invoice.id ? 'border-blue-500 bg-blue-50' : 'border-slate-200'}`}><div className="font-semibold">{invoice.supplierName || 'Sans fournisseur'} · {money(invoice.amountTtc)}</div><div className="text-sm text-slate-500">{invoice.invoiceNumber || 'N° ?'} · {invoice.status}</div></button>)}</div></div>
      <form onSubmit={saveInvoice} className="rounded-xl bg-white p-4 shadow lg:col-span-2"><h2 className="mb-4 text-xl font-semibold">{selected ? `Facture #${selected.id}` : 'Nouvelle facture'}</h2><InvoiceFields form={form} setForm={setForm}/><div className="mt-4 flex gap-3"><button className="rounded bg-emerald-600 px-4 py-2 text-white">Valider / enregistrer</button></div>
        <div className="mt-6 rounded-lg border border-dashed p-4"><h3 className="mb-2 flex items-center gap-2 font-semibold"><Upload size={18}/>Upload & OCR</h3><input type="file" accept="image/png,image/jpeg,application/pdf" onChange={e => setFile(e.target.files?.[0])}/><button type="button" onClick={uploadAndOcr} className="ml-3 rounded bg-purple-600 px-3 py-2 text-white"><Wand2 className="inline" size={16}/> Lancer OCR</button></div>
        {ocrResult && <OcrPanel result={ocrResult} applySuggestion={applySuggestion}/>} </form>
    </section>
    {dashboard && <section className="grid grid-cols-1 gap-4 md:grid-cols-4"><Chart title="Par statut" data={dashboard.invoicesByStatus}/><Chart title="Par mois" data={dashboard.expensesByMonth} moneyValues/><Chart title="Par fournisseur" data={dashboard.expensesBySupplier} moneyValues/><Chart title="Par catégorie" data={dashboard.expensesByCategory} moneyValues/></section>}
  </main>
}

function InvoiceFields({ form, setForm }) { const update = e => setForm({ ...form, [e.target.name]: e.target.value }); return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
  {[['supplierName','Fournisseur'], ['invoiceNumber','N° facture'], ['invoiceDate','Date facture','date'], ['amountHt','Montant HT','number'], ['vatAmount','TVA','number'], ['amountTtc','Montant TTC','number'], ['currency','Devise'], ['category','Catégorie']].map(([name,label,type='text']) => <label key={name} className="text-sm font-medium">{label}<input name={name} type={type} step="0.01" value={form[name] ?? ''} onChange={update} className="mt-1 w-full rounded border p-2"/></label>)}
  <label className="text-sm font-medium">Statut<select name="status" value={form.status} onChange={update} className="mt-1 w-full rounded border p-2">{statuses.map(s => <option key={s}>{s}</option>)}</select></label><label className="text-sm font-medium md:col-span-2">Commentaire<textarea name="comment" value={form.comment ?? ''} onChange={update} className="mt-1 w-full rounded border p-2"/></label></div> }
function OcrPanel({ result, applySuggestion }) { const s = result.suggestions || {}; return <div className="mt-6 grid gap-4 md:grid-cols-2"><div className="rounded bg-slate-50 p-4"><h3 className="font-semibold">Suggestions OCR ({result.confidence || 'LOW'})</h3>{Object.entries(s).map(([k,v]) => <div key={k} className="mt-2 flex items-center justify-between gap-2 text-sm"><span>{k}: <b>{String(v ?? '')}</b></span><button type="button" onClick={() => applySuggestion(k, v)} className="rounded bg-slate-800 px-2 py-1 text-white">Copier</button></div>)}</div><div className="rounded bg-black p-4 text-green-200"><h3 className="mb-2 font-semibold text-white">Texte OCR brut (debug)</h3><pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{result.rawText}</pre></div></div> }
function Chart({ title, data, moneyValues }) { return <div className="rounded-xl bg-white p-4 shadow"><h3 className="font-semibold">{title}</h3>{Object.entries(data || {}).map(([k,v]) => <div key={k} className="mt-2 flex justify-between border-b pb-1 text-sm"><span>{k}</span><span>{moneyValues ? money(v) : v}</span></div>)}</div> }
function normalizeForm(form) { return Object.fromEntries(Object.entries(form).map(([k,v]) => [k, ['amountHt','vatAmount','amountTtc'].includes(k) && v !== '' ? Number(v) : (v === '' ? null : v)])) }
function money(value) { return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(value || 0)) }

createRoot(document.getElementById('root')).render(<App />)
