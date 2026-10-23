import { ButtonLink } from '../components/Button.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { EmptyState } from '../components/states.jsx'

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState title="There is nothing at this address." action={<ButtonLink to="/">Go to the home page</ButtonLink>}>
        The link may be out of date, or the page may not exist yet.
      </EmptyState>
    </>
  )
}
