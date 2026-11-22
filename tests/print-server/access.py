"""Who may do what on the print server (see compose.yaml).

    access.py clients    from an address in ALLOW_FROM, one in WEB_FROM, one in neither
    access.py host       from a process that shares the server's network

Exit status: 0 = every rule holds, 1 = one does not.
"""

from __future__ import annotations

import base64
import http.client
import http.cookies
import json
import struct
import sys
import time
import urllib.parse

CLIENT = ("172.30.61.10", "172.30.61.20")  # server, own address
PROXY = ("172.30.62.10", "172.30.62.20")
OUTSIDE = ("172.30.63.10", "172.30.63.20")
EVERYONE = ("172.30.63.11", "172.30.63.20")  # the server with ALLOW_FROM "*"
LOOPBACK = ("127.0.0.1", "127.0.0.1")
HOST_LAN = ("172.30.61.10", "127.0.0.1")  # to the LAN address, with a loopback source
HOST_OWN = ("172.30.62.10", None)
QUEUE = "/printers/HL3070CW"

TAGS = {"int": 0x21, "bool": 0x22, "name": 0x42, "keyword": 0x44, "uri": 0x45, "mime": 0x49, "text": 0x41,
        "octets": 0x30}
PRINT, CREATE, SEND, CANCEL, JOB_ATTRS, HOLD, RELEASE, RESTART, REPROCESS = 2, 5, 6, 8, 9, 12, 13, 14, 0x2C
GET_JOBS, SUBSCRIBE = 10, 0x16
PRINTER_ATTRS, PAUSE, RESUME, PURGE, SET_PRINTER, SET_JOB, CANCEL_JOBS = 11, 16, 17, 18, 19, 20, 0x38
ENABLE, DISABLE, HOLD_NEW, RELEASE_NEW, CLOSE = 0x22, 0x23, 0x25, 0x26, 0x3B
ADD_MODIFY, DELETE, ADD_CLASS, DELETE_CLASS, ACCEPT, REJECT, SET_DEFAULT = 0x4003, 0x4004, 0x4006, 0x4007, 0x4008, 0x4009, 0x400A
DEVICES, MOVE, AUTHENTICATE, GET_DOCUMENT, CREATE_LOCAL = 0x400B, 0x400D, 0x400E, 0x4027, 0x4028
SECRET = b"%!PS-Adobe-3.0\n% CONFIDENTIAL-TEST-DOCUMENT\nshowpage\n"
UNKNOWN = b"\x00\x01\x02 data in no format the driver knows \xfe\xff"
BANNER = b"#PDF-BANNER\nTemplate default.pdf\n"
HELD = [("keyword", "job-hold-until", "indefinite")]


def tiny_pdf() -> bytes:
    """A one-page PDF with a correct cross-reference table."""
    objects = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
               b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return out + b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)

failures = []


def check(ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)
        print(f"FAIL {what}", flush=True)


def connect(way) -> http.client.HTTPConnection:
    server, source = way
    return http.client.HTTPConnection(server, 631, timeout=20, source_address=(source, 0) if source else None)


def attribute(kind: str, name: str, value) -> bytes:
    if kind == "int":
        raw = struct.pack(">i", value)
    elif kind == "bool":
        raw = bytes([bool(value)])
    else:
        raw = value.encode()
    key = name.encode()
    return bytes([TAGS[kind]]) + struct.pack(">H", len(key)) + key + struct.pack(">H", len(raw)) + raw


