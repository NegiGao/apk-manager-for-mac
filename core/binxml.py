# -*- coding: utf-8 -*-
"""Android 二进制资源格式解析（纯 Python，无第三方依赖）。

包含:
  - StringPool : RES_STRING_POOL_TYPE 字符串池
  - AXML       : AndroidManifest.xml 等二进制 XML
  - ARSC       : resources.arsc 资源表
"""
import struct

# ---- chunk 类型 ----
RES_NULL_TYPE = 0x0000
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202
RES_TABLE_LIBRARY_TYPE = 0x0203

# ---- Res_value 数据类型 ----
TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_ATTRIBUTE = 0x02
TYPE_STRING = 0x03
TYPE_FLOAT = 0x04
TYPE_DIMENSION = 0x05
TYPE_FRACTION = 0x06
TYPE_DYNAMIC_REFERENCE = 0x07
TYPE_DYNAMIC_ATTRIBUTE = 0x08
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12


class ParseError(Exception):
    pass


class Reader(object):
    """小端字节读取器。"""

    __slots__ = ("buf", "pos", "size")

    def __init__(self, buf, pos=0):
        self.buf = buf
        self.pos = pos
        self.size = len(buf)

    def u8(self):
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def bytes(self, n):
        v = self.buf[self.pos:self.pos + n]
        self.pos += n
        return v

    def skip(self, n):
        self.pos += n


def read_chunk_header(r):
    """返回 (type, header_size, size, chunk_start)。"""
    start = r.pos
    if start + 8 > r.size:
        raise ParseError("数据被截断")
    ctype = r.u16()
    hsize = r.u16()
    size = r.u32()
    if size < 8 or start + size > r.size:
        # 末尾 chunk 允许被截断，交由调用方判断
        size = min(size, r.size - start) if size >= 8 else 8
    return ctype, hsize, size, start


# --------------------------------------------------------------------------
# 字符串池
# --------------------------------------------------------------------------
class StringPool(object):
    FLAG_SORTED = 1 << 0
    FLAG_UTF8 = 1 << 8

    def __init__(self, buf, offset):
        r = Reader(buf, offset)
        ctype, hsize, size, start = read_chunk_header(r)
        if ctype != RES_STRING_POOL_TYPE:
            raise ParseError("不是字符串池 chunk: 0x%04x" % ctype)
        self.count = r.u32()
        self.style_count = r.u32()
        self.flags = r.u32()
        strings_start = r.u32()
        r.u32()  # styles_start
        self.utf8 = bool(self.flags & self.FLAG_UTF8)
        self.buf = buf
        self.chunk_start = start
        self.chunk_end = start + size
        # 偏移表紧跟在 header 之后
        r.pos = start + hsize
        self.offsets = []
        for _ in range(self.count):
            if r.pos + 4 > self.chunk_end:
                break
            self.offsets.append(r.u32())
        self.data_start = start + strings_start
        self._cache = {}

    def __len__(self):
        return self.count

    def get(self, idx):
        if idx is None or idx < 0 or idx >= len(self.offsets):
            return None
        if idx in self._cache:
            return self._cache[idx]
        try:
            s = self._decode(self.data_start + self.offsets[idx])
        except Exception:
            s = None
        self._cache[idx] = s
        return s

    def _decode(self, off):
        buf = self.buf
        if self.utf8:
            # 两个长度: UTF-16 字符数, UTF-8 字节数
            n, off = self._varint8(buf, off)
            blen, off = self._varint8(buf, off)
            raw = buf[off:off + blen]
            return raw.decode("utf-8", "replace")
        else:
            n, off = self._varint16(buf, off)
            raw = buf[off:off + n * 2]
            return raw.decode("utf-16-le", "replace")

    @staticmethod
    def _varint8(buf, off):
        v = buf[off]
        off += 1
        if v & 0x80:
            v = ((v & 0x7F) << 8) | buf[off]
            off += 1
        return v, off

    @staticmethod
    def _varint16(buf, off):
        v = struct.unpack_from("<H", buf, off)[0]
        off += 2
        if v & 0x8000:
            v2 = struct.unpack_from("<H", buf, off)[0]
            off += 2
            v = ((v & 0x7FFF) << 16) | v2
        return v, off


# --------------------------------------------------------------------------
# 二进制 XML
# --------------------------------------------------------------------------
ANDROID_NS = "http://schemas.android.com/apk/res/android"


