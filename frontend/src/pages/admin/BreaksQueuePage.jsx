import { BreakQueue } from '../../features/admin-breaks/components/BreakQueue.jsx'
import '../PageLayout.css'

export function BreaksQueuePage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Reconciliation breaks</h1>
      <BreakQueue />
    </div>
  )
}
