import Decimal from 'decimal.js'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { ErrorState } from '../../../components/ErrorState'
import { Input } from '../../../components/Input'
import { Select } from '../../../components/Select'
import { Skeleton } from '../../../components/Skeleton'
import { useToast } from '../../../components/Toast'
import { useSecurities } from '../../portfolio/hooks/useSecurities.js'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatMoney } from '../../../utils/format.js'
import { usePlaceOrder } from '../hooks/usePlaceOrder.js'
import { parseQuantity } from '../parseQuantity.js'
import './OrderForm.css'

export function OrderForm() {
  const { status: securitiesStatus, securities, error: securitiesError, refetch: refetchSecurities } = useSecurities()
  const { status, error, placeOrder } = usePlaceOrder()
  const { showToast } = useToast()
  const navigate = useNavigate()

  const [securityId, setSecurityId] = useState('')
  const [side, setSide] = useState('buy')
  const [quantity, setQuantity] = useState('')
  const [referencePrice, setReferencePrice] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  if (securitiesStatus === 'idle' || securitiesStatus === 'loading') {
    return <Skeleton height="200px" width="360px" />
  }

  if (securitiesStatus === 'error') {
    return <ErrorState description={getErrorMessage(securitiesError)} onRetry={refetchSecurities} />
  }

  const selectedSecurity = securities.find((security) => security.security_id === securityId) || securities[0]
  const isSubmitting = status === 'submitting'

  const notional =
    quantity && referencePrice && !Number.isNaN(Number(quantity)) && !Number.isNaN(Number(referencePrice))
      ? (() => {
          try {
            return new Decimal(quantity).times(referencePrice).toFixed(2)
          } catch {
            return null
          }
        })()
      : null

  const handleSubmit = (event) => {
    event.preventDefault()
    setValidationMessage(null)
    const parsedQuantity = parseQuantity(quantity)
    if (!parsedQuantity) {
      setValidationMessage('Enter a valid quantity greater than zero.')
      return
    }
    if (!selectedSecurity) {
      setValidationMessage('Choose a security.')
      return
    }
    if (!referencePrice || Number.isNaN(Number(referencePrice)) || Number(referencePrice) <= 0) {
      setValidationMessage('Enter a valid reference price greater than zero.')
      return
    }

    placeOrder({
      securityId: selectedSecurity.security_id,
      side,
      quantity: parsedQuantity,
      referencePrice,
    })
      .then((order) => {
        showToast({ message: 'Order placed.', tone: 'success' })
        navigate(`/orders/${order.id}`)
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getErrorMessage(error) : null)

  return (
    <form className="tu-order-form" onSubmit={handleSubmit}>
      <Select label="Security" name="security" value={selectedSecurity?.security_id} onChange={(event) => setSecurityId(event.target.value)}>
        {securities.map((security) => (
          <option key={security.security_id} value={security.security_id}>
            {security.symbol}
          </option>
        ))}
      </Select>
      <Select label="Side" name="side" value={side} onChange={(event) => setSide(event.target.value)}>
        <option value="buy">Buy</option>
        <option value="sell">Sell</option>
      </Select>
      <Input
        label="Quantity"
        name="quantity"
        inputMode="decimal"
        value={quantity}
        onChange={(event) => setQuantity(event.target.value)}
        placeholder="0"
        required
      />
      <Input
        label="Reference price"
        name="referencePrice"
        inputMode="decimal"
        value={referencePrice}
        onChange={(event) => setReferencePrice(event.target.value)}
        placeholder="0.00"
        required
      />
      {notional && (
        <div className="tu-order-form__preview">
          <span className="tu-order-form__preview-label">Estimated notional</span>
          <span className="tu-order-form__preview-value">{formatMoney(notional)}</span>
        </div>
      )}
      {displayError && (
        <p className="tu-order-form__error" role="alert">
          {displayError}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Place order
      </Button>
    </form>
  )
}
