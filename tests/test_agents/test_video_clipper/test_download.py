"""Unit tests for the video_clipper download step (no network)."""

import httpx
import pytest

from app.agents.video_clipper.steps import download


# ── helpers / fakes ─────────────────────────────────────────────────────────

def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://r.googlevideo.com/x")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


class _FakeSettings:
    RAPIDAPI_KEY = "test-key"


class _FakeResolveResponse:
    """Stands in for the httpx response of the RapidAPI /dl call."""

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeStream:
    def __init__(self, chunks: list[bytes], status: int = 200):
        self._chunks = chunks
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise _http_error(self._status)

    def iter_bytes(self, chunk_size: int = 0):
        yield from self._chunks


class _FakeHttpxClient:
    """Fake httpx.Client supporting both `.get()` and `.stream()`."""

    captured_headers: dict = {}

    def __init__(self, *, payload=None, chunks=None, stream_status=200, **_kwargs):
        self._payload = payload or {}
        self._chunks = chunks if chunks is not None else [b"data"]
        self._stream_status = stream_status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *_args, **_kwargs):
        return _FakeResolveResponse(self._payload)

    def stream(self, _method, _url, headers=None, **_kwargs):
        type(self).captured_headers = headers or {}
        return _FakeStream(self._chunks, status=self._stream_status)


# ── _download_youtube: retry / iteration logic ──────────────────────────────

class TestDownloadYoutubeRetry:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        import app.config

        monkeypatch.setattr(app.config, "get_settings", lambda: _FakeSettings())

    def test_succeeds_on_first_format(self, monkeypatch, tmp_path):
        resolves = []
        monkeypatch.setattr(
            download, "_resolve_mp4_candidates",
            lambda vid, s: resolves.append(1) or [{"url": "u1", "itag": 18}],
        )
        used = []
        monkeypatch.setattr(download, "_stream_media", lambda url, out: used.append(url))

        out = tmp_path / "v.mp4"
        download._download_youtube("https://youtu.be/abcdef12345", out)

        assert used == ["u1"]
        assert len(resolves) == 1  # no re-resolve needed

    def test_falls_through_to_next_format_on_403(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            download, "_resolve_mp4_candidates",
            lambda vid, s: [{"url": "bad", "itag": 22}, {"url": "good", "itag": 18}],
        )

        def _stream(url, out):
            if url == "bad":
                raise _http_error(403)

        used = []
        monkeypatch.setattr(
            download, "_stream_media",
            lambda url, out: used.append(url) or _stream(url, out),
        )

        download._download_youtube("https://youtu.be/abcdefg1234", tmp_path / "v.mp4")
        assert used == ["bad", "good"]

    def test_reresolves_once_when_all_formats_403(self, monkeypatch, tmp_path):
        resolve_calls = {"n": 0}

        def _resolve(vid, s):
            resolve_calls["n"] += 1
            if resolve_calls["n"] == 1:
                return [{"url": "stale", "itag": 18}]
            return [{"url": "fresh", "itag": 18}]

        monkeypatch.setattr(download, "_resolve_mp4_candidates", _resolve)

        def _stream(url, out):
            if url == "stale":
                raise _http_error(403)

        monkeypatch.setattr(download, "_stream_media", _stream)

        download._download_youtube("https://youtu.be/abcdefg1234", tmp_path / "v.mp4")
        assert resolve_calls["n"] == 2

    def test_raises_runtime_error_after_exhausting(self, monkeypatch, tmp_path):
        resolve_calls = {"n": 0}

        def _resolve(vid, s):
            resolve_calls["n"] += 1
            return [{"url": "u", "itag": 18}]

        monkeypatch.setattr(download, "_resolve_mp4_candidates", _resolve)
        monkeypatch.setattr(
            download, "_stream_media",
            lambda url, out: (_ for _ in ()).throw(_http_error(403)),
        )

        with pytest.raises(RuntimeError, match="403 after re-resolving"):
            download._download_youtube("https://youtu.be/abcdefg1234", tmp_path / "v.mp4")
        assert resolve_calls["n"] == 2  # tried, re-resolved, tried again

    def test_non_403_propagates_immediately(self, monkeypatch, tmp_path):
        resolve_calls = {"n": 0}
        monkeypatch.setattr(
            download, "_resolve_mp4_candidates",
            lambda vid, s: resolve_calls.__setitem__("n", resolve_calls["n"] + 1)
            or [{"url": "u", "itag": 18}],
        )
        monkeypatch.setattr(
            download, "_stream_media",
            lambda url, out: (_ for _ in ()).throw(_http_error(404)),
        )

        with pytest.raises(httpx.HTTPStatusError):
            download._download_youtube("https://youtu.be/abcdefg1234", tmp_path / "v.mp4")
        assert resolve_calls["n"] == 1  # no re-resolve on non-403

    def test_missing_api_key_raises(self, monkeypatch, tmp_path):
        import app.config

        class _NoKey:
            RAPIDAPI_KEY = ""

        monkeypatch.setattr(app.config, "get_settings", lambda: _NoKey())
        with pytest.raises(RuntimeError, match="RAPIDAPI_KEY is not configured"):
            download._download_youtube("https://youtu.be/abcdefg1234", tmp_path / "v.mp4")


