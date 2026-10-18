"""Local copy of the CHG-0027 models (SPEC §7.16): `pam_cards` items and `connector.yaml` must validate.

Copied from SPEC.md CHG-0027 so the mock's tests do not import the backend package. `PamModel`
and `Slug` are copied from §7.1.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class PamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: str = "1.1.0"


class ConnectorAuth(BaseModel):
    type: Literal["none", "api_key", "bearer"] = "none"
    header: str | None = None
    env_var: str | None = None


class ConnectorParam(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    description: str = ""


class ConnectorTool(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,22}$")
    description: str
    method: Literal["GET", "POST"] = "GET"
    path: str = Field(pattern=r"^/[A-Za-z0-9_\-/{}.]*$")
    params: list[ConnectorParam] = []


class Connector(PamModel):
    id: Slug
    name: str
    description: str = ""
    base_url: str
    public_base_url: str | None = None
    auth: ConnectorAuth = ConnectorAuth()
    tools: list[ConnectorTool] = []
    enabled: bool = True
    archived: bool = False
    agents: list[Slug] = []


class CardField(BaseModel):
    label: str
    value: str


class CardPrice(BaseModel):
    amount: float
    period: Literal["once", "month"] = "month"
    was: float | None = None
    note: str | None = None


class CardLink(BaseModel):
    label: str
    url: str


class ChartSeries(BaseModel):
    label: str
    points: list[tuple[float, float]]


class CardChart(BaseModel):
    kind: Literal["line", "bar"] = "line"
    x_label: str
    y_label: str
    series: list[ChartSeries]
    marker_x: float | None = None


class ConnectorCard(BaseModel):
    kind: Literal["product", "plan", "verdict", "comparison", "chart", "notice"]
    title: str
    subtitle: str | None = None
    image_url: str | None = None
    image_alt: str | None = None
    badges: list[str] = []
    tone: Literal["neutral", "positive", "caution"] = "neutral"
    price: CardPrice | None = None
    fields: list[CardField] = []
    reasons: list[str] = []
    columns: list[str] = []
    rows: list[list[str]] = []
    chart: CardChart | None = None
    link: CardLink | None = None
    connector_id: str | None = None
