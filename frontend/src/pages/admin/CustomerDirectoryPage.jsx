import { CustomerDirectory } from '../../features/admin-customers/components/CustomerDirectory.jsx'
import '../PageLayout.css'

export function CustomerDirectoryPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Customers</h1>
      <CustomerDirectory />
    </div>
  )
}
