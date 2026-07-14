# TunnelLoom Development Instructions

## Project purpose

TunnelLoom is an unofficial Linux graphical manager for the SoftEther VPN
Client. It is intended to provide behavior similar to the Windows SoftEther
VPN Client Manager while hiding direct CLI interaction from the user.

Current primary platform:

- LMDE 7
- Cinnamon desktop
- Python 3
- PySide6 / Qt 6
- SoftEther VPN Client installed separately

Current release version: 0.1.19

## Licensing

The project is licensed under the MIT License.

Copyright (c) 2026 Keith Reiter

Do not replace or remove the MIT license unless explicitly instructed.

## Important design requirements

- Never modify existing SoftEther files, ownership, permissions, or ACLs.
- SoftEther's default program directory is `/usr/local/vpnclient`.
- The SoftEther program directory must remain configurable.
- `vpncmd`, `vpnclient`, and `hamcore.se2` are expected in that directory.
- Run SoftEther commands from the configured program directory.
- Use `./vpncmd` and `./vpnclient`, not merely executable paths from another cwd.
- Runtime SoftEther operations use a graphical PolicyKit authorization prompt.
- Authorization occurs before displaying the main application window.
- Keep one privileged helper session for the life of the application.
- Never expose a terminal window to the user.

## SoftEther data

The GUI must query SoftEther directly rather than maintaining a separate
account or adapter database.

Relevant commands include:

- `AccountList`
- `AccountGet`
- `AccountConnect`
- `AccountDisconnect`
- `NicList`

Existing accounts and virtual adapters created outside TunnelLoom must appear
in the GUI.

## Refresh behavior

Do not add periodic polling.

Refresh only:

- When the application loads
- When the user clicks Refresh
- After a successful user action such as connect, disconnect, create, edit,
  delete, service start, or service stop

Refresh must not erase visible rows because of a temporary empty response.

Do not use `vpnclient status` as the authoritative refresh gate. On the user's
SoftEther installation, that operation previously reported an incorrect state
while `vpncmd` remained functional.

When the service is genuinely stopped:

- Clear account and adapter rows
- Show a normal stopped-service status
- Do not display a repeated error dialog

## Linux adapter networking

A SoftEther adapter named `worknic` appears in Linux as:

`vpn_worknic`

After an account connects, acquire IPv4 configuration with `dhcpcd`.

Use options that prevent dhcpcd from modifying DNS:

`dhcpcd -4 -w -L -C resolv.conf <interface>`

Do not allow dhcpcd to overwrite or empty `/etc/resolv.conf`.

The application must distinguish between:

- SoftEther session connected
- Linux virtual adapter successfully assigned an IPv4 address

Do not report the connection as fully usable when the Linux adapter has no
IPv4 address.

Disconnect cleanup must preserve or restore:

- Normal default route
- NetworkManager-managed physical connection
- Working system DNS

## Connection table

The connections table includes a VPN IP Address column.

- Show the IPv4 address assigned to the account's Linux virtual adapter.
- Show an em dash when disconnected or unassigned.
- Clicking the IP address copies it to the clipboard.
- Do not show stale IP addresses after disconnecting.

## Installer

The current installer targets Debian-family systems.

Use current Debian package names:

- `polkitd`
- `pkexec`

Never reintroduce the obsolete `policykit-1` package name.

The installer must replace the installed application and launcher and verify
the installed version.

## Source control

Before changing code:

1. Inspect `git status`.
2. Read `README.md`.
3. Read `VERSION`.
4. Inspect the relevant implementation and tests.

After changing code:

1. Run the complete test suite.
2. Report changed files.
3. Report test results.
4. Do not commit or push unless explicitly instructed.

Do not modify generated files, caches, or the `.git` directory.

## Quality expectations

- Preserve currently working behavior.
- Prefer narrowly scoped fixes.
- Add regression tests for bugs.
- Avoid claiming graphical behavior was tested when no graphical environment
  was available.
- Clearly identify anything that still requires testing on LMDE.