import { ButtonLink } from '../components/Button.jsx'
import Alert from '../components/Alert.jsx'
import AuthLayout from '../features/auth/AuthLayout.jsx'
import './RequestAccessPage.css'

// Sentinel AI has no self-registration: an administrator creates each account. This page says
// so plainly and helps people ask for one. It has no form and sends nothing.
const STEPS = [
  ['Ask your administrator', 'Send them the email you will sign in with, the name to show, the role you need, and which projects you should join at what access level (read, run or manage).'],
  ['Receive an initial password', 'The administrator creates your account and shares a first password with you securely.'],
  ['Sign in and change it', 'After your first sign-in, change the password from your account page.'],
]
const ROLES = [
  ['Developer', 'Create and manage projects, upload sources, analyze, plan, run checks and triage findings in projects they belong to.'],
  ['Admin', 'Everything a developer can do, plus approving high-risk and remote-target checks, deciding finding risk and managing developer accounts.'],
  ['Super admin', 'Everything an admin can do, plus production approvals, privileged accounts, organization policy and break-glass access.'],
]

export default function RequestAccessPage() {
  return (
    <AuthLayout current="access" eyebrow="Chapter 02 · Access" title="Request access" intro="Accounts are created by an administrator. There is no sign-up form.">
      <h2>How to get access</h2>
      <Alert tone="neutral" title="This page does not send a request">Ask your administrator directly, using the steps below.</Alert>
      <ol className="access-steps">
        {STEPS.map(([head, text], i) => (
          <li key={head}>
            <span className="access-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
            <div><strong>{head}</strong><p>{text}</p></div>
          </li>
        ))}
      </ol>
      <details className="access-roles">
        <summary>What each role can do</summary>
        <dl>{ROLES.map(([name, text]) => <div key={name}><dt>{name}</dt><dd>{text}</dd></div>)}</dl>
        <p className="muted">A guide only: the server decides what each role may do.</p>
      </details>
      <ButtonLink to="/signin" variant="primary">I have an account: sign in</ButtonLink>
    </AuthLayout>
  )
}
