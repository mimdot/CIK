"""core.http — HTTP + anti-bot layer: Http, RobotsCache, proxy detection.

Extracted verbatim from astra.py (migration Step 4). Pure relocation:
no behavior, signature, or output changes. The optional dependency flags
(_HAVE_PLAYWRIGHT etc.) are re-detected here so the module is self-contained;
the monolith keeps its own copies for the source-layer functions.

Dependency direction: core.http imports only from core.config (Config +
constants). Nothing imports back, so the module stays acyclic.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import time
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from core.config import (
    AUTO_DETECT_PROXY,
    BROWSER_PROFILE_DIR,
    CHALLENGE_WAIT_MS,
    Config,
    CURL_IMPERSONATION,
    PROBE_TIMEOUT,
    PROBE_URL,
    PROXY,
    PROXY_CANDIDATES,
)


log = logging.getLogger("astra")

# Optional-dependency flags (feedparser, lxml, playwright, curl_cffi) are
# detected ONCE in core/deps.py and imported here — no divergent copies.
from core.deps import (                       # noqa: E402  dependency flags
    _HAVE_CURL_CFFI,
    _HAVE_FEEDPARSER,
    _HAVE_PLAYWRIGHT,
    _HTML_PARSER,
    curl_requests,
    feedparser,
)
from core.http_cache import (                  # noqa: E402  M2 conditional-GET
    apply_validators,
    cache_key,
    get_http_cache,
    response_from_cache,
)


# Realistic browser headers used for actual page fetches (several boards serve
# bot UAs a 403 or an empty shell). robots.txt is still consulted under the
# honest USER_AGENT in core.config.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}


# -----------------------------------------------------------------------------
# SSRF guard (Sprint 10, D1) — never fetch internal/private targets.
#
# A crawler-backed platform that lets an operator/user hand it URLs must not
# reach RFC1918 / loopback / link-local / metadata addresses (classic SSRF).
# Every outbound fetch funnels through Http, so the guard lives here. It
# rejects non-http(s) schemes, raw private-IP literals, and hostnames that
# resolve (at check time) to a private/local address. Disable only for local
# experimentation with `ASTRA_SSRF_GUARD=0`.
# -----------------------------------------------------------------------------

# Networks that are never legitimate crawl targets. IPv4 includes the RFC1918
# space, loopback, link-local (incl. the cloud metadata address 169.254.169.254),
# CGNAT, benchmarking/documentation ranges, multicast and broadcast.
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
        "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
        "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
    )
)

_IPV6_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::1/128", "::/128", "::ffff:0:0/96", "64:ff9b::/96", "fc00::/7",
        "fe80::/10", "2001:db8::/32",
    )
)

# Per-host check cache: host -> reason (None when safe). Prevents a DNS lookup
# per request; 5-minute TTL. Fail-open on expiration (re-check next time).
_HOST_CHECK_CACHE: dict[str, tuple[float, Optional[str]]] = {}
_HOST_CHECK_TTL = 300.0
# Also remember the current monotonic clock for TTL math.
_tt_clock = time.monotonic


def _ssrf_enabled() -> bool:
    from core.env import env_flag
    return env_flag("ASTRA_SSRF_GUARD", default=True)


def _is_private_ip(ip: str) -> bool:
    """True if `ip` (v4 or v6, already un-bracketed) is a private/local range."""
    try:
        addr = ipaddress.ip_address(ip.strip("[]"))
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS) or any(
        addr in net for net in _IPV6_PRIVATE_NETWORKS)


def _blocked_url_reason(url: str) -> Optional[str]:
    """Return a short human reason if `url` must NOT be fetched, else None.

    Only http/https is allowed; a host that is a private-IP literal is blocked
    outright; a hostname is resolved once (cached) and blocked if ANY answer is
    private/local. An unresolvable hostname is treated as safe (the fetch will
    fail naturally) so offline/dev setups keep working.
    """
    if not _ssrf_enabled():
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return "unparseable URL"
    if p.scheme not in ("http", "https"):
        return f"disallowed scheme {p.scheme!r}"
    host = p.hostname
    if not host:
        return "no hostname in URL"
    if _is_private_ip(host):
        return f"private IP literal {host!r}"
    now = _tt_clock()
    cached = _HOST_CHECK_CACHE.get(host)
    if cached and now - cached[0] < _HOST_CHECK_TTL:
        return cached[1]
    reason: Optional[str] = None
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if _is_private_ip(ip):
                reason = f"{host!r} resolves to private IP {ip}"
                break
    except socket.gaierror:
        reason = None  # fail-open: DNS down / NXDOMAIN — fetch will fail anyway
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("SSRF check failed for %r: %s", host, exc)
        reason = None
    _HOST_CHECK_CACHE[host] = (now, reason)
    return reason


def _guard_url(url: str) -> bool:
    """True if `url` passes the SSRF guard; False (after logging) if blocked."""
    reason = _blocked_url_reason(url)
    if reason is None:
        return True
    log.warning("[ssrf] blocked fetch of %s (%s)", url, reason)
    return False


# -----------------------------------------------------------------------------
# Proxy detection
# -----------------------------------------------------------------------------
def _proxy_reachable(proxy_url: str, timeout: float = 1.5) -> bool:
    """True if the proxy's TCP port accepts connections (fast local check)."""
    try:
        p = urlparse(proxy_url)
        host, port = p.hostname, p.port
        if not host or not port:
            return True  # can't check -> assume ok
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_proxy(proxy_url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """True only if `proxy_url` ACTUALLY routes traffic (a listening port can
    still be a dead/half-broken proxy) — a tiny real request is sent through
    it. Fails fast and silently on broken candidates."""
    if not _proxy_reachable(proxy_url, timeout=0.5):
        return False
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        r = requests.get(PROBE_URL, proxies=proxies, timeout=timeout)
        return bool(r.ok and (r.text or "").strip())
    except Exception:  # pragma: no cover - network dependent
        return False


def _direct_online(timeout: float = PROBE_TIMEOUT) -> bool:
    """True if a DIRECT request reaches the probe endpoint (i.e. we have plain
    internet, proxy or not)."""
    try:
        r = requests.get(PROBE_URL, timeout=timeout)
        return bool(r.ok and (r.text or "").strip())
    except Exception:  # pragma: no cover - network dependent
        return False


def detect_proxy(configured: Optional[str],
                 auto: bool = AUTO_DETECT_PROXY) -> Optional[str]:
    """Pick the best WORKING proxy: the configured one if it really routes
    traffic, else (when auto-detect is on) the first live local candidate.
    Returns None when nothing works (caller falls back to direct or fails)."""
    if configured:
        if _probe_proxy(configured):
            return configured
        log.warning("proxy %s is configured but NOT working — scanning local "
                    "ports for a live one", configured)
    if auto:
        for cand, label in PROXY_CANDIDATES:
            if cand == configured:
                continue
            if _probe_proxy(cand):
                log.info("auto-detected working proxy: %s (%s)", cand, label)
                return cand
        log.info("no live local proxy found on the common ports")
    return None


# Markers of an anti-bot interstitial (Cloudflare et al.) in fetched HTML.
_CHALLENGE_RE = re.compile(
    r"just a moment|attention required|cf-chl|challenge-platform|"
    r"enable javascript and cookies to continue", re.I)

# Stealth init-script injected into EVERY Playwright page before any site JS
# runs. Hides the tell-tale automation signals sites fingerprint (Selenium /
# Puppeteer / headless Chrome do not set these).
_STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
});
window.chrome = window.chrome || {
  runtime: {},
  loadTimes: function () {},
  csi: function () {},
  app: {},
};
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
  window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _query(parameters);
}
for (const p of ['CDPSession', 'network', 'debugger', 'webContents']) {
  delete Object.getOwnPropertyDescriptor(window, p)?.value;
  try { delete window[p]; } catch (e) {}
}
"""


# -----------------------------------------------------------------------------
# robots.txt cache
# -----------------------------------------------------------------------------
class RobotsCache:
    """Fetches & caches robots.txt PER HOST, through the proxied session."""

    def __init__(self, http: "Http", user_agent: str, obey: bool):
        self.http = http
        self.user_agent = user_agent
        self.obey = obey
        self._parsers: dict[str, Optional[RobotFileParser]] = {}

    def _base(self, url: str) -> Optional[str]:
        try:
            p = urlparse(url)
            return f"{p.scheme}://{p.netloc}" if p.netloc else None
        except Exception:  # pragma: no cover - defensive
            return None

    def _parser(self, base: str) -> Optional[RobotFileParser]:
        if base in self._parsers:
            return self._parsers[base]
        rp: Optional[RobotFileParser] = RobotFileParser()
        resp = self.http.raw_get(base + "/robots.txt")
        if resp is not None and resp.status_code == 200 and resp.text:
            try:
                rp.parse(resp.text.splitlines())
            except Exception:  # pragma: no cover - defensive
                rp = None
        else:
            rp = None  # unknown -> treat as allow
        self._parsers[base] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        if not self.obey:
            return True
        base = self._base(url)
        if not base:
            return True
        rp = self._parser(base)
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:  # pragma: no cover - defensive
            return True

    def crawl_delay(self, url: str) -> Optional[float]:
        base = self._base(url)
        if not base:
            return None
        rp = self._parser(base)
        if rp is None:
            return None
        try:
            cd = rp.crawl_delay(self.user_agent)
            return float(cd) if cd is not None else None
        except Exception:  # pragma: no cover - defensive
            return None


# -----------------------------------------------------------------------------
# Http — requests wrapper + anti-bot chain
# -----------------------------------------------------------------------------
class Http:
    """Requests wrapper: shared session, retry/backoff, proxy, polite throttle,
    robots-aware GETs, and a graceful anti-bot fallback chain:

        requests (browser headers) -> curl_cffi (browser TLS) -> Playwright
        headless -> Playwright headed (only if a display is present)

    Every stage goes through the same proxy. No CAPTCHA solving / ban evasion:
    when the chain is exhausted the URL is skipped with a clear log line.
    """

    def __init__(self, cfg: Config, *, detect: bool = True):
        """``detect`` runs proxy auto-detection / direct-internet probing in the
        constructor (the default). Pass ``detect=False`` for the per-source
        worker instances used during concurrent fetching: the parent already
        resolved ``cfg.proxy`` once, so the workers must not each re-probe the
        network (and must not mutate the shared cfg concurrently)."""
        self.cfg = cfg
        self.timeout = cfg.timeout
        self._last_request = 0.0
        self._pw_channel: Optional[str] = "?"  # resolved on first launch
        self._pw = None            # single sync_playwright instance per run
        self._pw_ctx = None        # ONE persistent browser context, reused
        self._pw_headless = True
        self._cffi_index = 0       # curl_cffi impersonation rotation cursor

        if detect:
            if cfg.proxy or cfg.auto_detect_proxy:
                detected = detect_proxy(cfg.proxy, cfg.auto_detect_proxy)
                if detected is not None:
                    cfg.proxy = detected
                elif cfg.proxy:
                    cfg.proxy = None  # configured proxy died; sweep failed
            if not cfg.proxy:
                if cfg.proxy_fallback_direct:
                    if _direct_online():
                        log.info("no working proxy — using a DIRECT connection")
                    else:
                        log.warning("no proxy AND no direct internet — check "
                                    "your VPN/proxy (requests will fail fast "
                                    "rather than hang)")
                else:
                    log.warning("no working proxy — requests will likely fail")

        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        if cfg.proxy:
            self.session.proxies.update({"http": cfg.proxy, "https": cfg.proxy})

        # respect_retry_after_header is a TRAP for anything interactive.
        #
        # When a server answers 429 with Retry-After, urllib3 SLEEPS for
        # whatever it asks — inside the adapter, where neither the read timeout
        # nor a cancel check can reach it. OpenAlex throttles hard, so a
        # supervisor search spent minutes asleep: measured at 64s inside a
        # single request with the read timeout already down to 8s, and Stop
        # unreachable for all of it.
        #
        # Turning retries OFF instead is worse, not better: the 429 then goes
        # straight through as a failure and the search returns nothing at all
        # (measured: pool=0 in 0.7s). So the retries stay and only the SLEEP is
        # bounded — exponential backoff, which backoff_factor caps.
        # Crawling keeps the polite default; see cfg.respect_retry_after.
        retry = Retry(
            total=cfg.max_retries, connect=cfg.max_retries,
            read=cfg.max_retries, status=cfg.max_retries,
            backoff_factor=cfg.backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=getattr(
                cfg, "respect_retry_after", True),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.robots = RobotsCache(self, cfg.user_agent, cfg.robots_obey)
        # M2: shared persistent conditional-GET cache (None when off / testing).
        self._cache = get_http_cache(cfg)

    # -- conditional-GET cache (M2) -------------------------------------------
    def _cache_lookup(self, url: str, params=None) -> Optional[dict]:
        """Cached entry for a request, or None (also None under --force-refresh
        so the request is made unconditionally but the cache is still updated)."""
        if self._cache is None or self.cfg.force_refresh:
            return None
        return self._cache.get_entry(cache_key(url, params))

    def _cache_store(self, url: str, params, resp) -> None:
        """Persist a 200 response's validators + body when it carries an ETag or
        Last-Modified (nothing to revalidate against otherwise)."""
        if self._cache is None or resp is None or resp.status_code != 200:
            return
        etag = resp.headers.get("ETag")
        last_modified = resp.headers.get("Last-Modified")
        if etag or last_modified:
            self._cache.store(cache_key(url, params), etag, last_modified,
                              resp.content, resp.encoding)

    # -- throttling -----------------------------------------------------------
    def _throttle(self, extra_delay: float = 0.0) -> None:
        wait = max(self.cfg.delay, extra_delay) - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # -- plain GETs -----------------------------------------------------------
    def raw_get(self, url: str, **kw) -> Optional["requests.Response"]:
        """GET without a robots check (used to fetch robots.txt itself)."""
        if not _guard_url(url):
            return None
        self._throttle()
        params = kw.get("params")
        entry = self._cache_lookup(url, params)
        if entry is not None:
            headers = dict(kw.get("headers") or {})
            apply_validators(headers, entry)
            kw["headers"] = headers
        try:
            resp = self.session.get(
                url, timeout=(self.cfg.connect_timeout, self.timeout), **kw)
        except requests.RequestException as exc:
            log.debug("raw_get failed %s: %s", url, exc)
            return None
        if resp.status_code == 304 and entry is not None:
            return response_from_cache(url, entry)
        self._cache_store(url, params, resp)
        return resp

    def get(self, url: str, *, params=None, headers=None, impersonate=True,
            ignore_robots=False):
        """Robots-aware, throttled, retrying GET with curl_cffi fallback on
        anti-bot 403/503. Returns a Response-like object or None.

        `ignore_robots=True` skips the robots.txt check for THIS request only.
        Reserved for low-volume, user-initiated personal queries against
        endpoints whose robots.txt blanket-disallows all bots (e.g. LinkedIn's
        public guest job search) —         never used for crawling."""
        if not _guard_url(url):
            return None
        if not ignore_robots and not self.robots.can_fetch(url):
            log.warning("robots.txt disallows %s — skipping", url)
            return None
        self._throttle(self.robots.crawl_delay(url) or 0.0)
        resp = None
        challenged = False
        # M2: revalidate with the cached ETag / Last-Modified when available.
        entry = self._cache_lookup(url, params)
        req_headers = headers
        if entry is not None:
            req_headers = dict(headers or {})
            apply_validators(req_headers, entry)
        try:
            resp = self.session.get(url, params=params, headers=req_headers,
                                    timeout=(self.cfg.connect_timeout,
                                             self.timeout))
            if resp.status_code == 304 and entry is not None:
                log.debug("304 %s — served from HTTP cache", url)
                return response_from_cache(url, entry)
            if resp.status_code < 400:
                # a 200 can still be a Cloudflare interstitial, not content
                if _CHALLENGE_RE.search(resp.text[:6000] or ""):
                    challenged = True
                else:
                    self._cache_store(url, params, resp)
                    return resp
        except requests.RequestException as exc:
            log.debug("GET failed %s: %s", url, exc)
        status = resp.status_code if resp is not None else "n/a"
        # Browser-TLS fallback only for anti-bot style rejections — a plain
        # 404 (e.g. Nature's zero-results response) is a real answer.
        blocked = (challenged or resp is None
                   or resp.status_code in (401, 403, 406, 429, 503))
        if blocked and impersonate and _HAVE_CURL_CFFI:
            log.debug("GET %s -> %s; retrying with browser TLS fingerprint",
                      url, status)
            r2 = self._cffi_get(url, params=params, headers=headers)
            if r2 is not None:
                return r2
        log.warning("GET failed %s (status %s%s)", url, status,
                    "" if _HAVE_CURL_CFFI else "; pip install curl_cffi for a "
                    "browser-TLS fallback")
        return None

    def _cffi_get(self, url: str, *, params=None, headers=None):
        """curl_cffi GET impersonating a real browser TLS fingerprint.
        Rotates through CURL_IMPERSONATION on consecutive blocked requests
        (a rotating, recent Chrome fingerprint trips far fewer bot filters
        than a single static one)."""
        if not _guard_url(url):
            return None
        self._throttle()
        proxies = None
        if self.cfg.proxy:
            proxies = {"http": self.cfg.proxy, "https": self.cfg.proxy}
        attempts = len(CURL_IMPERSONATION)
        for attempt in range(attempts):
            imp = CURL_IMPERSONATION[(self._cffi_index + attempt) % attempts]
            try:
                r = curl_requests.get(
                    url, params=params, impersonate=imp,
                    headers={"Accept-Language": "en-US,en;q=0.9",
                             **(headers or {})},
                    proxies=proxies, timeout=(self.cfg.connect_timeout,
                                              self.timeout))
                if r.status_code < 400:
                    if _CHALLENGE_RE.search((r.text or "")[:6000]):
                        log.debug("curl_cffi(%s) %s -> challenge page", imp, url)
                        continue
                    self._cffi_index += 1
                    return r
                log.debug("curl_cffi(%s) %s -> %s", imp, url, r.status_code)
            except Exception as exc:
                log.debug("curl_cffi(%s) failed %s: %s", imp, url, exc)
            if attempt == attempts - 1:
                # last try falls back to the safest generic fingerprint
                continue
        self._cffi_index += 1
        return None

    # -- parsed variants ------------------------------------------------------
    def get_soup(self, url: str, **kw) -> Optional[BeautifulSoup]:
        resp = self.get(url, **kw)
        if resp is None:
            return None
        try:
            return BeautifulSoup(resp.text, _HTML_PARSER)
        except Exception as exc:
            log.warning("HTML parse failed %s: %s", url, exc)
            return None

    def get_feed(self, url: str, **kw):
        """Fetch via the proxied/robots-aware chain, then hand to feedparser."""
        if not _HAVE_FEEDPARSER:
            log.warning("feedparser not installed; cannot read feed %s "
                        "(pip install feedparser)", url)
            return None
        resp = self.get(url, **kw)
        if resp is None:
            return None
        try:
            return feedparser.parse(resp.content)
        except Exception as exc:
            log.warning("feed parse failed %s: %s", url, exc)
            return None

    # -- full layered page fetch ---------------------------------------------
    def fetch_page(self, url: str, *, wait_selector: Optional[str] = None,
                   referer: Optional[str] = None) -> Optional[str]:
        """Fetch a page's HTML through the FULL anti-bot chain:

            (1) requests with realistic browser headers (+ Referer)
            (2) curl_cffi with a real browser TLS fingerprint   [auto in get()]
            (3) Playwright headless, domcontentloaded + wait_for_selector
                (never 'networkidle' — ad-heavy boards never reach it)

        Every stage goes through the configured proxy. Returns HTML or None
        (the URL is then skipped politely — no CAPTCHA solving, no evasion).
        """
        if not referer:
            try:
                p = urlparse(url)
                referer = f"{p.scheme}://{p.netloc}/"
            except Exception:
                referer = None
        headers = {"Referer": referer} if referer else None
        resp = self.get(url, headers=headers)          # layers 1 + 2
        if resp is not None and getattr(resp, "text", None):
            return resp.text
        if _HAVE_PLAYWRIGHT:                           # layer 3
            log.info("%s: plain fetch blocked — trying a headless browser", url)
            return self.get_rendered(url, wait_selector=wait_selector)
        log.warning("%s: blocked and Playwright not installed — skipping "
                    "(pip install playwright && playwright install chromium)",
                    url)
        return None

    # -- headless / headed browser -------------------------------------------
    def _pw_proxy(self) -> Optional[dict]:
        """Playwright proxy dict. Chromium only understands socks5:// (not
        socks5h://); remote DNS is forced via --host-resolver-rules instead."""
        if not self.cfg.proxy:
            return None
        return {"server": re.sub(r"^socks5h://", "socks5://", self.cfg.proxy)}

    def _pw_args(self) -> list[str]:
        args = []
        if self.cfg.proxy and self.cfg.proxy.startswith("socks5"):
            # Resolve DNS through the SOCKS proxy (Chromium resolves locally
            # by default, which breaks under DNS poisoning).
            args.append("--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1")
        return args

    def _pw_ensure(self) -> bool:
        """Lazily start ONE Playwright instance + ONE PERSISTENT browser
        context (cookies/localStorage survive between runs in
        BROWSER_PROFILE_DIR, so a site that trusted us yesterday usually
        still trusts us today). Reused by every get_rendered() call —
        no more browser-launch-per-URL."""
        if self._pw_ctx is not None:
            return True
        if not _HAVE_PLAYWRIGHT:
            return False
        try:
            from playwright.sync_api import sync_playwright as _sp
            self._pw = _sp().start()
        except Exception as exc:
            log.warning("Playwright unavailable (%s) — JS pages skipped", exc)
            self._pw = None
            return False
        headless = (self.cfg.browser_headless is None
                    or bool(self.cfg.browser_headless))
        base_kw = dict(
            user_data_dir=self.cfg.browser_profile_dir,
            headless=headless,
            args=self._pw_args(),
            proxy=self._pw_proxy(),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            user_agent=BROWSER_HEADERS["User-Agent"],
        )
        attempts = [("chrome", {"channel": "chrome"}), ("chromium", {})]
        if self._pw_channel == "chromium":
            attempts = [("chromium", {})]
        last_exc: Optional[Exception] = None
        for label, extra in attempts:
            try:
                self._pw_ctx = self._pw.chromium.launch_persistent_context(
                    **base_kw, **extra)
                self._pw_channel = label
                break
            except Exception as exc:
                last_exc = exc
                self._pw_ctx = None
        if self._pw_ctx is None:
            log.warning("could not start a browser (%s) — JS pages skipped",
                        last_exc)
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
            return False
        self._pw_ctx.add_init_script(_STEALTH_JS)
        self._pw_headless = headless
        log.info("browser: persistent profile %s (%s mode, %s channel)",
                 self.cfg.browser_profile_dir,
                 "headless" if headless else "headed", self._pw_channel)
        return True

    def _pw_headed_retry(self) -> None:
        """Relaunch the persistent context with a VISIBLE window. Only called
        once per run: after a Cloudflare interstitial refused to clear in
        headless mode AND a desktop display is present."""
        try:
            self._pw_ctx.close()
        except Exception:
            pass
        self._pw_ctx = None
        kw = dict(
            user_data_dir=self.cfg.browser_profile_dir,
            headless=False,
            args=self._pw_args(),
            proxy=self._pw_proxy(),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            user_agent=BROWSER_HEADERS["User-Agent"],
        )
        if self._pw_channel == "chrome":
            kw["channel"] = "chrome"
        try:
            self._pw_ctx = self._pw.chromium.launch_persistent_context(**kw)
            self._pw_ctx.add_init_script(_STEALTH_JS)
            self._pw_headless = False
            log.info("browser: relaunched HEADED (profile %s)",
                     self.cfg.browser_profile_dir)
        except Exception as exc:
            log.warning("headed relaunch failed (%s) — staying headless", exc)
            self._pw_ctx = None

    def _pw_browser(self, pw, *, headless: bool = True):
        """Launch a SHORT-LIVED (non-persistent) Chromium browser for one-off
        tasks like XHR interception, reusing the configured proxy/channel/UA.
        The caller owns the returned browser and must close() it. Does not
        touch the shared persistent context managed by _pw_ensure().

        NOTE: currently unused by any built-in source (academictransfer now
        intercepts through the shared persistent context). Kept as a public
        helper for future sources that need a throwaway browser (e.g. session
        bootstrapping) without touching the persistent profile."""
        kw = dict(
            headless=headless,
            args=self._pw_args(),
            proxy=self._pw_proxy(),
        )
        channel = self._pw_channel if self._pw_channel != "?" else "chromium"
        if channel == "chrome":
            kw["channel"] = "chrome"
        try:
            return pw.chromium.launch(**kw)
        except Exception as exc:
            log.warning("short-lived browser launch failed (%s)", exc)
            return None

    def close(self) -> None:
        """Close the shared browser if it was started (run cleanup)."""
        if self._pw_ctx is not None:
            try:
                self._pw_ctx.close()
            except Exception:
                pass
            self._pw_ctx = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def get_rendered(self, url: str, wait_selector: Optional[str] = None,
                     timeout_ms: int = 30000) -> Optional[str]:
        """Render a JS page with the SHARED persistent browser and return HTML.

        Uses wait_until='domcontentloaded' + wait_for_selector (NEVER
        'networkidle' — ad-heavy boards never reach network idle). If a
        Cloudflare challenge blocks the headless pass and a desktop display is
        available (and HEADED_FALLBACK), retries once with a visible window.
        Returns None if the page can't be loaded politely.
        """
        if not _HAVE_PLAYWRIGHT:
            log.warning("Playwright not installed, cannot render %s "
                        "(pip install playwright && playwright install chromium)",
                        url)
            return None
        if not _guard_url(url):
            return None
        if not self.robots.can_fetch(url):
            log.warning("robots.txt disallows %s — skipping", url)
            return None
        if not self._pw_ensure():
            return None

        has_display = bool(os.environ.get("DISPLAY")
                           or os.environ.get("WAYLAND_DISPLAY"))
        challenge_seen = False
        self._throttle(self.robots.crawl_delay(url) or 0.0)
        try:
            page = self._pw_ctx.new_page()
        except Exception as exc:
            log.warning("browser page create failed %s: %s", url, exc)
            return None
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            selector_ok = True
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    selector_ok = False
            html = page.content()
            if not _CHALLENGE_RE.search(html or ""):
                return html  # real content (selector may legitimately be absent)
            challenge_seen = True
            page.wait_for_timeout(self.cfg.challenge_wait_ms)
            html = page.content()
            if not _CHALLENGE_RE.search(html or ""):
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=8000)
                    except Exception:
                        pass
                return page.content()
            if (self.cfg.headed_fallback and has_display and self._pw_headless):
                log.info("%s: challenge persists headless — one visible-window "
                         "retry", url)
                self._pw_headed_retry()
                if self._pw_ctx is None:
                    return None
                # Use a SEPARATE page object so an exception in this branch can
                # never orphan the outer page (which finally closes itself).
                page2 = self._pw_ctx.new_page()
                try:
                    page2.goto(url, timeout=timeout_ms,
                               wait_until="domcontentloaded")
                    if wait_selector:
                        try:
                            page2.wait_for_selector(wait_selector,
                                                    timeout=timeout_ms)
                        except Exception:
                            pass
                    html2 = page2.content()
                    if not _CHALLENGE_RE.search(html2 or ""):
                        return html2
                finally:
                    try:
                        page2.close()
                    except Exception:
                        pass
            log.warning("%s: blocked by an anti-bot challenge. This is "
                        "usually the PROXY EXIT IP's reputation, not this "
                        "script — try a different V2Ray server, or warm the "
                        "profile once with --fresh-profile. Skipping politely.",
                        url)
            return None
        except Exception as exc:
            log.debug("Playwright render failed %s: %s", url, exc)
            return None
        finally:
            try:
                page.close()
            except Exception:
                pass