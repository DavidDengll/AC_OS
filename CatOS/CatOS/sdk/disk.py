#!/usr/bin/env python3
"""
disk.py — 向 CatOS 的 FAT32 磁盘映像里放文件（纯 Python，不挂载）

为什么不用 mount:
    WSL / 某些容器环境没有 loop 设备, `mount -o loop` 会报
    "wrong fs type, bad option, bad superblock"。而且挂载需要 root。
    这里直接按 FAT32 结构读写映像字节流, 普通权限即可, 也不依赖操作系统。

用法:
    python3 disk.py <映像文件> <要放入的文件> [镜像内的文件名]
    python3 disk.py --list  <映像文件>        # 列出根目录
    python3 disk.py --check <映像文件>        # 一致性自检 (FAT/根目录/簇链)
    不带参数双击运行: 弹出文件选择对话框

会自动识别镜像布局:
    - MBR 分区表 + 分区内 FAT32 (catos_hd32.img)
    - 无分区表的超级软盘 FAT32
暂不支持 FAT12/FAT16 (catos.img 是 FAT12 软盘, 由 build.sh 直接生成)。

写文件时会做三件事, 缺一不可:
    1. 数据区: 分配空闲簇, 写入文件内容, 末簇补零
    2. FAT 表: 建立簇链 (末簇写 EOC), 所有 FAT 副本同步更新
    3. 根目录: 写入/复用 32 字节目录项 (含首簇与大小)
   另外会同步更新 FSInfo 的空闲簇数, 避免系统提示空间不准。
"""

import sys
import os
import struct
import json

# ======================================================================
#  FAT32 相关常量
# ======================================================================
DIR_ENTRY_SIZE = 32
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F
ATTR_VOLUME_ID = 0x08
ATTR_DIRECTORY = 0x10
FAT_FREE = 0x00000000
FAT_EOC = 0x0FFFFFFF
FAT_MASK = 0x0FFFFFFF
ENTRY_FREE = 0xE5
ENTRY_END = 0x00

CONFIG_FILE = os.path.expanduser("~/.disk_img_put_config.json")

# 8.3 名字里不允许出现的字符
_INVALID_SHORT = set('"*+,/:;<=>?[\\]|.')
_INVALID_SHORT.update(chr(i) for i in range(32))


class FatError(Exception):
    """映像结构错误 / 不支持的情况"""


