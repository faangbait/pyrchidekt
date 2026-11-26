"""
This is the api querying that will return decks based on ID
"""

from .deck import Deck
from typing import Optional
import os
import requests

ARCHIDEKT_API_BASE = "https://www.archidekt.com/api/"
DECK_SEARCH_ENDPOINT = ARCHIDEKT_API_BASE + "decks/{}/"
LOGIN_ENDPOINT = ARCHIDEKT_API_BASE + "rest-auth/login/"
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
