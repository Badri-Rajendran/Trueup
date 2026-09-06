import { Badge } from '../../../components/Badge'
import { Card } from '../../../components/Card'
import { StatusPill } from '../../../components/StatusPill'
import './IdentityStatusBanner.css'

const TONE_BY_STATUS = { pending: 'warning', approved: 'success', rejected: 'error' }
const LABEL_BY_STATUS = { pending: 'Pending', approved: 'Approved', rejected: 'Rejected' }

// design-system.md §8.3, ADR 21
export function IdentityStatusBanner({ kycStatus, accountApprovalStatus }) {
  return (
    <Card>
      <div className="tu-identity-status">
        <div className="tu-identity-status__item">
          <span className="tu-identity-status__label">Identity verification</span>
          <span className="tu-identity-status__value">
            <StatusPill tone={TONE_BY_STATUS[kycStatus] || 'neutral'}>
              {LABEL_BY_STATUS[kycStatus] || kycStatus}
            </StatusPill>
          </span>
        </div>
        <div className="tu-identity-status__item">
          <span className="tu-identity-status__label">Account approval</span>
          <span className="tu-identity-status__value">
            <StatusPill tone={TONE_BY_STATUS[accountApprovalStatus] || 'neutral'}>
              {LABEL_BY_STATUS[accountApprovalStatus] || accountApprovalStatus}
            </StatusPill>
            {accountApprovalStatus === 'approved' && <Badge tone="neutral">Simulated</Badge>}
          </span>
        </div>
      </div>
    </Card>
  )
}
