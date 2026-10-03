/*
 * noegress - refuse every non-loopback network operation, and log all of them.
 *
 * Loaded ahead of the process under test: DYLD_INSERT_LIBRARIES on macOS,
 * LD_PRELOAD on Linux. Intercepts connect(), sendto() and sendmsg(), which
 * between them cover TCP connections and UDP sends including DNS queries.
 *
 * This exists so the offline claim can be demonstrated, not just asserted.
 * The log it writes is the evidence: every network operation the process
 * attempted, and what was done about it.
 *
 * Two honest limits, stated here so nobody over-reads the result:
 *   - It intercepts libc. A statically linked binary, or one issuing raw
 *     syscalls, would bypass it. The harness is Python on system libc, so
 *     this holds for the thing being tested.
 *   - On macOS it does not apply to hardened or SIP-protected binaries. The
 *     script checks for this and says so instead of reporting a false pass.
 *
 * For a stronger guarantee on Linux, run inside a network namespace with only
 * loopback. See scripts/egress-test.sh.
 */

#define _GNU_SOURCE

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef __APPLE__
#include <dlfcn.h>
#endif

static FILE *logfile(void)
{
    static FILE *fp = NULL;
    if (fp == NULL) {
        const char *path = getenv("NOEGRESS_LOG");
        fp = path ? fopen(path, "a") : stderr;
        if (fp == NULL)
            fp = stderr;
    }
    return fp;
}

/* Returns 1 if the address is loopback, 0 if it is not, -1 if not network. */
static int classify(const struct sockaddr *addr, char *ip, size_t cap)
{
    if (addr == NULL)
        return -1;

    if (addr->sa_family == AF_INET) {
        const struct sockaddr_in *s = (const struct sockaddr_in *)addr;
        inet_ntop(AF_INET, &s->sin_addr, ip, (socklen_t)cap);
        return (ntohl(s->sin_addr.s_addr) >> 24) == 127;
    }

    if (addr->sa_family == AF_INET6) {
        const struct sockaddr_in6 *s = (const struct sockaddr_in6 *)addr;
        inet_ntop(AF_INET6, &s->sin6_addr, ip, (socklen_t)cap);
        if (IN6_IS_ADDR_LOOPBACK(&s->sin6_addr))
            return 1;
        /* ::ffff:127.0.0.1 is loopback wearing a v6 hat */
        if (IN6_IS_ADDR_V4MAPPED(&s->sin6_addr))
            return s->sin6_addr.s6_addr[12] == 127;
        return 0;
    }

    return -1; /* AF_UNIX and friends are not network egress */
}

static int permitted(const struct sockaddr *addr, const char *op)
{
    char ip[INET6_ADDRSTRLEN] = "?";
    int verdict = classify(addr, ip, sizeof(ip));

    if (verdict < 0)
        return 1; /* not a network address; nothing to police */

    fprintf(logfile(), "%s\t%s\t%s\n", op, ip,
            verdict == 1 ? "ALLOW" : "BLOCK");
    fflush(logfile());

    return verdict == 1;
}

#ifdef __APPLE__
#define REAL(fn) fn
#define WRAPPER(fn) my_##fn
#else
#define WRAPPER(fn) fn
static void *real_sym(const char *name)
{
    void *sym = dlsym(RTLD_NEXT, name);
    if (sym == NULL) {
        fprintf(logfile(), "noegress: cannot resolve %s\n", name);
        _exit(97);
    }
    return sym;
}
#endif

int WRAPPER(connect)(int fd, const struct sockaddr *addr, socklen_t len);
int WRAPPER(connect)(int fd, const struct sockaddr *addr, socklen_t len)
{
    if (!permitted(addr, "connect")) {
        errno = ENETUNREACH;
        return -1;
    }
#ifdef __APPLE__
    return connect(fd, addr, len);
#else
    static int (*real)(int, const struct sockaddr *, socklen_t);
    if (!real) real = real_sym("connect");
    return real(fd, addr, len);
#endif
}

ssize_t WRAPPER(sendto)(int fd, const void *buf, size_t n, int flags,
                        const struct sockaddr *addr, socklen_t len);
ssize_t WRAPPER(sendto)(int fd, const void *buf, size_t n, int flags,
                        const struct sockaddr *addr, socklen_t len)
{
    if (!permitted(addr, "sendto")) {
        errno = ENETUNREACH;
        return -1;
    }
#ifdef __APPLE__
    return sendto(fd, buf, n, flags, addr, len);
#else
    static ssize_t (*real)(int, const void *, size_t, int,
                           const struct sockaddr *, socklen_t);
    if (!real) real = real_sym("sendto");
    return real(fd, buf, n, flags, addr, len);
#endif
}

ssize_t WRAPPER(sendmsg)(int fd, const struct msghdr *msg, int flags);
ssize_t WRAPPER(sendmsg)(int fd, const struct msghdr *msg, int flags)
{
    if (msg && msg->msg_name &&
        !permitted((const struct sockaddr *)msg->msg_name, "sendmsg")) {
        errno = ENETUNREACH;
        return -1;
    }
#ifdef __APPLE__
    return sendmsg(fd, msg, flags);
#else
    static ssize_t (*real)(int, const struct msghdr *, int);
    if (!real) real = real_sym("sendmsg");
    return real(fd, msg, flags);
#endif
}

#ifdef __APPLE__
__attribute__((used)) static struct {
    const void *replacement;
    const void *replacee;
} noegress_interposers[] __attribute__((section("__DATA,__interpose"))) = {
    { (const void *)(unsigned long)&my_connect,
      (const void *)(unsigned long)&connect },
    { (const void *)(unsigned long)&my_sendto,
      (const void *)(unsigned long)&sendto },
    { (const void *)(unsigned long)&my_sendmsg,
      (const void *)(unsigned long)&sendmsg },
};
#endif
