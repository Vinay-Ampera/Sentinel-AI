import { useRef, useState } from 'react'
import { useReducedMotion } from '../../hooks/useReducedMotion.js'
import { usePauseOffscreen } from '../../hooks/usePauseOffscreen.js'
import './HeroVisual.css'

// Decorative hero scene: tests flow in from the left along circuit traces, a central testing
// system (rings, checklist and scanner inside a hexagon) processes them, and evidence flows out
// to the right. It is illustration only, with no product data or numbers, so it is hidden from
// assistive technology; the "How it works" section states the same thing in text.
//
// Motion: arrows travel along the traces (SVG animateMotion), the rings turn, the scanner
// sweeps and dashed traces flow. All of it stops for visitors who prefer reduced motion, when
// the visitor presses Pause, and while the scene is off screen or the tab is hidden.

const TRACES = [
  { id: 'in-1', d: 'M0 112 H236 C268 112 286 124 304 146 L346 196 C362 216 384 224 412 224 H683' },
  { id: 'in-2', d: 'M0 262 H683' },
  { id: 'in-3', dashed: true, d: 'M0 372 H120 C146 372 156 362 170 346 L194 316 C206 300 222 294 246 294 H683' },
  { id: 'out-1', d: 'M917 224 H1188 C1216 224 1238 216 1254 196 L1296 146 C1314 124 1332 112 1364 112 H1600' },
  { id: 'out-2', dashed: true, d: 'M917 262 H1600' },
  { id: 'out-3', d: 'M1600 372 H1480 C1454 372 1444 362 1430 346 L1406 316 C1394 300 1378 294 1354 294 H917' },
]

// path: which trace it follows; at: where it rests when motion is off (x, y, degrees).
const ARROWS = [
  { path: 'in-1', dur: 10, begin: 0, at: [150, 112, 0] },
  { path: 'in-1', dur: 10, begin: -5, at: [560, 224, 0] },
  { path: 'in-2', dur: 8, begin: 0, at: [260, 262, 0] },
  { path: 'in-2', dur: 8, begin: -4, at: [540, 262, 0] },
  { path: 'in-3', dur: 11, begin: -2, at: [60, 372, 0] },
  { path: 'out-1', dur: 9, begin: -1, at: [1000, 224, 0], tone: 'success' },
  { path: 'out-1', dur: 9, begin: -5.5, at: [1480, 112, 0], tone: 'success' },
  { path: 'out-2', dur: 8, begin: -3, at: [1060, 262, 0] },
  { path: 'out-2', dur: 8, begin: -7, at: [1420, 262, 0] },
  { path: 'out-3', dur: 11, begin: -6, at: [1540, 372, 180], tone: 'muted' },
]

const MARKS = {
  pass: 'M-4.5 0l3 3L5 -3.5',
  fail: 'M-3.5 -3.5l7 7M3.5 -3.5l-7 7',
  skip: 'M-4.5 0h9',
}
const NODES = [
  { x: 200, y: 112, k: 'pass' },
  { x: 180, y: 262, k: 'pass' },
  { x: 520, y: 262, k: 'pass' },
  { x: 400, y: 294, k: 'skip' },
  { x: 1420, y: 112, k: 'pass' },
  { x: 1100, y: 262, k: 'pass' },
  { x: 1180, y: 262, k: 'fail' },
  { x: 1280, y: 294, k: 'pass' },
]
const JUNCTIONS = [[683, 224], [683, 262], [683, 300], [917, 224], [917, 262], [917, 300]]
const PLUS = 'M-8 0h16M0 -8v16'

function Arrow({ arrow, animated }) {
  const cls = `hv-arrow${arrow.tone ? ` hv-arrow-${arrow.tone}` : ''}`
  const shape = 'M-7 -6L7 0L-7 6Z'
  if (!animated) {
    const [x, y, a] = arrow.at
    return <path className={cls} d={shape} transform={`translate(${x} ${y}) rotate(${a})`} />
  }
  return (
    <path className={cls} d={shape}>
      <animateMotion dur={`${arrow.dur}s`} begin={`${arrow.begin}s`} repeatCount="indefinite" rotate="auto">
        <mpath href={`#hv-${arrow.path}`} />
      </animateMotion>
    </path>
  )
}

