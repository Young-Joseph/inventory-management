<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-header">
        <label class="budget-label" for="budget-slider">{{ t('restocking.availableBudget') }}</label>
        <span class="budget-amount">{{ formatMoney(budget) }}</span>
      </div>
      <input
        id="budget-slider"
        v-model.number="budget"
        class="budget-slider"
        type="range"
        :min="BUDGET_MIN"
        :max="BUDGET_MAX"
        :step="BUDGET_STEP"
        :style="sliderFillStyle"
      />
      <div class="budget-scale">
        <span>{{ formatMoney(BUDGET_MIN) }}</span>
        <span class="budget-help">{{ t('restocking.budgetHelp') }}</span>
        <span>{{ formatMoney(BUDGET_MAX) }}</span>
      </div>
    </div>

    <div v-if="confirmation" class="order-confirmation">
      <strong>{{ confirmation }}</strong>
      <router-link to="/orders">{{ t('restocking.viewInOrders') }}</router-link>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.availableBudget') }}</div>
          <div class="stat-value info">{{ formatMoney(budget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.allocated') }}</div>
          <div class="stat-value warning">{{ formatMoney(totalCost) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value success">{{ formatMoney(budgetRemaining) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order-btn"
            :disabled="!canPlaceOrder"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="recommendations.length" class="table-container">
          <table>
            <thead>
              <tr>
                <th class="col-sku">{{ t('restocking.table.sku') }}</th>
                <th class="col-name">{{ t('restocking.table.itemName') }}</th>
                <th class="col-warehouse">{{ t('restocking.table.warehouse') }}</th>
                <th class="col-num">{{ t('restocking.table.onHand') }}</th>
                <th class="col-num">{{ t('restocking.table.forecast') }}</th>
                <th class="col-trend">{{ t('restocking.table.trend') }}</th>
                <th class="col-num">{{ t('restocking.table.quantity') }}</th>
                <th class="col-money">{{ t('restocking.table.unitCost') }}</th>
                <th class="col-money">{{ t('restocking.table.lineCost') }}</th>
                <th class="col-lead">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendations" :key="item.item_sku">
                <td class="sku">{{ item.item_sku }}</td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>{{ translateWarehouse(item.warehouse) }}</td>
                <td class="num">{{ item.quantity_on_hand.toLocaleString() }}</td>
                <td class="num">{{ item.forecasted_demand.toLocaleString() }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t('trends.' + item.trend) }}</span>
                </td>
                <td class="num qty">{{ item.recommended_quantity.toLocaleString() }}</td>
                <td class="num">{{ formatMoney(item.unit_cost, 2) }}</td>
                <td class="num">{{ formatMoney(item.line_cost) }}</td>
                <td class="num">{{ t('orders.submitted.leadTimeDays', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-else class="empty-state">
          {{ hasCandidates ? t('restocking.noRecommendations') : t('restocking.nothingToRestock') }}
        </p>

        <p v-if="unfundedCount > 0 && recommendations.length" class="unfunded-note">
          {{ t('restocking.unfundedNote', { count: unfundedCount }) }}
        </p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_MIN = 0
const BUDGET_MAX = 50000
const BUDGET_STEP = 1000
const SLIDER_DEBOUNCE_MS = 300

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName, translateWarehouse } = useI18n()

    // Restocking is driven by where stock sits and what kind of part it is.
    // Time period and order status describe customer orders, so they don't apply here.
    const { selectedLocation, selectedCategory } = useFilters()

    const budget = ref(25000)
    const recommendations = ref([])
    const totalCost = ref(0)
    const budgetRemaining = ref(0)
    const unfundedCount = ref(0)
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const confirmation = ref('')

    let debounceTimer = null

    const formatMoney = (amount, decimals = 0) => {
      return decimals
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    // Paint the consumed portion of the track up to the thumb
    const sliderFillStyle = computed(() => {
      const percent = ((budget.value - BUDGET_MIN) / (BUDGET_MAX - BUDGET_MIN)) * 100
      return { '--fill-percent': `${percent}%` }
    })

    const hasCandidates = computed(() => recommendations.value.length > 0 || unfundedCount.value > 0)
    const canPlaceOrder = computed(() => recommendations.value.length > 0 && !submitting.value)

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null

        const data = await api.getRestockRecommendations(budget.value, {
          warehouse: selectedLocation.value,
          category: selectedCategory.value
        })

        recommendations.value = data.recommendations
        totalCost.value = data.total_cost
        budgetRemaining.value = data.budget_remaining
        unfundedCount.value = data.unfunded_count
      } catch (err) {
        error.value = 'Failed to load restocking recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      try {
        submitting.value = true
        error.value = null
        confirmation.value = ''

        const order = await api.submitRestockingOrder({
          budget: budget.value,
          items: recommendations.value.map(item => ({
            sku: item.item_sku,
            name: item.item_name,
            quantity: item.recommended_quantity,
            unit_price: item.unit_cost
          }))
        })

        confirmation.value = t('restocking.orderPlaced', {
          orderNumber: order.order_number,
          date: formatDate(order.expected_delivery),
          days: leadTimeDays(order)
        })

        await loadRecommendations()
      } catch (err) {
        const detail = err.response?.data?.detail
        error.value = 'Failed to place order: ' + (detail || err.message)
      } finally {
        submitting.value = false
      }
    }

    const leadTimeDays = (order) => {
      const ordered = new Date(order.order_date)
      const expected = new Date(order.expected_delivery)
      return Math.round((expected - ordered) / (1000 * 60 * 60 * 24))
    }

    const formatDate = (dateString) => {
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return new Date(dateString).toLocaleDateString(locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    // Dragging the slider fires continuously - wait for a pause before refetching
    watch(budget, () => {
      confirmation.value = ''
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendations, SLIDER_DEBOUNCE_MS)
    })

    watch([selectedLocation, selectedCategory], () => {
      confirmation.value = ''
      loadRecommendations()
    })

    onMounted(loadRecommendations)
    onUnmounted(() => clearTimeout(debounceTimer))

    return {
      t,
      BUDGET_MIN,
      BUDGET_MAX,
      BUDGET_STEP,
      budget,
      recommendations,
      totalCost,
      budgetRemaining,
      unfundedCount,
      loading,
      error,
      submitting,
      confirmation,
      hasCandidates,
      canPlaceOrder,
      sliderFillStyle,
      formatMoney,
      placeOrder,
      translateProductName,
      translateWarehouse
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem 1.75rem;
}

.budget-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.budget-amount {
  font-size: 2.25rem;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  border-radius: 6px;
  background: linear-gradient(
    to right,
    #3b82f6 0%,
    #3b82f6 var(--fill-percent),
    #e2e8f0 var(--fill-percent),
    #e2e8f0 100%
  );
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #2563eb;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.3);
  cursor: pointer;
  transition: transform 0.15s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  transform: scale(1.12);
}

.budget-slider::-moz-range-thumb {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #2563eb;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.3);
  cursor: pointer;
}

.budget-slider:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 4px;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 0.75rem;
  font-size: 0.8125rem;
  color: #94a3b8;
}

.budget-help {
  color: #64748b;
  text-align: center;
}

.order-confirmation {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.875rem 1.25rem;
  margin-bottom: 1.25rem;
  border: 1px solid #a7f3d0;
  border-left: 4px solid #059669;
  border-radius: 8px;
  background: #ecfdf5;
  color: #065f46;
  font-size: 0.9375rem;
}

.order-confirmation a {
  color: #047857;
  font-weight: 600;
}

.place-order-btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 0.9375rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.col-sku { width: 100px; }
.col-name { width: 220px; }
.col-warehouse { width: 140px; }
.col-num { width: 105px; }
.col-trend { width: 120px; }
.col-money { width: 115px; }
.col-lead { width: 110px; }

.sku {
  font-weight: 600;
  color: #0f172a;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.qty {
  font-weight: 700;
  color: #0f172a;
}

th.col-num,
th.col-money,
th.col-lead {
  text-align: right;
}

.empty-state {
  padding: 2.5rem 1rem;
  text-align: center;
  color: #64748b;
}

.unfunded-note {
  margin-top: 0.875rem;
  padding-top: 0.875rem;
  border-top: 1px solid #e2e8f0;
  font-size: 0.875rem;
  color: #64748b;
}
</style>
