"""Tests for the local setup page: real loopback sockets, no browser and no Google calls."""

import http.client
import json
import socket
import struct
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from easygsc import web_setup

SECRET = "SECRET-XYZ-123"
STEPS = (
    ("https://console.cloud.google.com/projectcreate", "Create a project", ("Click 'Create'.",)),
    ("https://console.cloud.google.com/auth/clients", "Create the client", ("Desktop app.",)),
)
CLIENT = json.dumps({"installed": {"client_id": "cid", "client_secret": SECRET}}).encode()


def validate(data: bytes) -> str | None:
    """The wizard's check: an error message for the page, or None for a usable client."""
    try:
        parsed = json.loads(data)
    except ValueError:
        return "That file is not valid JSON."
    if "web" in parsed:
        return "That is a Web application client; easygsc needs a Desktop app client."
    return None


@pytest.fixture
def server():
    with web_setup.SetupServer(STEPS, validate) as srv:
        yield srv


def token_of(srv) -> str:
    return parse_qs(urlparse(srv.url).query)["token"][0]


def request(srv, method, path, body=None, headers=None, host=None):
    port = srv.port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    sent = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    conn.request(method, path, body=body, headers=sent)
    response = conn.getresponse()
    return response.status, dict(response.getheaders()), response.read().decode()


def upload(srv, body=CLIENT, **headers):
    sent = {"X-Easygsc-Token": token_of(srv), "Content-Type": "application/json", **headers}
    return request(srv, "POST", "/client", body, sent)


class TestPage:
    def test_binds_only_to_loopback(self, server):
        assert server.url.startswith(f"http://127.0.0.1:{server.port}/?token=")

    def test_serves_every_step_with_its_link(self, server):
        status, headers, page = request(
            server, "GET", urlparse(server.url).path + "?token=" + token_of(server)
        )
        assert status == 200
        for url, title, actions in STEPS:
            assert title in page
            assert f'href="{url}"' in page
            assert all(action.replace("'", "&#x27;") in page for action in actions)
        assert 'type="file"' in page

    def test_explains_file_handling_before_the_file_picker(self, server):
        status, _, page = request(server, "GET", "/?token=" + token_of(server))
        assert status == 200
        assert 'aria-describedby="client-help"' in page
        assert page.index('id="client-help"') < page.index('id="client"')
        text = " ".join(page.split())
        assert "only to easygsc on your computer" in text
        assert "not to an easygsc cloud server" in text
        assert "~/.config/easygsc/client_secret.json" in text
        assert "leaving your download unchanged" in text
        assert "sign in with Google and request read-only access to Search Console" in text

    def test_nan_credit_is_a_safe_link_without_external_resources(self, server):
        status, headers, page = request(server, "GET", "/?token=" + token_of(server))
        assert status == 200
        assert '<footer class="credit">' in page
        assert '<a href="https://nan.builders/?ref=built-with-nan"' in page
        assert 'target="_blank" rel="noopener noreferrer">Built with NaN</a>' in page
        assert "<img" not in page
        assert "<iframe" not in page
        assert "default-src 'none'" in headers["Content-Security-Policy"]

    def test_links_and_headers_never_leak_the_token(self, server):
        _, headers, page = request(server, "GET", "/?token=" + token_of(server))
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["Cache-Control"] == "no-store"
        assert page.count('rel="noopener noreferrer"') == len(STEPS) + 1  # NaN credit

    @pytest.mark.parametrize("query", ["", "?token=", "?token=wrong"])
    def test_a_missing_or_wrong_token_gets_nothing(self, server, query):
        status, _, page = request(server, "GET", "/" + query)
        assert status == 404
        assert "Create a project" not in page

    def test_a_foreign_host_header_is_refused(self, server):
        # DNS rebinding: a page on evil.example resolving to 127.0.0.1 sends its own Host.
        status, _, _ = request(
            server, "GET", "/?token=" + token_of(server), host=f"evil.example:{server.port}"
        )
        assert status == 403

    def test_localhost_is_an_accepted_host(self, server):
        status, _, _ = request(
            server, "GET", "/?token=" + token_of(server), host=f"localhost:{server.port}"
        )
        assert status == 200

    def test_logs_nothing(self, server, capsys):
        request(server, "GET", "/?token=" + token_of(server))
        upload(server)
        captured = capsys.readouterr()
        assert token_of(server) not in captured.err + captured.out
        assert SECRET not in captured.err + captured.out


