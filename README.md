# CORRAL

Runs an interactive shell with the current directory writable and the whole
rest of the host read only. The point is to give a coding agent a blast radius
limited to the directory you started it in. There is no daemon, no image and
no container. Two unprivileged binaries do the work, and startup costs
nothing.

## Usage

```
corral                    # run as the default user from the config
corral -u throwaway       # run as another sandbox user
corral -m ../core         # also mount a sibling, read only, same path inside
corral -m /data:/data:rw  # mount a chosen path, writable
corral -m ./sdk::tmp      # writable, but the writes vanish at exit
corral -e RUST_LOG=1      # set a variable inside for this run
corral -e GITHUB_TOKEN    # forward the host's value for this run
corral -n host            # share the host's network for this run
corral --dry-run          # print the bwrap command and exit
corral claude             # run a tool directly instead of the shell
corral --help
```

Nothing survives the exit except the project directory and the sandbox user's
home.

## Requirements

`bubblewrap`, and `passt` for the default network mode. Neither needs root,
and neither needs you in a privileged group.

```
sudo pacman -S bubblewrap passt          # Arch
sudo apt install bubblewrap passt        # Debian, Ubuntu
```

`corral` refuses to start the `private` network mode when `pasta` is absent,
rather than fall back to a weaker mode without a word. `:tmp` mounts need
`bubblewrap` 0.11.0 or newer, which Ubuntu 24.04 does not have, and `corral`
says so instead of leaving `bwrap` to fail on an unknown option.

## Configuration

Settings live in `~/.config/corral/config.json` (or under `$XDG_CONFIG_HOME`).