class XmlElement(object):
    __slots__ = ("name", "attrs", "children", "parent")

    def __init__(self, name, parent=None):
        self.name = name
        self.attrs = {}        # (ns, name) -> 解析后的值
        self.children = []
        self.parent = parent

    def get(self, name, ns=ANDROID_NS):
        return self.attrs.get((ns, name))

    def find_all(self, name):
        out = []
        stack = [self]
        while stack:
            node = stack.pop()
            if node.name == name:
                out.append(node)
            stack.extend(node.children)
        return out


class AXML(object):
    """二进制 XML 解析器。属性值保留原始类型信息。"""

    def __init__(self, data):
        self.data = data
        self.strings = None
        self.root = None
        self.res_map = []
        self._parse()

    def _parse(self):
        buf = self.data
        r = Reader(buf)
        ctype, hsize, size, start = read_chunk_header(r)
        if ctype != RES_XML_TYPE:
            raise ParseError("不是二进制 XML (0x%04x)" % ctype)
        pos = start + hsize
        end = min(start + size, len(buf))
        root = None
        current = None
        while pos + 8 <= end:
            rr = Reader(buf, pos)
            ct, hs, sz, cs = read_chunk_header(rr)
            if sz <= 0:
                break
            if ct == RES_STRING_POOL_TYPE:
                self.strings = StringPool(buf, cs)
            elif ct == RES_XML_RESOURCE_MAP_TYPE:
                n = (sz - hs) // 4
                rr.pos = cs + hs
                self.res_map = [rr.u32() for _ in range(n)]
            elif ct == RES_XML_START_ELEMENT_TYPE:
                el = self._read_element(buf, cs, hs)
                if current is None:
                    root = el
                else:
                    el.parent = current
                    current.children.append(el)
                current = el
            elif ct == RES_XML_END_ELEMENT_TYPE:
                if current is not None and current.parent is not None:
                    current = current.parent
            pos = cs + sz
        self.root = root

    def _read_element(self, buf, chunk_start, header_size):
        r = Reader(buf, chunk_start + header_size)
        r.u32()  # ns
        name_idx = r.u32()
        attr_start = r.u16()
        attr_size = r.u16()
        attr_count = r.u16()
        r.u16(); r.u16(); r.u16()  # id/class/style index
        el = XmlElement(self._s(name_idx))
        base = chunk_start + header_size + attr_start
        for i in range(attr_count):
            ar = Reader(buf, base + i * attr_size)
            ns_i = ar.u32()
            nm_i = ar.u32()
            raw_i = ar.i32()
            ar.u16()          # value size
            ar.u8()           # res0
            vtype = ar.u8()
            data = ar.u32()
            ns = self._s(ns_i)
            nm = self._s(nm_i)
            el.attrs[(ns, nm)] = self._value(vtype, data, raw_i)
        return el

    def _s(self, idx):
        if self.strings is None:
            return None
        return self.strings.get(idx)

    def _value(self, vtype, data, raw_idx):
        if vtype == TYPE_STRING:
            s = self._s(data)
            if s is None and raw_idx >= 0:
                s = self._s(raw_idx)
            return s
        if vtype in (TYPE_REFERENCE, TYPE_DYNAMIC_REFERENCE):
            return ResRef(data)
        if vtype == TYPE_INT_BOOLEAN:
            return data != 0
        if vtype in (TYPE_INT_DEC, TYPE_INT_HEX):
            return struct.unpack("<i", struct.pack("<I", data))[0]
        if vtype == TYPE_NULL:
            return None
        if raw_idx >= 0:
            s = self._s(raw_idx)
            if s is not None:
                return s
        return data


class ResRef(object):
    """资源引用 @0x7f0a0001。"""
    __slots__ = ("id",)

    def __init__(self, rid):
        self.id = rid

    def __repr__(self):
        return "@0x%08x" % self.id

    def __eq__(self, other):
        return isinstance(other, ResRef) and other.id == self.id

    def __hash__(self):
        return hash(("ResRef", self.id))


