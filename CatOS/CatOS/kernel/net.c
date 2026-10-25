/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              net.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
         CatOS 网络栈 — E1000 驱动 + ARP + IPv4 + ICMP (轮询模式)

  QEMU slirp: Guest IP=10.0.2.15, Gateway=10.0.2.2
  轮询模式 (不用中断)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "net.h"
#include "protect.h"
#include "tty.h"
#include "console.h"
#include "proc.h"
#include "global.h"
#include "proto.h"

PRIVATE void net_print(const char *s)
{
	disp_str("[NET] ");
	disp_str((char *)s);
	disp_str("\n");
}

PRIVATE void net_print_val(const char *s, t_32 v)
{
	char buf[16];
	int i = 0, j;
	t_32 tmp = v;

	disp_str("[NET] ");
	disp_str((char *)s);
	disp_str(": ");
	if (tmp == 0) { disp_str("0"); }
	else {
		while (tmp > 0 && i < 15) { buf[i++] = (char)('0' + tmp % 10); tmp /= 10; }
		buf[i] = 0;
		for (j = i - 1; j >= 0; j--) disp_str((char *)&buf[j]);
	}
	disp_str("\n");
}

/* ===== E1000 寄存器 ===== */
#define E1000_REG_CTRL    0x0000
#define E1000_REG_STATUS  0x0008
#define E1000_REG_EECD    0x0010
#define E1000_REG_RCTL    0x0100
#define E1000_REG_TCTL    0x0400
#define E1000_REG_RDBAL   0x2800
#define E1000_REG_RDBAH   0x2804
#define E1000_REG_RDLEN   0x2808
#define E1000_REG_RDH     0x2810
#define E1000_REG_RDT     0x2818
#define E1000_REG_TDBAL   0x3800
#define E1000_REG_TDBAH   0x3804
#define E1000_REG_TDLEN   0x3808
#define E1000_REG_TDH     0x3810
#define E1000_REG_TDT     0x3818
#define E1000_REG_MTA     0x5200
#define E1000_REG_ICR     0x00C0

/* ===== 网络 ===== */
#define NET_ETH_TYPE_ARP    0x0806
#define NET_ETH_TYPE_IPV4   0x0800
#define NET_PROTO_ICMP      1
#define NET_ARP_REQUEST     1
#define NET_ARP_REPLY       2

/* ===== 缓冲区 (固定地址, 不占 .bss) ===== */
#define NET_TX_DESCS      8
#define NET_TX_BUF_SZ     2048
#define NET_RX_DESCS      8
#define NET_RX_BUF_SZ     2048
#define NET_TX_DESC_ADDR  0x1F0000
#define NET_TX_BUF_ADDR   0x1F0100
#define NET_RX_DESC_ADDR  0x1F5000
#define NET_RX_BUF_ADDR   0x1F5100

typedef struct {
	t_32 addr;
	t_16 length;
	t_16 cso;
	t_32 cmd;
	t_32 status;
} NET_DESC;

/* ===== PCI ===== */
#define PCI_CONFIG_ADDR   0xCF8
#define PCI_CONFIG_DATA   0xCFC

PRIVATE t_32 pci_read(t_32 bus, t_32 dev, t_32 fn, t_32 offset)
{
	t_32 addr = 0x80000000 | (bus << 16) | (dev << 11) | (fn << 8) | (offset & 0xFC);
	t_32 v;
	__asm__ __volatile__("outl %0, %w1" : : "a"(addr), "d"(PCI_CONFIG_ADDR));
	__asm__ __volatile__("inl %w1, %0" : "=a"(v) : "d"(PCI_CONFIG_DATA));
	return v;
}

/* ===== E1000 寄存器访问 ===== */
PRIVATE t_32 e1000_io_base;
PRIVATE int  e1000_use_mmio;
PRIVATE volatile t_8 *e1000_mmio_base;

PRIVATE t_32 e1000_read_reg(t_32 reg)
{
	if (e1000_use_mmio) {
		return *(volatile t_32 *)(e1000_mmio_base + reg);
	} else {
		t_32 v;
		__asm__ __volatile__("outl %0, %w1" : : "a"(reg), "d"(e1000_io_base));
		__asm__ __volatile__("inl %w1, %0" : "=a"(v) : "d"(e1000_io_base + 4));
		return v;
	}
}

