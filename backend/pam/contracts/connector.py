"""§7.16 Connectors — external HTTP APIs offered to agents as tools (M16)."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from .common import PamModel, Slug

class ConnectorAuth(BaseModel):
    type: Literal["none", "api_key", "bearer"] = "none"
    header: str | None = None              # api_key only, e.g. "x-api-key"
    env_var: str | None = None             # NAME of the secret; the value is never stored

class ConnectorParam(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    description: str = ""

class ConnectorTool(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,22}$")
    description: str
    method: Literal["GET", "POST"] = "GET"
    path: str = Field(pattern=r"^/[A-Za-z0-9_\-/{}.]*$")   # may contain {param} placeholders
    params: list[ConnectorParam] = []

class Connector(PamModel):                 # stored as vault/connectors/<id>.yaml
    id: Slug
    name: str
    description: str = ""
    base_url: str                          # http(s)://host[:port][/prefix], no trailing slash
    public_base_url: str | None = None     # browser-visible base for relative card images and links
    auth: ConnectorAuth = ConnectorAuth()
    tools: list[ConnectorTool] = []
    enabled: bool = True
    archived: bool = False                 # replaces delete (nothing is ever deleted)
    agents: list[Slug] = []                # agents allowed to use it; `default` is NOT implicit

class CardField(BaseModel):
    label: str
    value: str

class CardPrice(BaseModel):
    amount: float
    period: Literal["once", "month"] = "month"
    was: float | None = None
    note: str | None = None                # e.g. "after $350 trade-in, 24 months"

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
    marker_x: float | None = None          # drawn as a labelled "Today" line

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
    columns: list[str] = []                # comparison only
    rows: list[list[str]] = []             # comparison only
    chart: CardChart | None = None
    link: CardLink | None = None
    connector_id: str | None = None        # set by PAM, never by the service

class ConnectorResult(BaseModel):
    ok: bool
    status: int | None = None              # HTTP status, None if no request was sent
    latency_ms: int
    data: dict | list | None = None
    cards: list[ConnectorCard] = []
    error: dict | None = None              # {"code", "message"}
