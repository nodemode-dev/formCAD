---
name: vault
description: Uses FormCAD's local vault from an agent, covering versions, branches, check in and check out, comments, diff, merge and where-used. Use when asked to version a drawing, compare two versions, find which assemblies use a part, or comment on a model.
---

# The vault

The vault is a local, content-addressed store of document versions with branches, locks, tags and comments. It never leaves the computer. An agent may read it freely and may add versions and comments; it may not create a vault, change lifecycle states, lock, pin, revise or collect garbage, and it may not pass `vault`, `author` or `force` arguments: those belong to the person and the window.

## Read

| Need | Tool | Returns |
| --- | --- | --- |
| The versions of this drawing | `cmd_vaultlog` | The version list of the drawing's vault document. |
| What changed between two versions | `cmd_vaultdiff` | The entities that differ. |
| Which assemblies use this document | `cmd_vaultwhereused` | The using assemblies, optionally for one `version`, within a `scope`. |
| Whether the store is sound | `cmd_vaultverify` | Versions rebuilt from stored objects and compared; `deep` checks every object. |

## Write

| Need | Tool | Arguments that matter |
| --- | --- | --- |
| Store the drawing as a new version | `cmd_vaultcheckin` | `message` (say what changed and why), `branch`, `keep_lock` |
| Get a version as a file | `cmd_vaultcheckout` | `version` or `branch`, `path` inside a granted folder, `edit` and `lock` to work on it, `open` |
| Give a checkout up | `cmd_vaultundo` | `path`, `restore` |
| Branch | `cmd_vaultbranch` | `action` list, create, delete or rename; `name`, `from`, `to` |
| Name a version | `cmd_vaulttag` | `name`, `version`; a tag does not move |
| Merge | `cmd_vaultmerge` | `source`, `branch`, `choices`; first call reports conflicts, the merge is made when every conflict has a choice |
| Comment on an entity | `cmd_vaultcomment` | `action` list, add, reply, resolve, reopen or delete; `entity`, `body`, `parent`, `id` |

## Order of work

1. `cmd_vaultlog` first. An error that the drawing has no vault document means the person has not put it in a vault; creating one is theirs to do.
2. Check out with `edit` true before changing a vaulted file, so the lock is yours. A refused lock names its holder: stop and report it.
3. Make the change, verify it by measurement, then `cmd_vaultcheckin` with a message a person can read in a year.
4. For a conflict in `cmd_vaultmerge`, list the conflicts to the person unless the task told you how to choose.

## Refusals that are by design

`vaultcreate`, `vaultstate`, `vaultrevise`, `vaultgc`, `vaultlock` and `vaultpin` answer that they are not available to outside agents. Report it; the window does these.
