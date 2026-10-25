/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                               mouse.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
  CatOS PS/2 鼠标驱动 + 文本模式光标贴图

  功能:
    - 初始化 PS/2 鼠标 (通过 8042 控制器, IRQ 12)
    - 中断处理: 读取 3 字节数据包, 更新鼠标坐标
    - 文本模式光标: 反色显示鼠标位置下的字符 (贴图效果)

  注意:
    - IRQ 12 在从片, 必须同时 enable CASCADE_IRQ(2) 解除主片级联屏蔽
    - GS 段已由 tty.c 设置为 Video 段选择器 (0x1B)
    - 光标通过保存/恢复字符+属性, 反色显示实现, 不破坏原字符
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "protect.h"
#include "proc.h"
#include "tty.h"
#include "console.h"
#include "global.h"
#include "mouse.h"
#include "proto.h"
#include "gfx.h"


/*======================================================================
  鼠标状态 (全局变量, 供其他模块查询)
======================================================================*/
PRIVATE volatile int mouse_x     = 0;   /* 鼠标 X 坐标 (初始值会被 init_mouse 覆盖) */
PRIVATE volatile int mouse_y     = 0;   /* 鼠标 Y 坐标 (初始值会被 init_mouse 覆盖) */
PRIVATE volatile int mouse_btns  = 0;    /* 按键状态: bit0=左, bit1=右, bit2=中 */
PRIVATE volatile int mouse_cycle = 0;    /* 数据包字节计数 (0,1,2) */
PRIVATE volatile t_8 mouse_packet[3];    /* 3 字节数据包缓冲区 */
PRIVATE volatile int mouse_ready = 0;    /* 鼠标是否初始化完成 */

/* 文本模式灵敏度缩放: 原始 delta 较大, 80x25 字符屏幕太小, 需要降速
   MOUSE_SCALE 越大越慢; sub_x/sub_y 保存亚像素余量, 避免慢速移动被截断丢失 */
#define MOUSE_SCALE  32
PRIVATE volatile int sub_x = 0;   /* X 亚像素累加器 (文本模式) */
PRIVATE volatile int sub_y = 0;   /* Y 亚像素累加器 (文本模式) */

/* 图形模式像素级坐标 (独立维护, 不再受字符粒度限制) */
PRIVATE volatile int mouse_px = 0;       /* 像素 X 坐标 (原始目标值) */
PRIVATE volatile int mouse_py = 0;       /* 像素 Y 坐标 (原始目标值) */
#define MOUSE_PX_SCALE  3               /* 图形模式降速因子 (3=每3个delta更新1像素) */

/* 平滑鼠标显示位置 (时间驱动的指数逼近)
 * - 只在 ticks 变化时推进一步 → 与 wm_run() 忙循环的频率解耦
 * - 距离大时步长大(跟手), 距离小时小步收敛, 死区内直接吸附(消除抖动)
 * - 全过程 clamp 在 [0, w-1] x [0, h-1], 绝不越界 */
PRIVATE volatile int smooth_px = 0;
PRIVATE volatile int smooth_py = 0;
PRIVATE volatile int smooth_tick = -1;   /* 上次推进平滑的 ticks */

/* 平滑参数 */
#define MOUSE_SMOOTH_SHIFT  2   /* 指数逼近: 步长 = 距离 >> 2 (即 1/4) */
#define MOUSE_SMOOTH_MIN    1   /* 最小步进 1px: 保证一定收敛, 不会"卡住" */
#define MOUSE_SMOOTH_MAX    24  /* 单步上限 24px: 抑制大幅跳变带来的"飘逸" */
#define MOUSE_DEADZONE      1   /* 死区: 距离 <= 1px 直接吸附到目标 */