PRIVATE void e1000_write_reg(t_32 reg, t_32 val)
{
	if (e1000_use_mmio) {
		*(volatile t_32 *)(e1000_mmio_base + reg) = val;
	} else {
		__asm__ __volatile__("outl %0, %w1" : : "a"(reg), "d"(e1000_io_base));
		__asm__ __volatile__("outl %0, %w1" : : "a"(val), "d"(e1000_io_base + 4));
	}
}

/* ===== 状态 ===== */
PRIVATE struct {
	int       ready;
	t_8       mac[6];
	t_32      my_ip;
	t_32      gateway_ip;
	t_8       gateway_mac[6];
	int       have_gw_mac;
	t_32      tx_tail;
	t_32      rx_tail;
	int       arp_pending;
} net;

/*======================================================================*
                          E1000 初始化
 *======================================================================*/

PRIVATE int net_find_e1000(t_32 *bar0, t_32 *bar1, t_32 *bar_type)
{
	t_32 bus, dev, fn;
	t_32 vendor, device, header;

	for (bus = 0; bus < 4; bus++) {
		for (dev = 0; dev < 32; dev++) {
			for (fn = 0; fn < 2; fn++) {
				vendor = pci_read(bus, dev, fn, 0x00) & 0xFFFF;
				if (vendor == 0xFFFF) continue;
				device = pci_read(bus, dev, fn, 0x00) >> 16;
				if (vendor == 0x8086 && device == 0x100E) {
					header = pci_read(bus, dev, fn, 0x0C) >> 16;
					if ((header & 0x7F) != 0) continue;
					*bar0 = pci_read(bus, dev, fn, 0x10);
					*bar1 = pci_read(bus, dev, fn, 0x14);
					{
						t_32 raw = *bar0;
						if (raw & 0x01) {
							*bar_type = 0;
							*bar0 = raw & 0xFFFFFFFC;
						} else {
							*bar_type = 1;
							*bar0 = raw & 0xFFFFFFF0;
						}
						*bar1 = *bar1 & 0xFFFFFFF0;
					}
					return 0;
				}
			}
		}
	}
	return -1;
}

PRIVATE void net_read_mac_from_eeprom(void)
{
	t_32 i, val;

	for (i = 0; i < 3; i++) {
		e1000_write_reg(0x0014, (i << 8) | 0x01);
		{
			int timeout = 1000;
			while (timeout-- > 0) {
				val = e1000_read_reg(0x0014);
				if (val & 0x10) break;
			}
		}
		val = e1000_read_reg(0x0014) >> 16;
		net.mac[i * 2]     = (t_8)(val & 0xFF);
		net.mac[i * 2 + 1] = (t_8)(val >> 8);
	}
}

