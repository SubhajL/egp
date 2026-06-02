# Crawler proxy + warmed-profile runbook

How to activate residential-proxy crawling on the production host. Everything
below is **off by default** (the executor crawls exactly as before until these
steps are taken). All commands run on the host as:

```bash
cd /home/ubuntu/egp
sudo docker compose --env-file /etc/egp/egp.env <args>
```

Prerequisites already merged & deployable (default-off):
- `proxy-relay` gost sidecar behind the `proxy` compose profile (#132)
- env-configurable search timeouts (#133)
- navigation-race retry in the search step (#134)
- persistent warmed-profile mode + `egp_browser_profile` volume + `egp_worker.warmup` (#130, this PR)

## 1. Put the proxy upstream in the root-only env file
Edit `/etc/egp/egp.env` (root, `0600`, never the repo) and set:

```ini
# IPRoyal residential, sticky Thai IP, IP-allowlist auth — host IP already
# whitelisted in the IPRoyal dashboard. Credentials go ONLY here.
EGP_PROXY_UPSTREAM_URL=http://USER:PASS@geo.iproyal.com:12321

# Chrome (creds-free) -> local relay -> IPRoyal
EGP_BROWSER_PROXY_SERVER=http://proxy-relay:8118
EGP_BROWSER_USE_XVFB=true

# Persistent warmed profile (kept on the egp_browser_profile volume)
EGP_BROWSER_PROFILE_MODE=persistent
EGP_BROWSER_PERSISTENT_PROFILE_DIR=/var/lib/egp/browser-profile

# Generous timeouts for residential-proxy latency
EGP_BROWSER_NAV_TIMEOUT_MS=120000
EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS=180000
```

## 2. Start the relay and confirm a Thai egress IP
```bash
sudo docker compose --env-file /etc/egp/egp.env --profile proxy up -d proxy-relay
# verify egress is Thailand (run from a container on the compose network):
sudo docker compose --env-file /etc/egp/egp.env run --rm proxy-relay \
  -L=http://:0 -F=- >/dev/null 2>&1 || true   # (relay already up; see next check)
sudo docker run --rm --network "$(docker inspect egp-proxy-relay \
  --format '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{end}}')" \
  egp-discovery-executor bash -lc \
  'curl -s -x http://egp-proxy-relay:8118 https://ipinfo.io/country'   # expect: TH
```

## 3. Warm the persistent profile (once)
Loads e-GP through the proxy so Cloudflare grants a clearance the profile keeps:

```bash
sudo docker compose --env-file /etc/egp/egp.env --profile proxy \
  run --rm discovery-executor python -m egp_worker.warmup
# expect: WARMUP_OK profile=/var/lib/egp/browser-profile
```

## 4. Re-enable the crawler
```bash
sudo docker compose --env-file /etc/egp/egp.env up -d discovery-executor
# trigger one keyword and watch:
sudo docker logs -f egp-discovery-executor-1
```
A crawl should now clear the search and return real tenders.

## Rollback (instant, safe)
```bash
# back to the pre-proxy behavior:
#   in /etc/egp/egp.env set EGP_BROWSER_PROFILE_MODE=per_run and clear EGP_BROWSER_PROXY_SERVER
sudo docker compose --env-file /etc/egp/egp.env up -d discovery-executor   # re-create with per_run
sudo docker compose --env-file /etc/egp/egp.env stop proxy-relay           # stop the relay
# or pause crawling entirely:
sudo docker compose --env-file /etc/egp/egp.env stop discovery-executor
```
The warmed profile persists on the `egp_browser_profile` volume, so re-warming
is only needed if Cloudflare clearance expires or the profile is wiped.