| key | meaning |
|-----|---------|
| `homes` | host directory holding one `$HOME` per sandbox user |
| `tools` | host directory holding a shared toolchain, mounted read only at `/opt/corral`, empty for none |
| `default_user` | user to run as when `--user` is not given |
| `network` | `private`, `host` or `none`, see [Networking](#networking) |

Each key is asked for only when it is missing, so a setting added later asks
about that one alone. Delete the file to be asked everything again.

`homes` defaults to `~/.local/share/corral/homes`.

Settings that belong to one project go in its own
[`.corral.json`](#the-project-file) instead.

## The project file

A `.corral.json` in the project directory holds the flags that the project
always needs, so that nobody retypes them and everyone who clones the
repository gets the same sandbox:

```json
{
  "network": "host",
  "user": "myproject",
  "mounts": ["../core", "/data/fixtures:/data:ro"],
  "env": ["RUST_LOG=debug"]
}
```

The four keys stand for `-n`, `-u`, `-m` and `-e`, with the same syntax and
the same rules. A relative mount path resolves against the project directory.
A bare name under `env` forwards the host's value, as `-e NAME` does.

A flag always wins. `-n` and `-u` replace the file's value. Mounts and
variables add up, with the flag's after the file's, so a flag that names the
same target or the same variable covers the file's entry.

Only the working directory is looked at. A file in a parent directory is not
read, because walking upward is how a file you have never read ends up
applying to you. For the same reason the file cannot lift the guard on `$HOME`
and `/`: `--force` does not extend to its mounts, and a `force` key is
refused.

Before the sandbox starts, one line on stderr names the file and lists what it
added, as the flags it stands for, minus the entries a flag replaced:

```
$ corral
.corral.json: -n host -u myproject -m ../core -m /data/fixtures:/data:ro -e RUST_LOG=debug
```

That line is the whole safeguard for a repository you did not write. The guard
stops `$HOME` and `/` and nothing else, so a file that mounts
`/run/user/1000/gnupg/S.gpg-agent.ssh` is accepted, printed, and mounted. Read
the line, or read the file first.

## Sandbox users

`--user NAME` binds `<homes>/NAME` at `/home/NAME` and runs under that name.
A missing directory is created after a confirmation prompt, so a typo cannot
silently leave a stray home behind. A fresh home is seeded from `/etc/skel`.

The name must match `^[a-z_][a-z0-9_-]{0,31}$`, because it becomes a passwd
entry and a directory name.

There is no `useradd`, and no account is created on the host. `corral` generates
a `passwd` file whose entry names the sandbox user, and binds it over
`/etc/passwd`. That matters because tools disagree on how to find a home:
some read `$HOME`, others call `getpwuid()`. Both have to give the same
answer, or agent state lands in a directory that was never mounted.

The separation is the home, and only the home. Every sandbox user runs under
your own host uid, so this is a way to keep configurations, credentials and
agent state apart. It is not a privilege boundary between them.

## The working directory

The sandbox is started with

```
--bind "$PWD" "$PWD" --chdir "$PWD"
```

so `/home/davxy/foo/bar/project` on the host is the exact same path inside.
This is deliberate.

Absolute paths get baked into build output and tool state: dep files under
cargo's `target/`, `compile_commands.json`, ccache entries, coverage data, LSP
indexes, agent session files keyed by cwd. If the path differed inside and
outside, every one of those would become wrong the moment you switched between
the two. A mirrored path lets you alternate freely. It also means a path in a
stack trace copied out of the sandbox is a path your host editor can open.

`$HOME` and `/` are refused as the project directory, because everything below
them would come along. `--force` overrides that.

## What you can write

You are not root on the host, and the rootfs arrives read only, so:

- Everything under the project directory is a real host write. Files come out
  owned by you, including deletions and overwrites.
- `/home/<user>` is a real host write, landing in `<homes>/<user>`.
- `/tmp`, `/var/tmp` and `$XDG_RUNTIME_DIR` are fresh tmpfs mounts. Writes
  there succeed and are discarded on exit.
- Everywhere else the write fails outright:

```
$ touch /usr/local/bin/pwned
touch: cannot touch '/usr/local/bin/pwned': Read-only file system
```

That list is exhaustive, and the mount points corral has to invent are the
reason it needs saying. `/home` is a tmpfs, so the directories standing above a
project at `/home/you/work/project` are tmpfs too, and so is a directory
conjured to hold a `-m` target. Those exist to carry a mount and nothing else.
Left writable they would take a write and lose it at exit — the quiet loss
this whole arrangement is meant to turn into an error — so they are remounted
read only once every bind is in place:

```
$ touch /home/you/stray
touch: cannot touch '/home/you/stray': Read-only file system
```

`/tmp`, `/var/tmp` and `$XDG_RUNTIME_DIR` are left writable, because those are
scratch and everything expects to write there.

Docker gives you a writable overlay, so a stray write outside the project
succeeds and then evaporates. Here it fails, unless you ask for that overlay on
one directory with [`:tmp`](#writes-that-go-nowhere). A tool that writes to an
unexpected path breaks instead of losing data quietly. Which of those you
prefer is a real question, and the answer is not obvious.

## What is hidden

`/home` is replaced by a tmpfs, so no real home survives. Only the sandbox
user's home is bound back:

```
$ ls /home
corral
davxy
$ ls /home/davxy
develop
$ cat /home/davxy/.bashrc
cat: /home/davxy/.bashrc: No such file or directory
```

`/home/davxy` appears only because the project lives under it and the mount
point had to exist. It holds nothing but the path down to the project, it is
tmpfs, and it is read only, so a write into it fails rather than being
accepted and discarded.

A symlink out of the project does not escape. It resolves against the
sandbox namespace, where the target is not there:

```
$ cat escape-link
cat: escape-link: No such file or directory
```

`$XDG_RUNTIME_DIR` is replaced by a tmpfs as well, and that one is not
cosmetic. A read-only bind does not stop `connect()` on a unix socket, so a
sandbox that left the host's runtime directory in place would hand over the
live ssh and gpg agents. Measured, before the tmpfs was added:

```
$ SSH_AUTH_SOCK=/run/user/1000/gnupg/S.gpg-agent.ssh ssh-add -l
256 SHA256:RSj/... cardno:19_341_535 (ED25519)
```

An agent that reaches that socket can sign and push as you, whatever the
filesystem says. Docker never had this problem, because it never mounted
`/run`.

For the same reason `SSH_AUTH_SOCK` and `DBUS_SESSION_BUS_ADDRESS` are
unset inside, along with `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_CACHE_HOME` and `XDG_STATE_HOME`. Those last four would otherwise send
agent config back out to your own home, which is the exact split the sandbox
users exist to keep. `PATH` entries under your real home are dropped too,
since they point at directories that are no longer there.

If you do want the host agent, ask for it:

```
corral -m /run/user/1000/gnupg/S.gpg-agent.ssh -e SSH_AUTH_SOCK
```

## Extra mounts

`-m`/`--mount` binds one more host path:

```
corral -m ../core                  # read only, same path inside
corral -m /data/sets:/data:rw      # writable, at a chosen path
corral -m ../core -m ../docs       # repeatable
```

GUEST defaults to the host path, mirrored the same way the project directory
is, so a relative reference such as a cargo path dependency on `../core` keeps
resolving inside. A GUEST that is given must be absolute. Mounts are read only
unless `:rw` is appended, or `:tmp` for
[writes that go nowhere](#writes-that-go-nowhere).

The source has to exist, and the refusal of `$HOME` and `/` applies to mount
sources too, with `--force` overriding it as usual. There is deliberately no
key for this in the global config. A mount that persisted invisibly across
sessions is a hole you would forget about, while a flag you retype keeps it
intentional. A mount that one project always needs goes in that project's
[`.corral.json`](#the-project-file), which is committed and shows in every
diff.

When the guest path does not exist on the read-only rootfs, `corral` replaces
its parent with a tmpfs so the mount point can be created, and binds the
parent's real entries back so that nothing else disappears. The parent itself
has to exist: `-m src:/srv/data` works when `/srv` is there, `-m src:/a/b/c`
does not when `/a` is not.

`-m src:/data` names a parent of `/`, so that replacement is the whole rootfs.
It still works, because the invented mount points are laid down before the
sandbox's own mounts rather than over them. The order matters more than it
looks: re-binding a parent's real entries brings back its directories, not the
mounts that were made inside it, so doing this last would drop a tmpfs over
`/`, undo the one over `/home`, and bind the host's real home back in its
place — read only, and entirely readable. Invented parents are read only, like
the rest of the [skeleton](#what-you-can-write).

## Writes that go nowhere

`:tmp` is the third mount mode. The host path becomes a read-only lower layer,
and a tmpfs above it takes every write. The program writes, reads back what it
wrote, and carries on. The host directory never changes, and the writes are
gone at the next run.

```
corral -m ./vendor/sdk::tmp ./configure
corral -m /data/fixtures:/data:tmp
```

That is the Docker behaviour, one directory at a time and only when asked for.
`:ro` fails the write and `:rw` keeps it on the host, so `:tmp` is the only
mode that lets a program finish a write you do not want to keep.

Three limits come with it, and none of them is corral's own:

- Only files that you own can change. overlayfs copies a file up to the tmpfs
  before the first write to it, and the copy keeps the owner of the original.
  The sandbox maps one user id, so a copy of a root-owned file has no owner to
  keep and the write fails with `Permission denied`. An overlay over a
  root-owned tree takes new entries at its top level and nothing deeper.
  `corral -m /usr::tmp make install` does not work.
- The source must hold no mount point. overlayfs rejects such a lower layer
  with `Invalid argument` from deep inside bwrap, so corral reads
  `/proc/self/mountinfo` first and names the mount point instead. Which paths
  that rules out depends on the host: a separate mount for `/var/log` puts
  `/var` out of reach.
- Two `:tmp` sources must not nest. overlayfs leaves that case undefined rather
  than refuse it, and the kernel accepts it without a word, so corral refuses
  it instead.

The tmpfs keeps the writes in memory, so a large one costs RAM.

An overlay covers whatever already stands at its target, so it goes on after
every bind and before the generated `/etc/passwd`. Both ends of that matter.
An overlay on a directory inside the project needs the project bound first, or
the bind would cover the overlay and the writes it was asked to throw away
would land on the host. `-m /etc::tmp` needs the opposite, so the generated
passwd is bound last and stays on top of it.

`-m .::tmp` names the project itself, which covers the project bind and makes
the whole working directory a throwaway copy. That is a real use, and it is
also the one case where the [first promise of this tool](#the-working-directory)
stops holding, so it takes an explicit flag to get.

## Environment variables

`-e`/`--env` sets a variable, or forwards the host's value:

```
corral -e RUST_LOG=debug    # explicit value
corral -e GITHUB_TOKEN      # forward the host's value
corral -e A=1 -e B=2        # repeatable
```

Forwarding a name the host does not have is an error, not a silent no-op,
since an empty variable and an unforwarded one look identical from inside.

Three variables are set by default. `CORRAL` and `CORRAL_USER` are described
under [Knowing you are inside](#knowing-you-are-inside). The third is
`CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`, because claude otherwise renders in
the alternate screen, which terminals keep no scrollback for.
`-e CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=` restores the stock rendering.

The flag is per run by design. For a variable that one project always needs,
use its [`.corral.json`](#the-project-file). For one you always want, export
it from the sandbox home's `.bashrc`, above the guard that returns early for
non-interactive shells, so that a command run without the prompt picks it up
too.

## Knowing you are inside

Every sandbox gets two variables:

| variable | value |
|----------|-------|
| `CORRAL` | `1`, always |
| `CORRAL_USER` | the sandbox user's name |

Nothing else inside answers the question reliably. `USER` and `$HOME` are
whatever `--user` said, the hostname is fixed but a host can be called `corral`
too, and `uid=0` is [not what it looks like](#why-the-sandbox-runs-as-uid-0).
So a script that must not run on the host, a prompt that should say where it
is, or an agent hook that behaves differently in a sandbox, all test `CORRAL`:

```sh
[ -n "$CORRAL" ] || { echo "refusing to run outside corral" >&2; exit 1; }
```

In the sandbox home's `.bashrc`, above the non-interactive guard:

```sh
PS1="(${CORRAL_USER}) ${PS1}"
```

The same variable stops corral nesting inside itself:

```
$ corral
[corral@corral project]# corral
already inside the 'corral' sandbox.
Exit first, or run 'env -u CORRAL corral' to nest deliberately.
```

Nesting mostly works, and what it produces is never what was meant: the inner
sandbox is built out of the outer one's read-only rootfs and emptied `/home`,
so the host it claims to be hiding is already gone. The escape hatch is there
because the refusal is a convenience, not a rule.

## Networking

| mode | host loopback services | LAN and internet | binds a host port |
|------|------------------------|------------------|-------------------|
| `private` | unreachable | reachable | no |
| `host` | reachable | reachable | yes |
| `none` | unreachable | unreachable | no |

`private`, the default, gives the sandbox its own network namespace with a
userspace network stack, `pasta` from the `passt` package. Outbound traffic
works, which is all the agents need to reach their APIs, but services the host
has bound to `127.0.0.1` no longer answer, and two sandboxes at once do not
compete for host ports. This is what Docker's `bridge` mode bought, without
the bridge, the NAT rules or the daemon.

`pasta` is invoked with port forwarding off in both directions and with
`--no-map-gw`. Left to its defaults it forwards every port bound on the host
into the sandbox, binds every port the sandbox opens on the host, and maps the
host onto the gateway address. Each of the three would put the loopback back
within reach. Do not remove those flags.

`host` shares the host's network namespace. Take it when you develop something
that has to be reached from the host, or that has to talk to a database or a
model runner already on the host's loopback. The cost is that everything else
on that loopback is reachable too.

`none` unshares the network with nothing attached. Name lookups may still
answer, because the host resolver is reachable over a unix socket, but no
traffic leaves.

`-n`/`--net` overrides the config and the project file for a single run.

## Running a tool directly

Give corral a command and it replaces the interactive shell:

```
corral claude
corral cargo test
corral -u throwaway opencode
```

corral's own options come first. The command is everything from the first
argument that is not one of them, so its flags need no escaping:

```
corral claude --resume     # --resume goes to claude
corral --resume claude     # error: corral has no --resume
```

A command that starts with a dash needs `--` in front of it. That first `--`
is corral's; a second one belongs to the command:

```
corral -- ./-weird-name
corral cargo test -- --nocapture
```

The command runs through a login shell, so it sees the same `PATH` and profile
environment you would get at the prompt, and bare tool names resolve. Its exit
status becomes corral's, which makes this usable from scripts and CI.

## The shared toolchain

`tools` in the config names a host directory that is mounted read only at
`/opt/corral`. `PATH` inside is

```
/home/<user>/.local/bin:/home/<user>/.cargo/bin:/opt/corral/.local/bin:/opt/corral/.cargo/bin:<inherited>
```

so the per-user directories take precedence, and what a user installs on top
shadows the shared copy.

The guest path is fixed on purpose. rustup proxies, uv shims and Python entry
points hardcode absolute paths into what they install, so the directory only
works when it comes back at the same path every run.

`corral` does not provision it. It only mounts a directory that already exists.
Run the installers yourself with the directory mounted writable and `HOME`
pointed at it. A `tools` path that does not exist produces a warning on stderr
and no mount.

Everything else comes from the host rootfs. There is no base image, no
package list and no `--rebuild`. That is the trade: `corral` gives up a pinned,
disposable distribution in exchange for having no image at all.

## Why the sandbox runs as uid 0

`id` inside says `uid=0`, and bash draws a `#` prompt. That is not host root.

Creating a network namespace needs `CAP_NET_ADMIN`, which an unprivileged user
only gets by becoming root inside a new user namespace. `pasta` does exactly
that, with a uid map of `0 <your uid> 1`, so uid 0 is the only uid that exists
inside. A nested user namespace cannot map a uid its parent does not have, so
there is no way back to your real number under `private`.

Rather than let the identity change with the network flag, `corral` passes
`--unshare-user --uid 0 --gid 0` in every mode. That 0 maps to your own
unprivileged host uid. Files come out owned by you, and it grants nothing
anywhere on the host:

```
$ sudo -n true
sudo: /etc/sudo.conf is owned by uid 65534, should be 0
sudo: unable to open /etc/sudoers: Invalid argument
```

Host files owned by real root appear as `nobody`, because root is not in the
map.

## What is not isolated

This bounds the filesystem and the host's own loopback. It is not a security
boundary against something actively hostile.

- Whatever directory you start in is fully writable. The protection is a
  function of where you start: `$HOME` and `/` are refused unless `--force`
  is passed, but anything below them is fair game, and a launch from `~/work`
  mounts everything under it without a word.
- Outbound network access is unrestricted in `private` and `host`. The LAN is
  reachable in both. `private` keeps the sandbox off the host's loopback and
  nothing more.
- `host` gives up the network namespace entirely, so the sandbox sees every
  service on the host, including ones bound only to `127.0.0.1`, and can bind
  host ports.
- Credentials in the sandbox home are usable by anything in it. Once
  `gh auth login` has run there, an agent in that sandbox can push, open pull
  requests and read private repositories. A bound on the filesystem says
  nothing about what the credentials inside it reach.
- Sandbox users are separated by home directory, not by uid.

The PID and IPC namespaces are not shared, so host processes are neither
visible nor reachable through shared memory.

## Warts

- The prompt ends in `#` and `whoami` agrees with the passwd entry, but `id`
  reports uid 0. See [above](#why-the-sandbox-runs-as-uid-0). Nothing is
  wrong, and it does read as alarming the first time.
- The hostname is fixed to `corral`, and it does not resolve. On a system whose
  `nsswitch.conf` puts `resolve` ahead of `files`, no generated `/etc/hosts`
  can fix that, because systemd-resolved answers first and the search stops.
  Tools that look their own hostname up may warn.

## Tests

`tests/corral-test` asserts 142 properties of the sandbox: what is writable,
what is hidden, that each network mode differs from the others, that the host
agent socket is out of reach, that a project under `/home` survives the tmpfs
that empties it, and that a `.corral.json` adds what it says and no more.

```
$ ./tests/corral-test
...
137 passed, 0 failed, 5 skipped
```

It needs no configuration: it writes its own `config.json` under a temporary
`XDG_CONFIG_HOME`, so an existing one is neither read nor disturbed. It writes
under two temporary directories, one in `$TMPDIR` and one under `$HOME`,
because *a project below `/home` still works* is one of the properties being
asserted. Both are removed on exit, as is the single socket the
agent-reachability test has to place in `$XDG_RUNTIME_DIR`.

`bwrap` is required. The four `private`-mode assertions additionally need
`pasta` to be able to run, and report `skip` when it cannot — which is what
happens inside a sandbox with no `/dev/net/tun`, since running the suite from
inside corral is a normal thing to do. The `:tmp` assertions need a `bwrap`
with the overlay options, 0.11.0 or newer, and report one `skip` on an older
one. A skip is printed, never folded into the pass count.

CI runs the suite on `ubuntu-26.04` (`.github/workflows/test.yml`), because
`ubuntu-latest` is still 24.04 and its `bubblewrap` is 0.9.0. Ubuntu 23.10
and later deny unprivileged user namespaces by AppArmor policy, which
corral cannot work without, so the workflow lifts that sysctl before running.
The same policy is why corral may fail out of the box on a recent Ubuntu
workstation.

## License

MIT, see [LICENSE](LICENSE).
