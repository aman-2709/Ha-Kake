"""The HAKAKE_ names from before the rename still work at the places that read the environment, and the new
VEHICLETAP_ name wins when both are set. util.env() has its own tests; these go through the real readers."""
import json
import os
import sys

import pytest

from conftest import ROOT

import vehicles
import reader as rd

OLD, NEW = "HAKAKE_", "VEHICLETAP_"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for suffix in ("VEHICLE", "ADAPTERS", "SERIAL_PORT"):
        monkeypatch.delenv(OLD + suffix, raising=False)
        monkeypatch.delenv(NEW + suffix, raising=False)
    monkeypatch.setattr(vehicles, "_active", vehicles._active)          # get_vehicle() sets it; put it back


def test_the_old_vehicle_variable_still_selects_the_profile(monkeypatch):
    monkeypatch.setenv(OLD + "VEHICLE", "lancer_2009")
    assert vehicles.get_vehicle().NAME == "lancer_2009"


def test_the_new_vehicle_variable_wins(monkeypatch):
    monkeypatch.setenv(OLD + "VEHICLE", "lancer_2009")
    monkeypatch.setenv(NEW + "VEHICLE", "leaf_ze0")
    assert vehicles.get_vehicle().NAME == "leaf_ze0"


def test_the_old_adapters_variable_still_names_the_adapters(leaf_profile, monkeypatch):
    monkeypatch.setenv(OLD + "ADAPTERS", json.dumps([{"type": "ble"}]))
    assert [e["type"] for e in rd.adapter_entries(None, cfg={})] == ["ble"]


def test_the_new_adapters_variable_wins(leaf_profile, monkeypatch):
    monkeypatch.setenv(OLD + "ADAPTERS", json.dumps([{"type": "ble"}]))
    monkeypatch.setenv(NEW + "ADAPTERS", json.dumps([{"type": "usb"}]))
    assert [e["type"] for e in rd.adapter_entries(None, cfg={})] == ["usb"]


def test_a_bad_adapters_value_names_the_variable_the_user_should_fix(leaf_profile, monkeypatch):
    monkeypatch.setenv(OLD + "ADAPTERS", "not json")
    with pytest.raises(ValueError, match="VEHICLETAP_ADAPTERS is not valid JSON"):
        rd.adapter_entries(None, cfg={})


def test_the_bench_tool_finds_its_port_through_either_name(monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import bench_transport as bt
    monkeypatch.setenv(OLD + "SERIAL_PORT", "/dev/ttyOLD")
    assert bt.find_port() == "/dev/ttyOLD"
    monkeypatch.setenv(NEW + "SERIAL_PORT", "/dev/ttyNEW")
    assert bt.find_port() == "/dev/ttyNEW"
    assert bt.find_port("/dev/ttyEXPLICIT") == "/dev/ttyEXPLICIT"
