import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useApi, fmt } from '../lib'

// Form 8949 has hundreds of lots: group them by box, show box totals,
// and float lots with findings to the top so the review isn't swamped.
function groupLines(lines) {
  const groups = []
  const byKey = {}
  for (const l of lines) {
    const id = l.form === 'F8949' ? `F8949 box ${l.key.split('.')[1]}` : l.form
    if (!byKey[id]) { byKey[id] = { id, lines: [], large: l.form === 'F8949' }; groups.push(byKey[id]) }
    byKey[id].lines.push(l)
  }
  for (const g of groups) {
    if (g.large) {
      g.total = g.lines.find((l) => l.key.endsWith('.total'))
      g.lines = g.lines.filter((l) => !l.key.endsWith('.total'))
        .sort((a, b) => b.findings - a.findings)
    }
  }
  return groups
}

function LineRow({ l, version, qs }) {
  return (
    <tr className="border-t border-slate-100">
      <td className="py-1 pr-2">
        <Link className="text-blue-700 hover:underline" to={`/line/${version}/${encodeURIComponent(l.key)}${qs}`}>{l.label || l.key}</Link>
        <span className="ml-2 font-mono text-[10px] text-slate-400">{l.key}</span>
        {l.findings > 0 && <span className="ml-2 rounded bg-amber-100 px-1 text-[11px] text-amber-800">{l.findings} finding{l.findings > 1 ? 's' : ''}</span>}
      </td>
      <td className="py-1 text-right tabular-nums">{fmt(l.value, { cents: l.form === 'F8949' })}</td>
      <td className="py-1 pl-3 text-right tabular-nums text-slate-500">
        {l.prior !== null ? fmt(l.prior) : ''}
        {l.flag && <span className="ml-1 text-amber-700" title="Change over the firm's variance threshold">▲</span>}
      </td>
    </tr>
  )
}

export default function Area({ version }) {
  const { id } = useParams()
  const [params] = useSearchParams()
  const [open, setOpen] = useState({})
  const { data, error } = useApi(`/api/areas/${id}?version=${version}`)
  if (error) return <p className="text-red-700">{error.message}</p>
  if (!data || data.area.id !== id) return <p className="text-slate-500">Loading…</p>
  const qs = params.toString() ? `?${params}` : ''
  const groups = groupLines(data.lines)

  return (
    <div className="space-y-5">
      <div>
        <div className="text-xs text-slate-500"><Link to={`/${qs}`} className="hover:underline">Summary</Link> › Area</div>
        <h1 className="text-xl font-medium text-slate-900">{data.area.name}</h1>
        <p className="text-sm text-slate-500">{data.lines.length} lines · budget {Number(data.area.budget_hours)} h</p>
      </div>

      {data.findings.length > 0 && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <h2 className="text-sm font-medium text-amber-900">Findings in this area</h2>
          <ul className="mt-1 space-y-0.5 text-sm">
            {data.findings.map((f) => (
              <li key={f.id} className="flex justify-between gap-3">
                <Link to={`/findings${qs}#${f.id}`} className="text-amber-900 hover:underline"><span className="font-mono text-xs">{f.id}</span> {f.title}</Link>
                <span className="shrink-0 tabular-nums text-xs text-amber-800">{f.est_federal ? `${f.est_federal > 0 ? '+' : ''}${fmt(Number(f.est_federal))} fed` : ''}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.lines.length === 0 && <p className="text-sm text-slate-500">No return lines map to this area. It holds time and sign-offs only.</p>}

      {groups.map((g) => {
        const collapsed = g.large && !open[g.id]
        const shown = collapsed ? g.lines.filter((l) => l.findings > 0) : g.lines
        return (
          <section key={g.id}>
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm font-medium text-slate-700">{g.id}</h2>
              {g.large && (
                <button className="text-xs text-blue-700 hover:underline" onClick={() => setOpen({ ...open, [g.id]: !open[g.id] })}>
                  {collapsed ? `Show all ${g.lines.length} lots` : 'Collapse'}
                </button>
              )}
            </div>
            {g.total && <div className="mt-1 text-xs text-slate-500">{g.total.label}: <span className="tabular-nums text-slate-800">{fmt(g.total.value)}</span> gain or (loss)</div>}
            <table className="mt-1 w-full text-sm">
              <tbody>{shown.map((l) => <LineRow key={l.key} l={l} version={version} qs={qs} />)}</tbody>
            </table>
            {collapsed && shown.length === 0 && <p className="text-xs text-slate-500">No lots with findings. {g.lines.length} lots hidden.</p>}
          </section>
        )
      })}
    </div>
  )
}
