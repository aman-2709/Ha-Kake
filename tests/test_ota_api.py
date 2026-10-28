"""GET /api/ota and the /ota page (docs/OTA.md).

The endpoint is a window on a file a process on the host wrote: it answers 200 with an honest status
("waiting", "invalid", "stale", "ok") rather than an error, it is read-only, it never opens the real file in
demo mode, and nothing the exporter should not have said reaches the browser.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

from conftest import ROOT, fixture

import ota  # noqa: E402  (web/ota.py)

STATIC = os.path.join(ROOT, "web", "static")
TEMPLATES = os.path.join(ROOT, "web", "templates")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def fresh(**over):
    d = fixture("ota/status_v1.json")
    d["generated_at"] = ota.format_time(time.time() - 3)
    d.update(over)
    return d


@pytest.fixture
def api(tmp_path, monkeypatch, leaf_profile):
    """The Flask test client with the status file under tmp_path, plus a writer for it."""
    import app as webapp
    monkeypatch.setattr(webapp, "DEMO", None)
    monkeypatch.setattr(webapp, "STATE_FILE", str(tmp_path / "state.json"))
    f = tmp_path / "ota_status.json"
    monkeypatch.setenv("HAKAKE_OTA_FILE", str(f))
    webapp.app.config["TESTING"] = True

    def write(obj):
        f.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return str(f)

    with webapp.app.test_client() as client:
        yield client, write


# ── /api/ota ──

def test_no_file_yet_is_a_200_that_says_waiting_and_how_to_fix_it(api):
    client, _ = api
    r = client.get("/api/ota")
    assert r.status_code == 200 and r.is_json
    body = r.get_json()
    assert body["status"] == "waiting" and "ota_export" in body["message"]
    assert "os" not in body


def test_a_fresh_file_is_served_whole(api):
    client, write = api
    write(fresh())
    body = client.get("/api/ota").get_json()
    assert body["status"] == "ok" and 0 <= body["age_s"] < 60
    assert body["os"]["booted"]["version"] == "4.4.0" and body["os"]["rollback"]["version"] == "4.5.0"
    assert body["next_boot"]["source"] == "rollback" and body["next_boot"]["version"] == "4.5.0"
    assert [c["id"] for c in body["components"]] == ["RHIVOS-APP-CANDUMP", "RHIVOS-OS-AUTOSD"]
    assert [s["name"] for s in body["services"]] == ["esync", "candump", "cangen"]
    assert body["health"]["selinux"] == "enforcing" and body["health"]["ntp_synced"] is True


def test_an_old_file_is_stale_and_a_broken_one_invalid_both_still_200(api):
    client, write = api
    write(fresh(generated_at=ota.format_time(time.time() - 3600)))
    r = client.get("/api/ota")
    assert r.status_code == 200 and r.get_json()["status"] == "stale" and r.get_json()["os"]["booted"]
    write("{ this is not json")
    r = client.get("/api/ota")
    assert r.status_code == 200 and r.get_json()["status"] == "invalid" and "os" not in r.get_json()


def test_each_request_reads_the_file_again(api):
    client, write = api
    write(fresh())
    assert client.get("/api/ota").get_json()["status"] == "ok"
    write(fresh(schema=7))
    assert client.get("/api/ota").get_json()["status"] == "invalid"
    write(fresh())
    assert client.get("/api/ota").get_json()["status"] == "ok"


def test_what_the_exporter_should_not_have_said_never_reaches_the_browser(api):
    client, write = api
    d = fresh()
    d["apikey"] = "apikey-0123"
    d["os"]["booted"]["registry"] = "ghcr.example/secret/image"
    d["os"]["spec"] = {"image": "ghcr.example/secret/image"}
    d["components"][0]["device_id"] = "serial-SYNTH-0001"
    d["services"][0]["exec_start"] = "/usr/bin/x --key=apikey-0123"
    write(d)
    text = client.get("/api/ota").get_data(as_text=True)
    for secret in ("apikey-0123", "ghcr.example", "SYNTH-0001", "exec_start", "--key"):
        assert secret not in text, secret


def test_the_endpoint_is_read_only(api):
    client, _ = api
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/ota", json={}).status_code == 405
        assert getattr(client, method)("/ota", json={}).status_code == 405


def test_the_endpoint_takes_no_path_from_the_request(api, tmp_path):
    client, write = api
    other = tmp_path / "other.json"
    other.write_text(json.dumps(fresh(schema=7)))
    write(fresh())
    for q in (f"?file={other}", f"?path={other}", "?file=../../etc/passwd"):
        assert client.get("/api/ota" + q).get_json()["status"] == "ok"


def test_a_foreign_host_is_refused_like_every_other_route(api):
    client, write = api
    write(fresh())
    for url in ("/api/ota", "/ota"):
        assert client.get(url, headers={"Host": "evil.example"}).status_code == 403
        assert client.get(url, headers={"Host": "127.0.0.1:5000"}).status_code == 200


def test_the_security_headers_are_on(api):
    client, _ = api
    for url in ("/api/ota", "/ota"):
        r = client.get(url)
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]


# ── demo mode: canned data, never the real file ──

def test_demo_mode_never_opens_the_real_file(api, monkeypatch):
    import app as webapp
    client, write = api
    write(fresh(os={"booted": {"version": "REAL-FILE-MARKER"}}))
    monkeypatch.setattr(webapp, "DEMO", os.path.join(ROOT, "docs", "demo"))
    body = client.get("/api/ota").get_json()
    assert "REAL-FILE-MARKER" not in json.dumps(body)
    assert body["demo"] is True and body["status"] == "ok"
    assert body["os"]["booted"]["version"] == "4.4.0"


def test_demo_mode_keeps_the_canned_file_looking_current(api, monkeypatch):
    import app as webapp
    client, _ = api
    monkeypatch.setattr(webapp, "DEMO", os.path.join(ROOT, "docs", "demo"))
    assert client.get("/api/ota").get_json()["age_s"] < 60       # re-stamped, like /api/status


def test_demo_mode_without_a_canned_file_has_nothing_to_show(api, monkeypatch, tmp_path):
    import app as webapp
    client, write = api
    write(fresh())
    monkeypatch.setattr(webapp, "DEMO", str(tmp_path / "empty_demo_dir"))
    body = client.get("/api/ota").get_json()
    assert body["status"] == "waiting" and body["demo"] is True and "os" not in body


# ── the page ──

def test_the_page_renders_with_no_file_at_all(api):
    client, _ = api
    r = client.get("/ota")
    assert r.status_code == 200 and r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert 'id="ota-root"' in html and 'id="ota-banner"' in html
    assert "docs/OTA.md" in html                               # it says where the setup is described
    assert 'href="/"' in html                                  # and the way back to the dashboard


def test_the_page_carries_no_board_data_in_its_markup(api):
    """The data comes from /api/ota through textContent; nothing from the file is rendered by the server."""
    client, write = api
    d = fresh()
    d["os"]["booted"]["version"] = "MARKER-<b>4.4.0</b>"
    write(d)
    assert "MARKER" not in client.get("/ota").get_data(as_text=True)


def test_the_page_names_the_vehicle_in_its_title(api):
    client, _ = api
    import reader
    assert reader.VEHICLE.TITLE in client.get("/ota").get_data(as_text=True)


def test_the_page_loads_the_escape_helper_before_its_own_script(api):
    html = api[0].get("/ota").get_data(as_text=True)
    assert html.index('src="/static/html.js"') < html.index('src="/static/ota.js"')
    assert "/static/hakake.css" in html and "/static/ota.css" in html


def test_the_page_loads_nothing_from_outside_this_server(api):
    html = api[0].get("/ota").get_data(as_text=True)
    assert "http://" not in html and "https://" not in html


def test_the_dashboard_links_to_the_page(api):
    html = api[0].get("/").get_data(as_text=True)
    assert 'href="/ota"' in html


# ── ota.js: the pure half, in node; the call sites, by source ──

def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def node(script, *args):
    r = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


OTA_JS = os.path.join(STATIC, "ota.js")


def test_ota_js_writes_text_never_markup():
    src = read(OTA_JS)
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src and "outerHTML" not in src
    assert "document.write" not in src and "eval(" not in src
    assert "textContent" in src


def test_ota_js_only_reads_from_this_server_and_never_sends():
    src = read(OTA_JS)
    assert "fetch('/api/ota'" in src
    for verb in ("method:", "POST", "PUT", "DELETE", "XMLHttpRequest", "sendBeacon", "WebSocket"):
        assert verb not in src, verb


@needs_node
def test_short_digest_and_age_helpers():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      console.log(JSON.stringify([Ota.short('sha256:' + 'ab'.repeat(32)), Ota.short(''), Ota.short(null),
        Ota.ago(0), Ota.ago(5), Ota.ago(119), Ota.ago(120), Ota.ago(7199), Ota.ago(7200), Ota.ago(null), Ota.ago(-3)]));
    """, OTA_JS)
    assert out == ["abababababab", "", "", "0 s", "5 s", "119 s", "2 min", "119 min", "2 h", "", "0 s"]


