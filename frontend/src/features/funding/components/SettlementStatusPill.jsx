import { Icon } from '../../../components/Icon'
import { StatusPill } from '../../../components/StatusPill'
import { settlementDisplay } from '../utils/fundingSummary.js'

/** Thin `settlementDisplay()` -> `StatusPill` wrapper for one `FundingHistoryTable` row. */
export function SettlementStatusPill({ entry }) {
  const { label, tone, icon } = settlementDisplay(entry)

  return <StatusPill tone={tone} icon={icon ? <Icon name={icon} size="sm" /> : undefined}>{label}</StatusPill>
}
