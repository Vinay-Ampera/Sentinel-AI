import dark from '../assets/brand/sentinel-logo-dark.png'
import light from '../assets/brand/sentinel-logo-light.png'
import './BrandLogo.css'

// The Sentinel AI shield. Two renderings of the same logo: the original colours for light
// themes and a lightened-navy version for dark themes; CSS shows the one that matches the
// resolved theme (data-theme on <html>). It is decorative: the product name is always written
// next to it, so it is hidden from assistive technology.
export default function BrandLogo({ size = 28 }) {
  return (
    <span className="brand-logo" aria-hidden="true">
      <img className="brand-logo-light" src={light} alt="" width={size} height={size} decoding="async" />
      <img className="brand-logo-dark" src={dark} alt="" width={size} height={size} decoding="async" />
    </span>
  )
}
