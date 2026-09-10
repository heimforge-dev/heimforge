# valheim-dev OMP extension

Project-local tools for this Valheim suite. OMP discovers this extension natively from `.omp/extensions/`.

The canonical development host is WSL/Linux. Local Windows Valheim paths must therefore use WSL form, such as `/mnt/c/Program Files (x86)/Steam/steamapps/common/Valheim`. Schema-v2 server deployment may independently target a remote POSIX or Windows host through an SSH config alias.

Development configuration is read from `.valheim/dev.json`, which is gitignored and validated before use. Authentication remains entirely in SSH configuration; credentials and private keys do not belong in this file.

Tools:

- `valheim_preflight`
- `valheim_game_info`
- `valheim_build`
- `valheim_inspect`
- `valheim_deploy`
- `valheim_logs`
- `valheim_server_status`
- `valheim_package`

Safety/consistency properties:

- Deployment is blocked unless `developmentOnly: true` and the tool call explicitly confirms it.
- Deployment delegates to the same `scripts/deploy.py` used by Bash scripts, so client/server module classification has one implementation.
- The deployment tool's optional `restart` flag maps to the canonical script's explicit `--restart`; no deployment restarts a server by default.
- Schema-v2 SSH deployment uses staging and verified promotion; local deployment retains its stronger retained-directory-FD protections.
- Client deployment is metadata-driven and can never include a `serverOnly` project while `suite.config.json` remains valid.
- Server deployment is metadata-driven and can never include a `clientOnly` project while `suite.config.json` remains valid.
- A target side with no runtime module (e.g. requesting client deployment on a ServerCore-only suite) is rejected before the destination is touched -- `Common` alone is a shared library, not a runtime plugin.
- Assembly inspection resolves the requested path to its canonical (symlink-resolved) filesystem target and rejects it unless that target is a regular file inside the canonical `valheim_Data/Managed` directory.
- Server status and bounded logs delegate to `scripts/server_runtime.py`, which selects the configured local or SSH transport and exposes only fixed file/Docker operations. Arbitrary configured shell commands are not supported.
- Child processes use argument arrays rather than shell interpolation and receive the OMP cancellation signal.
