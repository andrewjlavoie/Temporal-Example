# Temporal Technical Exercise — Andrew Lavoie

This submission implements the e-commerce order flow and the rewards program.
This demo showcases a Saga implementation and the Workflow Entity concepts.

| | E-Commerce (`/ecommerce`) | Rewards (`/rewards`) |
|---|---|---|
| **Pattern** | Bounded saga with compensation | Long-running entity workflow |
| **Lifespan** | Seconds to minutes | Days to years |
| **Completion** | Always terminates (success or fully compensated) | Runs until the customer leaves |
| **Key primitives** | Activities, per-service retry policies, heartbeats, compensating transactions | Signals, Queries, Continue-As-New, wait conditions |
| **Workflow ID** | One-time process key (`order-{id}`) | Long-lived entity key (`rewards-customer-{id}`) |

---

## Use Case 1: E-Commerce Order Flow

An order placement workflow implementing the **Saga pattern**. Four steps execute sequentially — payment, inventory, shipping, notification — and if any step fails, compensating transactions undo the completed work in reverse order.

```
Client ──▶ OrderWorkflow(order)
             │
             ├─ 1. process_payment()    ──▶ Payment Service
             ├─ 2. reserve_inventory()  ──▶ Inventory Service
             ├─ 3. ship_package()       ──▶ Shipping Service
             └─ 4. notify_customer()    ──▶ Notification Service

           On failure at any step:
             ├─ cancel_shipment()       (if shipping started)
             ├─ release_inventory()     (if inventory reserved)
             └─ refund_payment()        (if payment processed)
```

## Use Case 2: Rewards Program

A long-running **entity workflow** where one workflow instance represents one customer's lifetime membership. The workflow runs indefinitely, responding to Signals (earn points, redeem, leave) and answering Queries (current tier, full status).

```
Client ──Signal──▶ RewardsWorkflow (runs indefinitely)
       ◀─Query──┤   │
                 │   ├─ State: {points, level, history}
                 │   ├─ on add_points  → update points, evaluate tier
                 │   ├─ on redeem      → validate & deduct points
                 │   ├─ on leave       → run offboarding, complete
                 │   └─ every 1000 events → Continue-As-New
```
---

## Running It

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), and a running Temporal server.

```bash
# Install dependencies
uv sync

# Start Temporal dev server (separate terminal)
temporal server start-dev

# E-Commerce Demo
uv run python -m ecommerce.worker          # Terminal A: start worker
uv run python -m ecommerce.starter          # Terminal B: happy path
uv run python -m ecommerce.starter --fail-at shipping   # compensation demo

# Rewards Demo
uv run python -m rewards.worker             # Terminal A: start worker
uv run python -m rewards.starter            # Terminal B: interactive mode
uv run python -m rewards.starter --scenario quick-demo   # automated walkthrough
```

The `--scenario quick-demo` flag runs a scripted sequence: enroll a customer, earn points through Gold to Platinum, redeem, and leave — useful for a non-interactive walkthrough.

---

