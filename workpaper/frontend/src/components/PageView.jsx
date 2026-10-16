// Renders one page of a source document with values highlighted.
//
// This is the ONLY place that knows documents are simulated text. It takes
// (page text, highlights). A real scanned page would swap this component for
// one that draws the image and places boxes at each value's `position`
// (x0,y0,x1,y1 as fractions of the page). Nothing that calls it changes.
export default function PageView({ text, highlights = [], activeId, onPick }) {
  const ranges = []
  for (const h of highlights) {
    if (!h.text) continue
    let from = 0
    // Highlight the first occurrence not already claimed by another value.
    while (from <= text.length) {
      const i = text.indexOf(h.text, from)
      if (i < 0) break
      const overlaps = ranges.some((r) => i < r.end && i + h.text.length > r.start)
      // Whole values only: "0.00" must not match inside "7,400.00".
      const before = text[i - 1] ?? ' '
      const after = text[i + h.text.length] ?? ' '
      const glued = /[\d,.]/.test(before) || /\d/.test(after)
      if (!overlaps && !glued) {
        ranges.push({ start: i, end: i + h.text.length, id: h.id })
        break
      }
      from = i + 1
    }
  }
  ranges.sort((a, b) => a.start - b.start)

  const parts = []
  let pos = 0
  for (const r of ranges) {
    if (r.start > pos) parts.push(<span key={`t${pos}`}>{text.slice(pos, r.start)}</span>)
    const active = r.id === activeId
    parts.push(
      <mark
        key={r.id}
        onClick={() => onPick?.(r.id)}
        title={r.id}
        className={
          'cursor-pointer rounded px-0.5 ' +
          (active ? 'bg-amber-200 text-slate-900 ring-1 ring-amber-400' : 'bg-transparent text-inherit underline decoration-slate-300 decoration-dotted')
        }
      >
        {text.slice(r.start, r.end)}
      </mark>,
    )
    pos = r.end
  }
  if (pos < text.length) parts.push(<span key={`t${pos}`}>{text.slice(pos)}</span>)

  return (
    <div className="rounded border border-slate-200 bg-white p-4 font-mono text-[12px] leading-relaxed text-slate-600 shadow-sm">
      {parts}
    </div>
  )
}