PUBLIC int net_init(void)
{
	t_32 bar0, bar1, bar_type;
	t_32 i;
	NET_DESC *tx_desc = (NET_DESC *)NET_TX_DESC_ADDR;
	NET_DESC *rx_desc = (NET_DESC *)NET_RX_DESC_ADDR;

	if (net.ready) return 0;

	for (i = 0; i < 6; i++) net.mac[i] = 0;
	net.my_ip      = (10 << 24) | (0 << 16) | (2 << 8) | 15;
	net.gateway_ip = (10 << 24) | (0 << 16) | (2 << 8) | 2;
	net.have_gw_mac = 0;
	net.arp_pending = 0;

	net_print("Scanning PCI bus for E1000...");
	if (net_find_e1000(&bar0, &bar1, &bar_type) != 0) {
		net_print("PCI scan: E1000 NOT FOUND");
		return -1;
	}
	net_print("E1000 found on PCI bus");
	net_print_val("bar_type (0=IO,1=MMIO)", bar_type);
	net_print_val("bar0", bar0);
	e1000_use_mmio = bar_type;
	if (bar_type) {
		e1000_mmio_base = (volatile t_8 *)bar0;
	} else {
		e1000_io_base = bar0;
	}

	net_print("Reading MAC from EEPROM...");
	net_read_mac_from_eeprom();
	net_print_val("MAC[0-1]", (t_32)net.mac[0] | ((t_32)net.mac[1] << 8));
	net_print_val("MAC[2-3]", (t_32)net.mac[2] | ((t_32)net.mac[3] << 8));
	net_print_val("MAC[4-5]", (t_32)net.mac[4] | ((t_32)net.mac[5] << 8));

	net_print("Init TX ring...");
	for (i = 0; i < NET_TX_DESCS; i++) {
		tx_desc[i].addr   = NET_TX_BUF_ADDR + i * NET_TX_BUF_SZ;
		tx_desc[i].length = 0;
		tx_desc[i].cmd    = 0;
		tx_desc[i].status = 0;
		tx_desc[i].cso    = 0;
	}
	net.tx_tail = 0;
	e1000_write_reg(E1000_REG_TDBAL, NET_TX_DESC_ADDR);
	e1000_write_reg(E1000_REG_TDBAH, 0);
	e1000_write_reg(E1000_REG_TDLEN, NET_TX_DESCS * 16);
	e1000_write_reg(E1000_REG_TDH, 0);
	e1000_write_reg(E1000_REG_TDT, 0);
	e1000_write_reg(E1000_REG_TCTL, 0x1040FA3C | 0x02);

	net_print("Init RX ring...");
	for (i = 0; i < NET_RX_DESCS; i++) {
		rx_desc[i].addr   = NET_RX_BUF_ADDR + i * NET_RX_BUF_SZ;
		rx_desc[i].status = 0;
		rx_desc[i].length = 0;
	}
	net.rx_tail = 0;
	e1000_write_reg(E1000_REG_RDBAL, NET_RX_DESC_ADDR);
	e1000_write_reg(E1000_REG_RDBAH, 0);
	e1000_write_reg(E1000_REG_RDLEN, NET_RX_DESCS * 16);
	e1000_write_reg(E1000_REG_RDH, 0);
	e1000_write_reg(E1000_REG_RDT, NET_RX_DESCS);
	e1000_write_reg(E1000_REG_RCTL, 0x4000803C);

	e1000_write_reg(E1000_REG_IMS, 0);

	net.ready = 1;
	net_print("E1000 initialized OK");
	return 0;
}

PUBLIC int net_is_ready(void) { return net.ready; }
PUBLIC void net_get_mac(t_8 mac[6]) { int i; for (i = 0; i < 6; i++) mac[i] = net.mac[i]; }
PUBLIC t_32 net_get_ip(void) { return net.my_ip; }
PUBLIC t_32 net_get_gateway(void) { return net.gateway_ip; }

/*======================================================================*
                          E1000 收发
 *======================================================================*/

PRIVATE int e1000_send(const t_8 *buf, int len)
{
	NET_DESC *tx_desc = (NET_DESC *)NET_TX_DESC_ADDR;
	t_32 tail;
	t_8 *tx_buf;

	if (!net.ready || len > NET_TX_BUF_SZ) return -1;

	tail = net.tx_tail;
	tx_buf = (t_8 *)NET_TX_BUF_ADDR + tail * NET_TX_BUF_SZ;
	{
		int i;
		for (i = 0; i < len; i++) tx_buf[i] = buf[i];
	}
	tx_desc[tail].addr   = NET_TX_BUF_ADDR + tail * NET_TX_BUF_SZ;
	tx_desc[tail].length = (t_16)len;
	tx_desc[tail].cmd    = 0x1B;
	tx_desc[tail].status = 0;
	net.tx_tail = (tail + 1) % NET_TX_DESCS;
	e1000_write_reg(E1000_REG_TDT, net.tx_tail);
	{
		int timeout = 100000;
		while (timeout-- > 0) {
			if (tx_desc[tail].status & 0x0F) break;
		}
		if (timeout <= 0) return -1;
	}
	tx_desc[tail].status = 0;
	return len;
}

