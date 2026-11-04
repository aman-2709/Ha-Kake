"""The header mark is one neutral dial for every vehicle.

The leaf silhouette was the original project's logo, which its NOTICE reserves; no profile can bring it back.
"""
import pytest

import reader as rd
import vehicles

LEAF_OUTLINE = "M16 3 C 23 8 26 18 16 29"
LEAF_VEINS = "M16 7 L16 26"
DIAL_OUTLINE = "M16 4 A 12 12 0 1 0 16 28"


@pytest.fixture
def client(tmp_path, monkeypatch, leaf_profile):
    import app as webapp
    monkeypatch.setattr(webapp, "DEMO", None)
    monkeypatch.setattr(webapp, "STATE_FILE", str(tmp_path / "state.json"))
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        yield c


def home(client):
    return client.get("/").get_data(as_text=True)


@pytest.mark.parametrize("profile", vehicles.available())
def test_every_profile_gets_the_dial(client, profile):
    rd.set_vehicle(profile)                              # the leaf_profile fixture puts the Leaf back
    html = home(client)
    assert DIAL_OUTLINE in html
    assert LEAF_OUTLINE not in html and LEAF_VEINS not in html
    assert 'aria-label="VehicleTap"' in html


def test_a_profile_that_still_sets_logo_leaf_is_ignored(client, monkeypatch):
    monkeypatch.setattr(rd.VEHICLE, "LOGO", "leaf", raising=False)
    html = home(client)
    assert DIAL_OUTLINE in html and LEAF_OUTLINE not in html


def test_the_page_context_no_longer_carries_a_logo():
    import app as webapp
    assert "logo" not in webapp.vehicle_ctx()


def test_the_leaf_art_is_gone_from_the_template():
    import os
    from conftest import ROOT
    with open(os.path.join(ROOT, "web", "templates", "index.html"), encoding="utf-8") as f:
        src = f.read()
    assert "leaf_path" not in src and LEAF_OUTLINE not in src and LEAF_VEINS not in src
