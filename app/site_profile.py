"""Read and save deployment settings scoped to the local Windows profile."""

from dataclasses import asdict, dataclass
from ipaddress import ip_address
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit


PROFILE_NAME = "site.json"


class ProfileError(ValueError):
    pass


def _origin(value: str, label: str) -> str:
    error = ProfileError(f"{label}请输入 HTTPS 站点地址，例如 https://srm.example.com。")
    if not isinstance(value, str):
        raise error
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value or "?" in value or "#" in value:
        raise error
    try:
        url = urlsplit(value)
        hostname = url.hostname
        port = url.port
    except ValueError:
        raise error from None
    if url.scheme != "https" or not hostname or url.path not in ("", "/") or url.username is not None or url.password is not None or port == 0:
        raise error
    try:
        address = ip_address(hostname)
    except ValueError:
        try:
            parts = hostname.encode("idna").decode("ascii").lower().split(".")
        except UnicodeError:
            raise error from None
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in parts):
            raise error
        host = ".".join(parts)
    else:
        if "%" in hostname:
            raise error
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"https://{host}" + (f":{port}" if port not in (None, 443) else "")


@dataclass(frozen=True)
class SiteProfile:
    srm_origin: str
    complaint_origin: str | None = None
    complaint_template_ids: tuple[str, ...] = ()

    def normalized(self):
        if not isinstance(self.complaint_template_ids, (tuple, list)):
            raise ProfileError("客诉模板编号应为列表。")
        if len(self.complaint_template_ids) > 100 or any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item)
            for item in self.complaint_template_ids
        ):
            raise ProfileError("客诉模板编号应使用字母、数字、下划线或横线。")
        return SiteProfile(
            srm_origin=_origin(self.srm_origin, "SRM"),
            complaint_origin=(None if self.complaint_origin in (None, "")
                              else _origin(self.complaint_origin, "客诉")),
            complaint_template_ids=tuple(dict.fromkeys(self.complaint_template_ids)),
        )


def load_site_profile(data_dir: Path) -> SiteProfile:
    path = Path(data_dir) / PROFILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ProfileError("请先在站点设置填写 SRM 地址。") from None
    except (OSError, UnicodeError, ValueError):
        raise ProfileError("无法读取站点设置，请在界面重新保存。") from None
    if not isinstance(data, dict):
        raise ProfileError("站点设置格式有误，请在界面重新保存。")
    return SiteProfile(
        srm_origin=data.get("srm_origin", ""),
        complaint_origin=data.get("complaint_origin"),
        complaint_template_ids=data.get("complaint_template_ids", ()),
    ).normalized()


def save_site_profile(data_dir: Path, profile: SiteProfile) -> None:
    profile = profile.normalized()
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(asdict(profile), stream, ensure_ascii=False, indent=2)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(directory / PROFILE_NAME)
    finally:
        temporary.unlink(missing_ok=True)