/*======================================================================
  Pointer Lock (指针锁定) — 类似 FPS 游戏的鼠标独占

  锁定后:
    - PS/2 增量不再移动光标 (mouse_px/mouse_py 冻结), 系统光标被隐藏
    - 增量累加到 rel_dx/rel_dy, 由独占窗口每帧取走
      (纯相对量, 所以鼠标永远撞不到屏幕边缘, 可以无限转动视角)
    - 按键状态 / 点击边沿事件照常更新, 锁定期间仍能开枪
======================================================================*/
PRIVATE volatile int mouse_locked = 0;   /* 1 = 锁定中 */
PRIVATE volatile int rel_dx = 0;         /* 累积相对位移 X (原始计数) */
PRIVATE volatile int rel_dy = 0;         /* 累积相对位移 Y (屏幕方向, 向下为正) */

#define MOUSE_REL_MAX   30000   /* 累加上限: 防止长时间没人取导致溢出 */


/*======================================================================
  坐标限幅: 任何对外暴露的坐标都必须落在 [0, hi-1]
======================================================================*/
static inline int mouse_clamp(int v, int hi)
{
	if (v < 0)  return 0;
	if (v >= hi) return (hi > 0) ? (hi - 1) : 0;
	return v;
}

/* 当前坐标系下的屏幕尺寸 (图形模式 = 像素, 文本模式 = 字符) */
static int mouse_scr_w(void)
{
	if (g_video_mode != 0) return (g_screen_width  > 0) ? g_screen_width  : 1;
	return MOUSE_SCR_W;
}

static int mouse_scr_h(void)
{
	if (g_video_mode != 0) return (g_screen_height > 0) ? g_screen_height : 1;
	return MOUSE_SCR_H;
}

/* 字符坐标系尺寸 (文本模式 80x25; 图形模式按字体换算出的字符网格) */
static int mouse_txt_w(void)
{
	if (g_video_mode != 0) return (g_text_cols > 0) ? g_text_cols : 80;
	return MOUSE_SCR_W;
}

static int mouse_txt_h(void)
{
	if (g_video_mode != 0) return (g_text_rows > 0) ? g_text_rows : 25;
	return MOUSE_SCR_H;
}

/* 平滑一步: 朝 target 逼近, 步长自适应 + 死区 + 上限 */
static int mouse_smooth_step(int cur, int target)
{
	int d  = target - cur;
	int ad = (d >= 0) ? d : -d;
	int step;

	if (ad <= MOUSE_DEADZONE) return target;      /* 死区: 直接吸附 */

	step = ad >> MOUSE_SMOOTH_SHIFT;              /* 距离越大步长越大 */
	if (step < MOUSE_SMOOTH_MIN) step = MOUSE_SMOOTH_MIN;
	if (step > MOUSE_SMOOTH_MAX) step = MOUSE_SMOOTH_MAX;
	if (step > ad) step = ad;

	return cur + ((d > 0) ? step : -step);
}

/* 点击事件检测 (左键按下边沿) */
PRIVATE volatile int mouse_prev_btns = 0;   /* 上次按键状态 (用于边沿检测) */
PRIVATE volatile int mouse_click_event = 0;  /* 点击事件标志: 1=有新点击事件 */

/* 光标渲染状态 */
PRIVATE int  cur_old_x    = -1;          /* 上次光标位置 */
PRIVATE int  cur_old_y    = -1;
PRIVATE t_8  cur_saved_ch = 0;           /* 保存的光标处原字符 */
PRIVATE t_8  cur_saved_at = 0;           /* 保存的光标处原属性 */
PRIVATE int  cur_active   = 0;           /* 光标是否处于激活(反色)状态 */


/*======================================================================
  读写 VGA 显存 (统一封装, 便于后续图形化适配)
======================================================================*/
static inline t_8 vga_read_byte(int pos)
{
	return vm_getc(pos);
}

static inline void vga_write_word(int pos, t_8 ch, t_8 attr)
{
	vm_putc(pos, ch, attr);
}


/*======================================================================
  8042 控制器辅助函数

  8042 状态寄存器 (端口 0x64) 关键位:
    bit0: 输出缓冲区满 (0x60 有数据可读)
    bit1: 输入缓冲区满 (0x60/0x64 暂不可写)
    bit5: aux (鼠标) 输出缓冲区满 (1=鼠标数据, 0=键盘数据)
======================================================================*/

