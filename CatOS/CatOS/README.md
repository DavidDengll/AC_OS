# CatOS

> Clean, 2026 7 12, China
> 一个基于 x86 保护模式的教学型操作系统内核，从零开始实现引导、内核、进程、文件系统、图形桌面与用户程序生态。

**版本**：v0.14 Release 3 Pre 3
**许可证**：Apache License 2.0

---

## 目录

- [简介](#简介)
- [特性](#特性)
- [项目结构](#项目结构)
- [工具链要求](#工具链要求)
- [构建](#构建)
- [运行](#运行)
- [Shell 命令](#shell-命令)
- [图形桌面](#图形桌面)
- [安装到硬盘](#安装到硬盘)
- [用户程序开发 (SDK)](#用户程序开发-sdk)
- [架构概述](#架构概述)
- [故障排查](#故障排查)

---

## 简介

CatOS 是一个 32 位 x86 保护模式操作系统，目标是清晰展示一个真实可运行的操作系统各层是如何协作的：从 BIOS 引导、加载器进入保护模式、内核初始化中断与进程，到 FAT 文件系统、控制台 Shell、图形桌面环境以及 Ring 3 用户程序加载。

系统从 1.44MB FAT12 软盘启动，可在 QEMU / Bochs / VMware 中运行，并支持通过内置 `setup` 安装器将系统安装到硬盘（标准 MBR + FAT32 分区布局）。Shell 提示符会显示当前路径（如 `CatOS / > ` 或 `CatOS /test/ > `）。

# 赞助者（非常感谢）： `小绿说电脑`

---

## 特性

- **引导链**：MBR → VBR → Loader → Kernel，全链路从实模式切换到保护模式并开启分页
- **内核**：中断/异常处理、8259A PIC、时钟驱动、多任务调度（基于时钟片轮转）
- **进程模型**：Ring 1 内核任务 + Ring 3 用户进程，基于 LDT 段级隔离
- **控制台**：多 TTY、VGA 80x25 文本模式、键盘驱动（含扩展键）、鼠标支持（带灵敏度调节）
- **图形模式**：VGA Mode 13h (320x200x256)，软件渲染原语（fill_rect、draw_string、字体）
- **窗口管理器**：桌面环境含主窗口、文件管理器、计算器、终端、记事本编辑器、内置浏览器，支持拖拽/最大化/最小化/关闭
- **内置浏览器**：离线网页查看器（`browse` 命令 / 桌面 Browser 图标），读取 FAT 硬盘里的 HTML 文件并渲染 `<h1>` / `<p>`，支持翻页与刷新，无任何网络代码
- **文件系统**：FAT12 / FAT16 / FAT32 三格式支持，IDE/ATA PIO 驱动，子目录导航（cd/mkdir）
- **Shell**：20+ 内置命令，含任务管理器、文件编辑器、安装器，动态路径提示符
- **用户程序生态**：CE 可执行格式 + SDK（crt0、链接脚本、打包工具、文件 IO API），可在系统中 `run` 用户程序
- **安装器**：内置 `setup` 命令将系统安装到硬盘，生成标准 MBR + FAT32 布局

---

## 项目结构

```
CatOS/
├── boot/                  # 引导代码
│   ├── boot.asm           # FAT12 软盘引导扇区
│   ├── hdboot.asm         # 硬盘 VBR 引导扇区
│   ├── mbr.asm            # 标准 MBR（含分区表与引导代码）
│   ├── loader.asm         # 加载器：进入保护模式、加载内核、开启分页
│   └── include/           # 引导阶段头文件 (fat12hdr.inc, load.inc, pm.inc)
│
├── kernel/                # 内核源码
│   ├── kernel.asm         # 内核入口、异常处理、中断入口
│   ├── start.c            # cstart：GDT/IDT 初始化
│   ├── main.c             # tinix_main：进程表初始化
│   ├── protect.c          # 中断描述符、TSS、保护机制
│   ├── proc.c             # 进程调度、切换
│   ├── i8259.c            # 8259A PIC 驱动
│   ├── clock.c            # 时钟中断处理
│   ├── console.c          # 控制台、TTY、VGA 输出
│   ├── tty.c              # TTY 抽象层
│   ├── keyboard.c         # 键盘驱动（含 0xE0 扩展键）
│   ├── mouse.c            # 鼠标驱动
│   ├── hd.c               # IDE/ATA PIO 硬盘驱动
│   ├── fat.c              # FAT12/16/32 文件系统（含子目录操作）
│   ├── installer.c        # 硬盘安装器
│   ├── editor.c           # 内置文本编辑器
│   ├── taskmgr.c          # 任务管理器界面
│   ├── shell.c            # 命令行 Shell
│   ├── exec.c             # CE 用户程序加载器（支持指定目录）
│   ├── gfx.c              # VGA Mode 13h 图形原语
│   ├── wm.c               # 窗口管理器（桌面环境）
│   ├── browser.c          # 内置浏览器（离线 HTML 查看器: h1/p/br/hr + 翻页）
│   ├── syscall.asm        # 系统调用入口 (int 0x90)
│   ├── syscall_c.c        # 系统调用分发
│   ├── printf.c / vsprintf.c  # 内核 printf
│   └── global.c           # 全局变量定义
│
├── lib/                   # 内核库
│   ├── klib.asm           # 内核汇编工具（disp_str、out_byte、IRQ 控制等）
│   ├── klibc.c            # 内核 C 工具函数
│   └── string.asm         # 字符串操作
│
├── include/               # 内核头文件
│   ├── type.h, const.h    # 类型与常量
│   ├── protect.h, proc.h  # 保护与进程结构
│   ├── proto.h            # 函数原型
│   ├── fat.h, hd.h        # 文件系统与硬盘接口
│   ├── tty.h, console.h   # 控制台接口
│   ├── keyboard.h, keymap.h, mouse.h
│   ├── shell.h, editor.h, taskmgr.h
│   ├── gfx.h              # 图形原语接口
│   ├── wm.h               # 窗口管理器接口
│   ├── browser.h          # 内置浏览器接口
│   └── scont.inc          # 汇编常量
│
├── sdk/                   # 用户程序开发工具包
│   ├── crt0.asm           # C 运行时启动代码
│   ├── user.ld            # 用户程序链接脚本
│   ├── mkcate.py          # CE 格式打包工具
│   ├── Makefile           # SDK 构建脚本
│   ├── app.c              # 示例程序
│   ├── app.ce             # 示例 CE 可执行文件
│   ├── makece.sh / makece.bat  # CE 打包脚本
│   ├── disk.py            # 镜像文件注入工具
│   ├── check.py           # CE 格式校验工具
│   ├── DEVELOPER.md       # 开发者文档（详细）
│   └── DEVELOPER.html / api.html  # 文档 HTML 版本
│
├── samples/               # 示例网页（构建时写入 FAT 镜像根目录）
│   └── INDEX.HTM          # 内置浏览器默认打开的页面
│
├── tools/preview/         # 宿主侧渲染预览工具（不用虚拟机也能看效果）
│   ├── preview.c          # 用真实字体/调色板把 browser.c 渲染成 BMP
│   ├── mkfont.py          # 从 kernel/gfx.c 提取 8x16 点阵字体
│   └── shim/              # 编译 browser.c 所需的最小头文件桩
│
├── build.sh               # 主构建脚本
├── kernel.ld              # 内核链接脚本
├── bochsrc.bxrc           # Bochs 配置
├── run.bat                # QEMU 启动脚本
├── Makefile               # 历史遗留 Makefile（参考用）
└── count.py               # 代码行数统计工具
```

---

## 工具链要求

| 工具 | 用途 | 备注 |
|------|------|------|
| **NASM** 2.13+ | 汇编引导/内核 ASM 源码 | 推荐 3.x |
| **GCC** (支持 `-m32`) | 编译内核 C 源码 | 推荐 `i686-w64-mingw32-gcc` 或 MinGW |
| **objcopy** | 提取纯二进制 | 随 binutils 提供 |
| **Python** 3.6+ | 生成硬盘镜像、打包 CATE | |

`build.sh` 会自动探测 MinGW 工具链，兼容 Git Bash / MINGW64 / WSL。

---

## 构建

```bash
# 完整构建并生成软盘镜像
./build.sh image

# 仅编译（不生成镜像）
./build.sh

# 清理所有构建产物
./build.sh clean

# 重新构建
./build.sh rebuild

# 生成 FAT16 硬盘镜像（10MB，文件浏览测试用）
./build.sh hdimg

# 生成 FAT32 硬盘镜像（256MB，标准 MBR 布局）
./build.sh hdimg32
```

构建产物：
- `boot/boot.bin` — 软盘引导扇区
- `boot/loader.bin` — 加载器
- `boot/mbr.bin` — 主引导记录
- `kernel.bin` — 内核纯二进制
- `catos.img` — 1.44MB FAT12 软盘镜像（可直接启动）
- `catos_hd.img` / `catos_hd32.img` — 硬盘镜像

**构建策略**：`build.sh` 采用两遍编译——第一遍用默认大小估算编译内核，第二遍用实际 `kernel.bin` 大小重新编译，使加载器能动态感知内核尺寸。

### 不用虚拟机预览浏览器渲染

`tools/preview/` 可以在宿主机（Windows/MinGW 或 Linux）上直接编译 `kernel/browser.c`，用真实的 8x16 点阵字体和调色板把页面渲染成 BMP/PNG，用来检查折行和排版，不需要启动 QEMU：

```bash
cd tools/preview
python mkfont.py ../../kernel/gfx.c font8x16.bin
gcc -DBR_HOST_BUILD -I shim -I ../../include -O1 -o preview.exe preview.c ../../kernel/browser.c
./preview.exe font8x16.bin ../../samples/INDEX.HTM out.bmp 640 480      # 640x480
./preview.exe font8x16.bin ../../samples/INDEX.HTM out2.bmp 320 200 1   # 末位参数=按几次 PgDn
```

工具除了写图片，还会把渲染结果打印成"字符画"，便于在没有图形界面的环境下核对排版。

### 浏览器自检 / 模糊测试

`tools/preview/selftest.c` 直接 `#include` 了 `kernel/browser.c`（同一编译单元，因此能检查它的静态缓冲区），不需要给内核加任何测试钩子，也不需要 AddressSanitizer：

```bash
cd tools/preview
gcc -DBR_HOST_BUILD -I shim -I ../../include -O2 -Wall -o selftest.exe selftest.c
./selftest.exe
```

覆盖的内容：

- 边界/畸形输入：空文件、文件不存在、未闭合标签、`<p` 到文件尾、`<!--` 未闭合、属性值里含 `>`、大写标签、嵌套标签、内嵌 NUL、控制字符、非 ASCII、CRLF/制表符、未知实体
- 缓冲边界：500 字符超长单词、200 个段落（触发 96 行上限）
- 排版：320x200 / 640x480 / 800x600 / 1024x768 / 1280x1024 / 1920x1080 六种分辨率绘制，以及窗口放大后重新折行
- 按键边界：PgUp/PgDn/↑/↓ 各 40 次、Home/End/F5，滚动位置始终落在合法范围
- 随机模糊：20000 组随机字节 + 5000 组随机标签组合，检查结构不变式（行长、行数、行种类、字符串结尾、绘制坐标）

当前结果：**全部通过，0 失败**（约 700 万次绘制调用）。这套自检在开发中真的抓到了四个 bug：长段落被 160 字符截断、滚动落在折行中间时重复绘制、属性值里的 `>` 提前结束标签、纯空白行也占用一行高度。

---

## 运行

### QEMU（推荐，启动最快）

```bash
# 软盘 + FAT32 硬盘（默认）
run.bat
# 或手动：
qemu-system-i386 -drive file=catos.img,if=floppy,format=raw \
                 -drive file=catos_hd32.img,format=raw
```

### Bochs

```bash
bochs -f bochsrc.bxrc
```

`bochsrc.bxrc` 默认挂载 `catos.img` 为软盘、`catos_hd32.img` 为硬盘，从软盘启动。

### VMware

将 `catos.img` 作为软盘镜像、`catos_hd32.img` 作为硬盘挂载，从软盘启动即可。

启动后会出现 `CatOS / > ` 提示符。

---

## Shell 命令

提示符会显示当前路径：根目录 `CatOS / > `，子目录 `CatOS /test/ > `。

| 命令 | 说明 |
|------|------|
| `help` | 显示命令帮助 |
| `ver` / `version` | 显示版本信息 |
| `about` | 关于 CatOS |
| `clear` / `cls` | 清屏 |
| `echo <text>` | 输出文本 |
| `sysinfo` | 系统信息（内存、CPU 等） |
| `taskmgr` | 任务管理器（查看运行中的进程） |
| `diskinfo` | 磁盘与 FAT 文件系统信息 |
| `dir` / `ls` | 列出当前目录文件 |
| `cd [dir]` | 切换目录（`cd`/`cd \`/`cd /` 回根，`cd ..` 父目录，`cd <name>` 进入子目录） |
| `mkdir <name>` | 创建子目录 |
| `type <file>` | 显示文件内容 |
| `format <drv> <type>` | 格式化磁盘（如 `format 1 32`） |
| `touch <file>` | 创建空文件 |
| `edit <file>` | 编辑文件（内置编辑器） |
| `rd <file>` | 删除文件 |
| `run <file.ce> [&]` | 运行 CE 用户程序（末尾 `&` 后台运行） |
| `ps` | 列出运行中的进程 |
| `cat` | 进入图形桌面环境（按 ESC 退出） |
| `browse [file]` | 进入桌面并打开内置浏览器（不带参数 = `INDEX.HTM`） |
| `setup` | 交互式安装器（安装到硬盘） |
| `reboot` | 重启系统 |
| `shutdown` | 关机 |

---

## 图形桌面

在 Shell 中输入 `cat` 即可进入图形桌面环境（VGA Mode 13h, 320x200x256），按 ESC 退出回到文本模式 Shell。

### 桌面应用

- **主窗口**：大图标排列，双击图标打开应用
- **文件管理器**：浏览文件/文件夹，双击进入子目录，单击选中；双击 `.ce` 文件直接运行
- **终端**：命令行界面，支持 `help`/`dir`/`cd`/`mkdir`/`type`/`touch`/`rd`/`edit`/`run`/`ps`/`sysinfo` 等命令，PageUp/PageDown 滚动回看历史
- **记事本**：文本编辑器，支持打开/编辑/保存（Ctrl+S）文件，含 File 下拉菜单
- **浏览器**：内置离线网页查看器，读取 FAT 硬盘里的 HTML 文件（默认 `/INDEX.HTM`），详见下节
- **计算器**：基本四则运算
- **关于**：显示系统信息

### 内置浏览器（离线网页查看器）

> 第一版目标：先把"能在 CatOS 里看网页"跑通，然后再逐步加功能。**没有任何网络代码**，只读本地 FAT 硬盘。

![内置浏览器 640x480](docs/img/browser-640x480.png)

打开方式（三种任选）：

1. Shell 里输入 `browse`（默认打开 `INDEX.HTM`）或 `browse OTHER.HTM`
2. 进入桌面（`cat`）后，双击主窗口里的 **Browser** 图标
3. 在文件管理器里双击任意 `*.HTM` 文件

支持的 HTML 子集（`kernel/browser.c`）：

| 标签 | 效果 |
|------|------|
| `<h1>…</h1>` | 标题行：蓝色 + 加粗 |
| `<p>…</p>` | 段落：自动按窗口宽度折行，段前留空行 |
| `<br>` | 强制换行 |
| `<hr>` | 水平分隔线 |
| 其他标签 | 忽略标签本身，保留其中的文字 |
| `<head>` / `<title>` / `<script>` / `<style>` | 整段跳过 |

- 字符实体：`&amp;` `&lt;` `&gt;` `&quot;` `&apos;` `&nbsp;` 会被解码
- 非 ASCII 字符（如中文）显示为 `.`：VGA 位图字体只包含 ASCII 32~126
- 按键：`PageUp` / `PageDown` / `↑` / `↓` 翻页，`Home` / `End` 跳首尾，`F5` 重新读取文件，`ESC` 退出桌面
- 窗口最大化后页面会按新宽度重新折行

实现要点（内核态安全）：

- 全部使用静态缓冲区（约 19KB BSS），**没有任何动态内存分配**，不存在分配失败导致缺页的路径
- 读文件长度、解析下标、折行宽度、滚动位置全部做边界夹紧，`uint8/uint16` 不溢出
- 解析器是单遍顺序扫描，无递归，遇到畸形 HTML（未闭合的标签、超长行）不会死循环或越界

默认示例页面 `samples/INDEX.HTM` 会在 `build.sh hdimg` / `hdimg32` 生成镜像时写入硬盘根目录，可以直接用记事本修改后按 `F5` 看效果。

还没有做的（后续计划）：可点击链接、地址栏、前进/后退历史、颜色/列表/图片、真正的滚动条。

### 控制台程序运行

在文件管理器中双击 `.ce` 可执行文件，或在终端中使用 `run <file.ce>` 命令，系统会为程序分配一个独立的**控制台窗口**。程序的标准输出（`puts`/`putc`/`put_int` 等）会显示在该窗口中，键盘输入（`getch`/`getc`）也从该窗口获取。

程序退出（调用 `exit` 或从 `main` 返回）后，控制台窗口不会立即关闭，而是显示：

```
Press any key to continue...
```

用户按下任意键后窗口才关闭。这样便于查看程序的最终输出结果。多个程序可同时运行，各自拥有独立的控制台窗口。

### 窗口操作

- 标题栏拖拽移动窗口
- 右上角三按钮：最大化 / 最小化 / 关闭
- 点击窗口激活并置顶
- 最小化的窗口显示在底部任务栏，点击还原

桌面终端与 Shell 各自维护独立的工作目录，互不影响。

---

## 安装到硬盘

CatOS 可通过内置 `setup` 命令将自身安装到硬盘，使其能够从硬盘启动：

1. 用软盘镜像启动 CatOS
2. 在 Shell 中执行 `setup`
3. 按照交互提示完成安装

安装过程会：
- 写入标准 MBR 到硬盘扇区 0
- 格式化 FAT32 分区（分区起始 LBA 2048，1MB 对齐）
- 将内核写入磁盘末尾（动态计算 LBA，避免被 FAT 表覆盖）
- 将 VBR 中写入内核扇区数，加载器据此动态读取

安装完成后可从硬盘启动，无需软盘。

---

## 用户程序开发 (SDK)

CatOS 支持 CE（CatOS Executable）格式的用户程序，运行在 Ring 3。开发者无需重新编译内核即可分发软件。

### 快速开始

```bash
cd sdk
make           # 编译生成 app.ce
```

将 `app.ce` 放入 FAT 文件系统镜像后，在 Shell 中执行：

```
CatOS / > run app.ce
```

### 系统调用 API

用户程序通过 `int 0x90` 软中断调用内核服务（节选，完整列表见 DEVELOPER.md）：

| NR | 函数 | 原型 | 说明 |
|----|------|------|------|
| 0 | `get_ticks` | `int get_ticks(void)` | 系统时钟滴答数 |
| 1 | `write` | `int write(char* buf, int len)` | 写入缓冲区到控制台 |
| 2 | `putc` | `void putc(int ch)` | 输出单字符 |
| 3 | `puts` | `void puts(char* str)` | 输出字符串 |
| 4 | `getc` | `int getc(void)` | 非阻塞读键盘 |
| 5 | `exit` | `void exit(int code)` | 终止程序 |
| 6 | `clrscr` | `void clrscr(void)` | 清屏 |
| 7 | `gotoxy` | `void gotoxy(int x, int y)` | 移动光标 |
| 11 | `set_color` | `void set_color(int color)` | 设置默认颜色 |
| 14 | `rand` | `int rand(void)` | 伪随机数 [0, 32767] |
| 19 | `delay` | `void delay(int ms)` | 毫秒延时 |
| 20 | `getch` | `int getch(void)` | 阻塞读键（含扩展键 0x100+code） |
| 23+ | `file_read/write/delete/exists/size/list/append/stat` | 文件 IO |  |
| 28 | `spawn` | `int spawn(char* name, int blocking)` | 启动另一个用户程序 |

### 示例程序

```c
extern void puts(char* str);
extern void putc(int ch);
extern void exit(int code);

int main(void)
{
    puts("Hello, CatOS!\n");
    putc('A');
    putc('\n');
    exit(0);
    return 0;
}
```

详细开发指南（CE 格式、内存布局、段隔离、文件 IO、限制与注意事项）请参见 [sdk/DEVELOPER.md](sdk/DEVELOPER.md)。

---

## 架构概述

### 启动流程

```
BIOS → MBR (扇区0) → VBR (分区起始) → Loader → Kernel (cstart → tinix_main)
```

1. **MBR**：标准 MBR，包含分区表与引导代码，跳转到活动分区的 VBR
2. **VBR**：FAT12 软盘引导扇区 / FAT32 硬盘引导扇区，加载 Loader
3. **Loader**：进入保护模式、读取内核到 `0x30400`、建立 GDT/IDT、开启分页、跳转内核
4. **Kernel**：`cstart` 初始化 GDT/IDT/TSS，`tinix_main` 初始化进程表并启动调度

### 内存布局

| 地址 | 内容 |
|------|------|
| `0x00000 ~ 0x9FBFF` | 常规内存 |
| `0x90000` 附近 | Loader 临时数据（GDT 等） |
| `0x30400` | 内核入口（KernelEntryPointPhyAddr） |
| `0x100000 ~ 0x180000` | 4 个用户进程区（各 128KB，槽位 i 基址 = `USER_PROC_BASE + i*USER_PROC_SIZE`） |
| `0x180000 ~ 0x1A0000` | 文件缓冲区（file_buf） |
| `0x1A0000 ~ 0x1C0000` | 任务栈区 |
| `0xA0000` | VGA Mode 13h 显存（320x200x256） |

### 特权级模型

| 层 | 特权级 | 说明 |
|----|--------|------|
| 内核 | Ring 0 | GDT 中的代码/数据段 |
| 内核任务 | Ring 1 | LDT 隔离，IOPL=2，可执行部分特权指令 |
| 用户程序 | Ring 3 | LDT 隔离，IOPL=0，禁止访问硬件 |

### 图形模式

- 通过 `cat` 命令从文本模式（80x25）切换到 VGA Mode 13h（320x200x256）
- `gfx.c` 提供软件渲染原语：`fill_rect`、`draw_string`、`vm_putc`、`gfx_scroll_up`
- `wm.c` 实现窗口管理器：Z-order 调度、标题栏按钮、拖拽、任务栏
- ESC 退出图形桌面回到文本模式 Shell

---

## 故障排查

### 启动后无显示 / CPU 关机
- 确认 `catos.img` 是最新构建（运行 `./build.sh image`）
- VMware 中如遇虚拟 CPU 关机（Triple Fault），通常是 TSS 描述符 limit 设置错误或异常处理中段寄存器恢复不当

### 内核构建后过大
内核加载器限制为 512 扇区（256KB）。若 `kernel.bin` 超过此限制，需精简内核代码。

### 硬盘安装失败 (HD error)
- 确认硬盘镜像已正确挂载
- 安装器会动态计算内核 LBA，确保 FAT32 已先格式化再写 MBR

### 用户程序输出乱码
裸机环境下 `.rodata` 段寻址在某些 GCC 版本下不可靠。改用全局数组定义字符串：

```c
static char msg[] = "Hello\n";   /* 放入 .data，寻址可靠 */
puts(msg);
```

### 桌面终端 run 命令无响应
桌面终端的 `run` 总是非阻塞启动程序（避免冻结 UI）。程序结束后控制台窗口会显示 "Press any key to continue..."，按键后关闭。如需前台阻塞行为，请使用文本模式 Shell 的 `run <file>`（不带 `&`）。

### 子目录文件操作失败
所有文件命令（`type`/`touch`/`rd`/`edit`/`run`）均在当前工作目录下查找文件。使用 `cd` 切换目录，`cd \` 或 `cd /` 回到根目录。

### 更多历史经验
项目积累的工程约定与教训见代码注释及提交历史。

---

## 最终状态与已知限制（务必先读）

### 已经完成且验证过的部分

| 部分 | 验证方式 | 结果 |
|---|---|---|
| 浏览器：HTML 子集解析/折行/渲染、链接点击、地址栏、前进后退、翻页、`about:home/help/files`、错误页 | `tools/preview/selftest.c`（含 2 万随机 + 5 千结构化模糊输入） | 0 失败 |
| 浏览器排版外观 | `tools/preview/preview.c` 用真字体/调色板渲染 PNG | `docs/img/browser-*.png` |
| SHA-256 / HMAC / TLS PRF / SHA-1 | Python `hashlib`/`hmac` + .NET 向量 | 27 组通过 |
| AES-128 ECB/CBC/CTR/GCM | .NET + 独立纯 Python（先自检 FIPS-197 与 NIST GCM） | 9 组通过 |
| RSA-2048 / PKCS#1 v1.5（modpow、验签、加密块） | .NET `BigInteger`/`RSA` | 6 组通过 |
| TLS 1.2 记录层、密钥派生、Finished、CBC+GCM 记录加解密 | C 客户端 ↔ Python 服务端双向互验 | 两种套件各一轮，0 失败 |
| X.509 解析与证书链校验 | .NET 生成的真证书 + 篡改/过期/畸形用例 | 全通过 |
| TLS 客户端握手驱动（分片重组/CCS/Alert/证书接链） | 同上（Certificate 特意拆两条记录） | 全通过 |
| HTTP/1.1 状态行/头部/chunked/请求构造 | 手工 RFC 形态报文 | 40+ 断言通过 |

### 明确未完成 / 不能声称可用的部分

1. **所有内核代码都没有在真机/虚拟机上启动验证过**（本机无 nasm/QEMU）。全部证据止于：`gcc -m32 -ffreestanding` 编译通过 + 宿主侧同名源码的单元测试。
2. **网卡驱动、ARP、IPv4、TCP、DNS 尚未编写** —— 因此浏览器目前**只能打开本地 FAT 硬盘上的 HTML 文件**，`http://` / `https://` 仍显示"无网络"提示页。
3. **ECC P-256 未完成**：`lib/ec.c` 的素域运算已通过 8 组独立向量，但点运算层未通过自带测试（另有一个独立探针能算对 2G，说明实现方向正确、测试或某处细节仍有问题）。该模块**未加入 `build.sh`、未被 TLS 调用**。
4. **没有 ECDHE**：现有 TLS 套件是静态 RSA（0x002F / 0x009C）。现代站点普遍只接受 ECDHE，所以即使接上网卡，也打不开大多数真实网站。
5. **随机源是演示级的**（LCG）：正式做 HTTPS 前必须换成 RDRAND/RTC/中断计时混合。
6. **证书信任锚只有单一 DER 位**：没有多根证书库、没有用户导入。

### 下一步的推荐顺序

1. 在能跑 QEMU 的环境里把现有代码跑起来（`./build.sh image hdimg32 && qemu-system-i386 ...`），确认桌面与浏览器真的能显示页面
2. 写 e1000 + ARP/IPv4/TCP/DNS（这层必须边跑边调）
3. 修完 P-256 点层 → ECDHE + ServerKeyExchange 验签 → 浏览器接 `https://`
4. 换掉演示级随机源，补多根信任锚

---
## 网络与 HTTPS（路线图 / 进行中）

> 目标：在核心里手写网卡驱动 + TCP/IP + HTTP + TLS，做到真正能访问 HTTPS 网页；不引入 lwIP / mbedTLS 等任何第三方库。

### 实测内存预算（决定了实现方式）

| 项目 | 数值 | 说明 |
|------|------|------|
| `kernel.bin`（C 目标文件） | 197,112 B | 加上汇编段约 210 KB（加载器上限 262,144 B） |
| 加载器上限 | 262,144 B | `boot/loader.asm: wKernelSectorCount = 512` |
| 代码余量 | ≈ 70 KB | 网卡+TCP+TLS 的代码必须先扩这个上限 |
| 内核 `.bss` | 137,616 B | 用户窗口画布（112 KB）已移出 → 镜像 0x30400 + 197 KB + 138 KB ≈ **0x81F88** |
| 到 0xA0000（VGA 显存洞） | ≈ 123 KB | 足够放 TLS 记录缓冲与证书链 |

**结论**：网络与 TLS 所需的几十 KB 缓冲区不能再放 `.bss`。

已落地的做法（本仓库现状）：**两块大缓冲都已移出 `.bss`** —— 浏览器的行表/链接区间/源文件（约 20 KB）放在 **0x1C0000** 起的固定 arena，用户窗口画布（4 × 200×140 = 112 KB）放在 **0x1D0000** 起的 arena（`wm_init` 里切分指针）。——这两个地址落在 `task_stack` 末端（0x1C0000）到 `PageDirBase`（0x200000）之间的空闲区，`loader.asm` 的 `SetupPaging` 至少 identity map 前 16 MB（`cmp ecx, 4` 保底）。**注意：页目录/页表本身就在 0x200000 / 0x201000（见 `boot/include/load.inc`），所以 arena 绝不能放在 0x200000 或 0x210000 —— 那里是页表，会直接引发三重故障。**这一步把内核 `.bss` 从 284,300 B 一路降到 **137,616 B**，内核末端从越过显存洞（0xA1FCC）拉回到 **0x81F88**，重新获得约 120 KB 余量。

后续 TLS/TCP 的缓冲继续沿用这个 arena（再加一个 bump 分配器和空闲链表即可），`.bss` 不再增长。宿主侧测试用 `-DBR_HOST_BUILD` 把 arena 换成本地数组。

*（尝试过的方案：直接把 `.bss` 段放在 0x200000 —— MinGW ld 的 PE 后端会拒绝这种大间隙，链接报 `base relocation ... above .reloc`，所以改成了运行时 arena。）*

> ⚠️ **事故记录（真机 Triple fault）**：即便链接器允许，也**绝对不能**把 `.bss` 放到 0x200000。那里是 `PageDirBase`（页目录），`_start` 的 `rep stosd` 清零 `.bss` 会把页目录和页表一起清零。现场特征：`CR3=0x00200000`（分页已开但目录已空）、`CR2=0xFD000000`（VBE LFB 的 PDE 丢失）、`CR2=0x00006FFC`（栈 push 时 PTE 也不在）、最终 `#PF` 送不进去 → 双重故障 → Triple fault。`.bss` 必须紧跟镜像连续排布，末端约 0x87xxx（低于 0xA0000，也不碰 0x90100 的 LOADER.BIN）。

### 已完成

- `lib/crypto.c` + `include/crypto.h`（零 libc、零 libgcc 依赖，`.text` 10.8 KB、`.rdata` 256 B、`.bss` 544 B）：
  - **SHA-256 / HMAC-SHA256 / TLS 1.2 PRF(P_SHA256)**
  - **SHA-1 / HMAC-SHA1**（TLS 1.2 的 Finished 旧算法、旧证书签名）
  - **AES-128**：分组加解密、**CBC**、**CTR**、**GCM**（GCM 含 AAD、常量时间 tag 校验、认证失败时不输出明文）
  - 说明：S 盒不是手抄常数表，而是首次使用时由 GF(2^8) 运算现场生成，避免抄错
- **RSA-2048 / PKCS#1 v1.5**（`lib/rsa.c`）：多精度整数（32 位 limb，32×32 用 `mull`，**不含除法/不需要 libgcc**）、模幂（e=65537，位串长除法取模）、签名校验（SHA-256 DigestInfo）、v1.5 加密块构造；`.text` 约 4 KB
- **TLS 1.2 记录层与握手编解码**（`lib/tls.c` + `include/tls.h`，`.text` 6.4 KB、零未定义符号、零 `.bss`）：记录头解析/生成、握手消息头读写、ClientHello 生成（含 SNI）、ServerHello / Certificate / ServerHelloDone 解析
- **X.509 证书解析 + 证书链校验**（`lib/x509.c` + `include/x509.h`，`.text` 4.3 KB）：极简 DER 解析、取 RSA 公钥（去 DER 前导 0）、有效期（UTCTime/GeneralizedTime）、`issuer == parent.subject`（整段 DER 比较）+ 用父证书公钥验子证书签名（sha256WithRSA）、根自签校验；用 .NET 生成的真证书（root/leaf/expired）验证，含篡改签名/篡改主体/截断/垃圾输入拒绝
- **ECC P-256（进行中）**：`lib/ec.c` + `include/ec.h` —— 素数域加/减/乘/求逆**已通过 8 组 Python 独立参考向量**（含接近模数的边界值、a·a⁻¹≡1）；**点运算层（雅可比倍点/加点/标量乘）仍有 bug，测试未通过，因此尚未接入 TLS 与 build.sh**。这点如实标注，不假装可用。
- **HTTP/1.1 报文处理**（`lib/http.c` + `include/http.h`）：状态行/头部解析（大小写不敏感）、`Content-Length`/`Transfer-Encoding: chunked`/`Connection`/`Content-Encoding` 识别、请求构造、**可续传的 chunked 解码**（含 chunk extension 与 trailer）、状态码分类；对不完整输入返回 `INCOMPLETE` 而不是误判
- **AES-128-GCM 套件（0x009C, AEAD）**：8 字节显式 nonce + 密文 + 16 字节 tag，AAD = `seq‖type‖version‖len`，按服务端 ServerHello 自动切换套件并重算密钥块（GCM 无独立 MAC、salt 4 字节）
- **信任锚存储**：`tls_trust_set()/tls_trust_get()`
- **TLS 1.2 客户端握手驱动**（`tls_client_*`）：ClientHello → 解析 ServerHello/Certificate/ServerHelloDone（**支持握手消息跨记录分片与多条消息共用记录**）→ 证书链校验 → RSA 密钥交换 → CCS → 加密 Finished → 校验服务端 Finished；Alert 一律按错误处理。整个驱动是"字节进/字节出"，不碰任何 I/O，网络层接上就能用
- **TLS 1.2 会话与握手状态**：`master_secret` / 密钥块派生（PRF-SHA256）、client/server Finished (`verify_data`)、AES-128-CBC 记录加解密（显式 IV、HMAC-SHA1 记录 MAC、填充校验、常量时间 MAC 比较、序号计数）；明确拒绝尚未实现的 GCM 套件而不是静默降级
  - 记录片段上限 2 KB（内核任务栈只有 32 KB，不能用 16 KB 缓冲）
- `tools/crypto_test/`：**三套独立实现交叉验证**（不是自己算完自己比）
  - SHA-256 / HMAC / PRF ← Python `hashlib`/`hmac`：11 + 5 + 4 组
  - SHA-1 / HMAC-SHA1 / AES-ECB / CBC / CTR ← **.NET** 的 `SHA1`/`HMACSHA1`/`Aes`：7 + 4 + 3 组（含 FIPS-197 附录 C.1）
  - AES-128-**GCM** ← `gen_gcm_vectors.py` 里另写的一套纯 Python AES+GCM，且它自身先过 **FIPS-197 + NIST GCM 测试用例 1/2** 才允许生成向量：6 组（含 AAD、0/1/16/17/100/255 字节、篡改 tag 必须被拒）
  - 合计 **45 组向量 + 解密回环 + 篡改拒绝**，当前 **0 失败**

```bash
cd tools/crypto_test
powershell -File run_tests.ps1     # 一条命令: 重建全部向量 + 编译 + 运行
```

`run_tests.ps1` 会依次调用 `gen_vectors.py`（SHA-256/HMAC/PRF、AES-GCM）、`gen_vectors_net.ps1`（SHA-1/AES-ECB/CBC/CTR）、`gen_rsa_vectors.ps1`（RSA-2048），再用 `gcc -DBR_HOST_BUILD` 编译 `test.c` 并运行。

### TLS 编解码自测

`tools/tls_test/` 用 **Python 独立实现 TLS 记录封装**做双向互验（避免"自己验自己"）：

```bash
cd tools/tls_test
python gen_fixtures.py fixtures.h          # 服务端记录流（ServerHello / Certificate / ServerHelloDone）
gcc -I shim -I ../../include -O2 -Wall -o tls_test.exe test_tls.c
./tls_test.exe client_hello.txt            # 解析夹具 + 生成 ClientHello
python verify_hello.py client_hello.txt    # 反向解析 C 生成的 ClientHello
```

覆盖：

- 记录层：多握手消息共用一条记录（合法但容易解析错）、截断记录、超过 16 KB 的记录长度
- 握手层：长度字段与消息体一致性、超长/截断握手消息
- ServerHello 字段（版本 / random / 空 session id / 套件 / null 压缩）
- Certificate 列表与按索引取证书（越界必须报错）、ServerHelloDone 必须为空
- **反向校验** C 生成的 ClientHello：记录与握手帧、两个套件 (`0x002F`/`0x009C`)、SNI 扩展里的主机名

### TLS 握手互验（两阶段）

`tools/tls_test/` 里还有一套**握手级**互验：C 侧扮演客户端，`server_emu.py` 用 Python 的 `hashlib`/`hmac` + 一套已过 FIPS-197 自检的纯 Python AES 扮演服务端。

```bash
cd tools/tls_test
powershell -NoProfile -ExecutionPolicy Bypass -File gen_hs_key.ps1   # RSA 密钥对
gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_handshake.c
./hs_test.exe phase1 client_out.txt server_out.txt    # 客户端消息 + 密钥派生 + 加密 Finished
python server_emu.py client_out.txt hs_key.txt server_out.txt
./hs_test.exe phase2 client_out.txt server_out.txt    # 解密并校验服务端 Finished
```

Python 侧独立完成的检查：RSA 私钥解密 + PKCS#1 v1.5 填充校验、`master_secret`、四个方向的密钥、client `Finished`、**解密 C 侧加密记录并校验 HMAC**、server `Finished`、再加密封一条服务端记录交给 C 解；C 侧 phase2 则校验该记录并拒绝篡改/截断。

### 待做（按依赖顺序）

1. **内核堆**：扩展 loader 页表，0x200000 起统计映射 1–2 MB 作内核堆；今后所有网络/TLS 缓冲都从这里取，`.bss` 不再增长
2. **网卡驱动**：QEMU 默认 **e1000**（PCI 枚举 + MMIO + TX/RX 环）优先，RTL8139 作备选
3. **协议栈**：ARP → IPv4（校验和、拒绝分片）→ ICMP echo → UDP → **TCP 客户端**（三次握手、重传、滑动窗口、RST/FIN）→ DNS(A) 解析
4. **HTTP/1.1**：请求构造、状态行/头部解析、`Content-Length` 与 `chunked` 解码，响应体直接喂给 `browser.c` 的排版引擎
5. **TLS 1.2**：~~记录层/握手编解码~~ ✅ → ~~密钥派生 + Finished + CBC 记录加解密~~ ✅ → ~~X.509 证书链校验~~ ✅ → ~~完整握手驱动（CCS/分片重组/Alert/证书接链）~~ ✅ → ~~AES-GCM 套件~~ ✅ → **ECDHE-P256**（现代站点普遍只接受 ECDHE，静态 RSA 密钥交换已基本被抛弃）→ 证书信任锚存储
6. **浏览器接入**：地址栏输入 `http://` / `https://` 走网络栈，其余渲染路径不变

### 验证边界（必须先说清楚）

- ✅ 可离线验证：密码学算法（RFC/NIST 向量）、HTTP 报文解析、TLS 记录/握手字节流的解析与生成（用抓包得到的十六进制流做夹具）
- ❌ 无法在本机验证：网卡寄存器时序、ARP/TCP 与真实对端的互操作 —— 这台开发机没有 QEMU/nasm。这两层只能"写 + 评审"，必须在一台能跑 QEMU 的机器上联调后才能声称可用

---
## 许可证

本项目基于 [Apache License 2.0](LICENCE.txt) 发布。

Copyright 2026 Clean.
## 已知问题 (最新): netmock 第 2 条记录解密失败

netmock_fetch() 的进度能走到 "Decrypting..."，第 1 条 AES-128-CBC 加密记录
解密成功；第 2 条 (seq=1) 在 tls_unseal() 里 MAC 校验失败 (-6)。

排查进度:
- TLS 握手 (证书链校验+密钥派生) 已在宿主探针中确认正常
  (3 条服务端记录全过，输出 342 字节 = CKE+CCS+Finished)
- 第 1 条应用数据记录解密正确
- 第 2 条疑似 seq_in 递增或 MAC 输入有差一错误
- netmock.c 里有临时 printf 调试代码，修复后请移除

