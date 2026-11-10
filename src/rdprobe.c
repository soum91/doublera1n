/*
 * Doublera1n read-only restore-ramdisk USB transport probe.
 *
 * This is deliberately NOT rdsetup. It does not open or mount disks, create
 * APFS volumes, read tickets, or launch any child process. Its only purpose
 * is to determine whether a Mac can reach a TCP listener inside the restore
 * ramdisk via usbmuxd/iproxy, so a future no-UART installer has a transport.
 */
#include <errno.h>
#include <netinet/in.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/sockio.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define PROBE_PORT 27047
#define PROBE_RUNTIME_SECONDS (15 * 60)

static const char banner[] =
    "DOUBLERA1N_USB_PROBE_V2\n"
    "read_only=yes\n"
    "apfs_writes=no\n"
    "ticket_access=no\n";

extern int rdprobe_init_usb(void);

static int init_loopback(void) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct ifreq flags = {0};
    strlcpy(flags.ifr_name, "lo0", sizeof(flags.ifr_name));
    if (ioctl(fd, SIOCGIFFLAGS, &flags) < 0) { close(fd); return -1; }
    flags.ifr_flags |= IFF_UP;
    if (ioctl(fd, SIOCSIFFLAGS, &flags) < 0) { close(fd); return -1; }
    struct ifaliasreq address = {0};
    strlcpy(address.ifra_name, "lo0", sizeof(address.ifra_name));
    struct sockaddr_in *ip = (struct sockaddr_in *)&address.ifra_addr;
    struct sockaddr_in *mask = (struct sockaddr_in *)&address.ifra_mask;
    ip->sin_len = mask->sin_len = sizeof(*ip);
    ip->sin_family = mask->sin_family = AF_INET;
    ip->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    mask->sin_addr.s_addr = htonl(0xff000000);
    int status = ioctl(fd, SIOCAIFADDR, &address);
    int saved_errno = errno;
    close(fd);
    return status == 0 || saved_errno == EEXIST ? 0 : -1;
}

int main(void) {
    setbuf(stdout, NULL);
    signal(SIGPIPE, SIG_IGN);
    puts("[usbprobe] V2 read-only transport test; NO APFS operations");
    if (init_loopback() != 0) {
        puts("[usbprobe] loopback configuration failed; no handshake claimed");
        goto idle;
    }
    if (rdprobe_init_usb() != 0) {
        puts("[usbprobe] USB initialization failed; no handshake claimed");
        goto idle;
    }

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { printf("[usbprobe] socket failed: %s\n", strerror(errno)); goto idle; }
    int reuse = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET;
    address.sin_port = htons(PROBE_PORT);
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0 || listen(fd, 1) != 0) {
        printf("[usbprobe] bind/listen failed: %s\n", strerror(errno));
        close(fd);
        goto idle;
    }
    printf("[usbprobe] listening on TCP %d for up to 15 minutes\n", PROBE_PORT);
    time_t end = time(NULL) + PROBE_RUNTIME_SECONDS;
    while (time(NULL) < end) {
        struct timeval tv = {.tv_sec = 2, .tv_usec = 0};
        fd_set ready;
        FD_ZERO(&ready);
        FD_SET(fd, &ready);
        int n = select(fd + 1, &ready, NULL, NULL, &tv);
        if (n <= 0) continue;
        int c = accept(fd, NULL, NULL);
        if (c < 0) continue;
        ssize_t sent = send(c, banner, sizeof(banner) - 1, 0);
        printf("[usbprobe] connection: banner sent=%zd\n", sent);
        close(c);
    }
    close(fd);
idle:
    puts("[usbprobe] stopped; force-reboot the phone to return to stock iOS");
    for (;;) sleep(3600);
}
