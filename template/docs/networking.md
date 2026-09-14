# Networking Design

See `.context/references/networking.md` for the concise working rules.

For each RPC document:

- owning module
- operation
- protocol version
- sender direction
- maximum expected payload
- validation rules
- authorization rules
- rate limit if needed
- response/failure semantics

Keep persistent gameplay authority on the server.

## Shared.Diagnostics ping

- Owning module: `Shared.Diagnostics`
- Operation: `shared.diagnostics.ping`
- Protocol version: `1`
- Sender direction: client to server; server acknowledgement to the initiating client
- Maximum expected payload: empty `ZPackage` in both directions
- Validation rules: the server requires server mode, a connected sender, and no prior acknowledgement for that peer; the client requires the acknowledgement from the current server for its pending connection
- Authorization rules: connected peers only
- Rate limit: one server acknowledgement per connected peer until disconnect
- Response/failure semantics: the server sends an empty acknowledgement; the client skips initiation when the module is absent on the server, and invalid, duplicate, or unexpected messages are ignored
