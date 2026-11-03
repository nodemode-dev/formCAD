from app.graph.nodes.common import NodeWarning, P, T, add, first_item, listing, single, tree_absent

CAT = "Trees"
TREE = "tree"


def whole(text, kind="any", default=None):
    return P("tree", kind, TREE, default, "T", text)


def unary(type_id, guid, name, nick, fn, text, group="Structure"):
    def run(ctx, trees):
        return {"tree": fn(trees["tree"])}

    add(type_id, guid, name, nick, CAT, group, [whole("The data tree.")], [P("tree", "any", TREE, None, "T", "The changed tree.")], run=run, description=text)


unary("tree.graft", "0998b520-47fe-4e14-b124-221b70e1b08c", "Branch Per Item", "PerItem", T.graft, "Puts every item in a branch of its own, one level deeper; empty branches vanish.")
unary("tree.simplify", "bedd2e4a-3785-446c-af29-2929f8e4526e", "Simplify Tree", "Simp", T.simplify, "Removes the leading path numbers shared by every branch, keeping at least one.")
unary("tree.flip", "5db8b5ab-2f9f-4c02-92e7-b26e8630380e", "Transpose Tree", "Transp", T.flip, "Swaps branches and items: the items at the same index of every branch form a new branch; short branches are padded with nulls.")


def flatten_run(ctx, trees):
    target = first_item(trees["path"])
    return {"tree": T.flatten(trees["tree"], T.as_path(target) if target is not None else None)}


add("tree.flatten", "0fbe0dcd-dbae-45ee-8b08-7347debb96d9", "Flatten Tree", "Flat", CAT, "Structure", [whole("The data tree."), P("path", "text", TREE, None, "P", "Path of the single branch made, like {4;2}; {0} when empty.", True)], [P("tree", "any", TREE, None, "T", "One branch with every item, in path order.")], run=flatten_run, description="Joins all branches into one, in path order.")


def flip_index_run(ctx, trees):
    return {"tree": T.flip_tree(trees["tree"], int(first_item(trees["position"], 0)))}


add("tree.flip_index", "bc95c727-d9b4-4106-83e3-3dda55d49172", "Flip By Index", "FlipI", CAT, "Structure", [whole("The data tree."), P("position", "integer", TREE, 0, "N", "Which path number swaps with the item index.")], [P("tree", "any", TREE, None, "T", "The tree with each item moved to the branch named by its index.")], run=flip_index_run, description="Replaces one path number of every item by the item's index and the index by that path number.")


def trim_run(ctx, trees):
    return {"tree": T.trim(trees["tree"], int(first_item(trees["depth"], 1)))}


add("tree.trim", "ce0f25cc-244a-48ec-b202-1a97c85ca4b6", "Trim Tree", "Trim", CAT, "Structure", [whole("The data tree."), P("depth", "integer", TREE, 1, "D", "How many path numbers to cut off the end; one always stays.")], [P("tree", "any", TREE, None, "T", "The tree with shorter paths; branches that meet are merged in path order.")], run=trim_run, description="Cuts numbers off the end of every path and merges the branches that end up together.")


def shift_run(ctx, trees):
    pos = first_item(trees["position"], "last")
    if isinstance(pos, str) and pos.strip().lstrip("-").isdigit():
        pos = int(pos)
    return {"tree": T.shift_paths(trees["tree"], int(first_item(trees["offset"], 1)), pos)}


add("tree.shift_paths", "4f945d26-1da2-423e-b038-9c817d682031", "Shift Paths", "ShiftP", CAT, "Structure", [whole("The data tree."), P("offset", "integer", TREE, 1, "O", "Amount added to one path number."), P("position", "any", TREE, "last", "P", "Which path number to shift: last, first, or a position counted from zero.")], [P("tree", "any", TREE, None, "T", "The tree with shifted paths.")], run=shift_run, description="Adds an offset to one number of every path; a negative result is an error.")


def mapper_run(ctx, trees):
    warns = []
    out = T.path_map(trees["tree"], str(first_item(trees["mapping"], "{A}(i) -> {A}(i)")), warns)
    for code, text in warns:
        ctx.warn(text, code, "mapping")
    return {"tree": out}


add("tree.path_mapper", "1c46db52-4902-4d84-859d-043f74a60d0a", "Rewrite Paths", "Rewrite", CAT, "Structure", [whole("The data tree."), P("mapping", "text", TREE, "{A}(i) -> {A}(i)", "M", "Source pattern, arrow, target pattern, like {A;B}(i) -> {A;i}(B); presets flatten, graft, renumber and reverse.")], [P("tree", "any", TREE, None, "T", "The remapped tree.")], run=mapper_run, description="Rewrites the path and index of every item by a pattern with names and arithmetic.")


def entwine_run(ctx, trees):
    out = T.DataTree()
    for k, name in enumerate(("a", "b", "c", "d")):
        t = trees[name]
        if tree_absent(t):
            continue
        items = t.items()
        if len(items) == 1:
            out.extend(T.Path((k,)), items[0][1])
        else:
            for path, row in items:
                out.extend(T.Path((k,) + tuple(path)), row)
    return {"tree": out}


add("tree.entwine", "6e719bce-2a65-40d4-9955-640f69d6da9f", "Interleave Trees", "Interl", CAT, "Combine", [P(n, "any", TREE, None, n.upper(), "Input %s." % n.upper(), True) for n in ("a", "b", "c", "d")], [P("tree", "any", TREE, None, "T", "Each single branch input as branch {k}; each multi branch input below {k}.")], run=entwine_run, description="Combines up to four inputs into one tree: the input number becomes the first path number.")


def merge_run(ctx, trees):
    out = T.DataTree()
    for name in ("a", "b", "c", "d"):
        t = trees[name]
        if not tree_absent(t):
            for path, row in t.items():
                out.extend(path, row)
    return {"tree": out}


