# CORRAL

Runs a shell with the current directory writable and the rest of the host read
only. A coding agent can then damage only the directory you start it in. There
is no daemon, no image and no container: `bwrap` and `pasta` do the work, and
neither needs root.

## Usage

```
corral                    # run as the default user from the config
corral -u throwaway       # run as another sandbox user
corral -m ../core         # also mount a sibling, read only, same path inside
corral -m /data:/data:rw  # mount a chosen path, writable
corral -m ./sdk::tmp      # writable, but the writes vanish at exit
corral -m .::ro           # the project read only too, for an untrusted checkout
corral -e RUST_LOG=1      # set a variable inside for this run
corral -e GITHUB_TOKEN    # forward the host's value for this run
corral -n host            # share the host's network for this run
corral --dry-run          # print the bwrap command and exit
corral claude             # run a tool directly instead of the shell
corral list               # the sandbox homes, their size and last start
corral remove NAME        # delete one, after a confirmation
corral check              # report what this host is missing
corral --help
```

Only the project directory and the sandbox user's home keep changes after exit.

## Install

corral needs `bubblewrap`, `passt` for the default network mode, and Python
3.11 or newer. `:tmp` mounts need `bubblewrap` 0.11.0 or newer.

```
sudo pacman -S bubblewrap passt          # Arch
sudo apt install bubblewrap passt        # Debian, Ubuntu
```

corral is one file that uses only the standard library. Install it with one
of:

```
install -Dm755 corral ~/.local/bin/corral
pipx install git+https://github.com/davxy/corral
makepkg -si                              # Arch, from the PKGBUILD
```

On a new machine, run `corral check` first. It reads no config:

```
$ corral check
bwrap                                         ok    bubblewrap 0.12.0
user namespace                                ok    bwrap can create one
kernel.apparmor_restrict_unprivileged_userns  ok    absent
kernel.unprivileged_userns_clone              ok    1
user.max_user_namespaces                      ok    2147483647
pasta                                         ok    pasta 2026_07_28.f8df3f1
```

The `user namespace` line is the result. It runs `bwrap` with the namespace
flags of corral, and shows the error of `bwrap` when it fails. The three
sysctls are the usual causes. Ubuntu 23.10 and later set the first to 1. corral
prints the `sysctl -w` fix only when the probe fails, because an AppArmor
profile can let `bwrap` through while the sysctl is 1. A missing `pasta` is a
warning, because `-n host` and `-n none` still work. The exit status is 1 when
a line says `FAIL`.

## Configuration

The config is `~/.config/corral/config.toml`, or the same path under
`$XDG_CONFIG_HOME`. [`config.example.toml`](config.example.toml) shows every
key.