/* 等待输入缓冲区空 (可以写命令/数据到 0x60/0x64) */
static void mouse_wait_write(void)
{
	int timeout = 100000;
	while (timeout-- > 0) {
		if (!(in_byte(MOUSE_PORT_STATUS) & 0x02)) return;
	}
}

/* 等待鼠标输出缓冲区满 (bit0=1 且 bit5=1, 确保读到的是鼠标数据而非键盘数据)
   若缓冲区里是键盘数据 (bit5=0), 丢弃后继续等, 避免误读键盘字节 */
static void mouse_wait_read(void)
{
	int timeout = 100000;
	t_8 s;
	while (timeout-- > 0) {
		s = in_byte(MOUSE_PORT_STATUS);
		if (s & 0x01) {
			if (s & 0x20) return;  /* 鼠标数据, 返回 */
			/* 键盘数据, 丢弃 (init_mouse 期间键盘已禁用, 不应出现, 但防御性处理) */
			in_byte(MOUSE_PORT_DATA);
		}
	}
}

/* 发送命令到鼠标 (通过 0xD4 前缀) */
static void mouse_send(t_8 cmd)
{
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0xD4);
	mouse_wait_write();
	out_byte(MOUSE_PORT_DATA, cmd);
}

/* 读取鼠标应答 (0xFA=ACK) */
static t_8 mouse_read_ack(void)
{
	mouse_wait_read();
	return in_byte(MOUSE_PORT_DATA);
}

/* 清空 8042 输出缓冲区: 丢弃所有残留的键盘/鼠标数据, 防止 mouse_read_ack 误读键盘字节 */
static void mouse_drain_buffer(void)
{
	int timeout = 1000;
	t_8 s;
	while (timeout-- > 0) {
		s = in_byte(MOUSE_PORT_STATUS);
		if (!(s & 0x01)) return;  /* 输出缓冲区空 */
		in_byte(MOUSE_PORT_DATA); /* 丢弃一个字节 */
	}
}


