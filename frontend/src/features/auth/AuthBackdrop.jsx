import './AuthBackdrop.css'

// A very quiet technical backdrop: a fine grid and a few test-related marks (pass, fail, skip,
// plus, brackets, a diamond) that drift slowly. Decoration only, so it is hidden from assistive
// technology; it moves with transforms only, and stops for visitors who prefer reduced motion.
const GLYPHS = {
  pass: 'M-6 0l4 4L7 -5',
  fail: 'M-5 -5l10 10M5 -5l-10 10',
  skip: 'M-6 0h12',
  plus: 'M-6 0h12M0 -6v12',
  brackets: 'M-5 -7h-4v14h4M5 -7h4v14h-4',
  diamond: 'M0 -7l7 7l-7 7l-7 -7z',
}

const MARKS = [
  { g: 'pass', x: 8, y: 18, d: 26, t: 0 },
  { g: 'brackets', x: 20, y: 74, d: 32, t: -6 },
  { g: 'plus', x: 31, y: 12, d: 28, t: -12 },
  { g: 'diamond', x: 44, y: 88, d: 34, t: -3 },
  { g: 'skip', x: 58, y: 8, d: 30, t: -9 },
  { g: 'fail', x: 70, y: 82, d: 27, t: -15 },
  { g: 'pass', x: 82, y: 22, d: 33, t: -5 },
  { g: 'plus', x: 92, y: 64, d: 29, t: -11 },
  { g: 'brackets', x: 14, y: 46, d: 35, t: -18 },
  { g: 'diamond', x: 88, y: 40, d: 31, t: -8 },
  { g: 'skip', x: 50, y: 50, d: 36, t: -14 },
  { g: 'pass', x: 36, y: 62, d: 28, t: -20 },
]

export default function AuthBackdrop() {
  return (
    <div className="auth-backdrop" aria-hidden="true">
      <div className="auth-grid" />
      {MARKS.map((m, i) => (
        <svg key={i} className="auth-mark" style={{ left: `${m.x}%`, top: `${m.y}%`, animationDuration: `${m.d}s`, animationDelay: `${m.t}s` }} width="22" height="22" viewBox="-11 -11 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" focusable="false">
          <path d={GLYPHS[m.g]} />
        </svg>
      ))}
    </div>
  )
}
