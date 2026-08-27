<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? 'Purchase Order' : 'Create Purchase Order' }}
            </h3>
            <button class="close-button" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div v-if="backlogItem" class="item-summary">
              <div class="summary-item">
                <span class="summary-label">Order</span>
                <span class="summary-value">{{ backlogItem.order_id }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">SKU</span>
                <span class="summary-value">{{ backlogItem.item_sku }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Item</span>
                <span class="summary-value">{{ backlogItem.item_name }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Shortage</span>
                <span class="summary-value shortage">{{ shortage }} units</span>
              </div>
            </div>

            <!-- View mode: read-only detail of the existing PO -->
            <template v-if="mode === 'view'">
              <div v-if="loading" class="state-message">Loading purchase order...</div>
              <div v-else-if="error" class="state-message error">{{ error }}</div>
              <div v-else-if="purchaseOrder" class="detail-list">
                <div class="detail-row">
                  <span class="detail-label">PO Number</span>
                  <span class="detail-value strong">{{ purchaseOrder.id }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Supplier</span>
                  <span class="detail-value">{{ purchaseOrder.supplier_name }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Quantity</span>
                  <span class="detail-value">{{ purchaseOrder.quantity }} units</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Unit Cost</span>
                  <span class="detail-value">{{ formatMoney(purchaseOrder.unit_cost) }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Total Cost</span>
                  <span class="detail-value strong">
                    {{ formatMoney(purchaseOrder.quantity * purchaseOrder.unit_cost) }}
                  </span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Expected Delivery</span>
                  <span class="detail-value">{{ formatDate(purchaseOrder.expected_delivery_date) }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Status</span>
                  <span class="status-badge">{{ purchaseOrder.status }}</span>
                </div>
                <div v-if="purchaseOrder.notes" class="detail-row notes-row">
                  <span class="detail-label">Notes</span>
                  <span class="detail-value">{{ purchaseOrder.notes }}</span>
                </div>
              </div>
            </template>

            <!-- Create mode -->
            <template v-else>
              <div class="po-form">
                <div class="form-group">
                  <label for="po-supplier">Supplier</label>
                  <input
                    id="po-supplier"
                    v-model="form.supplierName"
                    type="text"
                    class="po-input"
                    placeholder="Supplier name"
                  />
                </div>

                <div class="form-row">
                  <div class="form-group">
                    <label for="po-quantity">Quantity</label>
                    <input
                      id="po-quantity"
                      v-model.number="form.quantity"
                      type="number"
                      min="1"
                      class="po-input"
                    />
                  </div>

                  <div class="form-group">
                    <label for="po-unit-cost">Unit Cost (USD)</label>
                    <input
                      id="po-unit-cost"
                      v-model.number="form.unitCost"
                      type="number"
                      min="0"
                      step="0.01"
                      class="po-input"
                    />
                  </div>

                  <div class="form-group">
                    <label for="po-delivery">Expected Delivery</label>
                    <input
                      id="po-delivery"
                      v-model="form.expectedDeliveryDate"
                      type="date"
                      class="po-input"
                    />
                  </div>
                </div>

                <div class="form-group">
                  <label for="po-notes">Notes</label>
                  <textarea
                    id="po-notes"
                    v-model="form.notes"
                    class="po-input po-textarea"
                    rows="2"
                    placeholder="Optional"
                  ></textarea>
                </div>

                <div class="line-total">
                  <span>Total Cost</span>
                  <span class="line-total-value">{{ formatMoney(lineTotal) }}</span>
                </div>

                <div v-if="error" class="state-message error">{{ error }}</div>
              </div>
            </template>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" @click="close">Close</button>
            <button
              v-if="mode !== 'view'"
              class="btn-primary"
              :disabled="!canSubmit"
              @click="submit"
            >
              {{ submitting ? 'Creating...' : 'Create Purchase Order' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const DEFAULT_LEAD_TIME_DAYS = 14

export default {
  name: 'PurchaseOrderModal',
  props: {
    isOpen: {
      type: Boolean,
      required: true
    },
    backlogItem: {
      type: Object,
      default: null
    },
    mode: {
      type: String,
      default: 'create'
    }
  },
  emits: ['close', 'po-created'],
  setup(props, { emit }) {
    const { currentLocale } = useI18n()

    const purchaseOrder = ref(null)
    const loading = ref(false)
    const submitting = ref(false)
    const error = ref(null)

    const form = ref({
      supplierName: '',
      quantity: 0,
      unitCost: 0,
      expectedDeliveryDate: '',
      notes: ''
    })

    const shortage = computed(() => {
      if (!props.backlogItem) return 0
      return Math.abs(props.backlogItem.quantity_needed - props.backlogItem.quantity_available)
    })

    const lineTotal = computed(() => {
      const qty = Number(form.value.quantity) || 0
      const cost = Number(form.value.unitCost) || 0
      return qty * cost
    })

    const canSubmit = computed(() => {
      return (
        !submitting.value &&
        !!props.backlogItem &&
        form.value.supplierName.trim().length > 0 &&
        Number(form.value.quantity) > 0 &&
        Number(form.value.unitCost) >= 0 &&
        !!form.value.expectedDeliveryDate
      )
    })

    // Currency follows the app-wide locale, matching the rest of the dashboard.
    const formatMoney = (amount) => {
      const currency = currentLocale.value === 'ja' ? 'JPY' : 'USD'
      return formatCurrencyWithDecimals(amount, currency, 2)
    }

    // Built from local parts, not toISOString(), which shifts to UTC and can
    // land the default delivery date on the wrong day late in the evening.
    const toInputDate = (date) => {
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      return `${date.getFullYear()}-${month}-${day}`
    }

    const formatDate = (dateString) => {
      if (!dateString) return '-'
      // A bare YYYY-MM-DD parses as UTC midnight, which renders as the previous
      // day west of Greenwich. Pin it to local midnight so the date shown back
      // is the date that was picked.
      const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(dateString)
      const date = new Date(isDateOnly ? `${dateString}T00:00:00` : dateString)
      if (isNaN(date.getTime())) return dateString
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    const resetForm = () => {
      const delivery = new Date()
      delivery.setDate(delivery.getDate() + DEFAULT_LEAD_TIME_DAYS)
      form.value = {
        supplierName: '',
        // Default to covering exactly the shortage - the most common case.
        quantity: shortage.value,
        unitCost: 0,
        expectedDeliveryDate: toInputDate(delivery),
        notes: ''
      }
    }

    const loadPurchaseOrder = async () => {
      if (!props.backlogItem) return
      loading.value = true
      error.value = null
      try {
        purchaseOrder.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
      } catch (err) {
        error.value = 'Failed to load purchase order: ' + err.message
        purchaseOrder.value = null
      } finally {
        loading.value = false
      }
    }

    const submit = async () => {
      if (!canSubmit.value) return
      submitting.value = true
      error.value = null
      try {
        const created = await api.createPurchaseOrder({
          backlog_item_id: props.backlogItem.id,
          supplier_name: form.value.supplierName.trim(),
          quantity: Number(form.value.quantity),
          unit_cost: Number(form.value.unitCost),
          expected_delivery_date: form.value.expectedDeliveryDate,
          notes: form.value.notes.trim() || null
        })
        emit('po-created', created)
      } catch (err) {
        error.value = err.response?.data?.detail || 'Failed to create purchase order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    const close = () => {
      emit('close')
    }

    // Re-seed on every open: the parent keeps this component mounted and only
    // swaps isOpen/backlogItem, so state from the previous item would linger.
    watch(
      () => [props.isOpen, props.mode, props.backlogItem],
      () => {
        if (!props.isOpen) return
        error.value = null
        purchaseOrder.value = null
        if (props.mode === 'view') {
          loadPurchaseOrder()
        } else {
          resetForm()
        }
      },
      { immediate: true }
    )

    return {
      purchaseOrder,
      loading,
      submitting,
      error,
      form,
      shortage,
      lineTotal,
      canSubmit,
      formatMoney,
      formatDate,
      submit,
      close
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 90%;
  max-width: 640px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  border-bottom: 2px solid #e2e8f0;
}

.modal-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  padding: 2rem;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  padding: 1.5rem 2rem;
  border-top: 2px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

.btn-secondary {
  padding: 0.75rem 1.5rem;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Backlog item summary */
.item-summary {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  background: #f8fafc;
  border-radius: 12px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  color: #64748b;
}

.summary-value {
  font-size: 0.95rem;
  font-weight: 600;
  color: #0f172a;
}

.summary-value.shortage {
  color: #dc2626;
}

/* Create form */
.po-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-row {
  display: flex;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}

label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #475569;
}

.po-input {
  padding: 0.75rem;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.95rem;
  font-family: inherit;
  transition: border-color 0.2s ease;
  width: 100%;
}

.po-input:focus {
  outline: none;
  border-color: #2563eb;
}

.po-textarea {
  resize: vertical;
}

.line-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border-radius: 8px;
  font-weight: 600;
  color: #475569;
}

.line-total-value {
  font-size: 1.25rem;
  color: #0f172a;
}

/* View mode */
.detail-list {
  display: flex;
  flex-direction: column;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 0.875rem 0;
  border-bottom: 1px solid #e2e8f0;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row.notes-row {
  align-items: flex-start;
}

.detail-label {
  font-size: 0.875rem;
  color: #64748b;
  font-weight: 600;
}

.detail-value {
  font-size: 0.95rem;
  color: #0f172a;
  text-align: right;
}

.detail-value.strong {
  font-weight: 700;
}

.status-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.625rem;
  border-radius: 4px;
  background: #dbeafe;
  color: #1e40af;
}

.state-message {
  padding: 1rem;
  text-align: center;
  color: #64748b;
  font-size: 0.95rem;
}

.state-message.error {
  color: #991b1b;
  background: #fef2f2;
  border-radius: 8px;
  text-align: left;
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.9);
}
</style>