/*======================================================================
  PS/2 鼠标中断处理 (IRQ 12)
  读取 3 字节数据包, 更新鼠标坐标

  数据包格式:
    Byte 0: [Y overflow][X overflow][Y sign][X sign][1][Mid][Right][Left]
    Byte 1: X delta (有符号)
    Byte 2: Y delta (有符号, 向上为正, 需取反)
======================================================================*/
PUBLIC void mouse_handler(int irq)
{
	t_8 s = in_byte(MOUSE_PORT_STATUS);
	t_8 data;

	/* 仅处理鼠标数据 (bit5=1); 若为键盘数据则丢弃, 不窃取键盘字节 */
	if (!(s & 0x20)) {
		/* 缓冲区里不是鼠标数据, 不读 (留给 keyboard_handler) */
		return;
	}
	data = in_byte(MOUSE_PORT_DATA);

	mouse_packet[mouse_cycle] = data;
	mouse_cycle++;

	if (mouse_cycle >= 3) {
		mouse_cycle = 0;

		/* 检查同步位 (bit3 必须为 1) */
		if (mouse_packet[0] & 0x08) {
			int dx, dy;

			/* ---- X 偏移: 按 PS/2 规范的 9 位补码解析 ----
			 * byte1 = 低 8 位, byte0 bit4 = 符号位.
			 * 原来只靠 (signed char) 隐式符号扩展, 等价的前提是
			 * "byte1 的 MSB 与 bit4 永远一致". 一旦真机/模拟器不满足,
			 * 负数就会被解析成正数 → 光标反向乱飘. 这里显式用符号位扩展. */
			dx = (int)mouse_packet[1];
			if (mouse_packet[0] & 0x10) dx -= 256;   /* bit4=1 → 负值 */

			/* ---- Y 偏移: byte0 bit5 是符号位 ----
			 * PS/2 的 Y 轴"向上为正", 屏幕 Y "向下为正", 故取反 */
			dy = (int)mouse_packet[2];
			if (mouse_packet[0] & 0x20) dy -= 256;   /* bit5=1 → 负值 */
			dy = -dy;

			/* 溢出位: 该轴增量不可信, 丢弃本次偏移 (bit6=X, bit7=Y) */
			if (mouse_packet[0] & 0x40) dx = 0;
			if (mouse_packet[0] & 0x80) dy = 0;

			if (mouse_locked) {
				/* ---- 锁定模式: 增量只累加, 光标不动 ----
				 * 不在这里做 MOUSE_PX_SCALE 降速: 原始计数直接交给程序,
				 * 灵敏度由程序自己按需缩放 (FPS 的标准做法) */
				if (rel_dx > -MOUSE_REL_MAX && rel_dx < MOUSE_REL_MAX) rel_dx += dx;
				if (rel_dy > -MOUSE_REL_MAX && rel_dy < MOUSE_REL_MAX) rel_dy += dy;
			} else if (g_video_mode != 0) {
				/* ---- 图形模式: 像素级坐标 ---- */
				static volatile int psub_x = 0;
				static volatile int psub_y = 0;
				int pstep_x, pstep_y;
				int sw = mouse_scr_w();
				int sh = mouse_scr_h();

				psub_x += dx;
				pstep_x = psub_x / MOUSE_PX_SCALE;
				psub_x -= pstep_x * MOUSE_PX_SCALE;

				psub_y += dy;
				pstep_y = psub_y / MOUSE_PX_SCALE;
				psub_y -= pstep_y * MOUSE_PX_SCALE;

				mouse_px += pstep_x;
				mouse_py += pstep_y;

				/* 严格限幅; 撞边界时清空亚像素余量, 避免"抵住边缘蓄力"
				   导致松手回移时突然弹一下 */
				if (mouse_px < 0)      { mouse_px = 0;      psub_x = 0; }
				if (mouse_px >= sw)    { mouse_px = sw - 1; psub_x = 0; }
				if (mouse_py < 0)      { mouse_py = 0;      psub_y = 0; }
				if (mouse_py >= sh)    { mouse_py = sh - 1; psub_y = 0; }

				/* 字符坐标只作兼容查询, 由(已限幅的)像素坐标派生 */
				mouse_x = mouse_px / (g_font_width  > 0 ? g_font_width  : 8);
				mouse_y = mouse_py / (g_font_height > 0 ? g_font_height : 16);
				mouse_x = mouse_clamp(mouse_x, (g_text_cols > 0) ? g_text_cols : 80);
				mouse_y = mouse_clamp(mouse_y, (g_text_rows > 0) ? g_text_rows : 25);
			} else {
				/* ---- 文本模式: 字符级坐标 (用 MOUSE_SCALE 降速) ---- */
				int step_x, step_y;

				sub_x += dx;
				step_x = sub_x / MOUSE_SCALE;
				sub_x -= step_x * MOUSE_SCALE;

				sub_y += dy;
				step_y = sub_y / MOUSE_SCALE;
				sub_y -= step_y * MOUSE_SCALE;

				mouse_x += step_x;
				mouse_y += step_y;

				if (mouse_x < 0)              { mouse_x = 0;              sub_x = 0; }
				if (mouse_x >= MOUSE_SCR_W)   { mouse_x = MOUSE_SCR_W - 1; sub_x = 0; }
				if (mouse_y < 0)              { mouse_y = 0;              sub_y = 0; }
				if (mouse_y >= MOUSE_SCR_H)   { mouse_y = MOUSE_SCR_H - 1; sub_y = 0; }
			}

			/* 更新按键状态 + 点击边沿检测 */
			mouse_btns = mouse_packet[0] & 0x07;
			/* 左键按下边沿 (之前未按下, 现在按下) */
			if ((mouse_btns & 0x01) && !(mouse_prev_btns & 0x01)) {
				mouse_click_event = 1;
			}
			mouse_prev_btns = mouse_btns;
		}
	}
}


