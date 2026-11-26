"""Live read/write tests against Archidekt. Need ARCHIDEKT_USERNAME/ARCHIDEKT_PASSWORD; they create and delete a private deck."""
import os
import pytest
from pyrchidekt.api import (addCard, createDeck, deleteDeck, getDeckById, listDecks, loginFromEnv, massEdit, removeCard,
                            searchCards, updateCard, updateDeck)

pytestmark = pytest.mark.skipif(not os.environ.get("ARCHIDEKT_PASSWORD"), reason="no Archidekt credentials")


@pytest.fixture
def session():
    return loginFromEnv()


def testDeckLifecycle(session):
    deck = createDeck(session, "pyrchidekt-test-delete-me")
    try:
        assert deck.private and not deck.cards
        assert deck.id in [d.id for d in listDecks(session.user["username"], session)]

        updateDeck(session, deck.id, name="pyrchidekt-test-renamed", description="d")
        assert getDeckById(deck.id, session).name == "pyrchidekt-test-renamed"

        card = searchCards("Sol Ring", limit=1)[0]
        entry = addCard(session, deck.id, card.id, quantity=2, categories=["Ramp"])
        (c,) = getDeckById(deck.id, session).cards
        assert (c.id, c.quantity, c.categories) == (entry, 2, ["Ramp"])

        updateCard(session, deck.id, entry, card.id, quantity=3, categories=["Rocks"])
        (c,) = getDeckById(deck.id, session).cards
        assert (c.quantity, c.categories) == (3, ["Rocks"])

        removeCard(session, deck.id, entry, card.id, ["Rocks"])
        assert not getDeckById(deck.id, session).cards
    finally:
        deleteDeck(session, deck.id)
    with pytest.raises(RuntimeError):
        getDeckById(deck.id, session)


def testMassEdit(session):
    deck = createDeck(session, "pyrchidekt-test-delete-me")
    try:
        text = "1 Sol Ring [Ramp]\n2 Island\n1 Command Tower (frc) 22 [Lands]\nTotally Fake Card Name\n"
        assert massEdit(session, deck.id, text, dry_run=True).added == 3
        assert not getDeckById(deck.id, session).cards

        result = massEdit(session, deck.id, text)
        assert (result.added, result.removed, len(result.card_errors)) == (3, 0, 1)
        assert sorted(c.quantity for c in getDeckById(deck.id, session).cards) == [1, 1, 2]

        again = massEdit(session, deck.id, text)  # already in sync
        assert (again.added, again.removed) == (0, 0)

        massEdit(session, deck.id, "1 Sol Ring [Ramp]\n")
        assert [c.card.oracle_card.name for c in getDeckById(deck.id, session).cards] == ["Sol Ring"]
    finally:
        deleteDeck(session, deck.id)
