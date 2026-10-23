import './SectionHeader.css'

// A heading for a section inside a page that already has its page title (so it is an h2, and
// the document title is left alone).
export default function SectionHeader({ title, children }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {children}
    </div>
  )
}
