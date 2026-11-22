/*
 * web-gate: stands in front of each of CUPS's web programs (cgi-bin).
 *
 * CUPS's web programs do what they are asked over the server's own socket,
 * so to CUPS their requests come from localhost, whoever sent the form. This
 * gate looks at who did:
 *
 * - an address in WEB_FROM: the real program runs, and may use the socket's
 *   peer credentials to administer (the policy lets "lp" do that, and only
 *   this container's socket can prove that name);
 * - anyone else who may see the pages: GET only, never admin.cgi, and without
 *   those credentials. Every operation of CUPS's web programs needs a POST.
 *
 *   web-gate --check ADDRESS[/PREFIX] ...    exit 0 if WEB_FROM is usable
 *
 * SPDX-License-Identifier: MIT
 */

#include <sys/socket.h>
#include <sys/types.h>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define REAL_DIR "/usr/lib/cups/cgi-real/"
#define WEB_FROM_FILE "/etc/cups/web-from" /* written by the entrypoint */

typedef struct {
  unsigned char bytes[16]; /* IPv4 as ::ffff:a.b.c.d */
  unsigned bits;
} network;

/* "a.b.c.d[/n]", "x::y[/n]", or CUPS's "[v1.x::y]". 0 or -1. */
static int parse_network(const char *text, network *net) {
  char buf[128];
  size_t n = strlen(text);
  if (n == 0 || n >= sizeof buf)
    return -1;
  memcpy(buf, text, n + 1);
  char *addr = buf;
  if (!strncmp(addr, "[v1.", 4) && buf[n - 1] == ']') {
    buf[n - 1] = 0;
    addr += 4;
  }
  char *slash = strchr(addr, '/');
  if (slash)
    *slash = 0;

  unsigned max, offset;
  if (inet_pton(AF_INET, addr, &net->bytes[12]) == 1) {
    memset(net->bytes, 0, 10);
    net->bytes[10] = net->bytes[11] = 0xff;
    max = 32;
    offset = 96;
  } else if (inet_pton(AF_INET6, addr, net->bytes) == 1) {
    max = 128;
    offset = 0;
  } else {
    return -1;
  }

  unsigned bits = max;
  if (slash) {
    const char *p = slash + 1;
    if (!*p || strlen(p) > 3 || strspn(p, "0123456789") != strlen(p))
      return -1;
    bits = (unsigned)strtoul(p, NULL, 10);
    if (bits == 0 || bits > max) /* 0 would be everybody */
      return -1;
  }
  net->bits = offset + bits;
  return 0;
}

static int contains(const network *net, const network *addr) {
  unsigned whole = net->bits / 8, rest = net->bits % 8;
  if (whole > sizeof net->bytes || memcmp(net->bytes, addr->bytes, whole) != 0)
    return 0;
  if (!rest)
    return 1;
  if (whole >= sizeof net->bytes)
    return 0;
  unsigned mask = (0xFFu << (8 - rest)) & 0xFFu;
  return (net->bytes[whole] & mask) == (addr->bytes[whole] & mask);
}

/* Whether the sender may administer. Anything unclear is a no. */
static int from_web(const char *remote) {
  network addr, net;
  if (!remote || parse_network(remote, &addr))
    return 0;
  FILE *f = fopen(WEB_FROM_FILE, "r");
  if (!f)
    return 0;
  char entry[128];
  int found = 0;
  while (!found && fscanf(f, "%127s", entry) == 1)
    found = parse_network(entry, &net) == 0 && contains(&net, &addr);
  fclose(f);
  return found;
}

static int refuse(void) {
  fputs("Status: 403 Forbidden\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Changes are made through the print server's web address (WEB_FROM).\n"
        "To cancel a job, use the print queue of your computer or phone.\n",
        stdout);
  return 0;
}

static int check_entries(int count, char *entries[]) {
  network net;
  for (int i = 0; i < count; i++)
    if (parse_network(entries[i], &net)) {
      fprintf(stderr, "not an IP address or network: %s\n", entries[i]);
      return 1;
    }
  return 0;
}

int main(int argc, char *argv[]) {
  if (argc >= 2 && !strcmp(argv[1], "--check") && !getenv("REQUEST_METHOD"))
    return check_entries(argc - 2, argv + 2);

  /* which program this copy stands in front of: not argv[0], which the caller chooses */
  char self[512];
  ssize_t len = readlink("/proc/self/exe", self, sizeof self - 1);
  if (len <= 0 || (size_t)len >= sizeof self - 1)
    return refuse();
  self[len] = 0;
  const char *name = strrchr(self, '/');
  name = name ? name + 1 : self;
  size_t n = strlen(name);
  if (n <= 4 || strcmp(name + n - 4, ".cgi") != 0)
    return refuse();

  if (from_web(getenv("REMOTE_ADDR"))) {
    /* libcups offers the socket's peer credentials only outside of CGI */
    if (unsetenv("GATEWAY_INTERFACE"))
      return refuse();
  } else {
    const char *method = getenv("REQUEST_METHOD");
    if (!method || strcmp(method, "GET") != 0 || !strcmp(name, "admin.cgi") || !getenv("GATEWAY_INTERFACE"))
      return refuse();
  }

  char real[640];
  int r = snprintf(real, sizeof real, "%s%s", REAL_DIR, name);
  if (r < 0 || (size_t)r >= sizeof real)
    return refuse();
  /* no arguments: CUPS's programs take none, and cupsd fills them from the query string */
  char *const args[] = {real, NULL};
  execv(real, args);
  perror("web-gate: cannot start CUPS's program");
  return 1;
}