def ipp(way, op: int, user: str | None = None, job: int | None = None, data: bytes = b"", attrs=(), job_attrs=(),
        printer_attrs=(), path: str = QUEUE, auth: str | None = None, target: str = QUEUE, subscription_attrs=()):
    """(HTTP status, IPP status, attributes, what follows them)"""
    msg = struct.pack(">BBHI", 2, 0, op, 1) + b"\x01"
    msg += b"\x47" + struct.pack(">H", 18) + b"attributes-charset" + struct.pack(">H", 5) + b"utf-8"
    msg += b"\x48" + struct.pack(">H", 27) + b"attributes-natural-language" + struct.pack(">H", 2) + b"en"
    msg += attribute("uri", "printer-uri", f"ipp://localhost{target}")
    if job is not None:
        msg += attribute("int", "job-id", job)
    if user is not None:
        msg += attribute("name", "requesting-user-name", user)
    msg += b"".join(attribute(*a) for a in attrs)
    for group, values in ((b"\x02", job_attrs), (b"\x04", printer_attrs), (b"\x06", subscription_attrs)):
        if values:
            msg += group + b"".join(attribute(*a) for a in values)
    headers = {"Content-Type": "application/ipp"}
    if "127.0.0.1" in way:
        headers["Host"] = "localhost:631"
    if auth:
        headers["Authorization"] = auth
    try:
        con = connect(way)
        con.request("POST", path, msg + b"\x03" + data, headers)
        res = con.getresponse()
        body = res.read()
    except (OSError, http.client.HTTPException):
        return 0, -1, {}, b""
    if res.status != 200 or len(body) < 9:
        return res.status, -1, {}, b""
    found, name, i = {}, "", 8
    while i < len(body):
        tag = body[i]
        i += 1
        if tag == 3:
            break
        if tag < 0x10:
            continue
        n = struct.unpack_from(">H", body, i)[0]
        name = body[i + 2:i + 2 + n].decode() or name
        i += 2 + n
        n = struct.unpack_from(">H", body, i)[0]
        raw = body[i + 2:i + 2 + n]
        i += 2 + n
        if tag in (0x21, 0x23) and n == 4:
            value = struct.unpack(">i", raw)[0]
        elif tag == 0x22:
            value = raw == b"\x01"
        else:
            value = raw.decode(errors="replace")
        found.setdefault(name, []).append(value)
    return res.status, struct.unpack_from(">H", body, 2)[0], found, body[i:]


def done(reply) -> bool:
    return reply[0] == 200 and 0 <= reply[1] < 0x100


def login_wanted(reply) -> bool:
    return reply[0] in (401, 403, 426) or (reply[0] == 200 and reply[1] in (0x0401, 0x0402, 0x0403))


def printer() -> dict:
    return ipp(CLIENT, PRINTER_ATTRS, attrs=[("keyword", "requested-attributes", "all")])[2]


def state():
    p = printer()
    return tuple(json.dumps(p.get(k)) for k in (
        "printer-is-accepting-jobs", "printer-location", "requesting-user-name-denied", "requesting-user-name-allowed"))


def paused() -> bool:
    return "paused" in printer().get("printer-state-reasons", [])


def get(way, path: str):
    try:
        con = connect(way)
        con.request("GET", path, headers={"Host": "localhost:631"} if "127.0.0.1" in way else {})
        res = con.getresponse()
        return res.status, res.read().decode(errors="replace"), res.headers
    except (OSError, http.client.HTTPException):
        return 0, "", {}