# ── _stream_media: headers + write ──────────────────────────────────────────

class TestStreamMedia:
    def test_sends_range_and_android_vr_ua_and_writes(self, monkeypatch, tmp_path):
        _FakeHttpxClient.captured_headers = {}
        monkeypatch.setattr(
            download.httpx, "Client",
            lambda **kw: _FakeHttpxClient(chunks=[b"abc", b"def"]),
        )

        out = tmp_path / "v.mp4"
        download._stream_media("https://r.googlevideo.com/x", out)

        assert out.read_bytes() == b"abcdef"
        assert _FakeHttpxClient.captured_headers["Range"] == "bytes=0-"
        assert _FakeHttpxClient.captured_headers["User-Agent"] == download._ANDROID_VR_UA

    def test_206_partial_content_is_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            download.httpx, "Client",
            lambda **kw: _FakeHttpxClient(chunks=[b"x"], stream_status=206),
        )
        out = tmp_path / "v.mp4"
        download._stream_media("https://r.googlevideo.com/x", out)
        assert out.read_bytes() == b"x"

    def test_403_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            download.httpx, "Client",
            lambda **kw: _FakeHttpxClient(chunks=[b"x"], stream_status=403),
        )
        with pytest.raises(httpx.HTTPStatusError):
            download._stream_media("https://r.googlevideo.com/x", tmp_path / "v.mp4")


# ── _resolve_mp4_candidates: parsing / sorting ──────────────────────────────

class TestResolveMp4Candidates:
    def _patch_client(self, monkeypatch, payload):
        monkeypatch.setattr(
            download.httpx, "Client",
            lambda **kw: _FakeHttpxClient(payload=payload),
        )

    def test_filters_non_mp4_and_urlless_then_sorts_desc(self, monkeypatch):
        payload = {
            "formats": [
                {"url": "u360", "mimeType": "video/mp4", "height": 360, "itag": 18},
                {"url": "u720", "mimeType": "video/mp4", "height": 720, "itag": 22},
                {"url": "uwebm", "mimeType": "video/webm", "height": 480, "itag": 43},
                {"mimeType": "video/mp4", "height": 1080, "itag": 37},  # no url
            ]
        }
        self._patch_client(monkeypatch, payload)
        out = download._resolve_mp4_candidates("vid", _FakeSettings())
        assert [f["itag"] for f in out] == [22, 18]  # best-first, mp4+url only

    def test_prefers_le_1080_when_available(self, monkeypatch):
        payload = {
            "formats": [
                {"url": "u4k", "mimeType": "video/mp4", "height": 2160, "itag": 313},
                {"url": "u1080", "mimeType": "video/mp4", "height": 1080, "itag": 137},
            ]
        }
        self._patch_client(monkeypatch, payload)
        out = download._resolve_mp4_candidates("vid", _FakeSettings())
        assert [f["itag"] for f in out] == [137]

    def test_raises_when_no_progressive_mp4(self, monkeypatch):
        self._patch_client(monkeypatch, {"formats": []})
        with pytest.raises(RuntimeError, match="no progressive mp4"):
            download._resolve_mp4_candidates("vid", _FakeSettings())

    def test_raises_on_provider_status_fail(self, monkeypatch):
        self._patch_client(monkeypatch, {"status": "fail", "msg": "quota"})
        with pytest.raises(RuntimeError, match="RapidAPI YouTube download failed"):
            download._resolve_mp4_candidates("vid", _FakeSettings())
