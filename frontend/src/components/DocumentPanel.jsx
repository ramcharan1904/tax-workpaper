// Right-hand evidence panel. Driven by the URL (?doc=D08&page=1&ev=ev-0016)
// so any view of the evidence is a shareable link.
import { Link, useSearchParams } from 'react-router-dom'
import { useApi, fmt, STATUS_LABEL } from '../lib'
import PageView from './PageView'

const STATUS_STYLE = {
  used: 'bg-emerald-50 text-emerald-700',
  not_used: 'bg-amber-50 text-amber-800',
  duplicate: 'bg-slate-100 text-slate-700',
  superseded: 'bg-slate-100 text-slate-700',
  not_extracted: 'bg-slate-100 text-slate-700',
  supporting: 'bg-slate-100 text-slate-600',
}

export default function DocumentPanel({ version }) {
  const [params, setParams] = useSearchParams()
  const docId = params.get('doc')
  const evId = params.get('ev')
  const { data, error } = useApi(docId ? `/api/documents/${docId}?version=${version}` : null)
  if (!docId) return null

  const close = () => {
    const p = new URLSearchParams(params)
    p.delete('doc'); p.delete('page'); p.delete('ev')
    setParams(p)
  }
  const pick = (id, page) => {
    const p = new URLSearchParams(params)
    p.set('ev', id)
    if (page) p.set('page', page)
    setParams(p)
  }

  if (error) return <aside className="w-[420px] shrink-0 border-l border-slate-200 p-4 text-red-700">{String(error.message)}</aside>
  if (!data || data.document.id !== docId) return <aside className="w-[420px] shrink-0 border-l border-slate-200 p-4 text-slate-500">Loading {docId}…</aside>

  const active = data.values.find((v) => v.id === evId)
  const pageNo = Number(params.get('page')) || active?.page || 1
  const page = data.pages.find((p) => p.page === pageNo) || data.pages[0]
  const pageValues = data.values.filter((v) => v.page === page.page)
  const d = data.document

  return (
    <aside className="w-[420px] shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs text-slate-500">{d.id} · received {d.received_at.slice(0, 10)}</div>
          <h2 className="font-medium text-slate-900">{d.title}</h2>
        </div>
        <button onClick={close} className="rounded px-2 text-slate-500 hover:bg-slate-200" aria-label="Close document">✕</button>
      </div>

      <div className={`mt-2 rounded px-2 py-1 text-xs ${STATUS_STYLE[data.status]}`}>
        <span className="font-medium">{STATUS_LABEL[data.status]}:</span> {data.reason}
      </div>

      {data.pages.length > 1 && (
        <div className="mt-3 flex flex-wrap gap-1 text-xs">
          {data.pages.map((p) => (
            <button key={p.page} onClick={() => { const q = new URLSearchParams(params); q.set('page', p.page); q.delete('ev'); setParams(q) }}
              className={`rounded px-2 py-0.5 ${p.page === page.page ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>
              p{p.page}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3">
        <PageView
          text={page.printed_content}
          highlights={pageValues.map((v) => ({ id: v.id, text: v.text_as_read }))}
          activeId={evId}
          onPick={(id) => pick(id)}
        />
      </div>

      {active && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm">
          <div className="font-medium text-slate-900">{active.label}</div>
          <div className="mt-1 grid grid-cols-[90px_1fr] gap-y-0.5 text-xs text-slate-700">
            <span className="text-slate-500">Value</span><span>{typeof active.value === 'number' ? fmt(active.value, { cents: true }) : String(active.value ?? '—')}</span>
            <span className="text-slate-500">Read as</span><span className="font-mono">{active.text_as_read || '(nothing printed)'}</span>
            <span className="text-slate-500">Field</span><span className="font-mono">{active.field}</span>
            <span className="text-slate-500">Confidence</span><span>{active.confidence.toFixed(2)}</span>
            <span className="text-slate-500">Value ID</span><span className="font-mono">{active.id}</span>
          </div>
        </div>
      )}

      <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-500">Landed on</h3>
      {data.landed_on.length === 0 && <p className="mt-1 text-sm text-slate-500">No line in this version.</p>}
      <ul className="mt-1 space-y-1 text-sm">
        {data.landed_on.slice(0, 40).map((l) => (
          <li key={l.key} className="flex justify-between gap-2">
            <Link className="truncate text-blue-700 hover:underline" to={`/line/${version}/${encodeURIComponent(l.key)}?${params}`}>
              {l.label || l.key} <span className="text-xs text-slate-400">{l.key}</span>
            </Link>
            <span className="shrink-0 tabular-nums">{fmt(l.value)}</span>
          </li>
        ))}
        {data.landed_on.length > 40 && <li className="text-xs text-slate-500">and {data.landed_on.length - 40} more</li>}
      </ul>

      {data.findings.length > 0 && (
        <>
          <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-500">Findings</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {data.findings.map((f) => (
              <li key={f.id}><Link className="text-amber-800 hover:underline" to={`/findings?${params}#${f.id}`}>{f.id}</Link> {f.title}</li>
            ))}
          </ul>
        </>
      )}

      <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-500">Values on this page ({pageValues.length})</h3>
      <ul className="mt-1 max-h-64 space-y-0.5 overflow-y-auto text-xs">
        {pageValues.map((v) => (
          <li key={v.id}>
            <button onClick={() => pick(v.id, v.page)} className={`flex w-full justify-between gap-2 rounded px-1 text-left hover:bg-white ${v.id === evId ? 'bg-white ring-1 ring-amber-300' : ''}`}>
              <span className="truncate">{v.label}</span>
              <span className={`shrink-0 tabular-nums ${v.confidence < 0.9 ? 'text-red-600' : 'text-slate-500'}`}>{v.confidence.toFixed(2)}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  )
}
