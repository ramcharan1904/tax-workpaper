import { useEffect, useState } from 'react'

// Skeleton page: proves browser -> FastAPI -> Postgres -> loaded packet.
export default function App() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e) => setError(e.message))
  }, [])

  return (
    <main className="mx-auto max-w-2xl p-8 font-sans text-slate-800">
      <h1 className="text-2xl font-medium">Miraflores Workpaper</h1>
      <p className="mt-1 text-slate-500">Okafor-Lindqvist household, tax year 2025</p>

      {error && <p className="mt-6 rounded bg-red-50 p-3 text-red-700">Not connected: {error}</p>}
      {!health && !error && <p className="mt-6 text-slate-500">Connecting…</p>}

      {health && (
        <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border border-slate-200 p-4">
          <dt className="text-slate-500">Database</dt><dd>connected, {health.tables} tables</dd>
          <dt className="text-slate-500">Documents</dt><dd>{health.documents}</dd>
          <dt className="text-slate-500">Extracted values</dt><dd>{health.extracted_values.toLocaleString()}</dd>
          <dt className="text-slate-500">Return lines (v3)</dt><dd>{health.lines_v3}</dd>
          <dt className="text-slate-500">Open findings</dt><dd>{health.open_findings}</dd>
          <dt className="text-slate-500">Packet SHA-256</dt>
          <dd className="truncate font-mono text-xs" title={health.packet_sha256}>{health.packet_sha256}</dd>
        </dl>
      )}
    </main>
  )
}
