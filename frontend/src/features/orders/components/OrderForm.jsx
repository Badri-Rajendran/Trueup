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
import { formatMoney } from '../../../utils/format.js'
import { getOrdersErrorMessage } from '../ordersErrorMessage.js'
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
  const [quantityError, setQuantityError] = useState(null)
  const [referencePriceError, setReferencePriceError] = useState(null)

  if (securitiesStatus === 'idle' || securitiesStatus === 'loading') {
    return <Skeleton height="200px" width="360px" />
  }

  if (securitiesStatus === 'error') {
    return <ErrorState description={getOrdersErrorMessage(securitiesError)} onRetry={refetchSecurities} />
  }

  if (securities.length === 0) {
    return <p className="tu-order-form__empty">No tradable securities are available right now.</p>
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
    setQuantityError(null)
    setReferencePriceError(null)

    const parsedQuantity = parseQuantity(quantity)
    if (!parsedQuantity) {
      setQuantityError('Enter a valid quantity greater than zero.')
      return
    }

    const trimmedReferencePrice = referencePrice.trim()
    if (!trimmedReferencePrice || Number.isNaN(Number(trimmedReferencePrice)) || Number(trimmedReferencePrice) <= 0) {
      setReferencePriceError('Enter a valid reference price greater than zero.')
      return
    }

    placeOrder({
      securityId: selectedSecurity.security_id,
      side,
      quantity: parsedQuantity,
      referencePrice: trimmedReferencePrice,
    })
      .then((order) => {
        showToast({ message: 'Order placed.', tone: 'success' })
        navigate(`/orders/${order.id}`)
      })
      .catch(() => {})
  }

  const submitError = status === 'error' ? getOrdersErrorMessage(error) : null

  return (
    <form className="tu-order-form" onSubmit={handleSubmit}>
      <Select
        label="Security"
        name="security"
        required
        value={selectedSecurity?.security_id}
        onChange={(event) => setSecurityId(event.target.value)}
      >
        {securities.map((security) => (
          <option key={security.security_id} value={security.security_id}>
            {security.symbol}
          </option>
        ))}
      </Select>
      <Select label="Side" name="side" required value={side} onChange={(event) => setSide(event.target.value)}>
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
        error={quantityError}
        required
      />
      <Input
        label="Reference price"
        name="referencePrice"
        inputMode="decimal"
        value={referencePrice}
        onChange={(event) => setReferencePrice(event.target.value)}
        placeholder="0.00"
        error={referencePriceError}
        required
      />
      {notional && (
        <div className="tu-order-form__preview">
          <span className="tu-order-form__preview-label">Estimated notional</span>
          <span className="tu-order-form__preview-value">{formatMoney(notional)}</span>
        </div>
      )}
      {submitError && (
        <p className="tu-order-form__error" role="alert">
          {submitError}
        </p>
      )}
      <Button type="submit" className="tu-order-form__submit" loading={isSubmitting} disabled={isSubmitting}>
        Place order
      </Button>
    </form>
  )
}
