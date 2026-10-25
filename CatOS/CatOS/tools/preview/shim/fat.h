/* tools/preview/shim/fat.h — 宿主预览用: browser.c 需要的 FAT 接口 */
#ifndef _SHIM_FAT_H_
#define _SHIM_FAT_H_

#include "type.h"

#define FAT_ATTR_READ_ONLY  0x01
#define FAT_ATTR_VOLUME_ID  0x08
#define FAT_ATTR_DIRECTORY  0x10
#define FAT_ATTR_ARCHIVE    0x20

typedef struct {
	char	name[8];
	char	ext[3];
	t_8	attr;
	t_8	reserved[10];
	t_16	time;
	t_16	date;
	t_16	start_cluster;
	t_32	file_size;
} FAT_DIR_ENTRY;

int  fat_init(void);
int  fat_read_file_in(t_32 dir_cluster, const char *name, void *buf, int bufsize);
void fat_list_dir(t_32 dir_cluster, void (*callback)(FAT_DIR_ENTRY *));

#endif