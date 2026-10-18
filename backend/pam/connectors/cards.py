"""Display cards from a connector's response: the optional top-level `pam_cards` list (SPEC §8 M16)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlsplit

from pydantic import ValidationError

from pam.contracts.connector import Connector, ConnectorCard

log = logging.getLogger(__name__)

CARDS_KEY = "pam_cards"
MAX_CARDS = 6
SAFE_SCHEME = "https"


def extract_cards(body: Any, connector: Connector) -> tuple[Any, list[ConnectorCard]]:
    """Split a response body into the data for the model and the validated display cards.

    Behavior:
        Only a JSON object can carry cards; its `pam_cards` key is removed from the data. Each item
        is validated as `ConnectorCard`; invalid items are dropped and logged, and at most
        `MAX_CARDS` valid ones are kept. `image_url` and `link.url` go through `resolve_url`; a URL
        that is removed leaves `image_url` empty or drops the link. Every card gets
        `connector_id = connector.id`, whatever the service sent.
    Returns:
        `(data, cards)`: the body without `pam_cards`, and the cards.
    Parameters:
        body: The parsed JSON response.
        connector: The connector that answered.
    """
    if not isinstance(body, dict) or CARDS_KEY not in body:
        return body, []
    data = {k: v for k, v in body.items() if k != CARDS_KEY}
    raw = body[CARDS_KEY]
    if not isinstance(raw, list):
        log.warning("connector %s: %s is not a list; ignored", connector.id, CARDS_KEY)
        return data, []
    cards: list[ConnectorCard] = []
    for index, item in enumerate(raw):
        try:
            card = ConnectorCard.model_validate(item)
        except ValidationError as e:
            log.warning("connector %s: dropped invalid card %d: %s", connector.id, index, " ".join(str(e).split()))
            continue
        if len(cards) == MAX_CARDS:
            log.warning("connector %s: kept the first %d cards of %d", connector.id, MAX_CARDS, len(raw))
            break
        cards.append(_finish(card, connector))
    return data, cards


def resolve_url(url: str, public_base_url: str | None) -> str | None:
    """Make a card URL safe for the browser.

    Behavior:
        An absolute URL is kept only if it is `https`; a scheme-relative URL (`//host/...`) is
        removed. A relative URL is joined to `public_base_url` the way a browser joins a link, so
        both `images/a.svg` and `/connectors/x/images/a.svg` work with a base of `/connectors/x`.
        Without a `public_base_url`, a relative URL is removed.
    Returns:
        The URL to show, or `None` to remove it.
    Parameters:
        url: The URL from the card.
        public_base_url: The connector's browser-visible base, or `None`.
    """
    parts = urlsplit(url)
    if parts.scheme:
        return url if parts.scheme.lower() == SAFE_SCHEME else None
    if parts.netloc or not public_base_url:
        return None
    return urljoin(public_base_url.rstrip("/") + "/", url)


def _finish(card: ConnectorCard, connector: Connector) -> ConnectorCard:
    update: dict[str, Any] = {"connector_id": connector.id}
    if card.image_url is not None:
        update["image_url"] = resolve_url(card.image_url, connector.public_base_url)
    if card.link is not None:
        url = resolve_url(card.link.url, connector.public_base_url)
        update["link"] = card.link.model_copy(update={"url": url}) if url else None
    return card.model_copy(update=update)
