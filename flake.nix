{
  description = "auto-self-modeling: record, understand, and replay terminal sessions";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python312.withPackages (ps: [
        ps.click
      ]);
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          python
          pkgs.tmux
          pkgs.sqlite
        ];
        shellHook = ''
          export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
          alias selfmod="python -m selfmod"
        '';
      };
    };
}
