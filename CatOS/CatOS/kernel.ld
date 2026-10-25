/*======================================================================
  kernel.ld — CatOS 内核链接脚本

  作用:
    1. 将 .text 段放置在 0x30400 (内核加载地址)
    2. 按 .text → .data → .rdata → .bss 顺序排列所有段
    3. 定义 __bss_start__ / __bss_end__ 符号, 供 kernel.asm 中
       _start 清零 BSS 段使用 (objcopy 不输出 .bss, 必须运行时清零)

  编译流程:
    gcc -m32 用此脚本链接 → kernel.elf (PE)
    objcopy -O binary -j .text -j .data -j .rdata → kernel.bin (不含 BSS)
    loader 将 kernel.bin 加载到 0x30400, BSS 区域为内存垃圾
    _start 中 rep stosd 清零 [__bss_start__, __bss_end__]
======================================================================*/

ENTRY(cstart)

SECTIONS
{
    . = 0x30400;

    .text : {
        *(.text)
        *(.text.*)
        *(.gnu.linkonce.t.*)
    }

    .data : {
        *(.data)
        *(.data.*)
        *(.gnu.linkonce.d.*)
    }

    .rdata : {
        *(.rdata)
        *(.rdata.*)
        *(.rodata)
        *(.rodata.*)
        *(.gnu.linkonce.r.*)
    }

    /* ------------------------------------------------------------------
       .bss 紧跟在镜像后面 —— 绝对不要再把它指到 0x200000 !

       ★★★ 教训 (真机 Triple fault 事故) ★★★
       曾把 .bss 放到 0x200000 想给低端内存腾地方, 但 boot/include/
       load.inc 里定义的是:
           PageDirBase equ 200000h      ← 页目录就在 0x200000
           PageTblBase equ 201000h      ← 页表从 0x201000 开始
       而 kernel/kernel.asm 的 _start 会 rep stosd 清零整个 .bss,
       于是内核一初始化就把【页目录 + 页表】清成 0, 分页结构全毁.
       随后任何一次 TLB miss 都变成缺页, 现场就是:
           CR3=0x00200000   分页已开, 但那张"目录"已被清零
           CR2=0xFD000000   LFB (VBE 帧缓冲) 的 PDE 没了
           CR2=0x00006FFC   0x6000 页的 PTE 也没了, 栈 push 触发
           #PF 送不进去 → 双重故障 → Triple fault

       正确做法: 让 .bss 紧跟在 .rdata 后面连续排, 末端约 0x87xxx,
       既低于 0xA0000 (VGA 显存洞), 也不碰 0x90100 的 LOADER.BIN.
       大缓冲区不要靠挪 .bss 解决, 改用固定 arena (见 browser.c / wm.c).

       当前真实内存图 (与 load.inc / const.h / global.h 一致):
         0x0007C00            boot sector
         0x0007E00            loader 保护模式栈 (往下生长)
         0x0010000            kernel.bin 临时缓冲 (loader 读盘用)
         0x0030400            KERNEL 入口 / 镜像起点 (.text/.data/.rdata)
         0x0065DCC~0x087xxx   本文件排出来的 .bss (末端 < 0xA0000)
         0x0090100            LOADER.BIN
         0x00A0000            VGA 显存洞 (Mode 13h 起)
         0x0100000~0x0180000  用户进程区 (4 x 128KB, USER_PROC_BASE)
         0x0180000~0x01A0000  file_buf
         0x01A0000~0x01C0000  task_stack
         0x01C0000            browser 固定 arena (20240 B, 末端 0x1C4F10)
         0x01D0000            wm 画布固定 arena (112000 B, 末端 0x1EB580)
         0x0200000            PageDirBase — 页目录, 内核禁止占用
         0x0201000            PageTblBase — 页表 (每 4MB 内存一张 4KB)
       ------------------------------------------------------------------ */
    __bss_start__ = .;
    .bss : {
        *(.bss)
        *(.bss.*)
        *(.gnu.linkonce.b.*)
        *(COMMON)
    }
    __bss_end__ = .;

    /DISCARD/ : {
        *(.comment)
        *(.note.*)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.drectve)
        *(.ctors)
        *(.dtors)
    }
}
