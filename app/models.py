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
    "qc": "QC / lab",
    "operator": "Plant operator",
    "management": "Management (view only)",
}

DECISIONS = ["Accepted", "On hold", "Rejected"]

CATEGORIES = [
    "Cement",
    "Supplementary cementitious material",
    "Coarse aggregate",
    "Fine aggregate",
    "Coating material",
    "Admixture",
    "Water",
    "Packaging",
    "Other",
]

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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def product_line_list(self) -> list[str]:
        return [x.strip() for x in (self.product_lines or "").splitlines() if x.strip()]

    @property
    def shift_list(self) -> list[str]:
        return [x.strip() for x in (self.shifts or "").splitlines() if x.strip()]


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(60))
    supplier: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parameters: Mapped[list["QCParameter"]] = relationship(
        back_populates="material", order_by="QCParameter.sort_order, QCParameter.name"
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

    material: Mapped[Material] = relationship(back_populates="parameters")
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
    status: Mapped[str] = mapped_column(String(20))  # pass / fail / missing / nolimit

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
