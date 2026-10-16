import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useApi, fmt } from '../lib'

function LineList({ title, items, version, qs, empty }) {
  return (
    <section className="rounded-lg ring-1 ring-slate-200 p-3">
      <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</h2>
      {items.length === 0 && <p className="mt-1 text-sm text-slate-500">{empty}</p>}
      <ul className="mt-1 space-y-0.5 text-sm">
        {items.map((i) => (
          <li key={i.key} className="flex justify-between gap-3">
            <Link className="truncate text-blue-700 hover:underline" to={`/line/${version}/${encodeURIComponent(i.key)}${qs}`}>
              {i.label || i.key} <span className="font-mono text-[10px] text-slate-400">{i.key}</span>
            </Link>
            <span className="shrink-0 tabular-nums">{fmt(i.value)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function Line({ version }) {
  const { key } = useParams()
  const [params, setParams] = useSearchParams()
  const { data, error } = useApi(`/api/lines/${version}/${encodeURIComponent(key)}`)
  if (error) return <p className="text-red-700">{error.message}</p>
  if (!data || data.line.key !== key) return <p className="text-slate-500">Loading…</p>
  const qs = params.toString() ? `?${params}` : ''
  const l = data.line
  const openDoc = (e) => {
    const p = new URLSearchParams(params)
    p.set('doc', e.document_id); p.set('page', e.page); p.set('ev', e.ev_id)
    setParams(p)
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs text-slate-500">
          <Link to={`/${qs}`} className="hover:underline">Summary</Link>
          {l.area_id && <> › <Link to={`/area/${l.area_id}${qs}`} className="hover:underline">{l.area_id.replaceAll('_', ' ')}</Link></>}
          {' '}› <span className="font-mono">{l.key}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-4">
          <h1 className="text-xl font-medium text-slate-900">{l.label || l.key}</h1>
          <span className="text-2xl font-medium tabular-nums">{fmt(l.value, { cents: l.form === 'F8949' })}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
          {data.history.map((h) => (
            <Link key={h.version} to={`/line/${h.version}/${encodeURIComponent(key)}${qs}`}
              className={`rounded px-1.5 py-0.5 ring-1 ${h.version === version ? 'bg-slate-800 text-white ring-slate-800' : 'ring-slate-200 hover:ring-slate-400'}`}>
              {h.version} {fmt(h.value)}
            </Link>
          ))}
        </div>
        {l.rule && <p className="mt-2 text-xs text-slate-500">Engine rule <span className="font-mono">{l.rule}</span> · {l.jurisdiction}</p>}
        {l.note && <p className="mt-1 rounded bg-slate-50 px-2 py-1 text-sm text-slate-700">Engine note: {l.note}</p>}
      </div>

      {data.findings.length > 0 && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <h2 className="text-sm font-medium text-amber-900">Open questions on this number</h2>
          <ul className="mt-1 space-y-0.5 text-sm">
            {data.findings.map((f) => (
              <li key={f.id}><Link to={`/findings${qs}#${f.id}`} className="text-amber-900 hover:underline"><span className="font-mono text-xs">{f.id}</span> {f.title}</Link></li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <LineList title="Built from" items={data.inputs} version={version} qs={qs} empty="Not built from other lines: see the evidence below." />
        <LineList title="Feeds into" items={data.used_by} version={version} qs={qs} empty="Nothing uses this line." />
      </div>

      <section className="rounded-lg ring-1 ring-slate-200 p-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">Evidence from documents</h2>
        {data.evidence.length === 0 && <p className="mt-1 text-sm text-slate-500">No extracted values feed this line directly.</p>}
        <table className="mt-1 w-full text-sm">
          <tbody>
            {data.evidence.map((e) => (
              <tr key={e.ev_id} className={`border-t border-slate-100 ${params.get('ev') === e.ev_id ? 'bg-amber-50' : ''}`}>
                <td className="py-1 pr-2">
                  <button onClick={() => openDoc(e)} className="text-left text-blue-700 hover:underline">{e.document_id} · {e.label}</button>
                  <div className="text-xs text-slate-500">{e.document_title} · page {e.page} · <span className="font-mono">{e.field}</span></div>
                </td>
                <td className="py-1 text-right tabular-nums">{typeof e.value === 'number' ? fmt(e.value, { cents: true }) : String(e.value)}</td>
                <td className={`py-1 pl-3 text-right text-xs tabular-nums ${e.confidence < 0.9 ? 'text-red-600' : 'text-slate-500'}`}>{e.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {data.other_sources.length > 0 && (
        <section className="rounded-lg ring-1 ring-slate-200 p-3">
          <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500">Other sources</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {data.other_sources.map((s) => (
              <li key={s.ref}>
                {s.link
                  ? <Link className="text-blue-700 hover:underline" to={`/line/${s.link.version}/${encodeURIComponent(s.link.key)}${qs}`}>{s.title}</Link>
                  : <span className="text-slate-800">{s.title}</span>}
                {s.detail !== null && s.detail !== undefined && <span className="text-slate-600">: {typeof s.detail === 'number' ? fmt(s.detail) : String(s.detail)}</span>}
                <div className="font-mono text-[10px] text-slate-400">{s.ref}</div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