| key | meaning |
|-----|---------|
| `homes` | host directory with one `$HOME` per sandbox user, default `~/.local/share/corral/homes` |
| `default_user` | user when `-u` is not given |
| `network` | `private`, `host` or `none`, see [Networking](#networking) |
| `mounts` | mounts for every sandbox, same syntax as `-m` |
| `env` | variables for every sandbox, same syntax as `-e` |

corral asks for `homes`, `default_user` and `network` when they are missing.
Delete the file to answer all of them again.

A value can contain `$(command)`, `$NAME` and `${NAME}`, so the file can name
a secret without the secret in it:

```toml
env = ["GH_TOKEN=$(pass github/token)", "DATA=$HOME/datasets"]
```

The commands run on the host with `sh -c`, at every start and also for `list`
and `remove`. They use your terminal for stdin and stderr, so `pass` can ask
for the passphrase. Trailing newlines are removed. A failed command or an unset
variable stops the run. `$$` is a literal `$`. The parentheses in a command
must balance.

A host path under `mounts` must be absolute or start with `~`. `--force` does
not apply to these mounts. Every start prints the config mounts and variables
on stderr, because a mount that stays from run to run is easy to forget:

```
$ corral
/home/you/.config/corral/config.toml: -m '~/datasets:/data:ro' -m /srv/cache:/cache:rw -e RUST_LOG=debug
```

This line, and the file that corral writes back, show the text as written and
not the expanded value. A `$(pass ...)` entry does not show the secret, but a
literal `NAME=VALUE` entry does.

## The project file

A `.corral.toml` in the working directory holds the `-n`, `-u`, `-m` and `-e`
values that a project always needs. It uses the same syntax:

```toml
network = "host"
user = "myproject"
mounts = ["../core", "/data/fixtures:/data:ro"]
env = ["RUST_LOG=debug"]
```

A relative mount path resolves against the project directory. A bare name under
`env` forwards the host value.

The order is config, then project file, then flags. `-n` and `-u` replace the
earlier value. Mounts and variables add up, and a later entry for the same
target or name replaces the earlier one.

The file comes with a repository, so corral trusts it less than the config:

- It expands nothing, so a `$(command)` in it does not run.
- corral does not look in parent directories.
- `--force` does not apply to its mounts, and a `force` key is refused.

Every start prints what the file added:

```
$ corral
.corral.toml: -n host -u myproject -m ../core -m /data/fixtures:/data:ro -e RUST_LOG=debug
```

For a repository that you did not write, read this line or the file. corral
refuses only `$HOME` and `/`, so a file that mounts
`/run/user/1000/gnupg/S.gpg-agent.ssh` is accepted.

## Sandbox users

`-u NAME` binds `<homes>/NAME` at `/home/NAME`. corral asks before it creates a
missing home, and fills a new home from `/etc/skel`. The name must match
`^[a-z_][a-z0-9_-]{0,31}$`.

No host account is created. corral writes a `passwd` file with the sandbox user
and binds it over `/etc/passwd`, so `$HOME` and `getpwuid()` give the same
home.

All sandbox users run under your host uid. They keep configuration, credentials
and agent state apart. They are not a privilege boundary.

```
$ corral list
USER     SIZE  LAST USED         HOME
corral   1.2G  2026-09-19 08:39  /home/you/.local/share/corral/homes/corral
review     0B  never             /home/you/.local/share/corral/homes/review
rust     334M  2026-09-12 17:02  /home/you/.local/share/corral/homes/rust
```

`LAST USED` is the modification time of the generated `passwd`, which corral
writes at every start. A home made by hand shows `never`.

`corral remove NAME` deletes a home and its generated files, after a
confirmation that shows the path and the size. It takes a user name, not a
path. It refuses a name that is not a valid user name and a symbolic link in
`homes`. `list` does not show them.

To run a program called `list`, `remove` or `check`, put `--` before it.

## Filesystem

The project directory has the same path inside as on the host
(`--bind "$PWD" "$PWD"`). Build output and tool state keep absolute paths:
cargo dep files, `compile_commands.json`, ccache, LSP indexes, agent sessions
keyed by directory. With one path, you can use them from both sides. corral
refuses `$HOME` and `/` as the project directory or as a mount source, unless
you give `--force`.

These are the only writable paths:

- The project directory, unless you give `-m .::ro`. The writes go to the host.
- `/home/<user>`, which is `<homes>/<user>` on the host.
- `/tmp`, `/var/tmp` and `$XDG_RUNTIME_DIR`. They are new tmpfs mounts, and
  their contents go at exit.

A write anywhere else fails:

```
$ touch /usr/local/bin/pwned
touch: cannot touch '/usr/local/bin/pwned': Read-only file system
```

This includes the tmpfs mount points that corral makes to hold a bind, such as
`/home/you` above a project at `/home/you/work/project`. A write in the wrong
place fails, and does not disappear at exit without a sign. For a writable
layer that disappears, use [`:tmp`](#tmp-mounts) on one directory.

These are hidden:

- `/home` is a tmpfs. It contains the sandbox home and the path down to the
  project, and nothing more. A symbolic link out of the project resolves in
  the sandbox, where the target is missing.
- `$XDG_RUNTIME_DIR` is a tmpfs. A read-only bind does not stop `connect()` on
  a unix socket, so without the tmpfs the sandbox can use the host ssh and gpg
  agents, and sign and push as you.
- `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME` are unset. `PATH`
  entries under your real home are removed.

To give the host ssh agent to the sandbox:

```
corral -m /run/user/1000/gnupg/S.gpg-agent.ssh -e SSH_AUTH_SOCK
```

`PATH` starts with `/home/<user>/.local/bin:/home/<user>/.cargo/bin`, so a tool
in the sandbox home comes before the host copy. All other software comes from
the host rootfs. There is no image to pin or rebuild.

## Extra mounts

```
corral -m ../core                  # read only, same path inside
corral -m /data/sets:/data:rw      # writable, at a chosen path
corral -m ../core -m ../docs       # repeatable
corral -m ~/notes:~/notes:rw       # into the sandbox home
```

The syntax is `HOST[:GUEST[:MODE]]`. GUEST is the host path when not given, so
a relative path such as a cargo path dependency on `../core` still resolves. A
given GUEST must be absolute or start with `~`. MODE is `ro` (default), `rw` or
`tmp`. The source must exist.

In HOST, `~` is your home. In GUEST, `~` is the sandbox home, so one mount fits
all sandbox users. `~name` is refused in GUEST.

When the mount point is missing:

- Under `~`, corral creates it in the sandbox home on the host. It stays there
  after exit.
- Inside the project, `bwrap` creates it in the project on the host.
- Elsewhere, corral replaces the parent with a read-only tmpfs and binds the
  real entries of the parent back. The parent must exist: `-m src:/srv/data`
  works when `/srv` exists, `-m src:/a/b/c` fails when `/a` does not.

corral makes these mount points before its own mounts, so `-m src:/data`, which
replaces `/`, does not remove the `/home` tmpfs.

A mount inside the project goes after the project bind. `-m .::ro` makes the
whole project read only, and `-m ./vendor::ro` one directory. A project file
can ask for `mounts = [".::ro"]`.

## `:tmp` mounts

```
corral -m ./vendor/sdk::tmp ./configure
corral -m /data/fixtures:/data:tmp
```

The host path is the read-only lower layer of an overlay, and a tmpfs above it
gets the writes. The program can write and read back. The host does not
change, and the writes go at exit. They use RAM.

The limits come from overlayfs:

- Only your own files can change. A copy-up keeps the owner of the original,
  and the sandbox maps only your uid, so a write to a root-owned file fails
  with `Permission denied`. An overlay on a root-owned tree takes new entries
  at its top level and nothing deeper. `corral -m /usr::tmp make install` does
  not work.
- The source must not contain a mount point. corral reads
  `/proc/self/mountinfo` and names it. On a host with a separate `/var/log`
  mount, `/var` cannot be a `:tmp` source.
- Two `:tmp` sources must not nest. The kernel accepts this but the result is
  not defined, so corral refuses it.

The overlays go after every bind and before the generated `/etc/passwd`. Thus
the project bind does not cover an overlay inside the project, and
`-m /etc::tmp` does not cover the generated `passwd`.

`-m .::tmp` makes the whole project a temporary copy. A build script can write
and finish, and the checkout does not change.

## Environment variables

```
corral -e RUST_LOG=debug    # explicit value
corral -e GITHUB_TOKEN      # forward the host's value
corral -e A=1 -e B=2        # repeatable
```

To forward a name that the host does not have is an error, because an empty
variable and a missing one look the same inside.

corral sets three variables:

| variable | value |
|----------|-------|
| `CORRAL` | `1` |
| `CORRAL_USER` | the sandbox user name |
| `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN` | `1`, because the alternate screen has no scrollback. `-e CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=` removes it. |

Use `CORRAL` to know that you are in a sandbox. `USER`, `$HOME`, the hostname
and the uid do not tell you.

```sh
[ -n "$CORRAL" ] || { echo "refusing to run outside corral" >&2; exit 1; }
PS1="(${CORRAL_USER}) ${PS1}"   # in the sandbox .bashrc
```

corral does not start inside a sandbox. `env -u CORRAL corral` starts it
anyway, but the inner sandbox sees only the read-only rootfs and the empty
`/home` of the outer one.

## Networking

| mode | host loopback services | LAN and internet | binds a host port |
|------|------------------------|------------------|-------------------|
| `private` | unreachable | reachable | no |
| `host` | reachable | reachable | yes |
| `none` | unreachable | unreachable | no |

`private` is the default. The sandbox gets its own network namespace, with
`pasta` as a userspace network stack. Outbound traffic works. Services on the
host `127.0.0.1` do not answer, and two sandboxes do not compete for host
ports. corral starts `pasta` with port forwarding off in both directions and
with `--no-map-gw`. Each of the `pasta` defaults makes the host loopback
reachable again. Do not remove these flags.

`host` shares the network namespace of the host. Use it to reach a service on
the host loopback, or to let the host reach the sandbox.

`none` has no network. Name lookups can still answer through the unix socket
of the host resolver, but no traffic goes out.

`-n` overrides the config and the project file.

## Running a command

```
corral claude
corral cargo test
corral -u throwaway opencode
corral claude --resume          # --resume goes to claude
corral -- ./-weird-name
corral cargo test -- --nocapture
```

The command starts at the first argument that is not a corral option. Put `--`
before a command that starts with a dash. The command runs in a login shell,
and its exit status is the exit status of corral.

## Uid and capabilities

The sandbox runs as your host uid and gid in every network mode, under the
name of the sandbox user. Host files that root owns show as `nobody`.

The sandbox has no capabilities, also when you start corral as root. bwrap
makes the read-only binds and the tmpfs mounts in the user namespace of the
sandbox. A capability in that namespace is enough to unmount them or to make
them writable.

## Limits

corral limits the filesystem and the host loopback. It is not a security
boundary against hostile code.

- The start directory is fully writable. A start in `~/work` gives all of
  `~/work`.
- `private` and `host` have full outbound access, the LAN included.
- Anything in a sandbox can use the credentials in its home. After
  `gh auth login`, an agent can push and read private repositories.
- Sandbox users share your uid.
- The hostname `corral` does not resolve when `nsswitch.conf` puts `resolve`
  before `files`. Tools that look up their own hostname can warn.

The PID and IPC namespaces are not shared with the host.

## Tests

```
$ ./tests/corral-test
```

The suite needs `bwrap` and no config. It writes its own `config.toml` under a
temporary `XDG_CONFIG_HOME`. It also uses a temporary directory in `$TMPDIR`
and one under `$HOME`, because a project below `/home` is one of the tested
cases. It removes all of them at exit.

The `private` tests skip when `pasta` cannot run, for example in a corral
sandbox without `/dev/net/tun`. The `:tmp` tests skip with `bwrap` older than
0.11.0. The output shows the skips apart from the passes.

CI uses `ubuntu-26.04`, because `ubuntu-latest` is 24.04 with `bubblewrap`
0.9.0. The workflow sets the AppArmor user namespace sysctl to 0 first. On a
recent Ubuntu workstation, corral can fail for the same reason, and
`corral check` names it.

## License

MIT, see [LICENSE](LICENSE).
