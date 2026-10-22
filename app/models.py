"""Database tables.

Limits and material names are copied onto each QC result and production component
when the record is saved, so later changes in Setup never rewrite past records.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = {
    "admin": "Administrator",
    "qc": "Quality team",
    "operator": "Plant operators",
    "management": "Management",
}

DECISIONS = ["Accepted", "On hold", "Rejected"]

CATEGORIES = [
    "Cement",
    "Supplementary cementitious material",
    "Coarse aggregate",
    "Fine aggregate",
    "Coating material",
    "Coated aggregate",
    "Ground cementitious material",
    "Fibre",
    "Admixture",
    "Water",
    "Packaging",
    "Other",
]
# Categories offered for a batching tolerance (packaging is not batched).
TOLERANCE_CATEGORIES = [c for c in CATEGORIES if c != "Packaging"]

UNITS = ["kg", "t", "L", "mL", "bags", "m³"]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def display(self) -> str:
        return self.full_name or self.username


class PlantSettings(Base):
    """Single row (id = 1)."""
    __tablename__ = "plant_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    plant_name: Mapped[str] = mapped_column(String(200), default="")
    plant_address: Mapped[str] = mapped_column(Text, default="")
    tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_lines: Mapped[str] = mapped_column(Text, default="")  # one per line
    shifts: Mapped[str] = mapped_column(Text, default="")  # one per line
    # Batching tolerance per material category, JSON {category: ± % of planned}. When saved, it replaces
    # the single tolerance_pct above (kept for databases set up before per-category tolerances).
    category_tolerances: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def product_line_list(self) -> list[str]:
        return [x.strip() for x in (self.product_lines or "").splitlines() if x.strip()]

    @property
    def shift_list(self) -> list[str]:
        return [x.strip() for x in (self.shifts or "").splitlines() if x.strip()]

    @property
    def tolerance_map(self) -> dict[str, float]:
        import json
        try:
            raw = json.loads(self.category_tolerances) if self.category_tolerances else None
        except ValueError:
            raw = None
        return {k: float(v) for k, v in (raw or {}).items() if v is not None}

    @property
    def per_category(self) -> bool:
        return bool(self.category_tolerances)

    def tolerance_for(self, category: str | None) -> float | None:
        """± % of planned weight that applies to a material of this category, or None if not set."""
        if self.per_category:
            return self.tolerance_map.get(category or "")
        return self.tolerance_pct

    @property
    def tolerance_set(self) -> bool:
        return bool(self.tolerance_map) if self.per_category else self.tolerance_pct is not None


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(60))
    supplier: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Stock is kept in this unit; quantities in other units of the same kind are converted (kg/t, mL/L).
    stock_unit: Mapped[str | None] = mapped_column(String(20), nullable=True, default="kg")
    reorder_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Coated aggregate only: coating material dosage target, % of the aggregate mass coated.
    coating_target_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    parameters: Mapped[list["QCParameter"]] = relationship(
        back_populates="material", order_by="QCParameter.sort_order, QCParameter.id"
    )


class QCParameter(Base):
    __tablename__ = "test_parameters"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(40), default="")
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(240), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Added with the IS 383 test sets (nullable so existing databases upgrade in place).
    group_name: Mapped[str | None] = mapped_column(String(60), nullable=True, default="")
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True, default="Every lot")
    calc: Mapped[str | None] = mapped_column(String(30), nullable=True, default="")
    value_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="number")
    sieve_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default="")

    material: Mapped[Material] = relationship(back_populates="parameters")

    @property
    def periodic(self) -> bool:
        return (self.frequency or "Every lot") != "Every lot"
    __table_args__ = (UniqueConstraint("material_id", "name", name="uq_param_material_name"),)


class QCTest(Base):
    __tablename__ = "qc_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    test_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    test_date: Mapped[date] = mapped_column(Date, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    material_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60), default="")
    supplier: Mapped[str] = mapped_column(String(160), default="")
    lot_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    vehicle_no: Mapped[str] = mapped_column(String(40), default="")
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(20), default="")
    overall: Mapped[str] = mapped_column(String(20))  # pass / fail / incomplete
    decision: Mapped[str] = mapped_column(String(20), index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decision_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["QCResult"]] = relationship(
        back_populates="test", cascade="all, delete-orphan", order_by="QCResult.id"
    )
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    decision_by: Mapped[User | None] = relationship(foreign_keys=[decision_by_id])


class QCResult(Base):
    __tablename__ = "qc_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("qc_tests.id", ondelete="CASCADE"), index=True)
    parameter_id: Mapped[int | None] = mapped_column(ForeignKey("test_parameters.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(40), default="")
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String(240), default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # pass / fail / missing / nolimit / skipped
    group_name: Mapped[str | None] = mapped_column(String(60), nullable=True, default="")
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True, default="Every lot")
    value_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="number")
    workings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of worksheet inputs and results

    test: Mapped[QCTest] = relationship(back_populates="results")


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    product_line: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    components: Mapped[list["RecipeComponent"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeComponent.id"
    )


class RecipeComponent(Base):
    __tablename__ = "recipe_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="kg")

    recipe: Mapped[Recipe] = relationship(back_populates="components")
    material: Mapped[Material] = relationship()


class ProductionRecord(Base):
    __tablename__ = "production_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prod_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(40), default="")
    product_line: Mapped[str] = mapped_column(String(120), index=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    recipe_name: Mapped[str] = mapped_column(String(160), default="")
    bags: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bag_target_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_actual_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_dev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # ok / over / notol / nodata
    lot_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    remarks: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual / csv / api
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    components: Mapped[list["ProductionComponent"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", order_by="ProductionComponent.id"
    )
    created_by: Mapped[User | None] = relationship()


class ProductionComponent(Base):
    __tablename__ = "production_components"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("production_records.id", ondelete="CASCADE"), index=True
    )
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    material_name: Mapped[str] = mapped_column(String(160))
    lot_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    lot_decision: Mapped[str] = mapped_column(String(30), default="")
    lot_test_id: Mapped[int | None] = mapped_column(ForeignKey("qc_tests.id"), nullable=True)
    planned: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="kg")
    dev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)   # for this material's category

    record: Mapped[ProductionRecord] = relationship(back_populates="components")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class AIReview(Base):
    __tablename__ = "ai_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(80))
    qc_count: Mapped[int] = mapped_column(Integer, default=0)
    production_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text)

    created_by: Mapped[User] = relationship()


# ================================================================ dispatch

DELIVERY_STATUSES = ["Dispatched", "Delivered", "Returned", "Cancelled"]
ORDER_STATUSES = ["Open", "Closed", "Cancelled"]
VEHICLE_TYPES = ["Truck", "Mixer on wheels", "Other"]


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    gstin: Mapped[str] = mapped_column(String(30), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    sites: Mapped[list["Site"]] = relationship(back_populates="customer", order_by="Site.name")


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(Text, default="")
    contact_person: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer] = relationship(back_populates="sites")
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_site_customer_name"),)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    reg_no: Mapped[str] = mapped_column(String(40), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConcreteGrade(Base):
    """Concrete grade with acceptance values entered from the specification. All values optional."""
    __tablename__ = "concrete_grades"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    specified_strength_mpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    acceptance_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_individual_mpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_mean_mpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference: Mapped[str] = mapped_column(String(240), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_date: Mapped[date] = mapped_column(Date)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("concrete_grades.id"), nullable=True)
    # Mix design for the bags packed for this order: kg of each material per bag set (a recipe in Setup).
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    quantity_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    customer_ref: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="Open", index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    customer: Mapped[Customer] = relationship()
    site: Mapped[Site | None] = relationship()
    grade: Mapped[ConcreteGrade | None] = relationship()
    recipe: Mapped[Recipe | None] = relationship()
    dispatches: Mapped[list["Dispatch"]] = relationship(back_populates="order", order_by="Dispatch.dispatch_date")


class Dispatch(Base):
    __tablename__ = "dispatches"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    dispatch_date: Mapped[date] = mapped_column(Date, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    truck_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    mixer_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    driver_name: Mapped[str] = mapped_column(String(120), default="")
    driver_phone: Mapped[str] = mapped_column(String(40), default="")
    planned_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Dispatched", index=True)
    departed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[str] = mapped_column(String(120), default="")
    delivered_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    delivery_remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    delivered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    order: Mapped[Order] = relationship(back_populates="dispatches")
    truck: Mapped[Vehicle | None] = relationship(foreign_keys=[truck_id])
    mixer: Mapped[Vehicle | None] = relationship(foreign_keys=[mixer_id])
    items: Mapped[list["DispatchItem"]] = relationship(back_populates="dispatch", cascade="all, delete-orphan",
                                                       order_by="DispatchItem.id")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class DispatchItem(Base):
    """Bags from one production record loaded on one dispatch."""
    __tablename__ = "dispatch_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id", ondelete="CASCADE"), index=True)
    production_id: Mapped[int] = mapped_column(ForeignKey("production_records.id"), index=True)
    bags: Mapped[int] = mapped_column(Integer)

    dispatch: Mapped[Dispatch] = relationship(back_populates="items")
    production: Mapped[ProductionRecord] = relationship()


# ================================================================ strength tests

class CubeSample(Base):
    """Specimens cast from one delivery (or at the plant), tested at one or more ages."""
    __tablename__ = "cube_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    sample_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatches.id"), nullable=True, index=True)
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("concrete_grades.id"), nullable=True)
    cast_date: Mapped[date] = mapped_column(Date, index=True)
    cast_location: Mapped[str] = mapped_column(String(120), default="")
    specimen_type: Mapped[str] = mapped_column(String(40), default="Cube")
    specimen_size_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_ages: Mapped[str] = mapped_column(String(60), default="")  # e.g. "7,28" as entered
    specimens_per_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fresh_notes: Mapped[str] = mapped_column(Text, default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dispatch: Mapped[Dispatch | None] = relationship()
    grade: Mapped[ConcreteGrade | None] = relationship()
    results: Mapped[list["CubeResult"]] = relationship(back_populates="sample", cascade="all, delete-orphan",
                                                       order_by="CubeResult.age_days, CubeResult.specimen_no")
    created_by: Mapped[User | None] = relationship()

    @property
    def age_list(self) -> list[int]:
        out = []
        for part in (self.test_ages or "").replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and int(part) > 0:
                out.append(int(part))
        return sorted(set(out))


class CubeResult(Base):
    __tablename__ = "cube_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("cube_samples.id", ondelete="CASCADE"), index=True)
    age_days: Mapped[int] = mapped_column(Integer)
    test_date: Mapped[date] = mapped_column(Date)
    specimen_no: Mapped[str] = mapped_column(String(20), default="")
    mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_kn: Mapped[float | None] = mapped_column(Float, nullable=True)
    strength_mpa: Mapped[float] = mapped_column(Float)
    tested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    sample: Mapped[CubeSample] = relationship(back_populates="results")


# ================================================================ stock

class StockAdjustment(Base):
    """Manual stock correction (e.g. after a physical count). Positive adds, negative removes."""
    __tablename__ = "stock_adjustments"
    id: Mapped[int] = mapped_column(primary_key=True)
    adj_date: Mapped[date] = mapped_column(Date)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    lot_no: Mapped[str] = mapped_column(String(80), default="")
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    material: Mapped[Material] = relationship()
    created_by: Mapped[User | None] = relationship()


# ================================================================ NCR and equipment

NCR_SOURCES = ["Material QC", "Production", "Dispatch", "Strength test", "Customer complaint", "Internal audit", "Other"]
NCR_STATUSES = ["Open", "Action in progress", "Closed"]
CAL_RESULTS = ["Within limits", "Adjusted", "Out of limits"]


class NCR(Base):
    __tablename__ = "ncrs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ncr_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    raised_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    qc_test_id: Mapped[int | None] = mapped_column(ForeignKey("qc_tests.id"), nullable=True)
    production_id: Mapped[int | None] = mapped_column(ForeignKey("production_records.id"), nullable=True)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatches.id"), nullable=True)
    cube_sample_id: Mapped[int | None] = mapped_column(ForeignKey("cube_samples.id"), nullable=True)
    containment: Mapped[str] = mapped_column(Text, default="")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    corrective_action: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Open", index=True)
    verification: Mapped[str] = mapped_column(Text, default="")
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    raised_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    raised_by: Mapped[User | None] = relationship(foreign_keys=[raised_by_id])
    closed_by: Mapped[User | None] = relationship(foreign_keys=[closed_by_id])
    qc_test: Mapped[QCTest | None] = relationship()
    production: Mapped[ProductionRecord | None] = relationship()
    dispatch: Mapped[Dispatch | None] = relationship()
    cube_sample: Mapped[CubeSample | None] = relationship()


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(120), default="")
    make_model: Mapped[str] = mapped_column(String(160), default="")
    serial_no: Mapped[str] = mapped_column(String(80), default="")
    range_text: Mapped[str] = mapped_column(String(120), default="")
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="In use")
    notes: Mapped[str] = mapped_column(Text, default="")

    calibrations: Mapped[list["Calibration"]] = relationship(back_populates="equipment", cascade="all, delete-orphan",
                                                             order_by="Calibration.cal_date.desc()")


class Calibration(Base):
    __tablename__ = "calibrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), index=True)
    cal_date: Mapped[date] = mapped_column(Date)
    agency: Mapped[str] = mapped_column(String(160), default="")
    certificate_no: Mapped[str] = mapped_column(String(80), default="")
    result: Mapped[str] = mapped_column(String(30))
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    equipment: Mapped[Equipment] = relationship(back_populates="calibrations")


# ================================================================ plant process: coating, grinding, packing, site mixing

PROCESS_KINDS = {"coating": "Coating", "grinding": "Grinding"}
# Material categories allowed as inputs and as the output of each process.
PROCESS_INPUTS = {
    "coating": {"aggregate": ("Coarse aggregate",), "coating": ("Coating material", "Supplementary cementitious material")},
    "grinding": {"feed": ("Cement", "Supplementary cementitious material")},
}
PROCESS_OUTPUT = {"coating": "Coated aggregate", "grinding": "Ground cementitious material"}

# What each package may contain, by material category.
PACK_KINDS = {
    "Aggregate jumbo bag": ("Coated aggregate", "Coarse aggregate", "Fine aggregate"),
    "Cementitious jumbo bag": ("Cement", "Supplementary cementitious material", "Ground cementitious material"),
    "Fibre bag": ("Fibre",),
    "Admixture barrel": ("Admixture",),
}
PACK_STATUSES = ["Packed", "Loaded", "Used at site", "Returned", "Rejected"]


class ProcessBatch(Base):
    """One coating or grinding run. Its output is a lot of an in-house material with its own decision."""
    __tablename__ = "process_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    batch_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(40), default="")
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True)
    output_material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    output_material_name: Mapped[str] = mapped_column(String(160))
    output_lot_no: Mapped[str] = mapped_column(String(80), index=True)
    output_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_unit: Mapped[str] = mapped_column(String(20), default="kg")
    coating_pct: Mapped[float | None] = mapped_column(Float, nullable=True)   # coating mass / aggregate mass × 100
    blaine_m2kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    residue45_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Coating check, fixed when the batch is saved: target of the output material, deviation of the coating
    # mass from target % × aggregate mass, and the batching tolerance of the coating material's category.
    coating_target_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    coating_dev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    coating_tol_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    coating_status: Mapped[str | None] = mapped_column(String(20), nullable=True)   # ok / over / notol / notarget
    lot_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(30), default="On hold", index=True)
    decision_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    qc_test_id: Mapped[int | None] = mapped_column(ForeignKey("qc_tests.id"), nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    inputs: Mapped[list["ProcessInput"]] = relationship(back_populates="batch", cascade="all, delete-orphan",
                                                        order_by="ProcessInput.id")
    equipment: Mapped[Equipment | None] = relationship()
    output_material: Mapped[Material] = relationship()
    qc_test: Mapped[QCTest | None] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    decision_by: Mapped[User | None] = relationship(foreign_keys=[decision_by_id])


class ProcessInput(Base):
    __tablename__ = "process_inputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("process_batches.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))          # aggregate / coating / feed
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    material_name: Mapped[str] = mapped_column(String(160))
    lot_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    lot_decision: Mapped[str] = mapped_column(String(30), default="")
    lot_test_id: Mapped[int | None] = mapped_column(ForeignKey("qc_tests.id"), nullable=True)
    qty: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="kg")

    batch: Mapped[ProcessBatch] = relationship(back_populates="inputs")


class Pack(Base):
    """One jumbo bag, fibre bag or admixture barrel, packed for an order. Traced to its lots by its items."""
    __tablename__ = "packs"
    id: Mapped[int] = mapped_column(primary_key=True)
    pack_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    pack_date: Mapped[date] = mapped_column(Date, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    recipe_name: Mapped[str] = mapped_column(String(160), default="")
    net_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_dev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    batching_status: Mapped[str] = mapped_column(String(20), default="nodata")   # ok / over / notol / nodata
    lot_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="Packed", index=True)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatches.id"), nullable=True, index=True)
    site_mix_id: Mapped[int | None] = mapped_column(ForeignKey("site_mixes.id"), nullable=True, index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items: Mapped[list["PackItem"]] = relationship(back_populates="pack", cascade="all, delete-orphan",
                                                   order_by="PackItem.id")
    order: Mapped[Order] = relationship()
    dispatch: Mapped[Dispatch | None] = relationship()
    site_mix: Mapped["SiteMix | None"] = relationship(back_populates="packs", foreign_keys=[site_mix_id])
    created_by: Mapped[User | None] = relationship()


class PackItem(Base):
    __tablename__ = "pack_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    material_name: Mapped[str] = mapped_column(String(160))
    lot_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    lot_decision: Mapped[str] = mapped_column(String(30), default="")
    lot_test_id: Mapped[int | None] = mapped_column(ForeignKey("qc_tests.id"), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("process_batches.id"), nullable=True)
    planned: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="kg")
    dev_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)   # for this material's category

    pack: Mapped[Pack] = relationship(back_populates="items")


class SiteMix(Base):
    """What the mixer on wheels mixed at site from one dispatch."""
    __tablename__ = "site_mixes"
    id: Mapped[int] = mapped_column(primary_key=True)
    mix_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), index=True)
    mix_date: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    element: Mapped[str] = mapped_column(String(200), default="")
    volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    mixing_time_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    slump_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    concrete_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    ambient_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    cube_sample_id: Mapped[int | None] = mapped_column(ForeignKey("cube_samples.id"), nullable=True)
    supervisor: Mapped[str] = mapped_column(String(120), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    dispatch: Mapped[Dispatch] = relationship()
    packs: Mapped[list[Pack]] = relationship(back_populates="site_mix", foreign_keys="Pack.site_mix_id",
                                             order_by="Pack.pack_no")
    admixtures: Mapped[list["SiteMixAdmixture"]] = relationship(back_populates="mix", cascade="all, delete-orphan",
                                                                order_by="SiteMixAdmixture.id")
    cube_sample: Mapped[CubeSample | None] = relationship()
    created_by: Mapped[User | None] = relationship()


class SiteMixAdmixture(Base):
    __tablename__ = "site_mix_admixtures"
    id: Mapped[int] = mapped_column(primary_key=True)
    mix_id: Mapped[int] = mapped_column(ForeignKey("site_mixes.id", ondelete="CASCADE"), index=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"))
    dose: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="kg")

    mix: Mapped[SiteMix] = relationship(back_populates="admixtures")
    pack: Mapped[Pack] = relationship()
