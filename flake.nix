{
  description = "Security Laboratory Competency Register";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      treefmt-nix,
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems =
        f:
        nixpkgs.lib.genAttrs supportedSystems (
          system:
          f {
            inherit system;
            pkgs = nixpkgs.legacyPackages.${system};
          }
        );

      # Plain flake, so treefmt is wired through evalModule rather than the
      # flake-parts module.
      treefmtFor = system: treefmt-nix.lib.evalModule nixpkgs.legacyPackages.${system} ./nix/treefmt.nix;

      pythonDeps = ps: [
        ps.jsonschema
        ps.openpyxl
        ps.django
        ps.django-htmx
        ps.gunicorn
        ps.whitenoise
        ps.argon2-cffi
        ps.pytest
        ps.pytest-django
        ps.django-axes
      ];
    in
    {
      formatter = forAllSystems (
        { system, ... }:
        (treefmtFor system).config.build.wrapper
      );

      devShells = forAllSystems (
        { pkgs, ... }: {
          default = pkgs.mkShell {
            packages = [
              (pkgs.python3.withPackages pythonDeps)
              pkgs.nodejs
            ];
          };
        }
      );

      packages = forAllSystems (
        { pkgs, ... }: {
          personnel-web = pkgs.callPackage ./nix/package.nix { };

          demo = pkgs.callPackage ./nix/demo.nix {
            inherit pythonDeps;
            src = self;
            personnel-web = self.packages.${pkgs.stdenv.hostPlatform.system}.personnel-web;
          };

          default = pkgs.python3Packages.buildPythonApplication {
            pname = "personnel-cli";
            version = "0.1.0";
            format = "other";

            src = ./tools;

            propagatedBuildInputs = with pkgs.python3Packages; [
              jsonschema
              openpyxl
            ];

            installPhase = ''
              mkdir -p $out/lib/personnel-tools $out/bin
              cp *.py $out/lib/personnel-tools/

              makeWrapper ${pkgs.python3.withPackages pythonDeps}/bin/python3 $out/bin/personnel-cli \
                --add-flags "$out/lib/personnel-tools/cli.py" \
                --set PYTHONPATH "$out/lib/personnel-tools"
            '';

            nativeBuildInputs = [ pkgs.makeWrapper ];

            meta = {
              description = "CLI for the Security Lab Personnel Skill Database";
              mainProgram = "personnel-cli";
            };
          };
        }
      );

      apps = forAllSystems (
        { system, ... }: {
          demo = {
            type = "app";
            program = "${self.packages.${system}.demo}/bin/personnel-demo";
          };
        }
      );

      nixosModules.default = { pkgs, lib, ... }: {
        imports = [ ./nix/module.nix ];
        services.personnel.package =
          lib.mkDefault
            self.packages.${pkgs.stdenv.hostPlatform.system}.personnel-web;
      };

      checks = nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-linux" ] (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          # Fails when anything treefmt handles is unformatted.
          formatting = (treefmtFor system).config.build.check self;

          personnel-web = self.packages.${system}.personnel-web;

          demo =
            pkgs.runCommand "personnel-demo-check"
              {
                nativeBuildInputs = [ self.packages.${system}.demo ];
              }
              ''
                export HOME="$TMPDIR/home"
                export XDG_CACHE_HOME="$TMPDIR/cache"
                mkdir -p "$HOME" "$XDG_CACHE_HOME"
                personnel-demo --no-serve
                touch $out
              '';
          integration-test = pkgs.testers.runNixOSTest (
            import ./nix/test.nix {
              module = self.nixosModules.default;
            }
          );
        }
      );
    };
}
