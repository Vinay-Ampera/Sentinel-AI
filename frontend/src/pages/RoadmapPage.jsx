import Alert from '../components/Alert.jsx'
import Card from '../components/Card.jsx'
import PageHeader from '../components/PageHeader.jsx'
import RoadmapList from '../features/roadmap/RoadmapList.jsx'
import { LIMITS } from '../features/roadmap/roadmap.js'

export default function RoadmapPage() {
  return (
    <>
      <PageHeader title="Roadmap" description="What is planned, and where today's features have limits." />
      <Alert tone="info" title="Nothing on this list is available yet">
        These are designed but not built. They have no controls here on purpose, so nothing can be mistaken for a working feature.
      </Alert>
      <RoadmapList />
      <Card title="Limits of what exists today">
        <ul>{LIMITS.map((l) => <li key={l}>{l}</li>)}</ul>
      </Card>
    </>
  )
}