export default function HeroVisual() {
  const reduced = useReducedMotion()
  const [userPaused, setUserPaused] = useState(false)
  const animated = !reduced && !userPaused
  const box = useRef(null)
  const svg = useRef(null)
  usePauseOffscreen(box, svg)

  return (
    <div className="hero-visual">
      <div ref={box} className={animated ? 'hv' : 'hv hv-static'} aria-hidden="true">
        <svg ref={svg} viewBox="0 0 1600 440" preserveAspectRatio="xMidYMid slice" focusable="false">
          {/* traces */}
          {TRACES.map((t) => (
            <path key={t.id} id={`hv-${t.id}`} className={t.dashed ? 'hv-trace hv-dashed' : 'hv-trace'} d={t.d} />
          ))}

          {/* quiet geometry */}
          <g className="hv-geo">
            <rect x="96" y="150" width="184" height="56" rx="16" />
            {[0, 1, 2, 3, 4].map((i) => (
              <rect key={i} className={`hv-seg${i < 3 ? ' hv-seg-on' : ''}`} style={{ animationDelay: `${i * 0.5}s` }} x={116 + i * 34} y="168" width="24" height="20" rx="4" />
            ))}
            <rect x="1330" y="152" width="58" height="58" rx="14" />
            <path className="hv-plus" d={PLUS} transform="translate(1359 181)" />
            <circle cx="1470" cy="184" r="28" className="hv-faint" />
            <path className="hv-plus hv-faint" d={PLUS} transform="translate(1470 184)" />
            <path className="hv-plus" d={PLUS} transform="translate(42 330)" />
            <path className="hv-plus hv-spin-slow" d={PLUS} transform="translate(370 340)" />
            <path className="hv-plus" d={PLUS} transform="translate(1010 340)" />
            <path className="hv-plus" d={PLUS} transform="translate(1440 238)" />
            <path d="M120 424 L152 394 M160 424 L192 394" />
            <path d="M1424 428 L1476 386" />
            <circle cx="1480" cy="382" r="5" />
            {[140, 158, 176].map((x) => <circle key={x} className="hv-dot" cx={x} cy="62" r="3" />)}
            {[1180, 1198, 1216].map((x) => <circle key={x} className="hv-dot" cx={x} cy="62" r="3" />)}
            <circle className="hv-dot hv-dot-warning" cx="1234" cy="62" r="3" />
            {/* target brackets around the failing node */}
            <path d="M1152 238v-14h14M1208 238v-14h-14M1152 286v14h14M1208 286v14h-14" />
            {/* hexagon corner ticks */}
            <path d="M683 182L658 158M683 318L658 342M917 182L942 158M917 318L942 342" />
          </g>
          <rect className="hv-square hv-square-danger" x="24" y="106" width="12" height="12" />
          <rect className="hv-square hv-square-warning" x="1524" y="106" width="12" height="12" />

          {/* status nodes along the traces */}
          {NODES.map((n) => (
            <g key={`${n.x}-${n.y}`} className={`hv-node hv-${n.k}`} transform={`translate(${n.x} ${n.y})`}>
              <circle r="12" />
              <path d={MARKS[n.k]} />
            </g>
          ))}
          {JUNCTIONS.map(([x, y]) => <circle key={`${x}-${y}`} className="hv-junction" cx={x} cy={y} r="6" />)}

          {/* central testing system */}
          <g className="hv-core">
            <circle className="hv-ring-halo" cx="800" cy="250" r="104" />
            <polygon className="hv-hex" points="800,115 917,182 917,318 800,385 683,318 683,182" />
            <circle className="hv-ring hv-ring-a hv-spin" cx="800" cy="250" r="88" />
            <circle className="hv-ring hv-ring-b hv-spin hv-spin-rev" cx="800" cy="250" r="70" />
            <circle className="hv-ring hv-ring-c hv-spin hv-spin-fast" cx="800" cy="250" r="54" />
            <rect className="hv-panel" x="762" y="212" width="76" height="76" rx="8" />
            {[
              { y: 232, k: 'pass' },
              { y: 250, k: 'pass' },
              { y: 268, k: 'fail' },
            ].map((row) => (
              <g key={row.y} className={`hv-row hv-${row.k}`}>
                <circle cx="778" cy={row.y} r="5.5" />
                <path d={MARKS[row.k]} transform={`translate(778 ${row.y}) scale(0.62)`} />
                <path className="hv-bar" d={`M790 ${row.y}H826`} />
              </g>
            ))}
            <path className="hv-scan" d="M766 218H834" />
          </g>

          {/* moving arrows */}
          {ARROWS.map((a, i) => <Arrow key={i} arrow={a} animated={animated} />)}
        </svg>
      </div>
      <button type="button" className="hv-toggle" aria-pressed={!animated} onClick={() => setUserPaused((p) => !p)} disabled={reduced} title={reduced ? 'Animation is off because your system asks for reduced motion' : undefined}>
        {reduced ? 'Animation off (reduced motion)' : userPaused ? 'Play animation' : 'Pause animation'}
      </button>
    </div>
  )
}
