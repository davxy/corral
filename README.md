# CORRAL

Runs a shell with the current directory writable and the rest of the host read
only. A coding agent can then damage only the directory you start it in. There
is no daemon, no image and no container: `bwrap` and `pasta` do the work, and
neither needs root. Linux only.

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
corral --version
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

On a new machine, run `corral check` first:

```
$ corral check
bwrap                                         ok    bubblewrap 0.12.0
user namespace                                ok    bwrap can create one
kernel.apparmor_restrict_unprivileged_userns  ok    absent
kernel.unprivileged_userns_clone              ok    1
user.max_user_namespaces                      ok    2147483647
dev.tty.legacy_tiocsti                        ok    0, and the seccomp filter of corral refuses TIOCSTI
pasta                                         ok    pasta 2026_07_28.f8df3f1
```

`user namespace` is the result that matters. When it fails, the sysctl lines
show the usual cause and the fix. Ubuntu 23.10 and later block user
namespaces with AppArmor. The exit status is 1 when a line says `FAIL`.

## Configuration

The config is `~/.config/corral/config.toml`, or the same path under
`$XDG_CONFIG_HOME`. The file and each key are optional.
[`config.example.toml`](config.example.toml) shows every key.

| key | meaning |
|-----|---------|
| `homes` | host directory with one `$HOME` per sandbox user, default `~/.local/share/corral/homes` |
| `default_user` | user when `-u` is not given, default `corral` |
| `network` | `private` (default), `host` or `none`, see [Networking](#networking) |
| `mounts` | mounts for every sandbox, same syntax as `-m` |
| `env` | variables for every sandbox, same syntax as `-e` |
| `hide` | more files and directories to hide, see [Filesystem](#filesystem) |
| `shell` | interactive shell, default `$SHELL`, see [Running a command](#running-a-command) |

A value can contain `$(command)`, `$NAME` and `${NAME}`, so the file can name
a secret without the secret in it:

```toml
env = ["GH_TOKEN=$(pass github/token)", "DATA=$HOME/datasets"]
```

The commands run on the host with `sh -c` at every start, with your terminal
as stdin, so `pass` can ask for the passphrase. A failed command or an unset
variable stops the run. `$$` is a literal `$`.

A host path under `mounts` must be absolute or start with `~`, and `--force`
does not apply to it. Every start prints the config mounts and variables on
stderr, as written, not expanded. A literal `NAME=VALUE` shows its value:

```
$ corral
/home/you/.config/corral/config.toml: -m '~/datasets:/data:ro' -e RUST_LOG=debug
```

## The project file

A `.corral.toml` in the working directory holds the `-n`, `-u`, `-m` and `-e`
values that a project always needs:

```toml
network = "host"
user = "myproject"
mounts = ["../core", "/data/fixtures:/data:ro"]
env = ["RUST_LOG=debug"]
```

The order is config, then project file, then flags. `-n` and `-u` replace the
earlier value. Mounts and variables add up, and a later entry for the same
target or name wins.

The file comes with a repository, so corral trusts it less than the config. It
expands nothing, `--force` does not apply to it, and corral does not look for
it in parent directories. Every start prints what it added:

```
$ corral
.corral.toml: -n host -u myproject -m ../core -m /data/fixtures:/data:ro -e RUST_LOG=debug
```

Read this line for a repository that you did not write. A project file can
mount any path except `$HOME`, `/` and the parents of hidden directories.

## Sandbox users

`-u NAME` binds `<homes>/NAME` at `/home/NAME`. corral creates a missing home
from `/etc/skel`. A generated `passwd` gives the sandbox user, so `$HOME` and
`getpwuid()` agree. No host account is created.

The sandbox users keep configuration, credentials and agent state apart. They
all run under your uid, so they are not a privilege boundary.

```
$ corral list
USER     SIZE  LAST USED         HOME
corral   1.2G  2026-09-19 08:39  /home/you/.local/share/corral/homes/corral
review     0B  never             /home/you/.local/share/corral/homes/review
```

`corral remove NAME` deletes a home after a confirmation. To run a program
called `list`, `remove` or `check`, put `--` before it.

## Filesystem

The project directory has the same path inside as on the host, so absolute
paths in build output, LSP indexes and agent sessions work on both sides.
corral refuses `$HOME` and `/` as the project or as a mount source, unless you
give `--force`.

Writable:

- the project directory, unless you give `-m .::ro`;
- `/home/<user>`, which is `<homes>/<user>` on the host;
- `/tmp`, `/var/tmp` and `$XDG_RUNTIME_DIR`, which are empty and go at exit.

A write anywhere else fails with `Read-only file system`.

Hidden:

- `/home`, and your real home where it is not under `/home`. They hold your
  ssh and gpg keys and the tokens of your tools. Read-only is not enough,
  because an agent can read them and send them out. Only the sandbox home and
  the path down to the project are left.
- Each directory under the `hide` key, in the same way. With
  `hide = ["/mnt/ssd/develop"]`, a project there does not see the projects
  next to it. corral refuses a mount or a start in a parent of a hidden
  directory, because that shows it again. `--force` lifts this for `-m` and
  the start directory.
- `$XDG_RUNTIME_DIR`, which holds the sockets of the ssh and gpg agents.
- The sockets of Docker, containerd, podman, libvirt and pcscd, and the files
  under the `hide` key. corral covers them with `/dev/null`. Access to the
  Docker socket is root on the host.
- `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS` and the `XDG_*_HOME` variables.
  `PATH` entries under your real home.

To give the host ssh agent to the sandbox:

```
corral -m /run/user/1000/gnupg/S.gpg-agent.ssh -e SSH_AUTH_SOCK
```

`PATH` starts with `~/.local/bin` and `~/.cargo/bin` of the sandbox home. All
other software comes from the host.

## Extra mounts

```
corral -m ../core                  # read only, same path inside
corral -m /data/sets:/data:rw      # writable, at a chosen path
corral -m ~/notes:~/notes:rw       # into the sandbox home
corral -m ./vendor::ro             # one directory of the project read only
```

The syntax is `HOST[:GUEST[:MODE]]`, and `-m` is repeatable. GUEST is the host
path when not given. MODE is `ro` (default), `rw` or `tmp`. In HOST, `~` is
your home. In GUEST, `~` is the sandbox home.

A missing mount point is created. In the project and the sandbox home, it stays
on the host after exit. Elsewhere, its parent must exist on the host.

## `:tmp` mounts

```
corral -m ./vendor/sdk::tmp ./configure
corral -m .::tmp                   # the whole project as a throwaway copy
```

The host path becomes the lower layer of an overlay. The sandbox can write,
the host does not change, and the writes go at exit. They use RAM. Limits from
overlayfs:

- Only your own files can change. `corral -m /usr::tmp make install` fails.
- The source must not contain a mount point, and two sources must not nest.
  corral refuses both.

## Environment variables

```
corral -e RUST_LOG=debug    # explicit value
corral -e GITHUB_TOKEN      # forward the host's value, an error if unset
```

corral sets:

| variable | value |
|----------|-------|
| `CORRAL` | `1` |
| `CORRAL_USER` | the sandbox user name |
| `SHELL` | the interactive shell |
| `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN` | `1`, for scrollback. `-e CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=` removes it. |

Use `CORRAL` to know that you are in a sandbox:

```sh
[ -n "$CORRAL" ] || { echo "refusing to run outside corral" >&2; exit 1; }
PS1="(${CORRAL_USER}) ${PS1}"   # in the sandbox .bashrc
```

Claude Code hides the prompt. To show the sandbox in its status line, put this
in `~/.claude/settings.json` of the sandbox home:

```json
{
  "statusLine": {
    "type": "command",
    "command": "[ -n \"$CORRAL\" ] && echo \"corral: $CORRAL_USER\""
  }
}
```

corral refuses to start inside a sandbox. `env -u CORRAL corral` forces it.

## Networking

| mode | host loopback services | LAN and internet | binds a host port |
|------|------------------------|------------------|-------------------|
| `private` | unreachable | reachable | no |
| `host` | reachable | reachable | yes |
| `none` | unreachable | unreachable | no |

`private` gives the sandbox its own network stack with `pasta`. corral turns
off the port forwarding of `pasta` and its map of the host gateway, because
each of them makes the host loopback reachable.

`host` shares the network of the host. Use it to reach a service on the host
loopback, or to let the host reach the sandbox.

`-n` overrides the config and the project file.

## Running a command

```
corral claude
corral claude --resume          # --resume goes to claude
corral -u throwaway opencode
corral -- ./-weird-name
```

The command starts at the first argument that is not a corral option. It runs
in `bash -lc`, and its exit status is the exit status of corral.

Without a command, corral starts the `shell` key, else `$SHELL`, else
`/bin/bash`, as a login shell. Your shell setup is in your hidden home, so
mount it, for example `-m ~/.config/fish:~/.config/fish`.

## Uid, capabilities and the terminal

The sandbox runs as your uid and gid, with no capabilities, also when you
start corral as root. Host files that root owns show as `nobody`.

A seccomp filter refuses the `TIOCSTI` and `TIOCLINUX` ioctls. Without it, a
process in the sandbox could type a command into the shell that started
corral. The filter covers x86_64, aarch64 and riscv64. Elsewhere,
`corral check` warns when the kernel allows `TIOCSTI`.

## Limits

corral limits the filesystem and the host loopback. It is not a security
boundary against hostile code.

- The start directory is fully writable. A start in `~/work` gives all of
  `~/work`.
- `private` and `host` have full outbound access, the LAN included.
- `-n host` reaches a daemon on a TCP port of the host loopback, for example
  `dockerd -H tcp://127.0.0.1:2375`.
- Anything in a sandbox can use the credentials in its home. After
  `gh auth login`, an agent can push and read private repositories.
- `none` still resolves names through the unix socket of the host resolver.
- The hostname `corral` does not resolve when `nsswitch.conf` puts `resolve`
  before `files`. Some tools warn.

## Tests

```
$ ./tests/corral-test
```

The suite needs `bwrap` and no config. It removes its temporary files at exit.
The `private` tests skip when `pasta` cannot run, for example inside corral,
and the `:tmp` tests skip with `bwrap` older than 0.11.0.

CI uses `ubuntu-26.04`, because `ubuntu-latest` has `bubblewrap` 0.9.0, and
sets the AppArmor user namespace sysctl to 0 first.

## License

MIT, see [LICENSE](LICENSE).
