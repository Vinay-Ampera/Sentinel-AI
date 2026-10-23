import './Icon.css'
// Small inline icon set (16px, stroke only). Icons are decorative: the visible text label
// always carries the meaning, so they are hidden from assistive technology.
const PATHS = {
  check: 'M3 8.5l3.2 3.2L13 4.8',
  cross: 'M4 4l8 8M12 4l-8 8',
  alert: 'M8 2.5l6 10.5H2L8 2.5zM8 6.5v3M8 11.5v.01',
  minus: 'M3.5 8h9',
  ban: 'M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM4.2 4.2l7.6 7.6',
  clock: 'M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 5v3.2l2 1.3',
  stop: 'M4.5 4.5h7v7h-7z',
  circle: 'M8 3a5 5 0 100 10A5 5 0 008 3z',
  power: 'M8 2.5v5M4.7 4.6a5 5 0 106.6 0',
  play: 'M5 3.5v9l7-4.5-7-4.5z',
  flag: 'M4 14V2.5M4 3h8l-1.6 2.5L12 8H4',
  info: 'M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM8 7.2v3.6M8 5.2v.01',
  dot: 'M8 6.2a1.8 1.8 0 100 3.6 1.8 1.8 0 000-3.6z',
  sun: 'M8 5.2a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6zM8 1.5v1.3M8 13.2v1.3M1.5 8h1.3M13.2 8h1.3M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9',
  moon: 'M13 9.6A5.5 5.5 0 116.4 3a4.4 4.4 0 006.6 6.6z',
  monitor: 'M2.5 3h11v7.5h-11zM6 13.5h4M8 10.5v3',
  menu: 'M2.5 4.5h11M2.5 8h11M2.5 11.5h11',
  close: 'M4 4l8 8M12 4l-8 8',
  user: 'M8 7.5a2.75 2.75 0 100-5.5 2.75 2.75 0 000 5.5zM2.75 14c.4-2.7 2.6-4.25 5.25-4.25S12.85 11.3 13.25 14',
  chevron: 'M6 3.5L10.5 8 6 12.5',
}

export default function Icon({ name, size = 16 }) {
  const d = PATHS[name] || PATHS.circle
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={d} />
    </svg>
  )
}