class TestAbortedConnection:
    def test_a_client_that_hangs_up_mid_upload_prints_nothing(self, server, capsys):
        # A tab closed mid-upload must not dump a traceback into the wizard's terminal.
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        sock.sendall(
            (
                f"POST /client HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
                f"X-Easygsc-Token: {token_of(server)}\r\nContent-Length: 100\r\n\r\n"
            ).encode()
            + b"0123456789"
        )
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()  # RST: the server's reply write fails
        assert upload(server)[0] == 200  # the server still works
        assert capsys.readouterr().err == ""

    def test_a_stalled_upload_is_dropped_quietly(self, monkeypatch, capsys):
        monkeypatch.setattr(web_setup, "REQUEST_TIMEOUT", 0.3)
        with web_setup.SetupServer(STEPS, validate) as srv:
            sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
            sock.sendall(
                (
                    f"POST /client HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
                    f"X-Easygsc-Token: {token_of(srv)}\r\nContent-Length: 100\r\n\r\n"
                ).encode()
            )
            try:
                assert sock.recv(1024) == b""  # the server hung up instead of waiting
            except ConnectionResetError:
                pass
            sock.close()
            assert not srv.done
        assert capsys.readouterr().err == ""


class TestUpload:
    def test_a_valid_client_ends_the_wait_with_its_bytes(self, server):
        status, _, body = upload(server)
        assert status == 200
        assert json.loads(body) == {"ok": True}
        assert server.wait() == CLIENT

    def test_a_web_client_is_explained_and_the_page_keeps_waiting(self, server):
        web = json.dumps({"web": {"client_id": "cid", "client_secret": SECRET}}).encode()
        status, _, body = upload(server, web)
        assert status == 400
        assert "Desktop app" in json.loads(body)["error"]
        assert not server.done
        assert upload(server)[0] == 200
        assert server.wait() == CLIENT

    def test_invalid_json_is_reported_not_raised(self, server):
        status, _, body = upload(server, b"{not json")
        assert status == 400
        assert json.loads(body)["error"]
        assert not server.done

    def test_requires_the_token_header(self, server):
        status, _, _ = request(
            server, "POST", "/client", CLIENT, {"Content-Type": "application/json"}
        )
        assert status == 403
        assert not server.done

    def test_a_wrong_token_header_is_refused(self, server):
        assert upload(server, **{"X-Easygsc-Token": "wrong"})[0] == 403
        assert not server.done

    def test_a_cross_origin_request_is_refused(self, server):
        assert upload(server, Origin="https://evil.example")[0] == 403
        assert not server.done

    def test_its_own_origin_is_accepted(self, server):
        assert upload(server, Origin=f"http://127.0.0.1:{server.port}")[0] == 200

    def test_an_oversized_body_is_refused(self, server):
        big = b" " * (web_setup.MAX_UPLOAD + 1)
        assert upload(server, big)[0] == 413
        assert not server.done

    def test_a_second_upload_after_success_is_refused(self, server):
        assert upload(server)[0] == 200
        assert upload(server)[0] == 409

    def test_other_paths_are_not_found(self, server):
        sent = {"X-Easygsc-Token": token_of(server)}
        assert request(server, "POST", "/other", CLIENT, sent)[0] == 404
        assert request(server, "GET", "/client?token=" + token_of(server))[0] == 404


class TestCollectClient:
    def test_returns_none_and_stops_when_no_browser_opens(self, capsys):
        seen = []

        def opener(url):
            seen.append(url)
            return False

        assert web_setup.collect_client(STEPS, validate, opener=opener) is None
        port = urlparse(seen[0]).port
        with pytest.raises(OSError):
            http.client.HTTPConnection("127.0.0.1", port, timeout=1).request("GET", "/")

    def test_returns_the_uploaded_client(self, capsys):
        opened = threading.Event()
        seen = []

        def opener(url):
            seen.append(url)
            opened.set()
            return True

        result = []
        worker = threading.Thread(
            target=lambda: result.append(web_setup.collect_client(STEPS, validate, opener=opener))
        )
        worker.start()
        assert opened.wait(5)
        url = urlparse(seen[0])
        conn = http.client.HTTPConnection("127.0.0.1", url.port, timeout=5)
        token = parse_qs(url.query)["token"][0]
        conn.request("POST", "/client", CLIENT, {"X-Easygsc-Token": token})
        assert conn.getresponse().status == 200
        worker.join(5)
        assert result == [CLIENT]
        out = capsys.readouterr().out
        assert "browser" in out
        assert "Ctrl+C" in out
