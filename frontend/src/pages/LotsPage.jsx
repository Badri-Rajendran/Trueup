import { SimulatedBadge } from '../components/SimulatedBadge'
import { LotTable } from '../features/lots/components/LotTable.jsx'
import './PageLayout.css'

export function LotsPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">
        Tax lots <SimulatedBadge />
      </h1>
      <LotTable />
    </div>
  )
}
