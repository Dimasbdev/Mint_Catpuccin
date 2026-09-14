#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    if (argc < 3) return 1;
    const char *sock_path = argv[1];
    const char *msg = argv[2];

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return 1;

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        int err = errno;
        close(fd);
        if (err == ECONNREFUSED || err == ENOENT) {
            unlink(sock_path);
            return 2;
        }
        return 1;
    }

    size_t len = strlen(msg);
    if (write(fd, msg, len) < 0) {}
    if (write(fd, "\n", 1) < 0) {}
    close(fd);
    return 0;
}