@needs_node
def test_when_shows_an_iso_time_plainly():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      console.log(JSON.stringify([Ota.when('2026-08-07T23:03:53Z'), Ota.when('2026-08-07T23:03:53.358191364Z'),
                                  Ota.when(''), Ota.when(null), Ota.when(5)]));
    """, OTA_JS)
    assert out == ["2026-08-07 23:03:53 UTC", "2026-08-07 23:03:53 UTC", "", "", ""]


@needs_node
def test_image_rows_mark_what_differs_between_the_images():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      const d = 'sha256:' + 'ab'.repeat(32), e = 'sha256:' + 'cd'.repeat(32);
      const os = { booted: { version: '4.4.0', digest: d, built_at: '2026-08-07T23:03:53Z' },
                   staged: null,
                   rollback: { version: '4.5.0', digest: e, built_at: '2026-08-07T23:03:53Z' } };
      console.log(JSON.stringify(Ota.imageRows(os)));
    """, OTA_JS)
    by = {r["label"]: r for r in out}
    assert by["Version"]["differs"] is True and by["Digest"]["differs"] is True
    assert by["Built"]["differs"] is False                          # same build time on both: not highlighted
    assert by["Version"]["cells"] == {"booted": "4.4.0", "staged": "", "rollback": "4.5.0"}
    assert by["Digest"]["cells"]["booted"] == "abababababab"


