# Print server in Docker

Run the HL-3070CW as a network printer for the computers and phones in the house: CUPS with this
project's driver in a container, for example on a Raspberry Pi. Macs, iPhones and other clients of
AirPrint or IPP Everywhere print without installing a driver. It has been used from Macs and an
iPhone. Windows has not been tested.

The print server supports only the HL-3070CW. The driver itself also supports the
HL-3040CN, HL-3045CN, HL-3075CW, DCP-9010CN, MFC-9010CN,
MFC-9120CN, MFC-9125CN, MFC-9320CW and MFC-9325CW, untested. For those, install it on
the computer instead, as in [the main guide](../README.md#supported-printers).

Secure Print works with the native driver: **Print with PIN** in a Mac's print dialog reaches the
printer.

The image is built from Debian and this project's code and holds no file of Brother's. The data
files come from Brother's Linux driver package, which you download yourself. The container unpacks
it at every start and never runs Brother's program.

It is built on Debian testing (forky), which carries the current CUPS 2.4 release with its security
fixes. Debian stable stays on CUPS 2.4.10, with more known security problems open. To build on
stable anyway, add `--build-arg DEBIAN=trixie-slim` to `docker compose build`.

**Versions 0.5.0 and 0.5.1 of the print server, and builds from before them, have security flaws in
who may do what. Use 0.5.2 or newer.**

## What you need

- Docker with Compose on a Linux machine that is always on (tested on a Raspberry Pi with
  Raspberry Pi OS 13, 64-bit).
- For the native driver, Brother's Linux driver for the HL-3070CW: on Brother's
  [download page](https://support.brother.com/g/b/downloadtop.aspx?c=us&lang=en&prod=hl3070cw_all)
  choose **Linux**, then the **LPR printer driver** (rpm or deb). Put it in a folder of its own,
  for example `print-server/brother/`, and keep a copy in your backups: the container needs it at
  every start. For an rpm other than `hl3070cwlpr-1.1.2-1.i386.rpm` the log shows a warning.
- For AirPrint, Avahi on the host, to announce the printer (Raspberry Pi OS has it).

## Compose

```yaml
services:
  print-server:
    build:
      context: https://github.com/rolandzeiner/brother-hl3070cw-driver.git#v0.5.2   # a release tag, or a commit
      dockerfile: docker/Dockerfile
      network: host                 # only if a firewall blocks traffic from Docker networks
    image: hl3070cw-print-server:local
    container_name: print-server
    restart: unless-stopped
    network_mode: host
    init: true
    read_only: true
    tmpfs: [/etc/cups, /run, /tmp, /var/spool/cups, /var/cache/cups, /var/log/cups, /usr/share/hl3070cw-native]
    cap_drop: [ALL]
    cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID, KILL, NET_BIND_SERVICE]
    security_opt: [no-new-privileges=true]
    volumes:
      - ./print-server/brother:/brother:ro
    environment:
      - PRINTER_URI=socket://192.0.2.10:9100      # the printer's IP address
      - LISTEN=192.0.2.3:631                      # this machine's address
      - ALLOW_FROM=192.0.2.0/24                   # who may print
```

| Setting | Meaning | Default |
|---|---|---|
| `PRINTER_URI` | The printer: `socket://IP:9100` | required |
| `PRINTER_NAME` | Queue name | `HL3070CW` |
| `PRINTER_INFO` | Name the clients show | `Brother HL-3070CW` |
| `PRINTER_LOCATION` | Where the printer stands | empty |
| `PRINTER_DRIVER` | `native`, or `postscript`: the printer renders the pages itself, without Brother's package, Fine quality, Toner Save from clients and Secure Print | `native` |
| `PRINTER_OPTIONS` | Default options, for example `BREnhanceBlkPrt=ON`. A client's choice of colour or quality replaces the defaults for both, so don't use it for `BRMonoColor` or `BRResolution` | none |
| `PRINTER_COLOR` | `no` while a colour toner is empty: clients see a black-and-white printer, and whatever they choose there prints in Mono. A job that names the driver's own option (`lp -o BRMonoColor=FullColor`) still prints in colour | `yes` |
| `LISTEN` | Address and port CUPS listens on | `*:631` |
| `ALLOW_FROM` | Who may print: addresses or networks, separated by spaces, or `*` for everyone (from 0.5.2). `@LOCAL` is every network the machine is in, Docker's included | `@LOCAL` |
| `PRINTER_UUID` | The printer's UUID. Set it if you run two print servers with the same name and the default `LISTEN`: they would get the same one | derived from the name and `LISTEN` |
| `WEB_FROM` | IP addresses or networks (like `192.0.2.0/24`, no names) that may use the web interface's administration without a CUPS login, for example a reverse proxy that does the login | no web interface |
| `LOG_LEVEL` | `warn`, `info` or `debug`. At `debug` the log shows each job's settings, Secure Print PIN included | `warn` |

Then `docker compose up -d print-server`. When it is up, the log (`docker logs print-server`) says
`Printer HL3070CW ready (UUID …)`.

The container is set up from these settings at every start and keeps everything else in memory:

- Changes made in the web interface last until the next restart.
- A restart loses the jobs that are still waiting.
- A finished job stays listed for a day, without its document: iPhones send a job again when it
  disappears from the list right after printing.
- A failed job keeps its document until it is cancelled or the container restarts. Send it again
  from the computer or phone.
- If the printer is off, jobs wait. CUPS cancels the one it is trying to send after three hours.

## Who may do what

| | `ALLOW_FROM` | `WEB_FROM`, in the web interface | Everyone else |
|---|---|---|---|
| Print | Yes | Yes | No |
| See the printer and the list of jobs | Yes | Yes | No |
| Cancel any job, like the printer's Cancel button | Yes, from the print queue | Yes | No |
| Pause the printer, refuse jobs, change the printer | No | Yes | No |
| Read a waiting document, change a job or its PIN | No | No | No |

Put only networks you trust into `ALLOW_FROM`:

- CUPS does not check the user name a client gives. A client can hold or release a job under
  somebody else's name.
- Who may print may also send data straight to the printer, as anyone who can reach its port 9100
  can.
- The server answers to any host name, so a web page opened on an allowed computer may be able to
  print or cancel jobs.
- Nothing is encrypted between client, server and printer, the Secure Print PIN included. The job's
  record keeps the PIN in the container's memory, readable only by root, and CUPS does not return it
  to clients.
- With `network_mode: host`, programs on the server's machine count as allowed to print and cancel.
  They can't administer. Whoever controls that machine or its Docker can do everything and can see
  a PIN while the job prints.

## Web interface behind a reverse proxy

To pause the printer, cancel jobs or change settings in a browser, put a reverse proxy with a login
in front of CUPS (for example Traefik with Authelia) and set `WEB_FROM` to the address the proxy
connects from. Forms from that address need no CUPS login, so:

- The proxy must not let anyone through without logging in.
- Name just the proxy's address. A network admits everything in it.
- Don't use `127.0.0.1` or the machine's own address with `network_mode: host`: every program on the
  machine could then administer.

Administration works in the web interface only. `lpadmin` and other IPP clients get none, also from
`WEB_FROM`. With `WEB_FROM` set, clients in `ALLOW_FROM` can read the status pages, and the buttons
on them answer "Forbidden". Without `WEB_FROM` there is no web interface and no administration from
the network.

The image gives the web interface a look of its own (`docker/web/`) in the languages CUPS ships,
with a start page in English and German, light and dark mode and a layout that works on a phone. The
server settings on the Administration page are hidden, and CUPS refuses to save them: the container
writes its configuration itself.

## Announce it for AirPrint

The container has no Avahi of its own: giving a container the host's D-Bus would let it control the
host. Instead, the host's Avahi announces the printer from a service file. Copy the example below to
`/etc/avahi/services/airprint-hl3070cw.service` and fill in the UUID from the container's log. Avahi
picks it up by itself. `rp=` is `printers/` and the queue name.

```xml
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>Brother HL-3070CW</name>
  <service>
    <type>_ipp._tcp</type>
    <subtype>_universal._sub._ipp._tcp</subtype>
    <port>631</port>
    <txt-record>txtvers=1</txt-record>
    <txt-record>qtotal=1</txt-record>
    <txt-record>rp=printers/HL3070CW</txt-record>
    <txt-record>ty=Brother HL-3070CW</txt-record>
    <txt-record>product=(Brother HL-3070CW)</txt-record>
    <txt-record>pdl=application/octet-stream,application/pdf,application/postscript,image/jpeg,image/png,image/pwg-raster,image/urf</txt-record>
    <txt-record>URF=V1.4,CP1,W8,PQ3-4-5,SRGB24,RS600,FN3</txt-record>
    <txt-record>UUID=PUT-THE-UUID-FROM-THE-LOG-HERE</txt-record>
    <txt-record>air=none</txt-record>
    <txt-record>Color=T</txt-record>
    <txt-record>Duplex=F</txt-record>
    <txt-record>Copies=T</txt-record>
    <txt-record>Transparent=T</txt-record>
    <txt-record>Binary=T</txt-record>
    <txt-record>kind=document,envelope,label,postcard</txt-record>
    <txt-record>PaperMax=legal-A4</txt-record>
  </service>
</service-group>
```

`URF` and `Color` have to say what the server says. The example is for the native driver with
colour. For the other settings:

| Settings | `URF` | `Color` |
|---|---|---|
| native | `V1.4,CP1,W8,PQ3-4-5,SRGB24,RS600,FN3` | `T` |
| native, `PRINTER_COLOR=no` | `V1.4,CP1,W8,PQ3-4-5,RS600,FN3` | `F` |
| postscript | `V1.4,CP1,W8,PQ4,SRGB24,RS300,FN3` | `T` |
| postscript, `PRINTER_COLOR=no` | `V1.4,CP1,W8,PQ4,RS300,FN3` | `F` |

Clients remember what a printer can do: after a change, remove the printer there and add it again.

If your clients are in another network than the print server, the router has to pass mDNS between
the networks (on UniFi: the mDNS setting of the networks).

## Firewall

The print server needs to reach the printer on port 9100 (and 161/udp for its status), and your
clients need to reach the print server on port 631. With UFW and outgoing traffic denied by default:

```sh
sudo ufw allow out to 192.0.2.10 port 9100 proto tcp
sudo ufw allow out to 192.0.2.10 port 161 proto udp
sudo ufw allow in from 192.0.2.0/24 to any port 631 proto tcp
```

## What clients can choose

AirPrint and IPP Everywhere pass on the standard options: colour or black and white, quality, the
paper sizes of the driver, copies and, from clients that offer it, the Secure Print PIN. With the
native driver the print server turns colour and quality into the driver's options:

| | Black and white | Colour |
|---|---|---|
| Draft | Mono, Toner Save | Auto, Toner Save |
| Normal | Mono | Auto |
| Best | Mono, Fine quality | Auto, Fine quality |

Colour means Brother's Auto: the printer decides per page. A job that chooses neither prints with
the defaults. With `PRINTER_COLOR=no` every row prints in Mono. Enhance Black Printing has no
standard equivalent; set it for everyone with `PRINTER_OPTIONS=BREnhanceBlkPrt=ON` (it applies to
colour jobs).

With the PostScript driver there is only colour or black and white: no quality and no PIN.

## Update

For a new version, change the commit or tag in `build.context`. For the security fixes of Debian
and CUPS, rebuild now and then also without a new version: they arrive only with a build that
fetches them.

```sh
docker compose build --pull --no-cache print-server
docker compose up -d print-server
```