def form(way, path: str, fields: dict, multipart: bool = False):
    """A form as a browser sends it, with the session cookie the pages hand out."""
    jar = http.cookies.SimpleCookie()
    status, _, headers = get(way, QUEUE)
    if status:
        for value in headers.get_all("Set-Cookie") or []:
            jar.load(value)
    # a forged session passes CUPS's check too: it only compares cookie and field
    sid = jar["org.cups.sid"].value if "org.cups.sid" in jar else "0123456789abcdef0123456789abcdef"
    fields = {**fields, "org.cups.sid": sid}
    if multipart:
        mark = "hl3070cwboundary"
        body = "".join(f'--{mark}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                       for k, v in fields.items()) + f"--{mark}--\r\n"
        kind = f"multipart/form-data; boundary={mark}"
    else:
        body, kind = urllib.parse.urlencode(fields), "application/x-www-form-urlencoded"
    headers = {"Cookie": f"org.cups.sid={sid}", "Content-Type": kind}
    if "127.0.0.1" in way:
        headers["Host"] = "localhost:631"
    try:
        con = connect(way)
        con.request("POST", path, body.encode(), headers)
        res = con.getresponse()
        return res.status, res.read().decode(errors="replace")
    except (OSError, http.client.HTTPException):
        return 0, ""


def wait_for_server(way) -> None:
    for _ in range(120):
        reply = ipp(way, PRINTER_ATTRS)
        if done(reply) and reply[2].get("printer-is-shared", [True])[0]:
            time.sleep(3)  # the entrypoint restarts CUPS once while starting
            if done(ipp(way, PRINTER_ATTRS)):
                return
        time.sleep(1)
    sys.exit("the print server did not come up")


def new_job(way=CLIENT) -> int:
    reply = ipp(way, PRINT, user="alice", data=SECRET, attrs=[("mime", "document-format", "application/postscript")],
                job_attrs=[("keyword", "job-hold-until", "indefinite")])
    check(done(reply), f"printing from an allowed address refused: {reply[:2]}")
    return reply[2].get("job-id", [0])[0]


def failed_job(way=CLIENT) -> int:
    """A job that failed: only such a job can be restarted, and it keeps its document."""
    reply = ipp(way, PRINT, user="alice", data=b"%PDF-1.4\nnothing of a PDF\n",
                attrs=[("mime", "document-format", "application/pdf")])
    job = reply[2].get("job-id", [0])[0]
    for _ in range(80):
        if ipp(way, JOB_ATTRS, job=job)[2].get("job-state", [0])[0] >= 6:
            return job
        time.sleep(0.5)
    check(False, "the broken test job did not fail")
    return job


ADMIN = {
    "pause": (PAUSE, {}), "resume": (RESUME, {}), "enable": (ENABLE, {}), "disable": (DISABLE, {}),
    "hold new jobs": (HOLD_NEW, {}), "release new jobs": (RELEASE_NEW, {}), "cancel all": (CANCEL_JOBS, {}),
    "accept": (ACCEPT, {}), "reject": (REJECT, {}), "set default": (SET_DEFAULT, {}), "devices": (DEVICES, {}),
    "set printer": (SET_PRINTER, {"printer_attrs": [("text", "printer-location", "changed")]}),
    "modify printer": (ADD_MODIFY, {"printer_attrs": [("text", "printer-location", "changed")]}),
    "delete printer": (DELETE, {}),
    "add class": (ADD_CLASS, {"target": "/classes/extra"}),
    "delete class": (DELETE_CLASS, {"target": "/classes/extra"}),
    "create local printer": (CREATE_LOCAL, {"target": "", "attrs": [], "printer_attrs": [
        ("name", "printer-name", "extra"), ("uri", "device-uri", "ipp://127.0.0.1/ipp/print")]}),
}
OWNERS_ONLY = {
    "read the document": (GET_DOCUMENT, {"attrs": [("int", "document-number", 1)]}),
    "change the job": (SET_JOB, {"job_attrs": [("int", "job-priority", 77)]}),
    "change the PIN": (SET_JOB, {"job_attrs": [("octets", "job-password", "1111")]}),
    "move the job": (MOVE, {"job_attrs": [("uri", "job-printer-uri", f"ipp://localhost{QUEUE}")]}),
    "restart the job": (RESTART, {}),
    "reprocess the job": (REPROCESS, {}),
    "authenticate the job": (AUTHENTICATE, {}),
    "purge the jobs": (PURGE, {}),
}
FORMS = [(QUEUE, op) for op in ("stop-printer", "start-printer", "accept-jobs", "reject-jobs", "cancel-jobs",
                                "purge-jobs", "print-test-page", "move-jobs", "set-as-default")]
FORMS += [("/jobs", op) for op in ("cancel-job", "hold-job", "release-job", "restart-job", "move-job")]
FORMS += [("/classes/HL3070CW", op) for op in ("stop-class", "start-class", "accept-jobs", "reject-jobs")]
FORMS += [("/admin", op) for op in ("set-allowed-users", "set-as-default", "delete-printer", "config-server",
                                    "add-printer", "modify-printer")]


def no_admin(way, label: str) -> None:
    for name, (op, extra) in ADMIN.items():
        for user in (None, "root", "lp"):
            reply = ipp(way, op, user=user, **extra)
            # cupsd turns some away as a bad request before it asks for a login
            check(not done(reply), f"{label} as {user}: {name} went through")
    for login in ("root:", "root:root", "lp:", "lp:lp"):
        auth = "Basic " + base64.b64encode(login.encode()).decode()
        check(not done(ipp(way, PAUSE, auth=auth)), f"{label}: paused with the login {login!r}")
    for auth in ("PeerCred lp", "PeerCred root", "Local 0123456789abcdef0123456789abcdef"):
        check(not done(ipp(way, PAUSE, auth=auth)), f"{label}: paused with a forged {auth.split()[0]} login")


def no_owner_tricks(way, label: str, job: int, failed: int) -> None:
    for name, (op, extra) in OWNERS_ONLY.items():
        for user in (None, "mallory", "alice", "root", "lp"):
            target = failed if op in (RESTART, REPROCESS) else None if op == PURGE else job
            reply = ipp(way, op, user=user, job=target, **extra)
            check(login_wanted(reply) or reply[:2] == (200, 0x0501),
                  f"{label} as {user}: could {name} without a login ({reply[0]}, {reply[1]:#06x})")
            check(SECRET not in reply[3], f"{label} as {user}: got another user's document")


def no_forms(way, label: str, job: int) -> None:
    for path, op in FORMS:
        for multipart in (False, True):
            status, _ = form(way, path, {"OP": op, "JOB_ID": job, "PRINTER_NAME": "HL3070CW",
                                         "users": "mallory", "type": "requesting-user-name-denied"}, multipart)
            check(status in (0, 400, 401, 403, 404, 405, 426), f"{label}: the form {path} {op} was taken ({status})")
            check(not paused(), f"{label}: the form {path} {op} paused the printer")


def only_pages(way, label: str) -> None:
    """What reaches the printer is what the driver made of a page: no raw jobs, no banner documents."""
    for kind in (None, "application/octet-stream", "application/vnd.cups-raw"):
        attrs = [("mime", "document-format", kind)] if kind else []
        reply = ipp(way, PRINT, user="alice", data=UNKNOWN, attrs=attrs, job_attrs=HELD)
        check(not done(reply), f"{label}: a job in no known format was taken (document-format {kind or 'not given'})")
    for kind in (None, "application/vnd.cups-pdf-banner"):
        attrs = [("mime", "document-format", kind)] if kind else []
        reply = ipp(way, PRINT, user="alice", data=BANNER, attrs=attrs, job_attrs=HELD)
        check(not done(reply), f"{label}: a banner page was taken as a document ({kind or 'format not given'})")
    for attrs in ([("mime", "document-format", "application/pdf")], []):
        reply = ipp(way, PRINT, user="alice", data=tiny_pdf(), attrs=attrs, job_attrs=HELD)
        check(done(reply), f"{label}: a PDF was refused ({'format not given' if not attrs else 'application/pdf'})")


def notifications(way, label: str) -> None:
    """Clients fetch their notifications; the server sends none to an address a client names."""
    events = ("keyword", "notify-events", "printer-state-changed")
    for uri in ("rss:/hl3070cw-access-test", "mailto:nobody@example.invalid", "dbus:/"):
        reply = ipp(way, SUBSCRIBE, user="alice", subscription_attrs=[("uri", "notify-recipient-uri", uri), events])
        check(not done(reply), f"{label}: the server took a notification to {uri}")
    reply = ipp(way, SUBSCRIBE, user="alice", subscription_attrs=[("keyword", "notify-pull-method", "ippget"), events])
    check(done(reply), f"{label}: notifications that clients fetch were refused ({reply[0]}, {reply[1]:#06x})")


def job_count() -> int:
    reply = ipp(CLIENT, GET_JOBS, attrs=[("keyword", "which-jobs", "all"), ("keyword", "requested-attributes", "job-id")])
    return len(reply[2].get("job-id", []))


def clients() -> None:
    wait_for_server(CLIENT)
    only_pages(CLIENT, "client")
    notifications(CLIENT, "client")
    print("OK   clients: only pages through the driver, no banner pages, no notifications sent elsewhere")
    before = state()
    job = new_job()
    failed = failed_job()

    no_admin(CLIENT, "client")
    no_owner_tricks(CLIENT, "client", job, failed)
    no_owner_tricks(PROXY, "proxy over IPP", job, failed)
    no_admin(PROXY, "proxy over IPP")
    no_forms(CLIENT, "client", job)
    check(state() == before and not paused(), f"a client changed the printer: {before} -> {state()}")
    kept = ipp(CLIENT, JOB_ATTRS, job=job)[2].get("job-state")
    check(kept == [4], f"a client's forms changed another user's job: state {kept}")
    print("OK   clients: no administration, no forms, no other user's document or job")

    for path in ("/", QUEUE, "/jobs", "/jobs?which_jobs=all", "/cups.css"):
        check(get(CLIENT, path)[0] == 200, f"client: the status page {path} does not show")
    for path in ("/admin", "/admin/", "/admin/log/error_log", "/admin/conf/cupsd.conf"):
        check(get(CLIENT, path)[0] in (401, 403), f"client: {path} shows")
    reply = ipp(CLIENT, CREATE, user="alice", job_attrs=[("keyword", "job-hold-until", "indefinite")])
    check(done(reply), "client: Create-Job refused")
    second = reply[2].get("job-id", [0])[0]
    check(done(ipp(CLIENT, SEND, user="alice", job=second, data=SECRET,
                   attrs=[("mime", "document-format", "application/postscript"), ("bool", "last-document", True)])),
          "client: Send-Document refused (AirPrint prints with it)")
    check(done(ipp(CLIENT, RELEASE, user="alice", job=second)), "client: releasing the own job refused")
    check(done(ipp(CLIENT, HOLD, user="alice", job=second)), "client: holding the own job refused")
    check(done(ipp(CLIENT, CANCEL, user="someone", job=second)), "client: cancelling a job refused")
    print("OK   clients: print, hold, release, cancel, read the status pages")

    for op, test in (("stop-printer", paused), ("start-printer", lambda: not paused()),
                     ("reject-jobs", lambda: printer().get("printer-is-accepting-jobs") == [False]),
                     ("accept-jobs", lambda: printer().get("printer-is-accepting-jobs") == [True])):
        status, _ = form(PROXY, QUEUE, {"OP": op})
        check(status == 200 and test(), f"proxy: the web interface cannot {op} ({status})")
    # without IS_CLASS: even empty, it makes CUPS look for a class
    status, _ = form(PROXY, "/admin", {"OP": "set-allowed-users", "PRINTER_NAME": "HL3070CW",
                                       "users": "nobody-here", "type": "requesting-user-name-denied"}, True)
    check(status == 200 and "nobody-here" in json.dumps(printer().get("requesting-user-name-denied")),
          f"proxy: the Administration page cannot change the printer ({status})")
    # and back: a list of who may not print keeps others out too
    status, _ = form(PROXY, "/admin", {"OP": "set-allowed-users", "PRINTER_NAME": "HL3070CW",
                                       "users": "all", "type": "requesting-user-name-allowed"}, True)
    check(status == 200 and "nobody-here" not in json.dumps(printer().get("requesting-user-name-denied")),
          f"proxy: the Administration page cannot change it back ({status})")
    check(get(PROXY, "/admin")[0] == 200, "proxy: no Administration page")
    before_test_page = job_count()
    status, _ = form(PROXY, QUEUE, {"OP": "print-test-page"})
    check(status == 200 and job_count() == before_test_page + 1, f"proxy: Print Test Page made no job ({status})")
    status, _ = form(PROXY, "/jobs", {"OP": "cancel-job", "JOB_ID": job})
    check(status == 200 and ipp(CLIENT, JOB_ATTRS, job=job)[2].get("job-state") == [7], "proxy: cannot cancel a job")
    job = new_job()
    form(PROXY, QUEUE, {"OP": "cancel-jobs"})
    check(ipp(CLIENT, JOB_ATTRS, job=job)[2].get("job-state") == [7], "proxy: cannot cancel all jobs")
    print("OK   WEB_FROM: administers through the web interface")

    for path in ("/", QUEUE, "/jobs", "/admin"):
        check(get(OUTSIDE, path)[0] in (0, 403), f"outside: {path} shows")
    check(not done(ipp(OUTSIDE, PRINTER_ATTRS)), "outside: reads the printer")
    check(not done(ipp(OUTSIDE, PRINT, data=SECRET)), "outside: prints")
    print("OK   everyone else: nothing")

    wait_for_server(EVERYONE)
    check(done(ipp(EVERYONE, PRINT, data=SECRET, attrs=[("mime", "document-format", "application/postscript")])),
          "ALLOW_FROM=*: printing refused")
    no_admin(EVERYONE, "ALLOW_FROM=*")
    print("OK   ALLOW_FROM=*: everyone prints, nobody administers")


def host() -> None:
    wait_for_server(LOOPBACK)
    reply = ipp(LOOPBACK, PRINT, user="alice", data=SECRET,
                attrs=[("mime", "document-format", "application/postscript")],
                job_attrs=[("keyword", "job-hold-until", "indefinite")])
    job = reply[2].get("job-id", [0])[0]
    check(job > 0, "host: no test job")
    failed = failed_job(LOOPBACK)
    for way, label in ((LOOPBACK, "host, loopback"), (HOST_LAN, "host, loopback source"), (HOST_OWN, "host, own address")):
        no_admin(way, label)
        no_owner_tricks(way, label, job, failed)
    for way, label in ((LOOPBACK, "host, loopback"), (HOST_LAN, "host, loopback source")):
        for path, op in FORMS:
            status, _ = form(way, path, {"OP": op, "JOB_ID": job, "PRINTER_NAME": "HL3070CW"}, path == "/admin")
            check(status in (0, 400, 401, 403, 404, 405, 426), f"{label}: the form {path} {op} was taken ({status})")
    print("OK   host: no administration, no forms, no other user's document or job")


def main() -> int:
    roles = {"clients": clients, "host": host}
    if len(sys.argv) != 2 or sys.argv[1] not in roles:
        print(__doc__, file=sys.stderr)
        return 2
    roles[sys.argv[1]]()
    if failures:
        print(f"\n{len(failures)} rules broken")
        return 1
    print("All access rules hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
