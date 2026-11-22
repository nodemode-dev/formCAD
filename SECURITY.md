# Security policy

## Supported versions

Security fixes go into the newest release. Please update before reporting, and
check whether the problem is still there.

| Version | Supported |
| --- | --- |
| 0.23.x (latest release) | Yes |
| Anything older | No |

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Use GitHub's private
reporting instead: on the repository's **Security** tab, choose **Report a
vulnerability**. Include what you found, the steps to reproduce it, the version and
platform, and what an attacker could do with it.

You can expect an acknowledgement within a week. We will keep you informed while it
is fixed and credit you in the release notes, unless you would rather not be named.

## What counts

FormCAD runs on your own machine, so the things that matter most are the ways
something outside it could get in:

- **The engine** binds to loopback (127.0.0.1, port 8290 from source) and asks every
  request for a token made new at each start. Anything that makes it reachable from
  another machine, or lets a web page you visit call it: getting past the loopback
  check, the Host check, the Origin check or the token.
- **Agents**: the MCP server (`./formCAD mcp`), the command line and the control
  port (off unless it is asked for) running a command that touches files, processes
  or settings in a way its classification for macros and agents does not allow.
- **The agent dock**: its terminal and its Claude Code, Codex, Cursor and Antigravity
  tabs. A tab's token reaching anything but the MCP server, a token outliving its
  tab, the window's own token or the engine's settings reaching a program's
  environment or command line, or the terminal routes accepting a tab's or a macro's token.
- **Scripting**: the LISP dialect, macros and Python macros reaching outside the
  isolated process they run in, and a plug-in loading when its recorded hash does
  not match.
- **Files**: opening or importing a drawing or model (`.fcad`, DXF, SVG, STEP, IGES,
  3DM, STL, OBJ, PLY, 3MF, GLB), a node graph or a template in a way that crashes
  the engine, exhausts memory or writes outside the folder it was asked to write to.
- **The downloaded workers**: the geometry kernel and the mesher are separate
  programs the app downloads from
  [formai-binaries](https://github.com/nodemode-dev/formai-binaries) and checks
  file by file against a record shipped inside the app. Installing a file that does
  not match that record, a file the record does not list, or anything from another
  address is a vulnerability.
- **Jobs**: a simulation, generative or toolpath job that gets past its size checks
  and takes the machine down.

Bugs that need someone to already control your machine, or to run a modified build
of FormCAD, are ordinary bugs: please open an issue for those.

## What FormCAD sends over the network

FormCAD collects nothing about you and has no account, no telemetry and no update
check. It makes a request outside your computer in three cases only, each one
started by you:

- **The kernel and mesher downloads**: one archive each from the
  [formai-binaries](https://github.com/nodemode-dev/formai-binaries) releases on
  GitHub, checked file by file with SHA-256 against the record the app ships.
- **Render environments**: a larger copy of an environment is one HDR file from Poly
  Haven (`dl.polyhaven.org`), checked with SHA-256 and its size against the
  catalogue the app ships. No other host is accepted.
- **The agent dock's install lines**: when Claude Code, Codex, Cursor or Antigravity
  is missing, the dock shows the line that installs it. FormCAD never runs that
  line. A program you start in a tab talks to its own service as it does anywhere.

Nothing else is sent. A request from FormCAD to any other address is a
vulnerability, and so is any of the three happening without you asking for it.

## Who holds the session key

The engine makes one key at each start. The desktop app's own window receives it
from the app, never from a page the engine serves. Started for a browser
(`./formCAD serve`), the engine gives the key to the first page that loads and to no
later one. Agents and the command line read it from `session.token` in the data
folder, a file only your user can read. A second page, another user of the computer
or a web site getting a working key is a vulnerability.

`FORMCAD_HOST` set to anything but loopback makes the engine listen beyond this
computer and prints a warning at start. It still answers only requests whose Host is
127.0.0.1 or localhost.
