"""Pydantic input schemas used across routers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginInput(BaseModel):
    email: str
    password: str


class OtpRequestInput(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class OtpVerifyInput(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    otp: str = Field(min_length=4, max_length=8)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    full_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=20)
    address: str = ""
    plan_id: str
    start_date: str
    payment_amount: float = Field(ge=0)
    payment_status: str = "PAID"
    payment_method: str = "UPI"
    notes: str = ""
    photo_url: Optional[str] = None


class MemberUpdateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    phone: Optional[str] = Field(default=None, min_length=6, max_length=20)
    address: Optional[str] = None
    notes: Optional[str] = None
    photo_url: Optional[str] = None


class RenewInput(BaseModel):
    plan_id: str
    start_date: Optional[str] = None
    payment_amount: Optional[float] = Field(default=None, ge=0)
    payment_status: str = "PAID"
    payment_method: str = "UPI"


class PlanInput(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    duration_months: int = Field(ge=1, le=36)
    price: float = Field(ge=0)
    description: str = ""
    active: bool = True


class PlanUpdateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = Field(default=None, min_length=2, max_length=60)
    duration_months: Optional[int] = Field(default=None, ge=1, le=36)
    price: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None
    active: Optional[bool] = None


class SettingsInput(BaseModel):
    gym_name: str
    gym_phone: str
    gym_address: str
    timezone: str = "Asia/Kolkata"
    expiry_reminder_days: int = Field(ge=1, le=30)
    grace_period_days: int = Field(ge=1, le=30)
    retention_days: int = Field(ge=1, le=3650)


class PaymentInput(BaseModel):
    member_id: str
    amount: float = Field(ge=0)
    method: str = "UPI"
    status: str = "PAID"
    notes: str = ""
    transaction_reference: Optional[str] = None
