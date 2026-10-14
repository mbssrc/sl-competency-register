# NixOS VM test for services.personnel: a server running the full module
# (nginx TLS, fail2ban, backups) and a client that browses it and gets banned.
#
#   nix build .#checks.x86_64-linux.integration-test -L
{ module }:

{ pkgs, ... }:

let
  domain = "personnel.test";

  cert = pkgs.runCommand "personnel-test-cert" { nativeBuildInputs = [ pkgs.openssl ]; } ''
    mkdir $out
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=${domain} \
      -addext subjectAltName=DNS:${domain} \
      -keyout $out/key.pem -out $out/cert.pem
  '';

  hosts = { nodes, ... }: {
    networking.hosts.${nodes.server.networking.primaryIPAddress} = [ domain ];
  };

  # Fetch the login form and post one bad password with its CSRF token.
  badLogin = pkgs.writeShellScriptBin "bad-login" ''
    set -eu
    jar=$(mktemp)
    page=$(curl -sf --cacert ${cert}/cert.pem -c "$jar" https://${domain}/accounts/login/)
    token=$(printf '%s' "$page" | grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' | cut -d'"' -f4)
    curl -s --cacert ${cert}/cert.pem -b "$jar" -o /dev/null -w '%{http_code}\n' \
      -H "Referer: https://${domain}/accounts/login/" \
      --data-urlencode "csrfmiddlewaretoken=$token" \
      --data-urlencode "username=intruder" --data-urlencode "password=wrong" \
      https://${domain}/accounts/login/
  '';
in
{
  name = "personnel";

  nodes.server = {
    imports = [
      module
      hosts
    ];
    services.personnel = {
      enable = true;
      inherit domain;
      nginx = {
        enable = true;
        openFirewall = true;
        sslCertificate = "${cert}/cert.pem";
        sslCertificateKey = "${cert}/key.pem";
      };
      fail2ban = {
        enable = true;
        maxRetry = 3;
      };
      backup.enable = true;
    };
    environment.systemPackages = [ pkgs.sqlite ];
    virtualisation.memorySize = 2048;
  };

  nodes.client = {
    imports = [ hosts ];
    environment.systemPackages = [
      pkgs.curl
      badLogin
    ];
  };

  testScript = ''
    import json

    curl = "curl -sf --cacert ${cert}/cert.pem"
    data = "/var/lib/personnel"

    start_all()
    server.wait_for_unit("personnel.service")
    server.wait_for_unit("nginx.service")
    server.wait_for_unit("fail2ban.service")
    server.wait_until_succeeds("curl -sf http://127.0.0.1:8000/health/ -H 'X-Forwarded-Proto: https' -H 'Host: ${domain}'")

    with subtest("gunicorn listens on loopback only"):
        listeners = server.succeed("ss -Htln 'sport = :8000' | awk '{print $4}'").split()
        assert listeners == ["127.0.0.1:8000"], listeners

    with subtest("data directory and databases are owner-only"):
        assert server.succeed(f"stat -c '%a %U' {data}").strip() == "700 personnel"
        assert server.succeed(f"stat -c '%a %U' {data}/backups").strip() == "700 personnel"
        for db in ("personnel", "taxonomy"):
            assert server.succeed(f"stat -c '%a %U' {data}/{db}.sqlite3").strip() == "600 personnel"
        # WAL/SHM sidecars come and go with connections; whichever exist must match.
        assert server.succeed(f"find {data} -name '*.sqlite3*' ! -perm 600") == ""

    with subtest("SECRET_KEY comes from a file, not the environment"):
        assert server.succeed(f"stat -c '%a %U' {data}/secret_key").strip() == "600 root"
        key = server.succeed(f"cat {data}/secret_key").strip()
        pid = server.succeed("systemctl show -p MainPID --value personnel").strip()
        environ = server.succeed(f"tr '\\0' '\\n' < /proc/{pid}/environ")
        assert "DJANGO_SECRET_KEY=" not in environ
        assert key not in environ
        assert key not in server.succeed("systemctl show personnel")

    with subtest("taxonomy is seeded once, not on every restart"):
        server.succeed("systemctl restart personnel.service")
        server.wait_for_unit("personnel.service")
        seeds = server.succeed("journalctl -u personnel.service -o cat | grep -c 'Loaded TaxonomyMeta'").strip()
        assert seeds == "1", seeds

    with subtest("operator wrapper runs manage.py as the service user"):
        server.succeed("personnel-manage check_integrity")
        server.succeed(f"[ \"$(stat -c %U {data}/personnel.sqlite3)\" = personnel ]")

    with subtest("nginx serves the app over TLS with security headers"):
        client.wait_until_succeeds(f"{curl} https://${domain}/health/")
        assert json.loads(client.succeed(f"{curl} https://${domain}/health/")) == {"status": "ok"}
        headers = client.succeed(f"{curl} -D - -o /dev/null https://${domain}/accounts/login/").lower()
        assert "content-security-policy: default-src 'self'" in headers, headers
        assert "strict-transport-security" in headers, headers
        assert "x-frame-options: deny" in headers, headers
        redirect = client.succeed("curl -s -o /dev/null -w '%{http_code}' http://${domain}/")
        assert redirect == "301", redirect

    with subtest("nginx serves hashed static files itself"):
        page = client.succeed(f"{curl} https://${domain}/accounts/login/")
        css = next(w.split('"')[1] for w in page.split("href=")[1:] if ".css" in w.split('"')[1])
        assert css.startswith("/static/output.") and css != "/static/output.css", css
        headers = client.succeed(f"{curl} -D - -o /dev/null https://${domain}{css}").lower()
        assert "cache-control: public, immutable" in headers, headers

    with subtest("backup timer takes consistent owner-only snapshots"):
        server.succeed("systemctl list-timers | grep personnel-backup")
        server.succeed("systemctl start personnel-backup.service")
        for db in ("personnel", "taxonomy"):
            backup = server.succeed(f"ls {data}/backups/{db}-*.sqlite3").split()[0]
            assert server.succeed(f"stat -c %a {backup}").strip() == "600"
            assert server.succeed(f"sqlite3 {backup} 'PRAGMA integrity_check'").strip() == "ok"
        server.succeed(f"touch -d '40 days ago' {data}/backups/personnel-old.sqlite3")
        server.succeed("systemctl start personnel-backup.service")
        server.fail(f"test -e {data}/backups/personnel-old.sqlite3")

    with subtest("fail2ban bans a client after repeated failed logins"):
        for _ in range(3):
            assert client.succeed("bad-login").strip() == "200"
        client_ip = client.succeed("ip -4 -o addr show eth1 | awk '{print $4}' | cut -d/ -f1").strip()
        server.wait_until_succeeds(f"fail2ban-client status personnel-auth | grep -wF {client_ip}", timeout=60)
        client.fail(f"{curl} --max-time 5 https://${domain}/health/")

    with subtest("systemd sandbox stays tight"):
        verdict = server.succeed("systemd-analyze security personnel.service --no-pager | tail -1")
        print(verdict)
        assert float(verdict.split(": ")[1].split()[0]) <= 2.0, verdict
  '';
}
