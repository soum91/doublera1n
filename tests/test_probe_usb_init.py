"""Execute the actual C USB initializer against a simulated IOKit runtime."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class ProbeUsbInitializationTests(unittest.TestCase):
    def test_initialization_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'CoreFoundation').mkdir()
            (root / 'CoreFoundation/CoreFoundation.h').write_text('''
#include <stddef.h>
typedef const void *CFTypeRef;
typedef const void *CFAllocatorRef;
typedef const char *CFStringRef;
#define kCFAllocatorDefault NULL
#define CFSTR(s) (s)
void CFRelease(CFTypeRef);
''')
            (root / 'harness.c').write_text(r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <CoreFoundation/CoreFoundation.h>
static int scenario, creates, configured, releases;
static CFTypeRef desc(CFAllocatorRef a, CFStringRef type) {
    assert(!strcmp(type, "standardMuxOnly"));
    return scenario == 2 ? NULL : (void *)1;
}
static void serial(CFTypeRef d, CFStringRef name) {
    assert(d == (void *)1);
    assert(!strcmp(name, "DOUBLERA1N_USB_PROBE_V2"));
}
static int create(CFAllocatorRef a, CFTypeRef *out) {
    ++creates;
    if (scenario == 3 || (scenario == 5 && creates < 3)) return 7;
    *out = (void *)2;
    return 0;
}
static int configure(CFTypeRef c, CFTypeRef d) {
    assert(c == (void *)2 && d == (void *)1);
    ++configured;
    return scenario == 4 ? 9 : 0;
}
void CFRelease(CFTypeRef ref) { assert(ref); ++releases; }
void *test_dlopen(const char *path, int flags) { return (void *)3; }
int test_dlclose(void *handle) { return 0; }
char *test_dlerror(void) { return "test"; }
unsigned test_sleep(unsigned seconds) { return 0; }
void *test_dlsym(void *handle, const char *name) {
    if (scenario == 1) return NULL;
    if (!strcmp(name, "IOUSBDeviceDescriptionCreateWithType")) return desc;
    if (!strcmp(name, "IOUSBDeviceDescriptionSetSerialString")) return serial;
    if (!strcmp(name, "IOUSBDeviceControllerCreate")) return create;
    if (!strcmp(name, "IOUSBDeviceControllerSetDescription")) return configure;
    abort();
}
int rdprobe_init_usb(void);
int main(int argc, char **argv) {
    scenario = atoi(argv[1]);
    int result = rdprobe_init_usb();
    assert((result == 0) == (scenario == 0 || scenario == 5));
    assert(configured == (scenario == 0 || scenario == 4 || scenario == 5));
    if (scenario == 3) assert(creates == 30 && releases == 1);
    if (scenario == 5) assert(creates == 3 && releases == 2);
    return 0;
}
''')
            binary = root / 'usb-test'
            result = subprocess.run([
                'cc', '-I', str(root), '-Ddlopen=test_dlopen', '-Ddlsym=test_dlsym',
                '-Ddlclose=test_dlclose', '-Ddlerror=test_dlerror', '-Dsleep=test_sleep',
                str(ROOT / 'src/rdprobe_usb.c'), str(root / 'harness.c'), '-o', str(binary)
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for scenario in range(6):
                with self.subTest(scenario=scenario):
                    run = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