/*======================================================================
  初始化 PS/2 鼠标
  1. 通过 8042 控制器启用辅助设备 (鼠标)
  2. 配置 8042 允许鼠标中断 (IRQ 12)
  3. 复位鼠标, 设置默认参数, 启用数据流模式
  4. 注册 IRQ 12 中断处理, 启用级联 IRQ 2
======================================================================*/
PUBLIC void init_mouse(void)
{
	t_8 config;
	int i;

	/* 步骤0: 清空 8042 输出缓冲区, 丢弃残留的键盘/鼠标数据
	   防止后续 mouse_read_ack 误读键盘字节导致键盘失灵 */
	mouse_drain_buffer();

	/* 步骤1: 禁用两个设备 (避免初始化期间产生干扰) */
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0xAD);  /* 禁用键盘 */
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0xA7);  /* 禁用鼠标 */

	/* 步骤2: 读取当前 8042 配置字节 */
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0x20);
	mouse_wait_read();
	config = in_byte(MOUSE_PORT_DATA);

	/* 步骤3: 修改配置: 启用鼠标中断 (bit1), 保持键盘中断 (bit0) */
	config |= 0x02;    /* 启用 aux IRQ (IRQ12) */
	config &= ~0x20;   /* 禁用 aux 时钟屏蔽 */

	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0x60);
	mouse_wait_write();
	out_byte(MOUSE_PORT_DATA, config);

	/* 步骤4: 启用鼠标辅助设备 */
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0xA8);

	/* 步骤4b: 再次清空缓冲区 (A8 可能让鼠标发字节) */
	mouse_drain_buffer();

	/* 步骤5: 复位鼠标 (0xFF), 鼠标回复 0xFA(ACK) + 0xAA(自测) + 0x00(ID) */
	mouse_send(0xFF);
	/* 复位会发 3 个字节, 用循环读取并丢弃非鼠标字节 */
	for (i = 0; i < 3; i++) {
		mouse_read_ack();
	}

	/* 步骤5b: 复位后再清一次缓冲区 */
	mouse_drain_buffer();

	/* 步骤6: 设置默认参数 */
	mouse_send(0xF6);
	mouse_read_ack();    /* 0xFA */

	/* 步骤7: 启用数据流模式 (鼠标开始发送数据包) */
	mouse_send(0xF4);
	mouse_read_ack();    /* 0xFA */

	/* 步骤8: 重新启用键盘 */
	mouse_wait_write();
	out_byte(MOUSE_PORT_CMD, 0xAE);

	/* 步骤9: 注册 IRQ 12 中断处理 */
	put_irq_handler(MOUSE_IRQ, mouse_handler);
	enable_irq(CASCADE_IRQ);  /* 解除主片 IR2 级联屏蔽 (关键!) */
	enable_irq(MOUSE_IRQ);    /* 解除从片 IR4 鼠标屏蔽 */

	/* 初始化鼠标位置到屏幕中央 (图形模式下使用动态尺寸) */
	mouse_x = (g_video_mode != 0 ? g_text_cols : MOUSE_SCR_W) / 2;
	mouse_y = (g_video_mode != 0 ? g_text_rows : MOUSE_SCR_H) / 2;
	/* 确保初始位置在有效范围内 */
	if (mouse_x < 0) mouse_x = 0;
	if (mouse_y < 0) mouse_y = 0;
	/* 图形模式: 初始化像素坐标到屏幕中央 */
	if (g_video_mode != 0) {
		mouse_px = g_screen_width / 2;
		mouse_py = g_screen_height / 2;
	}
	mouse_cycle = 0;
	mouse_btns = 0;
	mouse_prev_btns = 0;
	mouse_click_event = 0;
	sub_x = 0;
	sub_y = 0;
	smooth_px = mouse_clamp(mouse_px, mouse_scr_w());
	smooth_py = mouse_clamp(mouse_py, mouse_scr_h());
	smooth_tick = ticks;   /* 与当前节拍对齐, 避免首帧就来一次大步追赶 */
	mouse_ready = 1;
}


