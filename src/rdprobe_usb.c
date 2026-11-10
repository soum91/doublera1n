/* First-party USB setup for the read-only probe. No disk or restore operations.
 * The IOKit call sequence and standardMuxOnly descriptor type were checked
 * against Pa7r0n/ICH_A12_plus_Ramdisk resources/restored_external.
 * Private APIs are resolved at runtime so missing exports produce a diagnostic
 * rather than a dyld failure before main. Physical iOS 27 validation is pending.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>

int rdprobe_init_usb(void) {
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) {
        printf("[usbprobe] IOKit load failed: %s\n", dlerror());
        return -1;
    }
    typedef CFTypeRef (*description_fn)(CFAllocatorRef, CFStringRef);
    typedef void (*serial_fn)(CFTypeRef, CFStringRef);
    typedef int (*controller_fn)(CFAllocatorRef, CFTypeRef *);
    typedef int (*configure_fn)(CFTypeRef, CFTypeRef);
    description_fn description = (description_fn)dlsym(kit, "IOUSBDeviceDescriptionCreateWithType");
    serial_fn serial = (serial_fn)dlsym(kit, "IOUSBDeviceDescriptionSetSerialString");
    controller_fn create = (controller_fn)dlsym(kit, "IOUSBDeviceControllerCreate");
    configure_fn configure = (configure_fn)dlsym(kit, "IOUSBDeviceControllerSetDescription");
    if (!description || !serial || !create || !configure) {
        puts("[usbprobe] required device-mode USB API missing; no handshake claimed");
        dlclose(kit);
        return -1;
    }
    CFTypeRef desc = description(kCFAllocatorDefault, CFSTR("standardMuxOnly"));
    if (!desc) {
        puts("[usbprobe] standardMuxOnly descriptor unavailable");
        dlclose(kit);
        return -1;
    }
    /* Fixed diagnostic name: never publish a device serial or owner name. */
    serial(desc, CFSTR("DOUBLERA1N_USB_PROBE_V2"));
    CFTypeRef controller = NULL;
    int status = -1;
    for (unsigned attempt = 0; attempt < 30; ++attempt) {
        controller = NULL;
        status = create(kCFAllocatorDefault, &controller);
        if (status == 0 && controller) break;
        printf("[usbprobe] USB controller not ready: 0x%08x (%u/30)\n", (unsigned)status, attempt + 1);
        sleep(1);
    }
    if (status == 0 && controller) {
        status = configure(controller, desc);
        printf("[usbprobe] USB standardMuxOnly configuration: 0x%08x\n", (unsigned)status);
        CFRelease(controller);
    } else {
        puts("[usbprobe] no USB controller after 30 seconds");
        status = -1;
    }
    CFRelease(desc);
    /* Keep IOKit loaded: its CF object callbacks may remain registered. */
    return status;
}
