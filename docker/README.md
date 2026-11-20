# Print server in Docker

Run the HL-3070CW as a network printer for every computer and phone in the house: CUPS with the
native driver in a container, for example on a Raspberry Pi. Macs, iPhones, iPads and Windows find
it over AirPrint or IPP Everywhere and print without installing any driver. Secure Print works too:
the print dialog's **Print with PIN** reaches the printer.

The image contains only this project's code. Brother's data files come from Brother's Linux driver
package, which you download yourself; the container unpacks it at every start and never runs
Brother's program.

## What you need

- Docker with Compose on a Linux machine that is always on (tested on a Raspberry Pi with
  Raspberry Pi OS 13, 64-bit).
- Brother's Linux driver for the HL-3070CW: on Brother's
  [download page](https://support.brother.com/g/b/downloadtop.aspx?c=us&lang=en&prod=hl3070cw_all)
  choose **Linux**, then the **LPR printer driver** (rpm or deb). Put it in a folder of its own,
  for example `print-server/brother/`. Keep a copy in your backups: it is the only source of the
  halftone patterns and colour tables.
- Avahi on the host, to announce the printer (Raspberry Pi OS has it).

## Compose

```yaml
services:
  print-server:
    build:
      context: https://github.com/rolandzeiner/brother-hl3070cw-driver.git#<release tag or commit>
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
      - PRINTER_OPTIONS=BRMonoColor=Auto
      - LISTEN=192.0.2.3:631                      # this machine's address
      - ALLOW_FROM=192.0.2.0/24                    # who may print
```

| Setting | Meaning | Default |
|---|---|---|
| `PRINTER_URI` | The printer: `socket://IP:9100` | required |
| `PRINTER_NAME` | Queue name | `HL3070CW` |
| `PRINTER_INFO` | Name the clients show | `Brother HL-3070CW` |
| `PRINTER_LOCATION` | Where the printer stands | empty |
| `PRINTER_DRIVER` | `native`, or `postscript` (the printer renders the pages itself) | `native` |
| `PRINTER_OPTIONS` | Default options, for example `BRMonoColor=Mono BRResolution=600x2400dpi` | none |
| `LISTEN` | Address and port CUPS listens on | `*:631` |
| `ALLOW_FROM` | Addresses or networks that may print, separated by spaces | `@LOCAL` |
| `PRINTER_UUID` | The printer's UUID | derived from the name and `LISTEN` |

Then `docker compose up -d print-server`. The log (`docker logs print-server`) ends with
`Printer HL3070CW ready (UUID …)`.

The container is set up from these settings at every start. There is no web interface and no
administration from the network, and CUPS keeps no record of finished jobs: it would store a job's
Secure Print PIN with it.

## Announce it for AirPrint

The container has no Avahi of its own: giving a container the host's D-Bus would let it control the
host. Instead, the host's Avahi announces the printer from a service file. Copy the example below to
`/etc/avahi/services/airprint-hl3070cw.service` and fill in the UUID from the container's log; Avahi
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
    <txt-record>URF=V1.4,CP1,W8,PQ4,SRGB24,RS600,FN3</txt-record>
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

AirPrint and IPP Everywhere pass on the standard options: colour or black and white, paper size,
copies and the Secure Print PIN. Fine quality, Toner Save and Enhance Black Printing are set with
`PRINTER_OPTIONS` for everyone; on a Mac, the native driver installed locally offers them per job.

## Update

Change the commit or tag in `build.context`, then `docker compose build print-server` and
`docker compose up -d print-server`.
