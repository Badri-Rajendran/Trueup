import { Button } from '../../../components/Button'

function buildExportContent(statement) {
  const lines = [
    'Field,Value',
    `Period Start,${statement.period_start}`,
    `Period End,${statement.period_end}`,
    `Balance,${statement.balance}`,
    `Return,${statement.twr}`,
    `Published At,${statement.published_at}`,
  ]
  return lines.join('\n')
}

// MOCK — no export-as-file endpoint yet. Generates the CSV client-side.
export function ExportButton({ statement }) {
  const handleExport = () => {
    const blob = new Blob([buildExportContent(statement)], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `statement-${statement.period_start}.csv`
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(url)
  }

  return (
    <Button variant="secondary" onClick={handleExport}>
      Export
    </Button>
  )
}
