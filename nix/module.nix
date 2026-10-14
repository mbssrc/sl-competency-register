# services.personnel: the web app behind gunicorn, with optional nginx TLS
# proxy, fail2ban jails and a backup timer.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (lib)
    mkOption
    mkEnableOption
    mkIf
    types
    ;

  cfg = config.services.personnel;
  app = "${cfg.package}/share/personnel-web";
  sqlite = lib.getExe pkgs.sqlite;

  environment = {
    DJANGO_SETTINGS_MODULE = "config.settings";
    DJANGO_DEBUG = "false";
    DJANGO_ALLOWED_HOSTS = lib.concatStringsSep "," ([ cfg.domain ] ++ cfg.extraAllowedHosts);
    DJANGO_CSRF_TRUSTED_ORIGINS = "https://${cfg.domain}";
    PERSONNEL_DATA_DIR = cfg.dataDir;
    PERSONNEL_TAXONOMY_DIR = "${cfg.taxonomyJsonPath}";
    PERSONNEL_TRUSTED_PROXY_COUNT = toString cfg.trustedProxyCount;
    # %d is systemd's credentials directory; see LoadCredential below.
    DJANGO_SECRET_KEY_FILE = "%d/secret_key";
  };

  # `personnel-manage <command>` for operators (run as root): manage.py as the
  # service user, with the service's environment, credential and sandbox.
  manage = pkgs.writeShellScriptBin "personnel-manage" ''
    if [ -t 0 ]; then io=--pty; else io=--pipe; fi
    exec ${config.systemd.package}/bin/systemd-run --quiet --wait --collect "$io" \
      --uid=personnel --gid=personnel \
      --property=LoadCredential=secret_key:${cfg.secretKeyFile} \
      --property=ProtectSystem=strict --property=ReadWritePaths=${cfg.dataDir} \
      --property=ProtectHome=true --property=PrivateTmp=true --property=UMask=0077 \
      --working-directory=${cfg.dataDir} \
      ${
        lib.concatMapStringsSep " " (k: "--setenv=${k}=${lib.escapeShellArg environment.${k}}") (
          lib.attrNames (removeAttrs environment [ "DJANGO_SECRET_KEY_FILE" ])
        )
      } \
      ${pkgs.runtimeShell} -c 'DJANGO_SECRET_KEY_FILE="$CREDENTIALS_DIRECTORY/secret_key" exec "$0" "$@"' \
      ${cfg.package}/bin/personnel-manage "$@"
  '';

  # Repeated in every location that adds its own headers: a nested add_header
  # drops all inherited ones.
  securityHeaders = ''
    add_header Content-Security-Policy "${cfg.nginx.contentSecurityPolicy}" always;
    add_header Referrer-Policy "same-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
  '';

  hardening = {
    NoNewPrivileges = true;
    ProtectHome = true;
    ProtectSystem = "strict";
    ReadWritePaths = [ cfg.dataDir ];
    PrivateTmp = true;
    PrivateDevices = true;
    ProtectKernelTunables = true;
    ProtectKernelModules = true;
    ProtectKernelLogs = true;
    ProtectControlGroups = true;
    ProtectClock = true;
    ProtectHostname = true;
    ProtectProc = "invisible";
    RestrictSUIDSGID = true;
    RestrictNamespaces = true;
    RestrictRealtime = true;
    RestrictAddressFamilies = [
      "AF_INET"
      "AF_INET6"
      "AF_UNIX"
    ];
    LockPersonality = true;
    MemoryDenyWriteExecute = true;
    SystemCallArchitectures = "native";
    SystemCallFilter = [
      "@system-service"
      "~@privileged"
      "~@resources"
    ];
    CapabilityBoundingSet = "";
    UMask = "0077";
  };