/*======================================================================
  mouse_update_smooth: 推进平滑鼠标位置 (时间驱动)

  ★ 原实现的问题: 每次调用就推进一步, 而 wm_run() 是 while(1) 忙循环,
    平滑的实际速度快慢取决于"这一圈循环跑得多快", 完全不可控:
    循环飞快时等于没平滑, 循环慢时又像灌了铅; 再叠加 1/8 的收缩,
    表现就是"移动有延迟 + 光标飘逸". 现在改为只在 ticks 变化时推进
    一步 (100Hz), 速度与循环频率彻底解耦.

  算法: 指数逼近 + 死区 + 最小步进
    - 步长 = 距离 >> MOUSE_SMOOTH_SHIFT (距离越远跟得越快, 手感跟手)
    - 步长至少 1px  → 保证一定收敛, 不会停在半路
    - 步长最多 24px → 抑制大跳变
    - 距离 <= 1px 直接吸附 → 消除静止时的微抖动
    - 结果全程 clamp, 分辨率切换后也不会越界
======================================================================*/
PUBLIC void mouse_update_smooth(void)
{
	int sw, sh, tx, ty;

	if (!mouse_ready) return;
	if (mouse_locked) return;   /* 锁定期间光标冻结, 不做平滑 */
	if (g_video_mode == 0) return;

	/* 与忙循环解耦: 每个时钟节拍 (10ms) 只推进一次 */
	if (smooth_tick == ticks) return;
	smooth_tick = ticks;

	sw = mouse_scr_w();
	sh = mouse_scr_h();

	/* 目标值在中断里已限幅, 这里再兜一次 (分辨率切换后旧坐标可能越界) */
	tx = mouse_clamp(mouse_px, sw);
	ty = mouse_clamp(mouse_py, sh);

	smooth_px = mouse_clamp(mouse_smooth_step(smooth_px, tx), sw);
	smooth_py = mouse_clamp(mouse_smooth_step(smooth_py, ty), sh);
}


/*======================================================================
  鼠标光标渲染
  - 文本模式: 反色字符贴图
  - 图形模式: 像素级方块光标 (gfx 模块提供)

  调用时机: TTY 主循环每次迭代时调用
  前提: 文本模式下 GS 段已设置为 Video 段选择器
======================================================================*/
PUBLIC void mouse_draw_cursor(void)
{
	if (!mouse_ready) return;
	if (mouse_locked) return;   /* 锁定期间不画系统光标 (游戏自己画准星) */

	/* 图形模式: 使用 gfx 模块的像素级鼠标光标 (用平滑坐标) */
	if (g_video_mode != 0) {
		mouse_update_smooth();
		gfx_set_mouse_pixel_cursor(smooth_px, smooth_py);
		cur_old_x = smooth_px;
		cur_old_y = smooth_py;
		cur_active = 1;
		return;
	}

	/* 文本模式: 反色字符贴图 */

	/* 如果光标位置没变, 不需要重绘 */
	if (cur_old_x == mouse_x && cur_old_y == mouse_y && cur_active) return;

	/* 擦除旧光标: 恢复保存的字符和属性 */
	if (cur_active && cur_old_x >= 0) {
		int old_pos = (cur_old_y * MOUSE_SCR_W + cur_old_x) * 2;
		vga_write_word(old_pos, cur_saved_ch, cur_saved_at);
		cur_active = 0;
	}

	/* 保存新位置的原字符和属性 */
	{
		int new_pos = (mouse_y * MOUSE_SCR_W + mouse_x) * 2;
		t_8 ch  = vga_read_byte(new_pos);
		t_8 at  = vga_read_byte(new_pos + 1);
		t_8 inv;

		cur_saved_ch = ch;
		cur_saved_at = at;

		/* 反色: 交换前景色和背景色 (高低 4 位互换) */
		inv = (t_8)(((at & 0x0F) << 4) | ((at & 0xF0) >> 4));
		vga_write_word(new_pos, ch, inv);

		cur_active = 1;
		cur_old_x = mouse_x;
		cur_old_y = mouse_y;
	}
}


