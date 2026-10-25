/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              ec.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                    CatOS 内核 P-256 椭圆曲线 (ECDHE 用)

  范围:
    - 素数域 F_p 运算 (p = 2^256 - 2^224 + 2^192 + 2^96 - 1)
    - P-256 点运算 (仿射进出, 内部雅可比), 标量乘 (双倍-加法)
    - ECDH: 给定私钥标量与对端公钥, 输出共享点的 x 坐标
  实现要点:
    - 32 位 limb; 乘法用 Montgomery (CIOS), n0' 与 R/R^2 都在初始化时算出来,
      不手抄任何魔数 (只有曲线参数 p/b/G 是标准常量)
    - 无 64 位除法; 32x32 用 mull
    - 所有入口检查"点是否在曲线上", 拒绝无效点
  未做: 常数时间实现 (内核演示用, 侧信道不在本阶段范围)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_EC_H_
#define _CATOS_EC_H_

#include "type.h"

#define EC_FE_LIMBS   8          /* 256 bit */

typedef struct {
	t_32 v[EC_FE_LIMBS];         /* 小端 32 位 limb */
} EC_FE;

typedef struct {
	EC_FE x, y;
	int   inf;                   /* 1 = 无穷远点 */
} EC_POINT;

/* 初始化 (幂等); 返回 0=成功 */
PUBLIC int ec_p256_init(void);

PUBLIC int ec_fe_from_bytes(EC_FE *r, const t_8 *be, int len);
PUBLIC int ec_fe_to_bytes(const EC_FE *a, t_8 *be, int len);
PUBLIC int ec_fe_is_zero(const EC_FE *a);
PUBLIC int ec_fe_cmp(const EC_FE *a, const EC_FE *b);
PUBLIC int ec_fe_add(EC_FE *r, const EC_FE *a, const EC_FE *b);
PUBLIC int ec_fe_sub(EC_FE *r, const EC_FE *a, const EC_FE *b);
PUBLIC int ec_fe_mul(EC_FE *r, const EC_FE *a, const EC_FE *b);
PUBLIC int ec_fe_sqr(EC_FE *r, const EC_FE *a);
PUBLIC int ec_fe_inv(EC_FE *r, const EC_FE *a);
PUBLIC int ec_fe_add_small(EC_FE *r, const EC_FE *a, t_32 c);   /* r = a + c */

PUBLIC int ec_p256_generator(EC_POINT *g);
PUBLIC int ec_point_on_curve(const EC_POINT *p);
PUBLIC int ec_point_add(EC_POINT *r, const EC_POINT *a, const EC_POINT *b);
PUBLIC int ec_point_mul(EC_POINT *r, const EC_FE *k, const EC_POINT *p);

/* ECDH: out = (priv * peer).x ; 返回 0=成功 */
PUBLIC int ec_ecdh(const t_8 priv[32], const EC_POINT *peer, t_8 out_x[32]);

#endif /* _CATOS_EC_H_ */