# ======================================================================
#  FAT32 卷: 直接对映像字节流做读写
# ======================================================================
class Fat32Volume:
    def __init__(self, path, readonly=False):
        self.path = path
        self.readonly = readonly
        # --list / --check 用只读模式打开, 不申请写权限, 也不会动映像
        self.f = open(path, "rb" if readonly else "r+b")
        self.file_size = os.path.getsize(path)
        self._parse_bpb()

    # ---------------- 解析几何信息 ----------------
    def _read_at(self, off, n):
        self.f.seek(off)
        b = self.f.read(n)
        if len(b) != n:
            raise FatError(f"读取越界: offset={off} len={n} (映像 {self.file_size} 字节)")
        return b

    def _write_at(self, off, data):
        if self.readonly:
            raise FatError("当前以只读模式打开映像, 不能写入")
        if off + len(data) > self.file_size:
            raise FatError(
                f"写入越界: offset={off} len={len(data)} 超出映像大小 {self.file_size}")
        self.f.seek(off)
        self.f.write(data)

    def _parse_bpb(self):
        # ---- 1. 判断是否带 MBR 分区表 ----
        sec0 = self._read_at(0, 512)
        part_start = 0
        sig_ok = sec0[510] == 0x55 and sec0[511] == 0xAA
        is_superfloppy = False

        if sig_ok and sec0[0] in (0xEB, 0xE9):
            # 扇区 0 本身就是引导扇区 (超级软盘)
            is_superfloppy = True
        else:
            # 尝试按 MBR 分区表解析
            pte = sec0[0x1BE:0x1BE + 16]
            if len(pte) == 16 and pte[4] != 0x00:
                part_start = struct.unpack_from("<I", pte, 8)[0]
            if part_start == 0:
                raise FatError("无法识别映像布局: 既不像 MBR 分区表, 也不像 FAT 引导扇区")

        self.part_start = part_start
        vbr = self._read_at(part_start * 512, 512)

        if not (vbr[510] == 0x55 and vbr[511] == 0xAA):
            raise FatError(f"分区 {part_start} 处没有 0x55AA 引导签名, 不是 FAT 卷")

        # ---- 2. BPB 字段 ----
        self.bps = struct.unpack_from("<H", vbr, 11)[0]
        self.sec_per_clus = vbr[13]
        self.rsvd = struct.unpack_from("<H", vbr, 14)[0]
        self.num_fats = vbr[16]
        self.root_ent_cnt = struct.unpack_from("<H", vbr, 17)[0]
        tot_sec16 = struct.unpack_from("<H", vbr, 19)[0]
        media = vbr[21]
        fatsz16 = struct.unpack_from("<H", vbr, 22)[0]
        tot_sec32 = struct.unpack_from("<I", vbr, 32)[0]
        fatsz32 = struct.unpack_from("<I", vbr, 36)[0]
        self.root_clus = struct.unpack_from("<I", vbr, 44)[0]
        self.fsinfo_sec = struct.unpack_from("<H", vbr, 48)[0]
        self.bkboot_sec = struct.unpack_from("<H", vbr, 50)[0]

        if self.bps not in (512, 1024, 2048, 4096):
            raise FatError(f"BPB 每扇区字节数异常: {self.bps}")
        if self.sec_per_clus == 0:
            raise FatError("BPB 每簇扇区数为 0")
        if fatsz16 != 0 or fatsz32 == 0:
            raise FatError(
                "这不是 FAT32 (FATSz16=%d, FATSz32=%d)。catos.img 是 FAT12 软盘, "
                "本工具只处理 FAT32 的 catos_hd32.img" % (fatsz16, fatsz32))
        if self.root_clus < 2:
            raise FatError(f"RootCluster 非法: {self.root_clus}")
        if self.root_ent_cnt != 0:
            raise FatError("FAT32 的 RootEntCnt 应为 0")

        self.fatsz = fatsz32
        self.total_sec = tot_sec32 if tot_sec32 else tot_sec16
        self.media = media

        # ---- 3. 关键偏移 ----
        self.fat_off = (self.part_start + self.rsvd) * self.bps
        self.fatsz_bytes = self.fatsz * self.bps
        self.data_off = (self.part_start + self.rsvd + self.num_fats * self.fatsz) * self.bps
        self.cluster_size = self.bps * self.sec_per_clus

        data_sec = self.total_sec - self.rsvd - self.num_fats * self.fatsz
        self.total_clusters = data_sec // self.sec_per_clus
        # 合法簇号范围: 2 .. total_clusters+1
        self.max_cluster = self.total_clusters + 1

        if self.data_off >= self.file_size:
            raise FatError(
                f"数据区偏移 {self.data_off} 超出映像大小 {self.file_size} (映像可能被截断)")

    # ---------------- 簇 <-> 偏移 ----------------
    def cluster_off(self, c):
        if c < 2 or c > self.max_cluster:
            raise FatError(f"簇号越界: {c} (合法 2..{self.max_cluster})")
        return self.data_off + (c - 2) * self.cluster_size

    # ---------------- FAT 表读写 (所有副本同步) ----------------
    def fat_get(self, c):
        off = self.fat_off + c * 4
        val = struct.unpack("<I", self._read_at(off, 4))[0]
        return val & FAT_MASK

    def fat_set(self, c, value):
        if c < 0 or c > self.max_cluster + 1:
            raise FatError(f"FAT 索引越界: {c}")
        val = value & FAT_MASK
        for i in range(self.num_fats):
            off = self.fat_off + i * self.fatsz_bytes + c * 4
            old = struct.unpack("<I", self._read_at(off, 4))[0]
            new = (old & 0xF0000000) | val        # 保留高 4 位
            self._write_at(off, struct.pack("<I", new))

    # ---------------- 簇链 ----------------
    def chain(self, start, limit=200000):
        out = []
        c = start
        seen = set()
        while 2 <= c <= self.max_cluster:
            if c in seen:
                raise FatError(f"检测到环形簇链 (簇 {c}), 映像可能已损坏")
            seen.add(c)
            out.append(c)
            nxt = self.fat_get(c)
            if nxt >= FAT_EOC - 8 or nxt == 0:
                break
            c = nxt
            if len(out) > limit:
                raise FatError("簇链过长, 疑似损坏")
        return out

    def free_chain(self, start):
        """释放整条簇链, 返回释放的簇数"""
        if start < 2:
            return 0
        cs = self.chain(start)
        for c in cs:
            self.fat_set(c, FAT_FREE)
        return len(cs)

    def _next_free_hint(self):
        hint = 2
        if self.fsinfo_sec:
            off = (self.part_start + self.fsinfo_sec) * self.bps + 492
            try:
                v = struct.unpack("<I", self._read_at(off, 4))[0]
                if 2 <= v <= self.max_cluster:
                    hint = v
            except FatError:
                pass
        return hint

    def alloc_cluster(self):
        """找一个空闲簇, 标记为 EOC, 返回簇号"""
        start = self._next_free_hint()
        span = self.max_cluster - 1
        for i in range(span):
            c = 2 + (start - 2 + i) % span
            if self.fat_get(c) == FAT_FREE:
                self.fat_set(c, FAT_EOC)
                return c
        raise FatError("磁盘已满: 没有空闲簇")

    # ---------------- 目录遍历 ----------------
    def dir_slots(self, start_cluster):
        """遍历目录链, 产出 (绝对偏移, 32 字节目录项)"""
        for c in self.chain(start_cluster):
            base = self.cluster_off(c)
            for s in range(self.cluster_size // DIR_ENTRY_SIZE):
                off = base + s * DIR_ENTRY_SIZE
                yield off, self._read_at(off, DIR_ENTRY_SIZE)

    def _is_usable_entry(self, ent):
        if ent[0] in (ENTRY_END, ENTRY_FREE):
            return False
        attr = ent[11]
        if attr == ATTR_LFN:              # 长文件名条目
            return False
        if attr & ATTR_VOLUME_ID:         # 卷标
            return False
        if ent[0] == 0x2E:                # "." / ".."
            return False
        return True

    def list_root(self):
        rows = []
        for off, ent in self.dir_slots(self.root_clus):
            if not self._is_usable_entry(ent):
                continue
            name = _decode_short_name(ent[0:11])
            attr = ent[11]
            hi = struct.unpack_from("<H", ent, 20)[0]
            lo = struct.unpack_from("<H", ent, 26)[0]
            size = struct.unpack_from("<I", ent, 28)[0]
            rows.append({
                "name": name,
                "attr": attr,
                "cluster": (hi << 16) | lo,
                "size": size,
                "dir": bool(attr & ATTR_DIRECTORY),
            })
        return rows

    def find_entry(self, name11):
        """按 11 字节短名查找, 返回 (偏移, 目录项) 或 None"""
        for off, ent in self.dir_slots(self.root_clus):
            if ent[0] in (ENTRY_END, ENTRY_FREE):
                continue
            if ent[11] == ATTR_LFN:
                continue
            if bytes(ent[0:11]).upper() == name11.upper():
                return off, bytes(ent)
        return None

    def _alloc_dir_slot(self):
        """在根目录里找一个空槽; 没有就扩容一个簇, 返回槽位偏移"""
        last_end = None
        for off, ent in self.dir_slots(self.root_clus):
            if ent[0] in (ENTRY_END, ENTRY_FREE):
                return off
            if ent[0] == ENTRY_END:
                last_end = off
        if last_end is not None:
            return last_end

        # 目录满了: 追加一个簇并链接到链尾
        cs = self.chain(self.root_clus)
        tail = cs[-1]
        newc = self.alloc_cluster()
        self._write_at(self.cluster_off(newc), b"\x00" * self.cluster_size)
        self.fat_set(tail, newc)
        self.fat_set(newc, FAT_EOC)
        return self.cluster_off(newc)

    # ---------------- FSInfo ----------------
    def _count_free_clusters(self):
        """精确统计空闲簇数: 直接扫 FAT 表, 不依赖任何已有记帐值

        不能做 +/- delta: 映像初始的 FSInfo 值本身就未必准,
        一次 delta 之后误差会永久保留。直接扫一遍最可靠。
        """
        raw = self._read_at(self.fat_off, self.fatsz_bytes)
        total = min(self.max_cluster, len(raw) // 4 - 1)
        n = 0
        for c in range(2, total + 1):
            if (struct.unpack_from("<I", raw, c * 4)[0] & FAT_MASK) == 0:
                n += 1
        return n

    def _fsinfo_sectors(self):
        secs = []
        if self.fsinfo_sec:
            secs.append(self.fsinfo_sec)
        if self.bkboot_sec and (self.bkboot_sec + 1) != self.fsinfo_sec:
            secs.append(self.bkboot_sec + 1)      # 备份 FSInfo
        return secs

    def update_fsinfo(self):
        """把精确的空闲簇数写回 FSInfo (主 + 备份)"""
        if not self.fsinfo_sec:
            return
        free = self._count_free_clusters()
        hint = self._next_free_hint()
        for sec in self._fsinfo_sectors():
            off = (self.part_start + sec) * self.bps
            try:
                sig = self._read_at(off + 484, 4)
            except FatError:
                continue
            if sig != b"\x72\x72\x41\x61":        # 'rrAa' = 0x61417272
                continue
            self._write_at(off + 488, struct.pack("<I", free))
            self._write_at(off + 492, struct.pack("<I", hint))

    # ---------------- 写文件 ----------------
    def put_file(self, local_path, want_name=None):
        with open(local_path, "rb") as fh:
            data = fh.read()

        base_name = want_name or os.path.basename(local_path)
        short, name11 = _short_name_for(base_name)

        # ---- 同名的旧文件: 先释放它的簇链 ----
        old = self.find_entry(name11)
        freed = 0
        slot_off = None
        if old is not None:
            slot_off, old_ent = old
            old_start = (struct.unpack_from("<H", old_ent, 20)[0] << 16) | \
                        struct.unpack_from("<H", old_ent, 26)[0]
            if old_start >= 2:
                freed = self.free_chain(old_start)

        # ---- 分配新簇链并写入数据 ----
        need = (len(data) + self.cluster_size - 1) // self.cluster_size
        first = 0
        if need:
            clusters = []
            for _ in range(need):
                clusters.append(self.alloc_cluster())
            for i in range(len(clusters) - 1):
                self.fat_set(clusters[i], clusters[i + 1])
            self.fat_set(clusters[-1], FAT_EOC)
            first = clusters[0]

            # 写数据: 逐簇写入, 末簇补零
            pos = 0
            for c in clusters:
                chunk = data[pos:pos + self.cluster_size]
                pos += len(chunk)
                if len(chunk) < self.cluster_size:
                    chunk = chunk + b"\x00" * (self.cluster_size - len(chunk))
                self._write_at(self.cluster_off(c), chunk)

        # ---- 写目录项 ----
        if slot_off is None:
            slot_off = self._alloc_dir_slot()

        entry = bytearray(DIR_ENTRY_SIZE)
        entry[0:11] = name11
        entry[11] = ATTR_ARCHIVE
        entry[12] = 0                      # NTRes
        entry[13] = 0                      # CrtTimeTenth
        # 写入一个合法的创建/修改时间 (2026-01-01 00:00:00), 避免其它工具报 0 日期
        wdate = ((2026 - 1980) << 9) | (1 << 5) | 1
        struct.pack_into("<H", entry, 14, 0)          # CrtTime
        struct.pack_into("<H", entry, 16, wdate)      # CrtDate
        struct.pack_into("<H", entry, 18, wdate)      # LstAccDate
        struct.pack_into("<H", entry, 20, (first >> 16) & 0xFFFF)   # FstClusHI
        struct.pack_into("<H", entry, 22, 0)          # WrtTime
        struct.pack_into("<H", entry, 24, wdate)      # WrtDate
        struct.pack_into("<H", entry, 26, first & 0xFFFF)           # FstClusLO
        struct.pack_into("<I", entry, 28, len(data) & 0xFFFFFFFF)   # FileSize
        self._write_at(slot_off, bytes(entry))

        # ---- 更新 FSInfo ----
        self.update_fsinfo()

        self.f.flush()
        os.fsync(self.f.fileno())

        return {
            "short": short,
            "name11": name11,
            "size": len(data),
            "clusters": need,
            "first": first,
            "freed": freed,
            "replaced": old is not None,
        }

    # ---------------- 读回校验 ----------------
    def read_file(self, name11_or_name):
        if isinstance(name11_or_name, str):
            _s, name11 = _short_name_for(name11_or_name)
        else:
            name11 = name11_or_name
        found = self.find_entry(name11)
        if found is None:
            raise FatError(f"镜像里找不到文件: {_decode_short_name(name11)}")
        off, ent = found
        size = struct.unpack_from("<I", ent, 28)[0]
        start = (struct.unpack_from("<H", ent, 20)[0] << 16) | \
                struct.unpack_from("<H", ent, 26)[0]
        if size == 0:
            return b""
        cs = self.chain(start)
        buf = bytearray()
        for c in cs:
            buf += self._read_at(self.cluster_off(c), self.cluster_size)
        return bytes(buf[:size])

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


# ======================================================================
#  8.3 短名生成
# ======================================================================
def _decode_short_name(name11):
    raw = bytes(name11)
    base = raw[0:8].decode("ascii", "replace").rstrip()
    ext = raw[8:11].decode("ascii", "replace").rstrip()
    return f"{base}.{ext}" if ext else base


def _sanitize(part, upper=True):
    out = []
    for ch in part:
        if upper:
            ch = ch.upper()
        if ch in _INVALID_SHORT or ch == " ":
            out.append("_")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _pack83(base, ext):
    base = base.ljust(8)[:8]
    ext = ext.ljust(3)[:3]
    return (base + ext).encode("ascii")


def _short_name_for(long_name):
    """把任意文件名**确定性**地压成合法的 8.3 短名, 返回 (显示名, 11 字节)

    这里故意不做"避免重名"的 ~N 递增:
      - 同一个源文件重复写入时, 必须命中同一个短名, 才能实现「同名覆盖」
      - CatOS 的 FAT 驱动不支持长文件名, 只认这 11 字节短名
    副作用: 两个长文件名若前 6 字符相同, 会映射到同一个短名而互相覆盖
            —— 用命令行第 3 个参数显式指定不同的短名即可避免。
    """
    name = os.path.basename(long_name)
    if "." in name:
        base, ext = name.rsplit(".", 1)
    else:
        base, ext = name, ""

    base = _sanitize(base)
    ext = _sanitize(ext)
    if not base:
        base = "FILE"

    if len(base) <= 8 and len(ext) <= 3:
        cand = _pack83(base, ext)
    else:
        # 压成 6 字符主体 + ~1
        cand = _pack83(base[:6] + "~1", ext[:3])

    return _decode_short_name(cand), cand


# ======================================================================
#  GUI / 配置 (双击运行时用)
# ======================================================================
def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError:
        pass


def gui_select_files():
    """弹两个文件选择框, 返回 (映像路径, 文件路径) 或 (None, None)"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter 不可用, 请用命令行: python3 disk.py <映像> <文件>")
        return None, None

    config = load_config()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    image_path = filedialog.askopenfilename(
        title="选择磁盘映像文件 (catos_hd32.img)",
        initialdir=config.get("image_dir", os.path.expanduser("~")),
        filetypes=[("磁盘映像", "*.img *.bin"), ("所有文件", "*.*")])
    if not image_path:
        root.destroy()
        return None, None
    config["image_dir"] = os.path.dirname(image_path)

    file_path = filedialog.askopenfilename(
        title="选择要放入映像的文件",
        initialdir=config.get("file_dir", os.path.dirname(image_path)),
        filetypes=[("所有文件", "*.*")])
    root.destroy()
    if not file_path:
        save_config(config)
        return None, None

    config["file_dir"] = os.path.dirname(file_path)
    save_config(config)
    return image_path, file_path


# ======================================================================
#  主流程
# ======================================================================
def do_list(image_path):
    vol = Fat32Volume(image_path, readonly=True)
    try:
        print(f"映像: {image_path}")
        print(f"  MBR 分区起始 LBA : {vol.part_start}")
        print(f"  每扇区字节 / 每簇扇区 : {vol.bps} / {vol.sec_per_clus}")
        print(f"  保留扇区 / FAT 数 / 每 FAT 扇区 : {vol.rsvd} / {vol.num_fats} / {vol.fatsz}")
        print(f"  根目录簇 / 总簇数 : {vol.root_clus} / {vol.total_clusters}")
        print()
        rows = vol.list_root()
        print(f"  根目录共 {len(rows)} 项:")
        print(f"  {'名称':<14}{'簇':>8}{'大小':>12}  类型")
        for r in rows:
            print(f"  {r['name']:<14}{r['cluster']:>8}{r['size']:>12}  "
                  f"{'目录' if r['dir'] else '文件'}")
    finally:
        vol.close()


def do_check(image_path):
    vol = Fat32Volume(image_path, readonly=True)
    problems = []
    try:
        cs = vol.chain(vol.root_clus)
        print(f"根目录簇链: {cs}")

        used = set()
        for c in cs:
            used.add(c)

        rows = vol.list_root()
        for r in rows:
            if r["dir"]:
                continue
            if r["size"] == 0:
                continue
            try:
                fc = vol.chain(r["cluster"])
            except FatError as e:
                problems.append(f"{r['name']}: 簇链异常 ({e})")
                continue
            overlap = used & set(fc)
            if overlap:
                problems.append(f"{r['name']}: 与根目录/其它文件交叉的簇 {sorted(overlap)[:5]}")
            used |= set(fc)
            capacity = len(fc) * vol.cluster_size
            if r["size"] > capacity:
                problems.append(
                    f"{r['name']}: 大小 {r['size']} 超过簇链容量 {capacity}")

            data = vol.read_file(_pack83(*_split83(r["name"])))
            if len(data) != r["size"]:
                problems.append(f"{r['name']}: 读回长度 {len(data)} != 记录 {r['size']}")

        if problems:
            print("\n发现 %d 个问题:" % len(problems))
            for p in problems:
                print("  [!] " + p)
            return 1
        print("\n[+] 一致性检查通过: 簇链无交叉, 目录尺寸与簇链容量匹配")
        return 0
    finally:
        vol.close()


def _split83(short):
    if "." in short:
        b, e = short.rsplit(".", 1)
    else:
        b, e = short, ""
    return b, e


def do_put(image_path, file_path, want_name=None):
    if not os.path.isfile(image_path):
        print(f"错误: 映像文件不存在: {image_path}")
        return 1
    if not os.path.isfile(file_path):
        print(f"错误: 要放入的文件不存在: {file_path}")
        return 1

    vol = Fat32Volume(image_path)
    try:
        print(f"[*] 映像: {image_path} ({vol.file_size / 1024 / 1024:.1f} MiB)")
        print(f"[*] 源文件: {file_path} ({os.path.getsize(file_path)} 字节)")

        info = vol.put_file(file_path, want_name)
        print(f"[+] 已写入目录项: {info['short']}")
        print(f"    大小 {info['size']} 字节, 占用 {info['clusters']} 个簇, "
              f"起始簇 {info['first']}")
        if info["replaced"]:
            print(f"    覆盖同名旧文件, 释放了 {info['freed']} 个簇")

        # ---- 立刻读回校验 (用真实写进去的 11 字节短名, 不要重新推算) ----
        data = vol.read_file(info["name11"])
        with open(file_path, "rb") as fh:
            src = fh.read()
        if data != src:
            print("[x] 校验失败: 读回内容与源文件不一致!")
            return 1
        print("[+] 校验通过: 读回内容与源文件逐字节一致")

        print()
        print(f"    在 CatOS 里用这个名字访问: {info['short']}")
        print(f"    (CatOS 的 FAT 驱动不支持长文件名, 所以是 8.3 短名)")
        return 0
    finally:
        vol.close()


def main():
    argv = sys.argv[1:]
    interactive = False

    if not argv:
        interactive = True
        print("请在弹出的对话框中选择文件...")
        image_path, file_path = gui_select_files()
        if image_path is None or file_path is None:
            print("用户取消, 退出。")
            return 0
        return do_put(os.path.abspath(image_path), os.path.abspath(file_path))

    if argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if argv[0] == "--list":
        if len(argv) < 2:
            print("用法: disk.py --list <映像文件>")
            return 1
        return do_list(os.path.abspath(argv[1]))

    if argv[0] == "--check":
        if len(argv) < 2:
            print("用法: disk.py --check <映像文件>")
            return 1
        try:
            return do_check(os.path.abspath(argv[1]))
        except FatError as e:
            print(f"[x] {e}")
            return 1

    if len(argv) < 2:
        print(__doc__)
        return 1

    image_path = os.path.abspath(argv[0])
    file_path = os.path.abspath(argv[1])
    want_name = argv[2] if len(argv) >= 3 else None

    try:
        return do_put(image_path, file_path, want_name)
    except FatError as e:
        print(f"[x] FAT32 操作失败: {e}")
        return 1


if __name__ == "__main__":
    rc = main()
    # 只有双击运行 (无参数) 才停顿, 免得影响命令行 / 脚本调用
    if len(sys.argv) == 1:
        try:
            input("press enter to continue...")
        except EOFError:
            pass
    sys.exit(rc)
