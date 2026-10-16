// Shared helpers: API calls, number formatting, ref parsing.
import { useEffect, useState } from 'react'

export async function api(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

// Fetch on mount and whenever `path` changes. Returns {data, error, loading}.
export function useApi(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    if (!path) return
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    api(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }))
    return () => { alive = false }
  }, [path])
  return state
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usdCents = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

// Return line values are whole dollars, except Form 8949 lots (cents) and
// a few ratios/text lines. Numbers between -1 and 1 that aren't 0 are ratios.
export function fmt(value, { cents = false } = {}) {
  if (value === null || value === undefined) return '—'
  if (typeof value !== 'number') return String(value)
  if (value !== 0 && Math.abs(value) < 1) return value.toFixed(4)
  return (cents ? usdCents : usd).format(value)
}

export function change(current, prior) {
  if (typeof current !== 'number' || typeof prior !== 'number') return null
  return current - prior
}

// "line:v3:F1040.11" -> {kind:'line', version:'v3', key:'F1040.11'}
// "doc:D11#page2"    -> {kind:'doc', doc:'D11', page:2}
// "ev:ev-0498"       -> {kind:'ev', ev:'ev-0498'}
export function parseRef(ref) {
  if (ref.startsWith('line:')) {
    const [, version, ...rest] = ref.split(':')
    return { kind: 'line', version, key: rest.join(':') }
  }
  if (ref.startsWith('doc:')) {
    const [doc, page] = ref.slice(4).split('#page')
    return { kind: 'doc', doc, page: page ? Number(page) : 1 }
  }
  if (ref.startsWith('ev:')) return { kind: 'ev', ev: ref.slice(3) }
  return { kind: 'other', text: ref }
}

export const STATUS_LABEL = {
  used: 'Used',
  not_used: 'Needs explanation',
  duplicate: 'Duplicate',
  superseded: 'Superseded',
  not_extracted: 'Not extracted',
  supporting: 'Supporting record',
}
