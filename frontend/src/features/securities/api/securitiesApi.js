import { apiClient } from '../../../services/apiClient.js'
import { paginationQuery } from '../../../utils/paginationQuery.js'

export const securitiesApi = {
  list: (pagination) => apiClient.get(`/securities${paginationQuery(pagination)}`),
}
