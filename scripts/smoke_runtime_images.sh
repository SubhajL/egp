#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <api-image> <worker-image>" >&2
  exit 2
fi

api_image="$1"
worker_image="$2"
api_max_bytes="${EGP_API_IMAGE_MAX_BYTES:-800000000}"
worker_max_bytes="${EGP_WORKER_IMAGE_MAX_BYTES:-2200000000}"
expected_release_sha="${EGP_EXPECTED_RELEASE_SHA:-}"

is_exact_release_sha() {
  value="$1"
  if [ "${#value}" -ne 40 ]; then
    return 1
  fi
  case "$value" in
    *[!0123456789abcdef]*) return 1 ;;
  esac
  return 0
}

if ! is_exact_release_sha "$expected_release_sha"; then
  echo "EGP_EXPECTED_RELEASE_SHA must be an exact 40-character lowercase Git SHA for release revision smoke" >&2
  exit 1
fi

require_non_root_user() {
  image="$1"
  configured_user="$(docker image inspect "$image" --format '{{.Config.User}}')"
  case "$configured_user" in
    "" | "0" | "0:0" | "root" | "root:root")
      echo "$image must configure a non-root runtime user" >&2
      exit 1
      ;;
  esac
}

require_non_root_user "$api_image"
require_non_root_user "$worker_image"

require_release_revision() {
  image="$1"
  revision="$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
  if ! is_exact_release_sha "$revision"; then
    echo "$image release revision must be an exact 40-character lowercase Git SHA" >&2
    exit 1
  fi
  if [ "$revision" != "$expected_release_sha" ]; then
    echo "$image release revision label mismatch: expected $expected_release_sha, got ${revision:-<missing>}" >&2
    exit 1
  fi

  config_env="$(docker image inspect "$image" --format '{{range .Config.Env}}{{println .}}{{end}}')"
  if ! printf '%s\n' "$config_env" | grep -Fqx "EGP_RELEASE_SHA=$expected_release_sha"; then
    echo "$image release revision environment mismatch: missing EGP_RELEASE_SHA=$expected_release_sha" >&2
    exit 1
  fi
}

require_release_revision "$api_image"
require_release_revision "$worker_image"

docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --mount type=volume,destination=/var/lib/egp/artifacts \
  --entrypoint python "$api_image" -c \
  'import importlib.util, os; from pathlib import Path; import egp_api.main; probe = Path("/var/lib/egp/artifacts/.image-smoke"); probe.write_text("ok", encoding="utf-8"); probe.unlink(); assert os.geteuid() != 0; assert importlib.util.find_spec("playwright") is None; assert importlib.util.find_spec("egp_worker") is None'

docker run --rm --read-only --tmpfs /tmp:rw,nosuid,size=64m,mode=1777 \
  --tmpfs /var/lib/egp/browser-profiles:rw,nosuid,size=64m,uid=10001,gid=10001,mode=0700 \
  --mount type=volume,destination=/var/lib/egp/artifacts \
  --mount type=volume,destination=/var/lib/egp/browser-profile \
  --entrypoint python "$worker_image" -c \
  'import os, shutil; from pathlib import Path; import egp_api.executors.discovery_dispatch; import egp_worker.main; from egp_worker.browser_discovery import BrowserDiscoverySettings, connect_playwright_to_chrome, launch_real_chrome, resolve_chrome_binary, safe_shutdown; from playwright.sync_api import sync_playwright; probes = [Path("/var/lib/egp/artifacts/.image-smoke"), Path("/var/lib/egp/browser-profile/.image-smoke")]; [probe.write_text("ok", encoding="utf-8") for probe in probes]; [probe.unlink() for probe in probes]; profile = Path("/var/lib/egp/browser-profiles/.image-smoke-profile"); settings = BrowserDiscoverySettings(cdp_port=9322, browser_profile_dir=profile, use_xvfb=True); executable = Path(resolve_chrome_binary(settings.chrome_path)); chrome_proc = launch_real_chrome(settings, clear_singleton_locks=True); runtime = sync_playwright().start(); browser, page = connect_playwright_to_chrome(runtime, settings); page.set_content("<title>egp-image-smoke</title>"); assert page.title() == "egp-image-smoke"; safe_shutdown(browser=browser, pw=runtime, chrome_proc=chrome_proc); shutil.rmtree(profile); assert os.geteuid() != 0; assert executable.is_file() and os.access(executable, os.X_OK)'

api_size="$(docker image inspect "$api_image" --format '{{.Size}}')"
worker_size="$(docker image inspect "$worker_image" --format '{{.Size}}')"

if [ "$api_size" -ge "$worker_size" ]; then
  echo "API image must be smaller than browser worker image ($api_size >= $worker_size)" >&2
  exit 1
fi
if [ "$api_size" -gt "$api_max_bytes" ]; then
  echo "API image exceeds ${api_max_bytes}-byte release bound ($api_size)" >&2
  exit 1
fi
if [ "$worker_size" -gt "$worker_max_bytes" ]; then
  echo "Worker image exceeds ${worker_max_bytes}-byte release bound ($worker_size)" >&2
  exit 1
fi

echo "runtime image smoke passed: api=${api_size}B worker=${worker_size}B"
