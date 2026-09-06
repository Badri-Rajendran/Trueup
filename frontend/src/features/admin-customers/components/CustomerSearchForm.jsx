import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import './CustomerSearchForm.css'

export function CustomerSearchForm({ onSearch, initialQuery = '' }) {
  const [query, setQuery] = useState(initialQuery)

  return (
    <form
      className="tu-customer-search-form"
      onSubmit={(event) => {
        event.preventDefault()
        onSearch(query)
      }}
    >
      <div className="tu-customer-search-form__field">
        <Input label="Search customers" name="query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Email" />
      </div>
      <Button type="submit">Search</Button>
    </form>
  )
}
