import { useId } from 'react'
import { Link } from 'react-router-dom'
import './Button.css'

const cls = (variant, size, extra) => ['btn', `btn-${variant}`, size === 'sm' ? 'btn-sm' : '', extra].filter(Boolean).join(' ')

// variant: primary | secondary | ghost | danger.
// A disabled button can say why (disabledReason): it is announced as the button's description
// and shown as a tooltip, so a disabled action is never a silent dead end.
export default function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  loadingLabel,
  disabled = false,
  disabledReason,
  type = 'button',
  className,
  children,
  ...rest
}) {
  const reasonId = useId()
  const isDisabled = disabled || loading
  const describedBy = disabled && disabledReason ? reasonId : undefined
  return (
    <>
      <button
        type={type}
        className={cls(variant, size, className)}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        aria-describedby={describedBy}
        title={disabled && disabledReason ? disabledReason : undefined}
        {...rest}
      >
        {loading && loadingLabel ? loadingLabel : children}
      </button>
      {disabled && disabledReason && (
        <span id={reasonId} className="visually-hidden">
          {disabledReason}
        </span>
      )}
    </>
  )
}

// A router link that looks like a button.
export function ButtonLink({ variant = 'secondary', size = 'md', className, ...props }) {
  return <Link className={cls(variant, size, className)} {...props} />
}
