# Security policy

## Supported versions

Security fixes go into the newest release. Please update before reporting, and
check whether the problem is still there.

| Version | Supported |
| --- | --- |
| 0.20.x (latest release) | Yes |
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
