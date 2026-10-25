/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              net.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
              CatOS 网络栈 — E1000 + ARP + IPv4 + ICMP

  最小可用网络栈 (仅客户端 ping):
    - E1000 网卡驱动 (QEMU 虚拟 82540EM)
    - ARP 解析 (获取网关 MAC)
    - IPv4 发送/接收 (校验和)
    - ICMP Echo Request/Reply (ping)
  不做: TCP/UDP/DNS/DHCP/中断 (轮询模式)

  QEMU 启动参数必须加: -net nic,model=e1000 -net user
  QEMU slirp 网络默认: Guest IP=10.0.2.15, Gateway=10.0.2.2
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_NET_H_
#define _CATOS_NET_H_

#include "type.h"

/* 网络 is ready */
PUBLIC int  net_init(void);
PUBLIC int  net_is_ready(void);
PUBLIC void net_poll(void);
PUBLIC int  net_ping(t_32 ip, int count);
PUBLIC void net_get_mac(t_8 mac[6]);
PUBLIC t_32 net_get_ip(void);
PUBLIC t_32 net_get_gateway(void);

#endif /* _CATOS_NET_H_ */
