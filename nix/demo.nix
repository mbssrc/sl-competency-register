# A self-contained demo: `nix run <flake>#demo` on any machine, no checkout.
#
# The demo script writes as it runs — a scratch database, a seeded taxonomy,
# Django's dev server — and the store is read-only, so this works from a copy
# of the source under the user's cache directory. The copy is keyed on the
# source's store hash, so a new flake revision gets a fresh one automatically
# while repeat runs of the same revision reuse it (which is what makes
# `--keep` still mean something).
#
# The stylesheet and background are taken from personnel-web, which builds
# them at package time. That is why the demo runs with --no-css: `npm install`
# would need network access, which `nix run` should not require and the Nix
# build sandbox forbids outright.
{
  writeShellApplication,
  python3,
  coreutils,
  personnel-web,
  src,
  pythonDeps,
}:

let
  python = python3.withPackages pythonDeps;
  assets = "${personnel-web}/share/personnel-web/app/static/dist";
in
writeShellApplication {
  name = "personnel-demo";

  runtimeInputs = [
    python
    coreutils
  ];

  text = ''
    cache="''${XDG_CACHE_HOME:-$HOME/.cache}/personnel-demo"
    work="$cache/$(basename ${src})"

    if [ ! -d "$work" ]; then
      echo "==> Unpacking the demo to $work"
      mkdir -p "$cache"
      rm -rf "$work.partial"
      cp -r --no-preserve=mode,ownership "${src}" "$work.partial"
      install -m644 "${assets}/output.css" "$work.partial/web/static/dist/output.css"
      install -m644 "${assets}/background.png" "$work.partial/web/static/dist/background.png"
      mv "$work.partial" "$work"
    fi

    exec bash "$work/demo/demo.sh" --no-css "$@"
  '';

  meta = {
    description = "Run a fully populated demo of the SecLab Competence Register";
    mainProgram = "personnel-demo";
  };
}
