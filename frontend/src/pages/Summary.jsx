import { Link, useSearchParams } from 'react-router-dom'
import { useApi, fmt, change } from '../lib'

export default function Summary({ version }) {
  const [params] = useSearchParams()
  const { data, error } = useApi(`/api/summary?version=${version}`)
  if (error) return <p className="text-red-700">{error.message}</p>
  if (!data) return <p className="text-slate-500">Loading…</p>
  const qs = params.toString() ? `?${params}` : ''

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-medium text-slate-900">Return summary</h1>
        <p className="text-sm text-slate-500">
          Version {version}. Compared with the 2024 return as filed. Flags follow the firm rule:
          change over {data.variance_rule.percent}% and over {fmt(data.variance_rule.amount)}.
        </p>
      </div>

      {Object.entries(data.headlines).map(([jur, items]) => (
        <section key={jur}>
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-500">{jur}</h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
            {items.map((h) => {
              const delta = change(h.value, h.prior)
              return (
                <Link key={h.key} to={`/line/${version}/${encodeURIComponent(h.key)}${qs}`}
                  className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 hover:ring-blue-300">
                  <div className="text-xs text-slate-500">{h.label}</div>
                  <div className="mt-1 text-xl font-medium tabular-nums text-slate-900">{fmt(h.value)}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {h.prior !== null ? <>2024 {fmt(h.prior)}</> : 'No 2024 equivalent'}
                    {delta !== null && h.flag && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-800">{delta > 0 ? '+' : ''}{fmt(delta)}</span>}
                  </div>
                  <div className="mt-1 font-mono text-[10px] text-slate-400">{h.key}</div>
                </Link>
              )
            })}
          </div>
        </section>
      ))}

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-slate-500">Review areas</h2>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
          {data.areas.map((a) => (
            <Link key={a.id} to={`/area/${a.id}${qs}`} className="rounded-lg p-3 ring-1 ring-slate-200 hover:ring-blue-300">
              <div className="font-medium text-slate-900">{a.name}</div>
              <div className="mt-1 flex gap-3 text-xs text-slate-500">
                <span>{a.lines} lines</span>
                <span>{Number(a.budget_hours)} h budget</span>
                {a.open_findings > 0 && <span className="text-amber-700">{a.open_findings} open findings</span>}
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