PRIVATE int e1000_recv(t_8 *buf, int cap)
{
	NET_DESC *rx_desc = (NET_DESC *)NET_RX_DESC_ADDR;
	t_32 tail;
	t_16 status;
	int len;
	t_8 *rx_buf;
	int i;

	if (!net.ready) return 0;

	tail = net.rx_tail;
	status = (t_16)(rx_desc[tail].status >> 0);
	if (!(status & 0x01)) return 0;

	len = rx_desc[tail].length & 0xFFFF;
	if (len <= 0 || len > NET_RX_BUF_SZ || len > cap) {
		rx_desc[tail].status = 0;
		net.rx_tail = (tail + 1) % NET_RX_DESCS;
		e1000_write_reg(E1000_REG_RDT, net.rx_tail);
		return 0;
	}

	rx_buf = (t_8 *)NET_RX_BUF_ADDR + tail * NET_RX_BUF_SZ;
	for (i = 0; i < len; i++) buf[i] = rx_buf[i];
	rx_desc[tail].status = 0;
	rx_desc[tail].length = 0;
	net.rx_tail = (tail + 1) % NET_RX_DESCS;
	e1000_write_reg(E1000_REG_RDT, net.rx_tail);
	return len;
}

/*======================================================================*
                          以太网 / ARP / ICMP
 *======================================================================*/

PRIVATE void eth_header(t_8 *buf, const t_8 *dst_mac, t_16 ethertype)
{
	int i;
	for (i = 0; i < 6; i++) buf[i] = dst_mac[i];
	for (i = 0; i < 6; i++) buf[6 + i] = net.mac[i];
	buf[12] = (t_8)(ethertype >> 8);
	buf[13] = (t_8)(ethertype & 0xFF);
}

PUBLIC void net_arp_request(t_32 target_ip)
{
	t_8 buf[42];
	t_8 broadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

	eth_header(buf, broadcast, NET_ETH_TYPE_ARP);
	buf[14] = 0x00; buf[15] = 1;
	buf[16] = 0x08; buf[17] = 0x00;
	buf[18] = 6; buf[19] = 4;
	buf[20] = 0x00; buf[21] = 1;
	buf[22] = net.mac[0]; buf[23] = net.mac[1];
	buf[24] = net.mac[2]; buf[25] = net.mac[3];
	buf[26] = net.mac[4]; buf[27] = net.mac[5];
	buf[28] = (t_8)(net.my_ip >> 24);
	buf[29] = (t_8)(net.my_ip >> 16);
	buf[30] = (t_8)(net.my_ip >> 8);
	buf[31] = (t_8)net.my_ip;
	buf[32] = buf[33] = buf[34] = buf[35] = 0;
	buf[36] = buf[37] = buf[38] = buf[39] = 0;
	buf[40] = (t_8)(target_ip >> 24);
	buf[41] = (t_8)(target_ip >> 16);
	buf[42 - 2] = (t_8)(target_ip >> 8);
	buf[43 - 2] = (t_8)target_ip;

	e1000_send(buf, 42);
	net.arp_pending = 1;
}

PRIVATE int net_arp_process(const t_8 *buf, int len)
{
	if (len < 42) return 0;
	if (buf[12] != 0x08 || buf[13] != 0x06) return 0;
	if (buf[20] != 0x00 || buf[21] != 0x02) return 0;
	{
		t_32 sender_ip = ((t_32)buf[28] << 24) | ((t_32)buf[29] << 16) |
		                 ((t_32)buf[30] << 8) | (t_32)buf[31];
		if (sender_ip != net.gateway_ip) return 0;
	}
	{
		int i;
		for (i = 0; i < 6; i++) net.gateway_mac[i] = buf[22 + i];
	}
	net.have_gw_mac = 1;
	net.arp_pending = 0;
	return 1;
}

PRIVATE t_16 ip_checksum(const t_8 *data, int len)
{
	t_32 sum = 0;
	int i;
	for (i = 0; i + 1 < len; i += 2) {
		sum += ((t_32)data[i] << 8) | data[i + 1];
	}
	if (len & 1) sum += (t_32)data[len - 1] << 8;
	while (sum >> 16) sum = (sum & 0xFFFF) + (sum >> 16);
	return (t_16)(~sum & 0xFFFF);
}

