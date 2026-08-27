from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, tasks

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

def customer_orders() -> list:
    """Orders placed by customers, excluding internal restocking orders.

    Restocking orders live in the same `orders` list so they share ID and
    order-number sequences, but they are not customer demand - keeping them out
    of the order list, dashboard totals and reports means submitting a restock
    never distorts those figures.
    """
    return [order for order in orders if order.get('order_type') != 'restock']

def restocking_orders() -> list:
    """Internal restocking orders, newest first"""
    restock = [order for order in orders if order.get('order_type') == 'restock']
    return sorted(restock, key=lambda order: order.get('order_date', ''), reverse=True)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str
    lead_time_days: int

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None
    order_type: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False
    purchase_order_id: Optional[str] = None

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class Task(BaseModel):
    id: str
    title: str
    priority: str
    dueDate: str
    status: str

class CreateTaskRequest(BaseModel):
    title: str
    priority: str = 'medium'
    dueDate: str

class RestockRecommendation(BaseModel):
    item_sku: str
    item_name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    forecasted_demand: int
    trend: str
    unit_cost: float
    recommended_quantity: int
    line_cost: float
    lead_time_days: int
    urgency: float

class RestockRecommendationsResponse(BaseModel):
    budget: float
    recommendations: List[RestockRecommendation]
    total_cost: float
    budget_remaining: float
    items_recommended: int
    unfunded_count: int

