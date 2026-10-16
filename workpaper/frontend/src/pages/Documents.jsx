import { useSearchParams } from 'react-router-dom'
import { useApi, STATUS_LABEL } from '../lib'

// Completeness view: every document, and where it landed or why it didn't.
// "Needs explanation" comes first: an unused tax document is either
// irrelevant (say why) or something the return is missing.
const ORDER = ['not_used', 'used', 'duplicate', 'superseded', 'not_extracted', 'supporting']

export default function Documents({ version }) {
  const [params, setParams] = useSearchParams()
  const { data, error } = useApi(`/api/documents?version=${version}`)
  if (error) return <p className="text-red-700">{error.message}</p>
  if (!data) return <p className="text-slate-500">Loading…</p>
  const open = (id) => { const p = new URLSearchParams(params); p.set('doc', id); p.delete('ev'); p.delete('page'); setParams(p) }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-medium text-slate-900">Documents</h1>
        <p className="text-sm text-slate-500">{data.documents.length} documents. Every one is accounted for: used, or a reason it isn't.</p>
      </div>
      {ORDER.map((status) => {
        const docs = data.documents.filter((d) => d.status === status)
        if (!docs.length) return null
        return (
          <section key={status}>
            <h2 className={`text-sm font-medium ${status === 'not_used' ? 'text-amber-800' : 'text-slate-700'}`}>{STATUS_LABEL[status]} ({docs.length})</h2>
            <table className="mt-1 w-full text-sm">
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className={`border-t border-slate-100 ${params.get('doc') === d.id ? 'bg-amber-50' : ''}`}>
                    <td className="w-12 py-1 font-mono text-xs text-slate-500">{d.id}</td>
                    <td className="py-1">
                      <button onClick={() => open(d.id)} className="text-left text-blue-700 hover:underline">{d.title}</button>
                      {status !== 'used' && <div className="text-xs text-slate-500">{d.reason}</div>}
                    </td>
                    <td className="py-1 text-right text-xs text-slate-500">{d.values} values</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