add("tree.merge", "49bff99e-5a27-4bd9-9852-b954f0f3d165", "Merge Trees", "Merge", CAT, "Combine", [P(n, "any", TREE, None, n.upper(), "Input %s." % n.upper(), True) for n in ("a", "b", "c", "d")], [P("tree", "any", TREE, None, "T", "Branches with the same path are joined, a first.")], run=merge_run, description="Merges up to four trees; branches with the same path are joined.")


def explode_run(ctx, trees):
    rows = trees["tree"].items()
    names = ("a", "b", "c", "d", "e", "f")
    out = {n: T.DataTree() for n in names}
    for k, (path, row) in enumerate(rows):
        n = names[min(k, len(names) - 1)]
        out[n].extend(T.Path((0,)), row)
    return out


add("tree.explode", "9c8165cf-a1af-4aba-a454-ede7657fce8a", "Explode Tree", "Expl", CAT, "Structure", [whole("The data tree.")], [P(n, "any", TREE, None, n.upper(), "Branch %d of the tree." % (i + 1)) for i, n in enumerate(("a", "b", "c", "d", "e", "f"))], run=explode_run, description="Sends each of the first branches to its own output; branches beyond the sixth join the last output.")


def resolve(tree, key):
    rows = tree.items()
    if isinstance(key, bool) or key is None:
        return None
    if isinstance(key, (int, float)) and float(key).is_integer():
        i = int(key)
        return rows[i][0] if -len(rows) <= i < len(rows) else None
    text = str(key).strip()
    if text.startswith("{"):
        p = T.as_path(text)
        return p if p in tree else None
    try:
        i = int(text)
    except ValueError:
        raise T.TreeError("PATH_INVALID", "%r is not a path or a branch number" % text)
    return rows[i][0] if -len(rows) <= i < len(rows) else None


def branch_run(ctx, trees):
    key = first_item(trees["path"], 0)
    path = resolve(trees["tree"], key)
    if path is None:
        ctx.warn("There is no branch %s." % key, "NO_BRANCH", "path")
        return {"branch": T.DataTree(), "path": T.DataTree()}
    return {"branch": listing(trees["tree"].branch(path)), "path": single(str(path))}


add("tree.branch", "fe701c1d-6db5-46b3-8482-a71b3f08c57e", "Tree Branch", "Branch", CAT, "Pick", [whole("The data tree."), P("path", "any", TREE, 0, "P", "A path like {0;1}, or the number of the branch counted from zero (negative from the end).")], [P("branch", "any", TREE, None, "B", "The items of the branch, as branch {0}."), P("path", "text", TREE, None, "P", "The path that was found.")], run=branch_run, description="Takes one branch out of a tree.")


def tree_item(ctx, tree, path, index):
    p = resolve(tree, path)
    if p is None:
        raise NodeWarning("There is no branch %s." % path, "NO_BRANCH", "path")
    row = tree.branch(p)
    if not -len(row) <= index < len(row):
        raise NodeWarning("Index %d is outside branch %s of %d items." % (index, p, len(row)), "INDEX_RANGE", "index")
    return row[index]


add("tree.item", "f2367d5e-1dc9-49be-a820-2d7d6b945c5d", "Tree Item", "TItem", CAT, "Pick", [whole("The data tree."), P("path", "any", "item", 0, "P", "A path like {0;1}, or the number of the branch."), P("index", "integer", "item", 0, "i", "Position inside the branch.")], [P("item", "any", "item", None, "E", "The item.")], solve=tree_item, description="Takes one item out of a tree by branch and index.")


def stats_run(ctx, trees):
    t = trees["tree"]
    rows = t.items()
    return {
        "paths": listing([str(p) for p, _ in rows]),
        "lengths": listing([len(r) for _, r in rows]),
        "branches": single(t.count),
        "items": single(t.item_count),
        "depth": single(t.max_depth),
    }


add("tree.statistics", "c2a7f3c2-4c3e-4801-8db7-e93f66b68a8b", "Tree Statistics", "Stats", CAT, "Inspect", [whole("The data tree.")], [P("paths", "text", TREE, None, "P", "The path of each branch."), P("lengths", "integer", TREE, None, "L", "Items in each branch."), P("branches", "integer", TREE, None, "B", "Number of branches."), P("items", "integer", TREE, None, "I", "Number of items, nulls included."), P("depth", "integer", TREE, None, "D", "Deepest path.")], run=stats_run, description="Describes a tree: its paths, branch lengths, counts and depth.")


def clean_run(ctx, trees):
    return {"tree": T.clean(trees["tree"], bool(first_item(trees["nulls"], True)), bool(first_item(trees["empties"], True)))}


add("tree.clean", "cb8e18b5-39aa-41ca-a69b-5e869530740a", "Clean Tree", "Clean", CAT, "Structure", [whole("The data tree."), P("nulls", "boolean", TREE, True, "N", "Remove null items."), P("empties", "boolean", TREE, True, "E", "Remove empty branches.")], [P("tree", "any", TREE, None, "T", "The cleaned tree.")], run=clean_run, description="Removes null items and empty branches.")


def renumber_run(ctx, trees):
    return {"tree": T.renumber(trees["tree"], int(first_item(trees["start"], 0)))}


add("tree.renumber", "78dfe408-fa92-45fd-9ba0-7048b14820df", "Renumber Tree", "Renum", CAT, "Structure", [whole("The data tree."), P("start", "integer", TREE, 0, "S", "First number.")], [P("tree", "any", TREE, None, "T", "The tree with branches numbered in order, one level deep.")], run=renumber_run, description="Gives the branches the paths {start}, {start+1}, and so on, in the old path order.")
