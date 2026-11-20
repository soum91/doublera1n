#ifndef DBNAND_BLOCK_MINIZ_H
#define DBNAND_BLOCK_MINIZ_H
/* Share exactly the same inflater layout/configuration in every translation
 * unit, including host tests. No allocation or compression APIs are built. */
#define MINIZ_NO_MALLOC
#define MINIZ_NO_STDIO
#define MINIZ_NO_TIME
#define MINIZ_NO_ARCHIVE_APIS
#define MINIZ_NO_DEFLATE_APIS
#define MINIZ_NO_ZLIB_APIS
#include "vendor/miniz/miniz.h"
#endif
