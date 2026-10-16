import { useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { useApi } from './lib'
import DocumentPanel from './components/DocumentPanel'
import Summary from './pages/Summary'
import Area from './pages/Area'
import Line from './pages/Line'
import Documents from './pages/Documents'
import Findings from './pages/Findings'

function Sidebar({ version }) {
  const { search } = useLocation()
  const { data } = useApi(`/api/summary?version=${version}`)
  const item = ({ isActive }) =>
    `flex justify-between rounded px-2 py-1 text-sm ${isActive ? 'bg-blue-50 text-blue-800' : 'text-slate-700 hover:bg-slate-100'}`
  return (
    <nav className="w-56 shrink-0 overflow-y-auto border-r border-slate-200 p-3">
      <NavLink end to={`/${search}`} className={item}>Return summary</NavLink>
      <div className="mt-4 px-2 text-xs uppercase tracking-wide text-slate-400">Areas</div>
      {data?.areas.map((a) => (
        <NavLink key={a.id} to={`/area/${a.id}${search}`} className={item}>
          <span className="truncate">{a.name}</span>
          {a.open_findings > 0 && <span className="text-amber-700">{a.open_findings}</span>}
        </NavLink>
      ))}
      <div className="mt-4 px-2 text-xs uppercase tracking-wide text-slate-400">Records</div>
      <NavLink to={`/documents${search}`} className={item}>Documents</NavLink>
      <NavLink to={`/findings${search}`} className={item}>Findings</NavLink>
    </nav>
  )
}

function Shell() {
  const [version, setVersion] = useState('v3')
  const { data: health } = useApi('/api/health')
  return (
    <div className="flex h-screen flex-col font-sans text-slate-800">
      <header className="flex items-center gap-4 border-b border-slate-200 px-4 py-2">
        <span className="font-medium">Okafor-Lindqvist 2025</span>
        <label className="text-sm text-slate-500">
          Return version{' '}
          <select value={version} onChange={(e) => setVersion(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5 text-slate-800">
            <option value="v3">v3 (current, 06/23)</option>
            <option value="v2">v2 (03/19)</option>
            <option value="v1">v1 (03/04)</option>
            <option value="2024">2024 as filed</option>
          </select>
        </label>
        <span className="flex-1" />
        {health && <span className="text-xs text-slate-400" title={health.packet_sha256}>Packet {health.packet_sha256.slice(0, 8)} · {health.open_findings} open findings</span>}
      </header>
      <div className="flex min-h-0 flex-1">
        <Sidebar version={version} />
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<Summary version={version} />} />
            <Route path="/area/:id" element={<Area version={version} />} />
            <Route path="/line/:lineVersion/:key" element={<LineRoute />} />
            <Route path="/documents" element={<Documents version={version} />} />
            <Route path="/findings" element={<Findings />} />
            <Route path="*" element={<p>Not found.</p>} />
          </Routes>
        </main>
        <DocumentPanel version={version} />
      </div>
    </div>
  )
}

// A line URL carries its own version (/line/v2/F1040.11) so links to any
// version work, independent of the header selector.
function LineRoute() {
  const version = useLocation().pathname.split('/')[2]
  return <Line version={version} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}