# --------------------------------------------------------------------------
# resources.arsc
# --------------------------------------------------------------------------
class ResConfig(object):
    """只解析我们关心的字段: 语言/地区/密度。"""
    __slots__ = ("language", "country", "density", "size")

    def __init__(self, buf, off):
        size = struct.unpack_from("<I", buf, off)[0]
        self.size = size
        self.language = ""
        self.country = ""
        self.density = 0
        try:
            if size >= 12:
                self.language = self._locale(buf[off + 8:off + 10])
                self.country = self._locale(buf[off + 10:off + 12])
            if size >= 16:
                self.density = struct.unpack_from("<H", buf, off + 14)[0]
        except Exception:
            pass

    @staticmethod
    def _locale(b):
        if len(b) < 2 or (b[0] == 0 and b[1] == 0):
            return ""
        if b[0] & 0x80:
            # 打包的 3 字母编码
            first = b[0] & 0x7F
            v = (b[1] << 8) | first
            out = []
            for i in range(3):
                out.append(chr((v & 0x1F) + ord('a')))
                v >>= 5
            return "".join(reversed(out))
        try:
            return b.decode("ascii")
        except Exception:
            return ""

    @property
    def locale(self):
        if not self.language:
            return ""
        if self.country:
            return "%s-%s" % (self.language.lower(), self.country.upper())
        return self.language.lower()

    def __repr__(self):
        return "<cfg %s d=%d>" % (self.locale or "default", self.density)


class ResEntry(object):
    __slots__ = ("value", "config", "is_complex", "map")

    def __init__(self, value, config, is_complex=False, mapping=None):
        self.value = value          # (type, data) 或 None
        self.config = config
        self.is_complex = is_complex
        self.map = mapping or {}