in
{
  options.services.personnel = {
    enable = mkEnableOption "the Personnel Skill Database web app";

    package = mkOption {
      type = types.package;
      description = "The personnel-web package (set by the flake's module).";
    };

    domain = mkOption {
      type = types.str;
      default = "localhost";
      description = "Host name the app is served under; becomes ALLOWED_HOSTS and the nginx vhost.";
    };

    extraAllowedHosts = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Additional ALLOWED_HOSTS entries.";
    };

    port = mkOption {
      type = types.port;
      default = 8000;
      description = "Port gunicorn listens on. It always binds 127.0.0.1.";
    };

    dataDir = mkOption {
      type = types.path;
      default = "/var/lib/personnel";
      description = "Holds both SQLite databases and backups/. Put it on an encrypted volume.";
    };

    secretKeyFile = mkOption {
      type = types.path;
      default = "${cfg.dataDir}/secret_key";
      defaultText = lib.literalExpression ''"''${config.services.personnel.dataDir}/secret_key"'';
      description = ''
        File holding Django's SECRET_KEY. Generated on first start if it does
        not exist. It is passed to the service as a systemd credential, so it
        may be owned by root with mode 0400.
      '';
    };

    taxonomyJsonPath = mkOption {
      type = types.path;
      default = "${cfg.package}/share/personnel-web/taxonomy-data";
      defaultText = lib.literalExpression ''"''${cfg.package}/share/personnel-web/taxonomy-data"'';
      description = ''
        Directory holding taxonomy/, profiles/ and services/. The taxonomy
        database is re-seeded from it whenever this path changes, that is,
        on a deploy that changes the taxonomy. Web edits made since the last
        deploy are overwritten then; export them first.
      '';
    };

    trustedProxyCount = mkOption {
      type = types.ints.unsigned;
      default = if cfg.nginx.enable then 1 else 0;
      defaultText = lib.literalExpression "if nginx.enable then 1 else 0";
      description = ''
        Reverse proxies in front of gunicorn whose X-Forwarded-For entries are
        trusted. Login lockout and fail2ban key on the client address this
        yields, so it must match the real topology.
      '';
    };

    gunicorn = {
      workers = mkOption {
        type = types.ints.positive;
        default = 2;
        description = "gunicorn worker processes.";
      };
      threads = mkOption {
        type = types.ints.positive;
        default = 4;
        description = "Threads per gunicorn worker.";
      };
    };

    nginx = {
      enable = mkEnableOption "an nginx TLS reverse proxy in front of gunicorn";
      openFirewall = mkOption {
        type = types.bool;
        default = false;
        description = "Open TCP 80 (redirects to https) and 443.";
      };
      sslCertificate = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = "TLS certificate (PEM) for the vhost.";
      };
      sslCertificateKey = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = "TLS private key for sslCertificate.";
      };
      contentSecurityPolicy = mkOption {
        type = types.str;
        # Templates carry inline <script> blocks and Alpine.js evaluates
        # expressions, hence the unsafe-* allowances; everything stays same-origin.
        default = lib.concatStringsSep "; " [
          "default-src 'self'"
          "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
          "style-src 'self' 'unsafe-inline'"
          "img-src 'self' data:"
          "object-src 'none'"
          "base-uri 'self'"
          "form-action 'self'"
          "frame-ancestors 'none'"
        ];
        description = "Content-Security-Policy header nginx adds to every response.";
      };
    };

    fail2ban = {
      enable = mkEnableOption "fail2ban jails for failed logins and repeated 403s";
      maxRetry = mkOption {
        type = types.ints.positive;
        default = 5;
        description = "Failed logins within findTime that trigger a ban.";
      };
      banTime = mkOption {
        type = types.str;
        default = "30m";
        description = "Ban duration for failed logins.";
      };
      findTime = mkOption {
        type = types.str;
        default = "10m";
        description = "Window in which failures are counted.";
      };
      forbidden = {
        maxRetry = mkOption {
          type = types.ints.positive;
          default = 10;
          description = "403 responses within findTime that trigger a ban.";
        };
        banTime = mkOption {
          type = types.str;
          default = "1h";
          description = "Ban duration for repeated 403s.";
        };
      };
    };

    backup = {
      enable = mkEnableOption "daily SQLite backups into dataDir/backups";
      retentionDays = mkOption {
        type = types.ints.positive;
        default = 30;
        description = "Backups older than this are deleted.";
      };
      onCalendar = mkOption {
        type = types.str;
        default = "daily";
        description = "systemd OnCalendar expression for the backup timer.";
      };
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion =
          cfg.nginx.enable -> (cfg.nginx.sslCertificate != null && cfg.nginx.sslCertificateKey != null);
        message = ''
          services.personnel.nginx needs sslCertificate and sslCertificateKey:
          the app redirects every plain-HTTP request to https.
        '';
      }
    ];

    environment.systemPackages = [ manage ];

    users.users.personnel = {
      isSystemUser = true;
      group = "personnel";
      home = cfg.dataDir;
    };
    users.groups.personnel = { };

    # Directories 0700; database files (and WAL/SHM sidecars) 0600 on every boot.
    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0700 personnel personnel -"
      "d ${cfg.dataDir}/backups 0700 personnel personnel -"
      "z ${cfg.dataDir}/*.sqlite3* 0600 personnel personnel -"
    ];

    systemd.services.personnel-secret-key = {
      description = "Generate the Personnel web app SECRET_KEY";
      unitConfig.ConditionPathExists = "!${cfg.secretKeyFile}";
      serviceConfig = {
        Type = "oneshot";
        UMask = "0077";
      };
      script = ''
        mkdir -p "$(dirname ${lib.escapeShellArg cfg.secretKeyFile})"
        ${pkgs.coreutils}/bin/head -c 48 /dev/urandom | ${pkgs.coreutils}/bin/base64 -w0 \
          > ${lib.escapeShellArg cfg.secretKeyFile}
      '';
    };

    systemd.services.personnel = {
      description = "Personnel Skill Database web app";
      after = [
        "network.target"
        "personnel-secret-key.service"
        "systemd-tmpfiles-setup.service"
      ];
      requires = [ "personnel-secret-key.service" ];
      wantedBy = [ "multi-user.target" ];
      inherit environment;
      path = [ cfg.package ];

      # Re-seed only when the JSON source changes: the taxonomy DB is the live
      # truth between deploys, and a restart must not discard web edits.
      preStart = ''
        personnel-manage migrate --noinput
        personnel-manage migrate --database taxonomy --noinput
        stamp=${lib.escapeShellArg cfg.dataDir}/.taxonomy-source
        if [ "$(cat "$stamp" 2>/dev/null)" != ${lib.escapeShellArg "${cfg.taxonomyJsonPath}"} ]; then
          personnel-manage seed_taxonomy
          printf '%s' ${lib.escapeShellArg "${cfg.taxonomyJsonPath}"} > "$stamp"
        fi
        personnel-manage check_integrity || echo "check_integrity reported problems; see above" >&2
      '';

      serviceConfig = hardening // {
        User = "personnel";
        Group = "personnel";
        WorkingDirectory = cfg.dataDir;
        LoadCredential = [ "secret_key:${cfg.secretKeyFile}" ];
        ExecStart = lib.escapeShellArgs [
          "${cfg.package}/bin/personnel-web"
          "--bind"
          "127.0.0.1:${toString cfg.port}"
          "--workers"
          (toString cfg.gunicorn.workers)
          "--threads"
          (toString cfg.gunicorn.threads)
          "--access-logfile"
          "-"
        ];
        Restart = "on-failure";
        RestartSec = "5s";
        TimeoutStartSec = "5min";
      };
    };

    networking.firewall.allowedTCPPorts = lib.optionals (cfg.nginx.enable && cfg.nginx.openFirewall) [
      80
      443
    ];

    services.nginx = mkIf cfg.nginx.enable {
      enable = true;
      recommendedProxySettings = true;
      recommendedTlsSettings = true;
      recommendedGzipSettings = true;
      virtualHosts.${cfg.domain} = {
        forceSSL = true;
        sslCertificate = cfg.nginx.sslCertificate;
        sslCertificateKey = cfg.nginx.sslCertificateKey;
        extraConfig = ''
          client_max_body_size 6m;
          ${securityHeaders}
        '';
        # Hashed by ManifestStaticFilesStorage at build time, so never stale.
        locations."/static/" = {
          alias = "${app}/app/staticfiles/";
          extraConfig = ''
            expires 1y;
            add_header Cache-Control "public, immutable" always;
            add_header X-Content-Type-Options "nosniff" always;
            ${securityHeaders}
          '';
        };
        locations."/" = {
          proxyPass = "http://127.0.0.1:${toString cfg.port}";
        };
      };
    };

    # Lines end with from=<client> and client-supplied fields are repr()'d
    # (see apps/core/middleware.py), so anchoring on the end of the line
    # means a crafted username or path cannot get another address banned.
    services.fail2ban = mkIf cfg.fail2ban.enable {
      enable = true;
      jails = {
        personnel-auth = {
          filter.Definition = {
            failregex = "personnel-auth: FAILED login user=.* from=<HOST>$";
            journalmatch = "_SYSTEMD_UNIT=personnel.service";
          };
          settings = {
            backend = "systemd";
            port = "http,https";
            maxretry = cfg.fail2ban.maxRetry;
            findtime = cfg.fail2ban.findTime;
            bantime = cfg.fail2ban.banTime;
          };
        };
        personnel-forbidden = {
          filter.Definition = {
            failregex = "personnel-auth: FORBIDDEN user=.* from=<HOST>$";
            journalmatch = "_SYSTEMD_UNIT=personnel.service";
          };
          settings = {
            backend = "systemd";
            port = "http,https";
            maxretry = cfg.fail2ban.forbidden.maxRetry;
            findtime = cfg.fail2ban.findTime;
            bantime = cfg.fail2ban.forbidden.banTime;
          };
        };
      };
    };

    # sqlite3 .backup takes a consistent snapshot of a live WAL database;
    # a plain cp of the main file could miss committed pages still in the WAL.
    systemd.services.personnel-backup = mkIf cfg.backup.enable {
      description = "Back up the Personnel SQLite databases";
      after = [ "personnel.service" ];
      serviceConfig = hardening // {
        Type = "oneshot";
        User = "personnel";
        Group = "personnel";
        RestrictAddressFamilies = [ "AF_UNIX" ];
      };
      script = ''
        set -eu
        dest=${lib.escapeShellArg cfg.dataDir}/backups
        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        for db in personnel taxonomy; do
          src=${lib.escapeShellArg cfg.dataDir}/$db.sqlite3
          [ -f "$src" ] || continue
          ${sqlite} "$src" ".backup '$dest/$db-$stamp.sqlite3'"
        done
        find "$dest" -maxdepth 1 -name '*.sqlite3' -type f \
          -mtime +${toString cfg.backup.retentionDays} -delete
      '';
      path = [
        pkgs.coreutils
        pkgs.findutils
      ];
    };

    systemd.timers.personnel-backup = mkIf cfg.backup.enable {
      description = "Daily backup of the Personnel SQLite databases";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.backup.onCalendar;
        Persistent = true;
        RandomizedDelaySec = "15m";
      };
    };
  };
}
