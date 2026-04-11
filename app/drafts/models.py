from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    CLASSIFIED = "classified"
    NEEDS_ATTENTION = "needs_attention"
    READY_FOR_REVIEW = "ready_for_review"
    READY_FOR_MARKETPLACE = "ready_for_marketplace"
    OFFER_CREATED = "offer_created"
    PUBLISHED = "published"
    BLOCKED = "blocked"
    ERROR = "error"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceImage(BaseModel):
    id: str
    original_filename: str = Field(alias="originalFilename")
    storage_path: str = Field(alias="storagePath")
    mime_type: str = Field(alias="mimeType")
    order: int
    kind: str

    model_config = ConfigDict(populate_by_name=True)


class SourceData(BaseModel):
    images: list[SourceImage] = Field(default_factory=list)
    notes: str = ""
    user_input: dict[str, Any] = Field(default_factory=dict, alias="userInput")

    model_config = ConfigDict(populate_by_name=True)


class ListingData(BaseModel):
    title: str = ""
    subtitle: str = ""
    category_suggestion: str = Field(default="", alias="categorySuggestion")
    condition: str = ""
    brand: str = ""
    model: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    included_items: list[str] = Field(default_factory=list, alias="includedItems")
    issues: list[str] = Field(default_factory=list)
    description_html: str = Field(default="", alias="descriptionHtml")
    price_suggestion: float | None = Field(default=None, alias="priceSuggestion")
    shipping_suggestion: dict[str, Any] = Field(default_factory=dict, alias="shippingSuggestion")

    model_config = ConfigDict(populate_by_name=True)


class EbayDraftData(BaseModel):
    inventory_item_data: dict[str, Any] = Field(default_factory=dict, alias="inventoryItemData")
    offer_data: dict[str, Any] = Field(default_factory=dict, alias="offerData")
    inventory_item_key: str | None = Field(default=None, alias="inventoryItemKey")
    offer_id: str | None = Field(default=None, alias="offerId")

    model_config = ConfigDict(populate_by_name=True)


class MarketplaceData(BaseModel):
    ebay: EbayDraftData = Field(default_factory=EbayDraftData)


class WorkflowData(BaseModel):
    status: WorkflowStatus = WorkflowStatus.DRAFT
    needs_review: bool = Field(default=True, alias="needsReview")
    missing_information: list[str] = Field(default_factory=list, alias="missingInformation")
    last_updated_at: datetime = Field(default_factory=utc_now, alias="lastUpdatedAt")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class Draft(BaseModel):
    id: str
    sku: str
    source: SourceData = Field(default_factory=SourceData)
    listing: ListingData = Field(default_factory=ListingData)
    marketplace: MarketplaceData = Field(default_factory=MarketplaceData)
    workflow: WorkflowData = Field(default_factory=WorkflowData)

    model_config = ConfigDict(populate_by_name=True)