@needs_node
def test_image_rows_with_one_image_have_nothing_to_compare():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      console.log(JSON.stringify(Ota.imageRows({ booted: { version: '4.4.0', digest: '', built_at: '' }, staged: null, rollback: null })));
    """, OTA_JS)
    assert all(r["differs"] is False for r in out)


@needs_node
def test_the_banner_says_what_each_status_means():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      const b = s => Ota.banner(Object.assign({ message: 'm' }, s));
      console.log(JSON.stringify([b({ status: 'ok' }), b({ status: 'waiting' }), b({ status: 'invalid' }),
                                  b({ status: 'stale', age_s: 600 }), b({ status: 'surprise' }), Ota.banner(null)]));
    """, OTA_JS)
    assert out[0] is None                                                         # all well: no banner
    assert out[1]["kind"] == "waiting" and out[2]["kind"] == "invalid" and out[3]["kind"] == "stale"
    assert "10 min" in out[3]["text"]
    assert out[4]["kind"] == "invalid" and out[5]["kind"] == "invalid"           # unknown or no answer: say so


@needs_node
def test_next_boot_line_warns_only_when_the_next_boot_is_another_image():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      const nb = (source, version) => Ota.nextBoot({ source, version, digest: '' });
      console.log(JSON.stringify([nb('booted', '4.4.0'), nb('rollback', '4.5.0'), nb('staged', '4.6.0'), Ota.nextBoot(null)]));
    """, OTA_JS)
    assert out[0]["warn"] is False and "4.4.0" in out[0]["text"]
    assert out[1]["warn"] is True and "rollback" in out[1]["text"] and "4.5.0" in out[1]["text"]
    assert out[2]["warn"] is True and "staged" in out[2]["text"]
    assert out[3]["warn"] is False and out[3]["text"] == ""


@needs_node
def test_status_classes_for_services_and_health():
    out = node("""
      globalThis.window = globalThis; require(process.argv[1]);
      console.log(JSON.stringify([
        ['active', 'failed', 'activating', 'inactive', 'unknown', 'nonsense'].map(Ota.serviceClass),
        ['enforcing', 'permissive', 'disabled', 'unknown'].map(Ota.selinuxClass),
        [true, false, null].map(Ota.ntpClass),
        [10, 74.9, 75, 89.9, 90, 100, null].map(Ota.diskClass)]));
    """, OTA_JS)
    assert out[0] == ["ok", "bad", "warn", "warn", "dim", "dim"]
    assert out[1] == ["ok", "warn", "bad", "dim"]
    assert out[2] == ["ok", "bad", "dim"]
    assert out[3] == ["ok", "ok", "warn", "warn", "bad", "bad", "dim"]


# ── ota.js against a fake DOM: the real render path, with hostile strings ──

FAKE_DOM = """
  class Node {}
  class El extends Node {
    constructor(tag) { super(); this.tag = tag; this.kids = []; this.className = ''; this.hidden = false; this.own = ''; }
    set textContent(v) { this.own = String(v); this.kids = []; }
    get textContent() { return this.own + this.kids.map(k => k.textContent).join(' | '); }
    set innerHTML(v) { throw new Error('innerHTML was used'); }
    appendChild(k) { this.kids.push(k); return k; }
    replaceChildren(...ks) { this.kids = ks; this.own = ''; }
  }
  class Txt extends Node { constructor(t) { super(); this.t = t; } get textContent() { return this.t; } }
  const els = {};
  globalThis.Node = Node;
  globalThis.document = {
    hidden: false,
    getElementById: id => els[id] || (els[id] = new El('div')),
    createElement: tag => new El(tag),
    createTextNode: t => new Txt(t),
  };
  globalThis.window = globalThis;
  globalThis.setInterval = () => 0;
  const answer = JSON.parse(process.argv[2]);
  globalThis.fetch = async (url, opts) => {
    if (answer === 'FAIL') throw new Error('network down');
    return { ok: true, json: async () => answer };
  };
  require(process.argv[1]);
  const settle = () => new Promise(r => setTimeout(r, 5));
