# -*- coding: utf-8 -*-
"""读取 APK 元信息: 包名、版本、真实应用名（用户看到的名字）、图标。"""
import io
import os
import struct
import zipfile

from .binxml import AXML, ARSC, ResRef, ANDROID_NS, ParseError

BUNDLE_EXTS = (".xapk", ".apks", ".apkm")
APK_EXTS = (".apk",)
ALL_EXTS = APK_EXTS + BUNDLE_EXTS

# 优先语言顺序：中文用户优先看到中文名
DEFAULT_LOCALES = ("zh-CN", "zh-Hans", "zh", "en-US", "en")


class ApkInfo(object):
    def __init__(self):
        self.package = None
        self.version_name = None
        self.version_code = None
        self.min_sdk = None
        self.target_sdk = None
        self.label = None
        self.icon_path = None
        self.is_split = False
        self.split_name = None
        self.error = None

    def to_dict(self):
        return {
            "package": self.package,
            "versionName": self.version_name,
            "versionCode": self.version_code,
            "minSdk": self.min_sdk,
            "targetSdk": self.target_sdk,
            "label": self.label,
            "isSplit": self.is_split,
            "splitName": self.split_name,
            "error": self.error,
        }


def _as_int(v, default=None):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v, 0)
        except Exception:
            return default
    return default


def parse_manifest(manifest_bytes, arsc_bytes=None, locales=DEFAULT_LOCALES):
    """从 AndroidManifest.xml(+resources.arsc) 字节解析信息。"""
    info = ApkInfo()
    axml = AXML(manifest_bytes)
    root = axml.root
    if root is None:
        raise ParseError("manifest 为空")
    info.package = root.attrs.get((None, "package")) or root.get("package")
    info.version_name = root.get("versionName")
    info.version_code = _as_int(root.get("versionCode"))
    vc_major = _as_int(root.get("versionCodeMajor"))
    if vc_major and info.version_code is not None:
        info.version_code = (vc_major << 32) | (info.version_code & 0xFFFFFFFF)
    info.split_name = root.attrs.get((None, "split")) or root.get("split")
    info.is_split = bool(info.split_name) or root.get("isFeatureSplit") is True

    for el in root.children:
        if el.name == "uses-sdk":
            info.min_sdk = _as_int(el.get("minSdkVersion"))
            info.target_sdk = _as_int(el.get("targetSdkVersion"))

    apps = [e for e in root.children if e.name == "application"]
    label = icon = None
    if apps:
        label = apps[0].get("label")
        icon = apps[0].get("icon") or apps[0].get("roundIcon")

    arsc = None
    if arsc_bytes:
        try:
            arsc = ARSC(arsc_bytes)
        except Exception:
            arsc = None

    if isinstance(label, ResRef):
        info.label = (arsc.string_of(label.id, locales) if arsc else None)
    elif isinstance(label, str):
        info.label = label
    if isinstance(info.version_name, ResRef) and arsc:
        info.version_name = arsc.string_of(info.version_name.id, locales)
    if isinstance(icon, ResRef) and arsc:
        cands = arsc.file_candidates(icon.id)
        info.icon_path = _pick_icon(cands)
    elif isinstance(icon, str):
        info.icon_path = icon

    if not info.label:
        info.label = info.package
    return info, arsc


def _pick_icon(candidates):
    """优先位图，其次 xml（自适应图标，后续再解一层）。"""
    bitmaps = [c for c in candidates if c.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))]
    if bitmaps:
        return bitmaps[0]
    return candidates[0] if candidates else None


def read_apk(path, locales=DEFAULT_LOCALES, want_icon=False):
    """读取本地 APK 文件。返回 (ApkInfo, icon_bytes or None)。"""
    info = ApkInfo()
    icon_bytes = None
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "AndroidManifest.xml" not in names:
                info.error = "不是有效的 APK（缺少 AndroidManifest.xml）"
                return info, None
            manifest = z.read("AndroidManifest.xml")
            arsc_bytes = z.read("resources.arsc") if "resources.arsc" in names else None
            info, arsc = parse_manifest(manifest, arsc_bytes, locales)
            if want_icon and info.icon_path:
                icon_bytes = _extract_icon(z, info.icon_path, arsc)
    except zipfile.BadZipFile:
        info.error = "文件损坏或不是 zip/APK 格式"
    except Exception as exc:
        info.error = "解析失败: %s" % exc
    return info, icon_bytes


def _extract_icon(z, icon_path, arsc, depth=0):
    """取出图标字节；自适应图标(xml)再往下解析一层前景图。"""
    try:
        if icon_path.lower().endswith(".xml") and depth < 2 and arsc is not None:
            data = z.read(icon_path)
            sub = AXML(data)
            refs = []
            stack = [sub.root] if sub.root else []
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                for (ns, nm), v in node.attrs.items():
                    if isinstance(v, ResRef) and nm in ("drawable", "src", "foreground"):
                        refs.append((nm, v.id))
                stack.extend(node.children)
            refs.sort(key=lambda x: 0 if x[0] == "foreground" else 1)
            for _, rid in refs:
                for cand in arsc.file_candidates(rid):
                    if cand == icon_path:
                        continue
                    out = _extract_icon(z, cand, arsc, depth + 1)
                    if out:
                        return out
            return None
        if icon_path in z.namelist():
            return z.read(icon_path)
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------
# 捆绑包 (.xapk/.apks/.apkm) 支持
# --------------------------------------------------------------------------
def is_bundle(path):
    return path.lower().endswith(BUNDLE_EXTS)