PUBLIC void net_icmp_echo_request(t_32 dest_ip, t_16 seq, const t_8 *payload, int plen)
{
	t_8 buf[98];
	int i;
	t_32 ip_total;
	t_16 ip_cksum, icmp_cksum;
	int icmp_len = 8 + plen;
	int ip_len = 20 + icmp_len;
	int frame_len = 14 + ip_len;

	if (!net.have_gw_mac) return;
	if (frame_len > (int)sizeof(buf)) return;

	eth_header(buf, net.gateway_mac, NET_ETH_TYPE_IPV4);
	buf[14] = 0x45;
	buf[15] = 0;
	buf[16] = (t_8)(ip_total >> 8);
	buf[17] = (t_8)ip_total;
	buf[18] = 0; buf[19] = 0;
	buf[20] = 0x40; buf[21] = 0;
	buf[22] = 64;
	buf[23] = NET_PROTO_ICMP;
	buf[24] = buf[25] = 0;
	buf[26] = (t_8)(net.my_ip >> 24);
	buf[27] = (t_8)(net.my_ip >> 16);
	buf[28] = (t_8)(net.my_ip >> 8);
	buf[29] = (t_8)net.my_ip;
	buf[30] = (t_8)(dest_ip >> 24);
	buf[31] = (t_8)(dest_ip >> 16);
	buf[32] = (t_8)(dest_ip >> 8);
	buf[33] = (t_8)dest_ip;
	ip_cksum = ip_checksum(&buf[14], 20);
	buf[24] = (t_8)(ip_cksum >> 8);
	buf[25] = (t_8)(ip_cksum & 0xFF);

	{
		int off = 34;
		buf[off] = 8;
		buf[off + 1] = 0;
		buf[off + 2] = buf[off + 3] = 0;
		buf[off + 4] = 0; buf[off + 5] = 0;
		buf[off + 6] = (t_8)(seq >> 8);
		buf[off + 7] = (t_8)(seq & 0xFF);
		for (i = 0; i < plen; i++) buf[off + 8 + i] = payload[i];
		icmp_cksum = ip_checksum(&buf[off], icmp_len);
		buf[off + 2] = (t_8)(icmp_cksum >> 8);
		buf[off + 3] = (t_8)(icmp_cksum & 0xFF);
	}

	e1000_send(buf, frame_len);
}

PRIVATE int net_icmp_process(const t_8 *buf, int len)
{
	if (len < 42) return 0;
	if (buf[12] != 0x08 || buf[13] != 0x00) return 0;
	if (buf[23] != 1) return 0;
	if (buf[34] != 0) return 0;
	return 1;
}

PUBLIC void net_poll(void)
{
	t_8 pkt[1600];
	int len;
	int processed = 0;

	if (!net.ready) return;

	while ((len = e1000_recv(pkt, (int)sizeof(pkt))) > 0 && processed < 4) {
		processed++;
		if (net_arp_process(pkt, len)) continue;
		if (net_icmp_process(pkt, len)) continue;
	}
}

PUBLIC int net_ping(t_32 ip, int count)
{
	int i;
	int replies = 0;
	static t_8 payload[32];

	for (i = 0; i < 32; i++) payload[i] = (t_8)('A' + (i % 26));

	net.arp_pending = 1;
	net_print("Sending ARP request...");
	net_arp_request(net.gateway_ip);

	for (i = 0; i < count * 100; i++) {
		net_poll();
		if (net.have_gw_mac) break;
	}
	net_print_val("ARP have_gw_mac", net.have_gw_mac);

	if (!net.have_gw_mac) {
		net_print("ARP retry...");
		net_arp_request(net.gateway_ip);
		for (i = 0; i < count * 1000; i++) {
			net_poll();
			if (net.have_gw_mac) break;
		}
		if (!net.have_gw_mac) {
			net_print("ARP FAILED: no gateway MAC");
			return -1;
		}
	}

	net_print("Sending ICMP Echo Request...");
	for (i = 0; i < count; i++) {
		net_icmp_echo_request(ip, (t_16)(i + 1), payload, 32);
		{
			int j;
			for (j = 0; j < 5000; j++) {
				net_poll();
			}
		}
		net_print_val("ping seq", i + 1);
		replies++;
	}

	return replies;
}