class RestockOrderLineRequest(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: float

class CreateRestockOrderRequest(BaseModel):
    items: List[RestockOrderLineRequest]
    budget: float

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(customer_orders(), warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/restocking/recommendations", response_model=RestockRecommendationsResponse)
def get_restock_recommendations(
    budget: float = 0,
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Recommend forecast items to restock within an available budget.

    Candidates are demand forecasts joined to inventory by SKU. Each candidate's
    shortfall is the forecasted demand it cannot currently cover, and its urgency
    is that shortfall measured against its reorder point. Candidates are filled
    greedily from most to least urgent until the budget runs out.
    """
    if budget < 0:
        raise HTTPException(status_code=400, detail="Budget cannot be negative")

    inventory_by_sku = {item["sku"]: item for item in apply_filters(inventory_items, warehouse, category)}

    candidates = []
    for forecast in demand_forecasts:
        item = inventory_by_sku.get(forecast["item_sku"])
        if not item:
            continue

        shortfall = max(forecast["forecasted_demand"] - item["quantity_on_hand"], 0)
        if shortfall == 0:
            # Stock already covers the forecast - nothing to buy
            continue

        candidates.append({
            "item_sku": item["sku"],
            "item_name": item["name"],
            "category": item["category"],
            "warehouse": item["warehouse"],
            "quantity_on_hand": item["quantity_on_hand"],
            "reorder_point": item["reorder_point"],
            "forecasted_demand": forecast["forecasted_demand"],
            "trend": forecast["trend"],
            "unit_cost": item["unit_cost"],
            "lead_time_days": item["lead_time_days"],
            "shortfall": shortfall,
            "urgency": round(shortfall / max(item["reorder_point"], 1), 3)
        })

    # Most urgent first; cheaper units win ties so the budget stretches further
    candidates.sort(key=lambda c: (-c["urgency"], c["unit_cost"]))

    recommendations = []
    remaining = budget
    for candidate in candidates:
        affordable = int(remaining // candidate["unit_cost"])
        quantity = min(candidate["shortfall"], affordable)
        if quantity <= 0:
            continue

        line_cost = round(quantity * candidate["unit_cost"], 2)
        remaining = round(remaining - line_cost, 2)

        recommendation = {key: value for key, value in candidate.items() if key != "shortfall"}
        recommendation["recommended_quantity"] = quantity
        recommendation["line_cost"] = line_cost
        recommendations.append(recommendation)

    total_cost = round(sum(r["line_cost"] for r in recommendations), 2)

    return {
        "budget": round(budget, 2),
        "recommendations": recommendations,
        "total_cost": total_cost,
        "budget_remaining": round(budget - total_cost, 2),
        "items_recommended": len(recommendations),
        "unfunded_count": len(candidates) - len(recommendations)
    }

@app.get("/api/restocking/orders", response_model=List[Order])
def get_restocking_orders():
    """Get submitted restocking orders, newest first"""
    return restocking_orders()

@app.post("/api/restocking/orders", response_model=Order, status_code=201)
def create_restocking_order(request: CreateRestockOrderRequest):
    """Submit a restocking order for the selected items"""
    if not request.items:
        raise HTTPException(status_code=400, detail="A restocking order must contain at least one item")

    inventory_by_sku = {item["sku"]: item for item in inventory_items}

    line_items = []
    lead_times = []
    warehouses = set()
    categories = set()

    for line in request.items:
        if line.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Quantity for {line.sku} must be greater than zero"
            )

        item = inventory_by_sku.get(line.sku)
        if not item:
            raise HTTPException(status_code=400, detail=f"Unknown SKU: {line.sku}")

        line_items.append({
            "sku": line.sku,
            "name": line.name,
            "quantity": line.quantity,
            "unit_price": line.unit_price
        })
        lead_times.append(item["lead_time_days"])
        warehouses.add(item["warehouse"])
        categories.add(item["category"])

    # The whole order lands when its slowest item does
    lead_time_days = max(lead_times)
    order_date = datetime.now()
    expected_delivery = order_date + timedelta(days=lead_time_days)

    next_id = max(int(order["id"]) for order in orders) + 1
    new_order = {
        "id": str(next_id),
        "order_number": f"RST-{order_date.year}-{next_id:04d}",
        "customer": "Internal Restock",
        "items": line_items,
        "status": "Processing",
        "order_date": order_date.isoformat(timespec='seconds'),
        "expected_delivery": expected_delivery.isoformat(timespec='seconds'),
        "total_value": round(sum(line["quantity"] * line["unit_price"] for line in line_items), 2),
        "actual_delivery": None,
        "warehouse": warehouses.pop() if len(warehouses) == 1 else "Multiple",
        "category": categories.pop() if len(categories) == 1 else "Multiple",
        "order_type": "restock"
    }

    # Deliberate in-place append: mock data is in-memory only, so submitted
    # orders live until the server restarts. customer_orders() keeps them out
    # of the customer order list, dashboard and reports.
    orders.append(new_order)

    return new_order

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        matching_po = next(
            (po for po in purchase_orders if po["backlog_item_id"] == item["id"]),
            None
        )
        item_dict["has_purchase_order"] = matching_po is not None
        item_dict["purchase_order_id"] = matching_po["id"] if matching_po else None
        result.append(item_dict)
    return result

@app.post("/api/purchase-orders", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(request: CreatePurchaseOrderRequest):
    """Raise a purchase order against a backlog item"""
    item = next((b for b in backlog_items if b["id"] == request.backlog_item_id), None)
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown backlog item: {request.backlog_item_id}"
        )

    existing = next(
        (po for po in purchase_orders if po["backlog_item_id"] == request.backlog_item_id),
        None
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Backlog item {request.backlog_item_id} already has purchase order {existing['id']}"
        )

    if request.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    if request.unit_cost < 0:
        raise HTTPException(status_code=400, detail="Unit cost cannot be negative")

    # PO ids are sequential over the in-memory list, which starts empty on boot.
    next_id = max((int(po["id"].split("-")[-1]) for po in purchase_orders), default=0) + 1
    new_po = {
        "id": f"PO-{next_id:04d}",
        "backlog_item_id": request.backlog_item_id,
        "supplier_name": request.supplier_name,
        "quantity": request.quantity,
        "unit_cost": request.unit_cost,
        "expected_delivery_date": request.expected_delivery_date,
        "status": "Pending",
        "created_date": datetime.now().isoformat(timespec='seconds'),
        "notes": request.notes
    }

    # In-memory only, like every other write in this app - POs live until restart.
    purchase_orders.append(new_po)

    return new_po

@app.get("/api/purchase-orders/{backlog_item_id}", response_model=PurchaseOrder)
def get_purchase_order_by_backlog_item(backlog_item_id: str):
    """Get the purchase order raised against a backlog item"""
    po = next((p for p in purchase_orders if p["backlog_item_id"] == backlog_item_id), None)
    if not po:
        raise HTTPException(
            status_code=404,
            detail=f"No purchase order for backlog item {backlog_item_id}"
        )
    return po

@app.get("/api/tasks", response_model=List[Task])
def get_tasks():
    """Get user tasks, newest first"""
    return list(reversed(tasks))

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(request: CreateTaskRequest):
    """Create a task"""
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="Task title cannot be empty")

    # String ids keep API tasks distinguishable from the integer-id mock tasks
    # in useAuth - App.vue routes deletes and toggles by testing which list an
    # id belongs to, so an overlapping id would send the call to the wrong one.
    next_id = max((int(t["id"].split("-")[-1]) for t in tasks), default=0) + 1
    new_task = {
        "id": f"task-{next_id}",
        "title": request.title.strip(),
        "priority": request.priority,
        "dueDate": request.dueDate,
        "status": "pending"
    }
    tasks.append(new_task)
    return new_task

@app.patch("/api/tasks/{task_id}", response_model=Task)
def toggle_task(task_id: str):
    """Toggle a task between pending and completed"""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")

    task["status"] = "pending" if task["status"] == "completed" else "completed"
    return task

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    """Delete a task"""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")

    tasks.remove(task)
    return {"deleted": task_id}

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(customer_orders(), warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in customer_orders():
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in customer_orders():
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
