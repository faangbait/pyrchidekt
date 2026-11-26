"""
This is the api querying that will return decks based on ID
"""

from .cards import Card
from .deck import Deck, DeckSummary
from .formats import Format
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional
import os
import re
import uuid
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ARCHIDEKT_API_BASE = "https://archidekt.com/api/"
DECK_SEARCH_ENDPOINT = ARCHIDEKT_API_BASE + "decks/{}/"
LOGIN_ENDPOINT = ARCHIDEKT_API_BASE + "rest-auth/login/"
DECK_LIST_ENDPOINT = ARCHIDEKT_API_BASE + "decks/v3/"
DECK_CREATE_ENDPOINT = ARCHIDEKT_API_BASE + "decks/v2/"
DECK_UPDATE_ENDPOINT = ARCHIDEKT_API_BASE + "decks/{}/update/"
DECK_MODIFY_CARDS_ENDPOINT = ARCHIDEKT_API_BASE + "decks/{}/modifyCards/v2/"
MASS_EDIT_ENDPOINT = ARCHIDEKT_API_BASE + "cards/massDeckEdit/"
CARD_SEARCH_ENDPOINT = ARCHIDEKT_API_BASE + "cards/v2/"
USERNAME_ENV = "ARCHIDEKT_USERNAME"
PASSWORD_ENV = "ARCHIDEKT_PASSWORD"