"""

HOSTILE = '<img src=x onerror="alert(1)">'


def page(answer):
    return node(FAKE_DOM + """
      settle().then(() => {
        const g = id => document.getElementById(id), t = id => g(id).textContent;
        console.log(JSON.stringify({
          bannerHidden: g('ota-banner').hidden, banner: t('ota-banner'), bannerClass: g('ota-banner').className,
          mainHidden: g('ota-main').hidden, age: t('ota-age'),
          next: t('ota-next'), nextClass: g('ota-next').className, images: t('ota-images'),
          osFacts: t('ota-os-facts'), components: t('ota-components'), services: t('ota-services'),
          health: t('ota-health')
        }));
      });
    """, OTA_JS, json.dumps(answer))


@needs_node
def test_render_writes_hostile_strings_as_text_and_never_touches_innerhtml():
    d = ota.view(fresh(), now=time.time())
    d["os"]["booted"]["version"] = HOSTILE
    d["os"]["kernel"] = HOSTILE
    d["components"][0]["id"] = HOSTILE
    d["services"][0]["name"] = HOSTILE
    d["services"][0]["sub_state"] = HOSTILE
    out = page(d)                                   # the fake El throws if innerHTML is ever assigned
    for key in ("images", "osFacts", "components", "services"):
        assert HOSTILE in out[key], key              # present, verbatim, as text


@needs_node
def test_render_shows_the_whole_page_for_a_good_answer():
    out = page(ota.view(fresh(), now=time.time()))
    assert out["bannerHidden"] is True and out["mainHidden"] is False
    assert "Next boot: 4.5.0" in out["next"] and out["nextClass"] == "ota-next warn"
    assert "4.4.0" in out["images"] and "4.5.0" in out["images"] and "Rollback (queued)" in out["images"]
    assert "6.12.0-251.el10iv.aarch64" in out["osFacts"]
    assert "RHIVOS-APP-CANDUMP" in out["components"] and "3.4.0" in out["components"]
    assert "esync" in out["services"] and "active (running)" in out["services"]
    assert "enforcing" in out["health"] and "synchronized" in out["health"] and "25.0 % used" in out["health"]
    assert out["age"].startswith("written ")


@needs_node
def test_render_for_a_stale_answer_shows_the_data_under_a_warning():
    d = ota.view(fresh(generated_at=ota.format_time(time.time() - 3600)), now=time.time())
    out = page(d)
    assert out["bannerHidden"] is False and out["bannerClass"] == "card ota-banner stale"
    assert "old" in out["banner"] and out["mainHidden"] is False and "4.4.0" in out["images"]


@needs_node
@pytest.mark.parametrize("status", ["waiting", "invalid"])
def test_render_for_no_usable_file_shows_the_message_and_no_data(status):
    out = page({"status": status, "age_s": None, "message": "no file here, see docs/OTA.md"})
    assert out["bannerHidden"] is False and out["bannerClass"] == "card ota-banner " + status
    assert "docs/OTA.md" in out["banner"] and out["mainHidden"] is True and out["age"] == ""


@needs_node
def test_render_survives_a_server_that_is_down_or_answers_nonsense():
    for answer in ("FAIL", None, 5, "text", [], {"status": "surprise"}):
        out = page(answer)
        assert out["bannerHidden"] is False and out["bannerClass"].endswith("invalid"), answer
        assert out["mainHidden"] is True


@needs_node
def test_render_copes_with_a_sparse_good_answer():
    """Status ok but nothing else: every section says it has nothing, none of them throws."""
    out = page({"status": "ok", "age_s": 1.0, "message": "", "os": {"booted": None, "staged": None, "rollback": None,
                                                                   "rollback_queued": False, "kernel": "", "booted_at": ""},
                "components": [], "services": [], "health": {}, "next_boot": None})
    assert out["mainHidden"] is False and out["next"] == "" and out["nextClass"] == "ota-next"
    assert "No components reported." in out["components"] and "No services reported." in out["services"]