def bundle_entries(path):
    """列出捆绑包里的 apk 条目名。"""
    try:
        with zipfile.ZipFile(path) as z:
            return [n for n in z.namelist() if n.lower().endswith(".apk")]
    except Exception:
        return []


def extract_bundle(path, dest_dir):
    """解开捆绑包，返回解出的 apk 路径列表（base 排在最前）。"""
    os.makedirs(dest_dir, exist_ok=True)
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.lower().endswith(".apk"):
                continue
            target = os.path.join(dest_dir, os.path.basename(name))
            with z.open(name) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            out.append(target)

    def rank(p):
        b = os.path.basename(p).lower()
        if b in ("base.apk",) or b.startswith("base"):
            return 0
        if "split" in b or "config." in b:
            return 2
        return 1
    out.sort(key=rank)
    return out


def read_any(path, locales=DEFAULT_LOCALES, want_icon=False, workdir=None):
    """读取 apk 或捆绑包。返回 (ApkInfo, icon_bytes, parts[list of apk paths])。"""
    if is_bundle(path):
        tmp = workdir or (os.path.splitext(path)[0] + "_parts")
        try:
            parts = extract_bundle(path, tmp)
        except Exception as exc:
            info = ApkInfo()
            info.error = "无法解开捆绑包: %s" % exc
            return info, None, []
        if not parts:
            info = ApkInfo()
            info.error = "捆绑包内没有 APK"
            return info, None, []
        info, icon = read_apk(parts[0], locales, want_icon)
        return info, icon, parts
    info, icon = read_apk(path, locales, want_icon)
    return info, icon, [path]


# --------------------------------------------------------------------------
# 远端(设备上)APK 的局部读取: 只取 manifest 与 resources.arsc 两个条目
# --------------------------------------------------------------------------
EOCD_SIG = b"PK\x05\x06"
EOCD64_LOC_SIG = b"PK\x06\x07"
EOCD64_SIG = b"PK\x06\x06"


def find_eocd(tail_bytes):
    idx = tail_bytes.rfind(EOCD_SIG)
    if idx < 0:
        return None
    return idx


def parse_central_directory(cd_bytes, wanted=None):
    """解析中央目录，返回 {name: dict(offset, csize, size, method)}。"""
    out = {}
    pos = 0
    n = len(cd_bytes)
    while pos + 46 <= n:
        if cd_bytes[pos:pos + 4] != b"PK\x01\x02":
            pos += 1
            continue
        method = struct.unpack_from("<H", cd_bytes, pos + 10)[0]
        csize = struct.unpack_from("<I", cd_bytes, pos + 20)[0]
        usize = struct.unpack_from("<I", cd_bytes, pos + 24)[0]
        nlen = struct.unpack_from("<H", cd_bytes, pos + 28)[0]
        elen = struct.unpack_from("<H", cd_bytes, pos + 30)[0]
        clen = struct.unpack_from("<H", cd_bytes, pos + 32)[0]
        lho = struct.unpack_from("<I", cd_bytes, pos + 42)[0]
        name = cd_bytes[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        extra = cd_bytes[pos + 46 + nlen:pos + 46 + nlen + elen]
        if csize == 0xFFFFFFFF or usize == 0xFFFFFFFF or lho == 0xFFFFFFFF:
            csize, usize, lho = _zip64_fix(extra, csize, usize, lho)
        if wanted is None or name in wanted:
            out[name] = {"offset": lho, "csize": csize, "size": usize, "method": method}
        pos += 46 + nlen + elen + clen
    return out


def _zip64_fix(extra, csize, usize, lho):
    pos = 0
    while pos + 4 <= len(extra):
        hid = struct.unpack_from("<H", extra, pos)[0]
        hsz = struct.unpack_from("<H", extra, pos + 2)[0]
        if hid == 0x0001:
            p = pos + 4
            if usize == 0xFFFFFFFF and p + 8 <= len(extra):
                usize = struct.unpack_from("<Q", extra, p)[0]; p += 8
            if csize == 0xFFFFFFFF and p + 8 <= len(extra):
                csize = struct.unpack_from("<Q", extra, p)[0]; p += 8
            if lho == 0xFFFFFFFF and p + 8 <= len(extra):
                lho = struct.unpack_from("<Q", extra, p)[0]; p += 8
            break
        pos += 4 + hsz
    return csize, usize, lho


def local_header_data_offset(local_bytes, base_offset):
    """给定本地文件头前 30+ 字节，算出数据真正起始偏移。"""
    if local_bytes[:4] != b"PK\x03\x04":
        return None
    nlen = struct.unpack_from("<H", local_bytes, 26)[0]
    elen = struct.unpack_from("<H", local_bytes, 28)[0]
    return base_offset + 30 + nlen + elen


def inflate(data, method):
    if method == 0:
        return data
    import zlib
    return zlib.decompressobj(-15).decompress(data)
