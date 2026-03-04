"""Data models for the e-commerce order workflow."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAYMENT_PROCESSED = "PAYMENT_PROCESSED"
    INVENTORY_RESERVED = "INVENTORY_RESERVED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


@dataclass
class OrderItem:
    product_id: str
    product_name: str
    quantity: int
    unit_price: float

    @property
    def total_price(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class OrderInput:
    """Input to the order workflow.
    The Workflow ID will be 'order-{order_id}' = exactly-once processing
    = starting the same order twice should not be possible.
    """

    order_id: str
    customer_id: str
    customer_email: str
    items: list[OrderItem]
    shipping_address: str
    payment_method: str = "credit_card"
    # For demo: inject failure at a specific step to show compensation
    fail_at_step: str | None = None

    @property
    def total_amount(self) -> float:
        return sum(item.total_price for item in self.items)


@dataclass
class PaymentResult:
    transaction_id: str
    amount_charged: float
    status: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class InventoryResult:
    reservation_id: str
    items_reserved: list[str]
    warehouse_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ShippingResult:
    tracking_number: str
    carrier: str
    estimated_delivery: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class NotificationResult:
    notification_id: str
    channel: str
    status: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