def login(username: str, password: str) -> requests.Session:
    """Logs in to Archidekt

    Posts the credentials to Archidekt's login endpoint and returns a `requests.Session` that sends the
    resulting JWT as an `Authorization: JWT <token>` header on every request. Pass the session to the
    other functions in this module to act as the logged in user (e.g. to read private decks).

    The session also carries `refresh_token` and `user` (the user object from the login response) as attributes.

    Args:
        username: `str` Archidekt username
        password: `str` Archidekt password

    Returns:
        An authenticated `requests.Session`.

    Raises:
        RuntimeError: If the credentials are rejected or the login response is unusable. The credentials are
            never included in the message.
    """
    session = requests.Session()
    # Archidekt throttles aggressively (HTTP 429); wait as long as it asks and retry, for every method
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=6, status_forcelist=[429], allowed_methods=None,
                                                            backoff_factor=1, respect_retry_after_header=True)))
    response = session.post(LOGIN_ENDPOINT, json={"username": username, "password": password}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Archidekt login failed (HTTP {response.status_code})")
    data = response.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError("Archidekt login response did not contain a token")
    session.headers["Authorization"] = f"JWT {token}"
    session.refresh_token = data.get("refresh_token")
    session.user = data.get("user")
    return session


def loginFromEnv() -> requests.Session:
    """Logs in using the `ARCHIDEKT_USERNAME` and `ARCHIDEKT_PASSWORD` environment variables

    Raises:
        RuntimeError: If either variable is unset, or the login fails
    """
    username, password = os.environ.get(USERNAME_ENV), os.environ.get(PASSWORD_ENV)
    if not username or not password:
        raise RuntimeError(f"Set {USERNAME_ENV} and {PASSWORD_ENV} to log in")
    return login(username, password)


def getDeckById(id: int, session: Optional[requests.Session] = None) -> Deck:
    """Retrieves a deck by id from Archidekt

    This queries the Archidekt API to retrieve the deck, returning the object representing the deck.

    Args:
        id: `int` The ID of the deck

        session: `requests.Session` Optional authenticated session from `login()`, needed for private decks

    Returns:
        The `Deck` object.

    Raises:
        RuntimeError: In either the case that the deck doesn't exist or it can't be retrieved for some reason
    """
    response = (session or requests).get(DECK_SEARCH_ENDPOINT.format(id))
    match response.status_code:
        case 200:
            return Deck.fromJson(response.json())
        case 404:
            raise RuntimeError(f"{id} is either not a valid deck or it's private")
        case _:
            raise RuntimeError(f"Unknown error trying to retrieve deck {id}")


def _check(response: requests.Response, action: str, ok: Iterable[int] = (200, 201, 204)) -> requests.Response:
    if response.status_code not in ok:
        raise RuntimeError(f"Archidekt {action} failed (HTTP {response.status_code}): {response.text[:200]}")
    return response


def listDecks(username: str, session: Optional[requests.Session] = None, page_size: int = 50) -> List[DeckSummary]:
    """Lists a user's decks

    Pages through `decks/v3/` filtered by owner. Pass an authenticated session to also see the logged in
    user's private decks.

    Args:
        username: `str` The owner's Archidekt username
        session: `requests.Session` Optional session from `login()`
        page_size: `int` Entries requested per page

    Returns:
        The user's decks as `DeckSummary` objects.
    """
    client = session or requests
    url, params, decks = DECK_LIST_ENDPOINT, {"ownerUsername": username, "pageSize": page_size}, []
    while url:
        data = _check(client.get(url, params=params, timeout=30), "deck listing").json()
        decks += [DeckSummary.fromJson(x) for x in data["results"]]
        url, params = data.get("next"), None
    return decks


def createDeck(session: requests.Session, name: str, format: Format = Format.COMMANDER, private: bool = True,
               folder_id: Optional[int] = None) -> Deck:
    """Creates an empty deck

    Args:
        session: `requests.Session` Authenticated session from `login()`
        name: `str` Deck name
        format: `Format` Deck format
        private: `bool` Create the deck private (default) or public
        folder_id: `int` Folder to create it in, defaults to the user's root folder

    Returns:
        The new `Deck`.
    """
    if folder_id is None:
        folder_id = (session.user or {}).get("rootFolder")
    body = {"name": name, "deckFormat": format.value, "private": private}
    if folder_id is not None:
        body["parentFolder"] = folder_id
    created = _check(session.post(DECK_CREATE_ENDPOINT, json=body, timeout=30), "deck creation").json()
    return getDeckById(created["id"], session=session)


def updateDeck(session: requests.Session, deck_id: int, *, name: Optional[str] = None,
               description: Optional[str] = None, format: Optional[Format] = None, private: Optional[bool] = None,
               unlisted: Optional[bool] = None, theorycrafted: Optional[bool] = None) -> None:
    """Updates deck metadata. Only the arguments you pass are changed."""
    fields = {"name": name, "description": description, "deckFormat": format.value if format else None,
              "private": private, "unlisted": unlisted, "theorycrafted": theorycrafted}
    body = {k: v for k, v in fields.items() if v is not None}
    _check(session.patch(DECK_UPDATE_ENDPOINT.format(deck_id), json=body, timeout=30), "deck update")


def deleteDeck(session: requests.Session, deck_id: int) -> None:
    """Permanently deletes a deck"""
    _check(session.delete(DECK_SEARCH_ENDPOINT.format(deck_id), timeout=30), "deck deletion")


def searchCards(name: str, session: Optional[requests.Session] = None, limit: int = 10) -> List[Card]:
    """Searches printings by name. `Card.id` is the id the deck-editing functions take."""
    response = (session or requests).get(CARD_SEARCH_ENDPOINT, params={"name": name, "pageSize": limit}, timeout=30)
    return [Card.fromJson(x) for x in _check(response, "card search").json()["results"]]


def _modifyCard(session: requests.Session, deck_id: int, item: dict) -> dict:
    item = {"patchId": str(uuid.uuid4()), "modifications": {}, **item}
    response = session.patch(DECK_MODIFY_CARDS_ENDPOINT.format(deck_id), json={"cards": [item]}, timeout=30)
    return _check(response, "card modification").json()


def addCard(session: requests.Session, deck_id: int, card_id: int, quantity: int = 1,
            categories: Optional[List[str]] = None, modifier: str = "Normal") -> int:
    """Adds a printing to a deck

    Args:
        card_id: `int` The printing id (`Card.id`, e.g. from `searchCards`)
        categories: `List[str]` Categories to file the card under (created if missing)

    Returns:
        The id of the new deck entry (`ArchidektCard.id`), needed to update or remove it.
    """
    result = _modifyCard(session, deck_id, {
        "action": "add", "cardid": card_id, "categories": categories or [], "modifier": modifier,
        "modifications": {"quantity": quantity},
    })
    return result["add"][0]["deckRelationId"]


def updateCard(session: requests.Session, deck_id: int, entry_id: int, card_id: int, quantity: int,
               categories: Optional[List[str]] = None, modifier: str = "Normal") -> None:
    """Sets the quantity and categories of a deck entry

    This sets state rather than patching it: pass the full `quantity` and `categories` you want.

    Args:
        entry_id: `int` The deck entry id (`ArchidektCard.id`)
        card_id: `int` The printing id (`Card.id`)
    """
    _modifyCard(session, deck_id, {
        "action": "modify", "deckRelationId": entry_id, "cardid": card_id, "categories": categories or [],
        "modifier": modifier, "modifications": {"quantity": quantity},
    })


def removeCard(session: requests.Session, deck_id: int, entry_id: int, card_id: int,
               categories: Optional[List[str]] = None, modifier: str = "Normal") -> None:
    """Removes a deck entry entirely"""
    _modifyCard(session, deck_id, {
        "action": "remove", "deckRelationId": entry_id, "cardid": card_id, "categories": categories or [],
        "modifier": modifier,
    })


@dataclass
class MassEditResult:
    """Outcome of `massEdit`

    Attributes:
        added: `int` Entries added
        removed: `int` Entries removed
        card_errors: `List[str]` Lines Archidekt couldn't match to a card (nothing is applied for them)
        syntax_errors: `List[Any]` Lines Archidekt couldn't parse
    """
    added: int = 0
    removed: int = 0
    card_errors: List[str] = field(default_factory=list)
    syntax_errors: List[Any] = field(default_factory=list)


def deckToText(deck: Deck, bare_names: Iterable[str] = ()) -> str:
    """Renders a deck in the text format `massDeckEdit` understands: `1x Name (set) number [Category]`

    Args:
        bare_names: Lower-case card names to render without `(set) number`, so they compare equal to
            decklist lines that don't say which printing they want
    """
    premier = {c.name for c in deck.categories if c.is_premier}
    bare = {n.lower() for n in bare_names}
    lines = []
    for c in deck.cards:
        name = c.card.oracle_card.name
        front = name.split(" // ")[0]  # lists usually name double-faced/split cards by their front face only
        shown = name if name.lower() in bare else front if front.lower() in bare else None
        line = f"{c.quantity}x {shown or name}"
        if shown is None:
            line += f" ({c.card.edition.code}) {c.card.collector_number}"
        if c.categories:
            line += " [" + ",".join(x + ("{top}" if x in premier else "") for x in c.categories) + "]"
        lines.append(line)
    return "\n".join(lines) + "\n"


_BARE_LINE = re.compile(r"^\s*\d+x?\s+([^\[(]+?)\s*(?:\[.*)?$")


def massEdit(session: requests.Session, deck_id: int, text: str, dry_run: bool = False) -> MassEditResult:
    """Makes a deck match a decklist, in a handful of requests

    `text` is the full desired list, one entry per line: `1 Sol Ring`, `1x Sol Ring (msc) 214 [Ramp]`, ... Put
    `[Commander{top}]` after a card to make it the commander. Archidekt resolves card names to printings and
    works out the difference from the deck's current contents, which is then applied: changed entries are
    removed and re-added, new ones added, missing ones removed. A line without `(set) number` matches whatever
    printing the deck already has, so re-running the same list is a no-op. Lines Archidekt can't match are reported in
    the result and skipped.

    Args:
        text: `str` The desired decklist
        dry_run: `bool` Only compute the result, don't change the deck

    Returns:
        A `MassEditResult`. With `dry_run` the counts are what would be changed.
    """
    deck = getDeckById(deck_id, session=session)
    bare_names = [m[1] for m in map(_BARE_LINE.match, text.splitlines()) if m]
    diff = _check(session.post(MASS_EDIT_ENDPOINT, json={"parser": "archidekt", "current": deckToText(deck, bare_names),
                                                         "edit": text}, timeout=30), "mass edit").json()
    result = MassEditResult(card_errors=diff["cardErrors"], syntax_errors=diff["syntaxErrors"])

    removals = []
    for r in diff["toRemove"]:
        match = next((c for c in deck.cards if c.card.oracle_card.name.lower() == r["name"].lower()
                      and (not r.get("edition") or c.card.edition.code == r["edition"])
                      and sorted(c.categories or []) == sorted(r["categories"]) and c not in removals), None)
        if match:
            removals.append(match)
    adds = diff["toAdd"]
    result.removed, result.added = len(removals), len(adds)
    if dry_run:
        return result

    def patch(items):
        body = {"cards": [{"patchId": str(uuid.uuid4()), "modifications": {}, **i} for i in items]}
        _check(session.patch(DECK_MODIFY_CARDS_ENDPOINT.format(deck_id), json=body, timeout=60), "mass edit apply")

    if removals:
        patch([{"action": "remove", "deckRelationId": c.id, "cardid": c.card.id, "categories": c.categories or [],
                "modifier": c.modifier} for c in removals])
    if adds:
        patch([{"action": "add", "cardid": a["card"]["id"], "categories": a["categories"],
                "modifier": "Foil" if a["foil"] else a["modifier"], "modifications": {"quantity": a["quantity"]}}
               for a in adds])
    return result
