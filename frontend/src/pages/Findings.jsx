import { Link, useSearchParams } from 'react-router-dom'
import { useApi, fmt, parseRef } from '../lib'

function Effect({ value, label }) {
  if (!value || Number(value) === 0) return null
  const n = Number(value)
  return <span className={`tabular-nums ${n > 0 ? 'text-red-700' : 'text-emerald-700'}`}>{n > 0 ? '+' : ''}{fmt(n)} {label}</span>
}

export default function Findings() {
  const [params, setParams] = useSearchParams()
  const { data, error } = useApi('/api/findings')
  if (error) return <p className="text-red-700">{error.message}</p>
  if (!data) return <p className="text-slate-500">Loading…</p>
  const qs = params.toString() ? `?${params}` : ''
  const openDoc = (doc, page, ev) => {
    const p = new URLSearchParams(params)
    p.set('doc', doc)
    // Opening by value: let the panel jump to that value's own page.
    page ? p.set('page', page) : p.delete('page')
    ev ? p.set('ev', ev) : p.delete('ev')
    setParams(p)
  }

  const refLink = (ref) => {
    const r = parseRef(ref)
    const cls = 'rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] hover:bg-blue-50 hover:text-blue-700'
    if (r.kind === 'line') return <Link key={ref} className={cls} to={`/line/${r.version}/${encodeURIComponent(r.key)}${qs}`}>{r.key}</Link>
    if (r.kind === 'doc') return <button key={ref} className={cls} onClick={() => openDoc(r.doc, r.page)}>{r.doc} p{r.page}</button>
    if (r.kind === 'ev' && data.ev_documents[r.ev]) return <button key={ref} className={cls} onClick={() => openDoc(data.ev_documents[r.ev], null, r.ev)}>{r.ev}</button>
    return <span key={ref} className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500">{ref}</span>
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-medium text-slate-900">Findings</h1>
        <p className="text-sm text-slate-500">
          Checks that don't trust the engine. Effects are estimates (change × the engine's per-dollar rates);
          positive means more tax.
        </p>
      </div>
      <ul className="space-y-3">
        {data.findings.map((f) => (
          <li key={f.id} id={f.id} className="rounded-lg p-3 ring-1 ring-slate-200 target:ring-2 target:ring-amber-400">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-medium text-slate-900"><span className="mr-2 font-mono text-xs text-slate-500">{f.id}</span>{f.title}</h2>
              <div className="flex gap-3 text-sm"><Effect value={f.est_federal} label="fed" /><Effect value={f.est_ca} label="CA" /></div>
            </div>
            <p className="mt-1 text-sm text-slate-700">{f.detail}</p>
            <div className="mt-2 flex flex-wrap gap-1">{f.evidence_refs.map(refLink)}</div>
            <div className="mt-2 text-xs text-slate-500">
              Check: <span className="font-mono">{f.check_id}</span> · found by <span className="font-mono">{f.found_by}</span> · {f.status}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