class ARSC(object):
    """resources.arsc 解析，支持稀疏表与 compact entry。"""

    def __init__(self, data):
        self.data = data
        self.global_strings = None
        # package_id -> {"name":, "types": {type_id: [(spec_name, {entry_id: [ResEntry]})]}}
        self.packages = {}
        self._res_cache = {}
        self._parse()

    # -- 解析 --------------------------------------------------------------
    def _parse(self):
        buf = self.data
        r = Reader(buf)
        ctype, hsize, size, start = read_chunk_header(r)
        if ctype != RES_TABLE_TYPE:
            raise ParseError("不是 resources.arsc (0x%04x)" % ctype)
        pos = start + hsize
        end = min(start + size, len(buf))
        while pos + 8 <= end:
            rr = Reader(buf, pos)
            ct, hs, sz, cs = read_chunk_header(rr)
            if sz <= 0:
                break
            if ct == RES_STRING_POOL_TYPE and self.global_strings is None:
                self.global_strings = StringPool(buf, cs)
            elif ct == RES_TABLE_PACKAGE_TYPE:
                try:
                    self._parse_package(cs, hs, sz)
                except Exception:
                    pass
            pos = cs + sz

    def _parse_package(self, cs, hs, sz):
        buf = self.data
        r = Reader(buf, cs + 8)
        pkg_id = r.u32()
        name_raw = r.bytes(256)
        name = name_raw.decode("utf-16-le", "ignore").split("\x00")[0]
        type_strings_off = r.u32()
        r.u32()  # lastPublicType
        key_strings_off = r.u32()
        r.u32()  # lastPublicKey
        if pkg_id == 0:
            pkg_id = 0x7F
        type_strings = StringPool(buf, cs + type_strings_off) if type_strings_off else None
        key_strings = StringPool(buf, cs + key_strings_off) if key_strings_off else None
        pkg = {"id": pkg_id, "name": name, "type_strings": type_strings,
               "key_strings": key_strings, "types": {}}
        self.packages[pkg_id] = pkg

        pos = cs + hs
        end = cs + sz
        while pos + 8 <= end:
            rr = Reader(buf, pos)
            ct, chs, csz, ccs = read_chunk_header(rr)
            if csz <= 0:
                break
            if ct == RES_TABLE_TYPE_TYPE:
                try:
                    self._parse_type(pkg, ccs, chs, csz)
                except Exception:
                    pass
            pos = ccs + csz

    def _parse_type(self, pkg, cs, hs, sz):
        buf = self.data
        r = Reader(buf, cs + 8)
        type_id = r.u8()
        flags = r.u8()
        r.u16()  # reserved
        entry_count = r.u32()
        entries_start = r.u32()
        config = ResConfig(buf, r.pos)
        sparse = bool(flags & 0x01)
        offset16 = bool(flags & 0x02)

        table = pkg["types"].setdefault(type_id, {})
        r.pos = cs + hs
        idx_pairs = []
        if sparse:
            for _ in range(entry_count):
                if r.pos + 4 > cs + sz:
                    break
                idx = r.u16()
                off = r.u16() * 4
                idx_pairs.append((idx, off))
        elif offset16:
            for i in range(entry_count):
                if r.pos + 2 > cs + sz:
                    break
                off = r.u16()
                if off != 0xFFFF:
                    idx_pairs.append((i, off * 4))
        else:
            for i in range(entry_count):
                if r.pos + 4 > cs + sz:
                    break
                off = r.u32()
                if off != 0xFFFFFFFF:
                    idx_pairs.append((i, off))

        base = cs + entries_start
        for idx, off in idx_pairs:
            try:
                entry = self._parse_entry(base + off, config)
            except Exception:
                entry = None
            if entry is not None:
                table.setdefault(idx, []).append(entry)

    def _parse_entry(self, off, config):
        buf = self.data
        size = struct.unpack_from("<H", buf, off)[0]
        flags = struct.unpack_from("<H", buf, off + 2)[0]
        if flags & 0x0008:   # FLAG_COMPACT: size 字段即 key 索引, 值类型在 flags 高 8 位
            data = struct.unpack_from("<I", buf, off + 4)[0]
            vtype = (flags >> 8) & 0xFF
            return ResEntry((vtype, data), config)
        if flags & 0x0001:   # FLAG_COMPLEX
            parent = struct.unpack_from("<I", buf, off + size)[0]
            count = struct.unpack_from("<I", buf, off + size + 4)[0]
            mapping = {}
            p = off + size + 8
            for _ in range(min(count, 512)):
                if p + 12 > len(buf):
                    break
                name = struct.unpack_from("<I", buf, p)[0]
                vtype = buf[p + 7]
                data = struct.unpack_from("<I", buf, p + 8)[0]
                mapping[name] = (vtype, data)
                p += 12
            e = ResEntry(None, config, True, mapping)
            e.map["__parent__"] = (TYPE_REFERENCE, parent)
            return e
        vtype = buf[off + size + 3]
        data = struct.unpack_from("<I", buf, off + size + 4)[0]
        return ResEntry((vtype, data), config)

    # -- 查询 --------------------------------------------------------------
    def entries_for(self, res_id):
        """返回某资源 id 的所有配置版本 [ResEntry]。"""
        if res_id in self._res_cache:
            return self._res_cache[res_id]
        pkg_id = (res_id >> 24) & 0xFF
        type_id = (res_id >> 16) & 0xFF
        entry_id = res_id & 0xFFFF
        pkg = self.packages.get(pkg_id)
        out = []
        if pkg:
            out = list(pkg["types"].get(type_id, {}).get(entry_id, []))
        self._res_cache[res_id] = out
        return out

    def string_of(self, res_id, locales=("zh-CN", "zh", "en"), _depth=0):
        """把资源 id 解析为字符串，按语言优先级挑选。"""
        if _depth > 6:
            return None
        entries = self.entries_for(res_id)
        if not entries:
            return None
        best = self._pick_by_locale(entries, locales)
        for e in best:
            if e.value is None:
                continue
            vtype, data = e.value
            if vtype == TYPE_STRING:
                s = self.global_strings.get(data) if self.global_strings else None
                if s:
                    return s
            elif vtype in (TYPE_REFERENCE, TYPE_DYNAMIC_REFERENCE) and data and data != res_id:
                s = self.string_of(data, locales, _depth + 1)
                if s:
                    return s
            elif vtype in (TYPE_INT_DEC, TYPE_INT_HEX):
                return str(data)
        return None

    def file_candidates(self, res_id, _depth=0):
        """解析资源 id 为 APK 内文件路径列表，按密度从高到低。"""
        if _depth > 6:
            return []
        entries = self.entries_for(res_id)
        out = []
        for e in entries:
            if e.value is None:
                continue
            vtype, data = e.value
            if vtype == TYPE_STRING:
                s = self.global_strings.get(data) if self.global_strings else None
                if s:
                    out.append((e.config.density or 0, s))
            elif vtype in (TYPE_REFERENCE, TYPE_DYNAMIC_REFERENCE) and data and data != res_id:
                for d, s in self.file_candidates(data, _depth + 1):
                    out.append((d, s))
        # 0xFFFE = anydpi，优先级应最低
        def rank(item):
            d = item[0]
            return -1 if d in (0xFFFE, 0xFFFF) else d
        out.sort(key=rank, reverse=True)
        seen = set()
        res = []
        for _, s in out:
            if s not in seen:
                seen.add(s)
                res.append(s)
        return res

    @staticmethod
    def _pick_by_locale(entries, locales):
        """按 locale 偏好排序: 指定语言 > 默认(无语言) > 其它。"""
        prefs = [l.lower() for l in locales]

        def score(e):
            loc = e.config.locale.lower()
            if loc in prefs:
                return prefs.index(loc)
            lang = (e.config.language or "").lower()
            for i, p in enumerate(prefs):
                if lang and p.split("-")[0] == lang:
                    return len(prefs) + i
            if not loc:
                return 100
            return 200
        return sorted(entries, key=score)
