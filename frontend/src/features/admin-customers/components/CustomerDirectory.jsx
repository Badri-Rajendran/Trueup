import { useNavigate } from 'react-router-dom'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useCustomerSearch } from '../hooks/useCustomerSearch.js'
import { CustomerSearchForm } from './CustomerSearchForm.jsx'
import { CustomerSummary } from './CustomerSummary.jsx'
import './CustomerDirectory.css'

export function CustomerDirectory() {
  const { status, query, results, error, search } = useCustomerSearch()
  const navigate = useNavigate()

  return (
    <div className="tu-customer-directory">
      <CustomerSearchForm onSearch={search} initialQuery={query} />
      {status === 'idle' && <EmptyState title="Search for a customer" description="Enter an email above to get started." />}
      {status === 'searching' && <Skeleton height="44px" />}
      {status === 'error' && <ErrorState description={getErrorMessage(error)} onRetry={() => search(query)} />}
      {status === 'loaded' && results.length === 0 && <EmptyState title="No customers match" description={`No results for "${query}".`} />}
      {status === 'loaded' && results.length > 0 && (
        <Table>
          <Table.Header>
            <Table.HeaderCell>Email</Table.HeaderCell>
            <Table.HeaderCell>KYC status</Table.HeaderCell>
            <Table.HeaderCell>Account approval</Table.HeaderCell>
            <Table.HeaderCell>&nbsp;</Table.HeaderCell>
          </Table.Header>
          <Table.Body>
            {results.map((customer) => (
              <CustomerSummary key={customer.id} customer={customer} onClick={() => navigate(`/admin/customers/${customer.id}`)} />
            ))}
          </Table.Body>
        </Table>
      )}
    </div>
  )
}
