"""SRM login and current-user Windows credential storage."""

import base64
import ctypes
import json
import os
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright

from site_profile import SiteProfile, load_site_profile


TARGET_PATH = "/srm/finance/sale/SaleDeductCostList"
LOGIN_PATH = "/user/login?redirect=%2Fsrm%2Ffinance%2Fsale%2FSaleDeductCostList"
CREDENTIALS_FILE = "credentials.dpapi"
SESSION_FILE = "session.dpapi"
STORAGE_KEYS = ("t_token", "pro__Access-Token", "pro__Login_elsAccount")
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class AuthError(RuntimeError):
    """An authentication error safe to display in the app or log."""


class SessionExpired(AuthError):
    """The server requires a fresh sign-in before querying SRM."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_protect(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise AuthError("保存登录信息需要 Windows。")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = (
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    )
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    try:
        if not operation(
            ctypes.byref(source), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
        ):
            message = "无法解密登录信息，请用当前 Windows 用户重新保存或登录。" if decrypt else "Windows 无法加密保存登录信息。"
            raise AuthError(message)
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if output.pbData:
            if decrypt:
                ctypes.memset(output.pbData, 0, output.cbData)
            kernel32.LocalFree(output.pbData)


def _write_protected(path: Path, data: dict) -> None:
    encrypted = _windows_protect(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as output:
            temp_path = Path(output.name)
            output.write(encrypted)
        temp_path.replace(path)
    except OSError:
        raise AuthError("无法写入本机的登录信息，请检查程序数据目录的权限。") from None
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _read_protected(path: Path) -> dict | None:
    try:
        encrypted = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise AuthError("无法读取本机的登录信息，请检查程序数据目录的权限。") from None

    try:
        data = json.loads(_windows_protect(encrypted, decrypt=True))
    except (UnicodeError, ValueError):
        raise AuthError("本机登录信息已损坏，请重新保存或登录。") from None
    if not isinstance(data, dict):
        raise AuthError("本机登录信息已损坏，请重新保存或登录。")
    return data


def _delete_protected(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise AuthError("无法清除本机登录信息，请检查程序数据目录的权限。") from None


def _credentials(account: str, sub: str, password: str) -> tuple[str, str, str]:
    if not all(isinstance(value, str) for value in (account, sub, password)):
        raise AuthError("请重新输入并保存 SRM 登录信息。")
    account, sub = account.strip(), sub.strip()
    if not account or not password:
        raise AuthError("请填写 ELS 账号和密码。")
    return account, sub, password


def has_credentials(data_dir: Path) -> bool:
    """Return whether this Windows user has credentials for the current site."""
    data_dir = Path(data_dir)
    return _load_credentials(data_dir, load_site_profile(data_dir).srm_origin) is not None


def _load_credentials(data_dir: Path, origin: str) -> tuple[str, str, str] | None:
    data = _read_protected(data_dir / CREDENTIALS_FILE)
    if not data or data.get("origin") != origin:
        return None
    return _credentials(data.get("account"), data.get("sub"), data.get("password"))


def save_credentials(data_dir: Path, account: str, sub: str, password: str) -> None:
    account, sub, password = _credentials(account, sub, password)
    data_dir = Path(data_dir)
    origin = load_site_profile(data_dir).srm_origin
    try:
        old = _load_credentials(data_dir, origin)
    except AuthError:
        old = None
    if old is None or old[:2] != (account, sub):
        clear_session(data_dir)
    _write_protected(data_dir / CREDENTIALS_FILE, {
        "origin": origin, "account": account, "sub": sub, "password": password,
    })


def forget_credentials(data_dir: Path) -> None:
    _delete_protected(Path(data_dir) / CREDENTIALS_FILE)


def clear_session(data_dir: Path) -> None:
    _delete_protected(Path(data_dir) / SESSION_FILE)


def has_session(data_dir: Path) -> bool:
    """Return whether the saved browser sign-in for the current site is still valid."""
    data_dir = Path(data_dir)
    try:
        state = _read_protected(data_dir / SESSION_FILE)
        if not state:
            return False
        SrmSession(state, origin=load_site_profile(data_dir).srm_origin).close()
    except (AuthError, ValueError):
        return False
    return True


def _unwrap(value: str) -> str:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return value
    if isinstance(decoded, dict) and "value" in decoded:
        return str(decoded["value"]) if decoded["value"] is not None else ""
    return value


def _token(local: dict) -> str:
    return local.get("t_token") or local.get("pro__Access-Token") or ""


def _has_expired(token: str) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        expiration = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return isinstance(expiration, (int, float)) and expiration <= time.time() + 20
    except (UnicodeError, ValueError, AttributeError):
        return False


def _srm_origin_key(url: str) -> tuple[str, int] | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    return parts.hostname, port if port is not None else 443


def _is_srm_url(url: str, origin: str) -> bool:
    key = _srm_origin_key(url)
    return key is not None and key == _srm_origin_key(origin)


class _SameOriginSession(requests.Session):
    def __init__(self, origin: str):
        super().__init__()
        self.origin = origin

    def send(self, request, **kwargs):
        if not _is_srm_url(request.url, self.origin):
            raise AuthError("SRM 返回了其他站点地址，请重新登录后再试。")
        return super().send(request, **kwargs)


class SrmSession:
    def __init__(self, state: dict, *, origin: str):
        if state.get("origin") != origin:
            raise SessionExpired("当前 SRM 站点需要重新登录。")
        self.origin = origin
        self.local = state.get("local") or {}
        self.token = _token(self.local)
        if not self.token or _has_expired(self.token):
            raise SessionExpired("SRM 会话已过期，请重新登录。")
        self.els_account = self.local.get("pro__Login_elsAccount", "")
        self.s = _SameOriginSession(origin)
        self.s.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{origin}{TARGET_PATH}",
            "Origin": origin,
            "X-Access-Token": self.token,
        })
        if state.get("user_agent"):
            self.s.headers["User-Agent"] = state["user_agent"]
        for cookie in state.get("cookies", []):
            self.s.cookies.set(
                cookie["name"], cookie["value"], domain=cookie["domain"],
                path=cookie["path"], secure=True,
                expires=int(cookie["expires"]) if cookie.get("expires", -1) > 0 else None,
            )

    def close(self) -> None:
        self.s.close()

    def get(self, path: str, **params) -> dict:
        url = urljoin(f"{self.origin}/", path)
        try:
            response = self.s.get(url, params=params, timeout=(10, 40))
        except requests.Timeout:
            raise requests.Timeout("连接 SRM 超时，请检查网络后重试。") from None
        except requests.RequestException:
            raise requests.RequestException("无法连接 SRM，请检查网络后重试。") from None
        if response.status_code == 401 or "/user/login" in urlsplit(response.url).path:
            raise SessionExpired("SRM 会话已过期，请重新登录。")
        if response.status_code == 403:
            raise AuthError("当前账号无权查询 SRM 扣款。")
        if not response.ok:
            raise requests.HTTPError(f"SRM 查询失败（HTTP {response.status_code}）。")
        try:
            data = response.json()
        except ValueError:
            raise requests.RequestException("SRM 查询没有返回数据，请检查系统是否可用。") from None
        if not isinstance(data, dict):
            raise requests.RequestException("SRM 查询返回了无法识别的数据。")
        code = str(data.get("code"))
        if code == "401" or _is_login_error(data):
            raise SessionExpired("SRM 会话已过期，请重新登录。")
        if code == "403":
            raise AuthError("当前账号无权查询 SRM 扣款。")
        return data


def _is_login_error(data: dict) -> bool:
    if data.get("result") or data.get("success") is True:
        return False
    message = str(data.get("message") or data.get("msg") or "").lower()
    return any(marker in message for marker in (
        "未登录", "没有登录", "请登录", "重新登录", "登录超时", "登录失效", "登录过期",
        "token失效", "token过期", "token expired", "invalid token",
    ))


def _open_login_dialog(page, *, manual: bool) -> None:
    account_field = page.get_by_placeholder("请输入ELS账号")
    if account_field.is_visible():
        return
    for label in ("登 录", "登录"):
        button = page.get_by_role("button", name=label, exact=True).first
        try:
            button.click(timeout=4000)
            return
        except PlaywrightTimeout:
            continue
    if not manual:
        account_field.wait_for(state="visible", timeout=10000)


def _browser_state(context, page, origin: str) -> dict | None:
    if not _is_srm_url(page.url, origin) or "/user/login" in urlsplit(page.url).path:
        return None
    storage = page.evaluate(
        "keys => ({origin: location.origin, local: Object.fromEntries(keys.map(key => [key, localStorage.getItem(key)]))})",
        list(STORAGE_KEYS),
    )
    if not _is_srm_url(storage["origin"], origin):
        return None
    local = {name: _unwrap(value) for name, value in storage["local"].items() if value}
    token = _token(local)
    if not token or _has_expired(token):
        return None
    return {
        "origin": origin,
        "local": local,
        "cookies": context.cookies(origin),
        "user_agent": page.evaluate("navigator.userAgent"),
    }


def launch_login(
    data_dir: Path, *, manual: bool = True, credentials: tuple[str, str, str] | None = None,
    profile: SiteProfile | None = None,
) -> SrmSession:
    data_dir = Path(data_dir)
    profile = profile or load_site_profile(data_dir)
    origin = profile.srm_origin
    if not manual:
        credentials = _credentials(*credentials) if credentials is not None else _load_credentials(data_dir, origin)
        if credentials is None:
            raise AuthError("请先保存 SRM 登录凭据，或打开浏览器登录一次。")

    try:
        with sync_playwright() as driver:
            try:
                browser = driver.chromium.launch(channel="msedge", headless=not manual)
            except PlaywrightError:
                raise AuthError("无法启动 Microsoft Edge，请确认已安装 Edge 后重试。") from None
            try:
                context = browser.new_context(locale="zh-CN")
                page = context.new_page()
                page.goto(f"{origin}{LOGIN_PATH}", wait_until="domcontentloaded", timeout=45000)
                if not _is_srm_url(page.url, origin):
                    raise AuthError("SRM 登录跳转到了其他站点，登录已停止。")
                _open_login_dialog(page, manual=manual)
                if not manual:
                    account, sub, password = credentials
                    account_field = page.get_by_placeholder("请输入ELS账号")
                    account_field.wait_for(state="visible", timeout=12000)
                    if not _is_srm_url(page.url, origin):
                        raise AuthError("SRM 登录跳转到了其他站点，自动登录已停止。")
                    account_field.fill(account, timeout=8000)
                    if sub:
                        page.get_by_placeholder("请输入子账号").fill(sub, timeout=8000)
                    if not _is_srm_url(page.url, origin):
                        raise AuthError("SRM 登录跳转到了其他站点，自动登录已停止。")
                    page.get_by_placeholder("密码").fill(password, timeout=8000)
                    page.locator("button.loginBtn").first.click(timeout=8000)

                deadline = time.monotonic() + (300 if manual else 35)
                while time.monotonic() < deadline:
                    try:
                        state = _browser_state(context, page, origin)
                    except PlaywrightError:
                        if page.is_closed():
                            raise AuthError("登录窗口已关闭，请重新打开后登录。") from None
                        state = None
                    if state:
                        if not manual:
                            state["saved_identity"] = list(credentials[:2])
                        session = SrmSession(state, origin=origin)
                        _write_protected(data_dir / SESSION_FILE, state)
                        return session
                    page.wait_for_timeout(700)
            finally:
                browser.close()
    except PlaywrightError:
        raise AuthError("无法完成 SRM 登录，请检查网络，并在浏览器中确认登录页面可用。") from None
    if manual:
        raise AuthError("浏览器登录等待超时，请重新打开登录窗口。")
    raise AuthError("SRM 自动登录失败，请核对已保存的凭据，或打开浏览器确认是否需要人工验证。")


def get_session(
    data_dir: Path, *, refresh: bool = False, scheduled: bool = False, profile: SiteProfile | None = None,
) -> SrmSession:
    data_dir = Path(data_dir)
    profile = profile or load_site_profile(data_dir)
    origin = profile.srm_origin
    credentials = _load_credentials(data_dir, origin) if scheduled else None
    if scheduled and credentials is None:
        raise AuthError("定时运行需要先保存当前 SRM 站点的登录凭据。")

    if not refresh:
        try:
            state = _read_protected(data_dir / SESSION_FILE)
            if state and (not scheduled or state.get("saved_identity") == list(credentials[:2])):
                return SrmSession(state, origin=origin)
        except AuthError:
            pass
    if credentials is None:
        credentials = _load_credentials(data_dir, origin)
    if credentials is None:
        raise AuthError("本机没有有效的 SRM 会话。请打开浏览器登录，或保存凭据以便自动登录。")
    return launch_login(data_dir, manual=False, credentials=credentials, profile=profile)
