# valheim-dev OMP extension

Project-local tools for this Valheim suite. OMP discovers this extension natively from `.omp/extensions/`.

The canonical host is WSL/Linux. Windows Valheim paths must therefore be written in WSL form, such as `/mnt/c/Program Files (x86)/Steam/steamapps/common/Valheim`.

Local configuration is read from `.valheim/dev.json`, which is gitignored and validated before use.

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
- Client deployment is metadata-driven and can never include a `serverOnly` project while `suite.config.json` remains valid.
- Server deployment is metadata-driven and can never include a `clientOnly` project while `suite.config.json` remains valid.
- A target side with no runtime module (e.g. requesting client deployment on a ServerCore-only suite) is rejected before the destination is touched -- `Common` alone is a shared library, not a runtime plugin.
- Assembly inspection resolves the requested path to its canonical (symlink-resolved) filesystem target and rejects it unless that target is a regular file inside the canonical `valheim_Data/Managed` directory.
- Server log access accepts only a configured log file or a fixed `docker compose logs` invocation. Arbitrary configured shell commands are not supported.
- Child processes use argument arrays rather than shell interpolation and receive the OMP cancellation signal.
