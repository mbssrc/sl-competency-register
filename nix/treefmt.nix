# Formatter configuration, evaluated by treefmt-nix.
#
# Covers Nix and Python. The Python rules and line length live in ruff.toml at
# the repository root rather than here, because ruff's own defaults are not
# stable enough to rely on: unpinned, ruff 0.16 enabled 413 rules and reported
# 138 findings against this tree, where its documented default set reports 20.
# Pinning keeps `nix flake check` from changing verdict when ruff moves.
#
# Not enabled: prettier and a JSON formatter would rewrite the 360-file
# taxonomy, which is authored data rather than code. Each is one line here if
# that is ever wanted.
#
# Exposed by flake.nix as `nix fmt` and as the `formatting` flake check.
_: {
  projectRootFile = "flake.nix";

  programs = {
    # The standard Nix formatter, per RFC 166.
    nixfmt.enable = true;

    # Removes unused bindings and arguments.
    deadnix.enable = true;

    # Flags Nix anti-patterns.
    statix.enable = true;

    # Python: formatter and linter. Configured by ruff.toml.
    ruff.format = true;
    ruff.check = true;
  };

  settings = {
    formatter = {
      # deadnix and statix rewrite expressions; nixfmt must run after them or
      # their output ships unformatted and the pass is not idempotent. Lower
      # priority runs first.
      deadnix.priority = -1;
      statix.priority = -1;

      # Same reasoning: the linter may rewrite, so the formatter runs after it.
      ruff-check.priority = -1;
    };

    global.excludes = [
      "*.lock"
      "*.png"
      "*.pdf"
      "*.pptx"
      "*.xlsx"
      "*.sqlite3"
      "*.min.js"
      ".envrc"
    ];
  };
}
