
/*======================================================================*
                    dbg_tls (仅 TLS_ERR_DEBUG 时有输出)
 *======================================================================*/
#ifdef TLS_ERR_DEBUG
PUBLIC void dbg_tls(const char *msg, int val)
{
	char buf[32];
	int  v = val;
	int  i = 0;
	int  j;
	char digits[12];

	disp_str("[TLS] ");
	disp_str((char *)msg);
	disp_str(" = ");

	if (v < 0) { disp_str("-"); v = -v; }
	if (v == 0) { disp_str("0"); }
	else {
		while (v > 0 && i < 11) { digits[i++] = (char)('0' + v % 10); v /= 10; }
		for (j = i - 1; j >= 0; j--) buf[i - 1 - j] = digits[j];
		buf[i] = 0;
		disp_str(buf);
	}
	disp_str("\n");
}
#endif