/*======================================================================
  擦除鼠标光标 (恢复原字符/原像素)
  在 shell 输出或清屏前调用, 防止光标残留
======================================================================*/
PUBLIC void mouse_hide_cursor(void)
{
	/* 图形模式: 使用 gfx 模块隐藏 */
	if (g_video_mode != 0) {
		gfx_hide_mouse_cursor();
		cur_active = 0;
		return;
	}

	/* 文本模式: 恢复原字符 */
	if (cur_active && cur_old_x >= 0) {
		int old_pos = (cur_old_y * MOUSE_SCR_W + cur_old_x) * 2;
		vga_write_word(old_pos, cur_saved_ch, cur_saved_at);
		cur_active = 0;
	}
}


/*======================================================================
  PUBLIC 查询接口 (供窗口管理器等模块使用)

  - mouse_get_x / mouse_get_y: 字符坐标 (文本模式兼容)
  - mouse_get_x_px / mouse_get_y_px: 像素坐标 (图形模式)
  - mouse_get_buttons: 实时按键状态 (bit0=左, bit1=右, bit2=中)
  - mouse_get_click: 获取点击事件并清除 (1=有新点击, 0=无)
======================================================================*/
PUBLIC int mouse_get_x(void)
{
	return mouse_clamp(mouse_x, mouse_txt_w());
}

PUBLIC int mouse_get_y(void)
{
	return mouse_clamp(mouse_y, mouse_txt_h());
}

PUBLIC int mouse_get_x_px(void)
{
	return mouse_clamp(mouse_px, mouse_scr_w());
}

PUBLIC int mouse_get_y_px(void)
{
	return mouse_clamp(mouse_py, mouse_scr_h());
}

PUBLIC int mouse_get_buttons(void)
{
	return mouse_btns;
}

PUBLIC int mouse_get_click(void)
{
	int c = mouse_click_event;
	mouse_click_event = 0;   /* 读取即清除 */
	return c;
}

/*======================================================================
  Pointer Lock 控制接口 (供 wm.c 使用)
  - mouse_set_lock(1): 进入锁定; 隐藏系统光标, 清空增量
  - mouse_set_lock(0): 退出锁定; 平滑坐标对齐到当前位置, 恢复光标
  - mouse_take_rel:    取走累积的相对位移 (读取即清零), 返回 1=有数据
======================================================================*/
PUBLIC void mouse_set_lock(int on)
{
	if (on) {
		if (mouse_locked) return;
		mouse_locked = 1;
		rel_dx = 0;
		rel_dy = 0;
		/* 隐藏系统光标 (文本模式擦掉反色字符, 图形模式恢复像素) */
		mouse_hide_cursor();
		gfx_hide_mouse_cursor();
	} else {
		if (!mouse_locked) return;
		mouse_locked = 0;
		rel_dx = 0;
		rel_dy = 0;
		/* 解锁后别让平滑光标从旧位置猛地追过来 */
		smooth_px = mouse_clamp(mouse_px, mouse_scr_w());
		smooth_py = mouse_clamp(mouse_py, mouse_scr_h());
		smooth_tick = ticks;
		if (g_video_mode != 0) gfx_show_mouse_cursor();
	}
}

PUBLIC int mouse_is_locked(void)
{
	return mouse_locked;
}

/* 取走累积的相对位移 (读取即清零)
   返回 1 = 本次取到了非零增量, 0 = 没有移动 */
PUBLIC int mouse_take_rel(int *pdx, int *pdy)
{
	int has = mouse_locked && (rel_dx != 0 || rel_dy != 0);

	if (pdx) *pdx = rel_dx;
	if (pdy) *pdy = rel_dy;
	rel_dx = 0;
	rel_dy = 0;
	return has;
}

/* 获取平滑后的像素坐标 (供窗口管理器做命中测试, 与光标显示位置一致) */
PUBLIC int mouse_get_smooth_x(void)
{
	return mouse_clamp(smooth_px, mouse_scr_w());
}

PUBLIC int mouse_get_smooth_y(void)
{
	return mouse_clamp(smooth_py, mouse_scr_h());
}
