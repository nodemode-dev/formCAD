from app.graph.nodes.common import NodeError, NodeWarning, P, T, absent, add, head, sort_rank

CAT = "Lists"
LIST = "list"


def item(ctx, lst, index, wrap):
    n = len(lst)
    if n == 0:
        raise NodeWarning("The list is empty.", "LIST_EMPTY", "list")
    i = index % n if wrap else index
    if not 0 <= i < n:
        raise NodeWarning("Index %d is outside a list of %d items." % (index, n), "INDEX_RANGE", "index")
    return lst[i]


add("list.item", "2dbe73d6-9d73-4990-8dd5-3942cea4aea1", "List Item", "Item", CAT, "Pick", [P("list", "any", LIST, None, "L", "The list."), P("index", "integer", "item", 0, "i", "Zero based position."), P("wrap", "boolean", "item", False, "W", "Count around the end of the list.")], [P("item", "any", "item", None, "E", "The picked item.")], solve=item, description="Picks the item at an index of each list; an index outside the list gives a warning and a null.")
add("list.length", "0849ab8a-5f55-40de-b0f0-288f3f497c16", "List Length", "Len", CAT, "Pick", [P("list", "any", LIST, None, "L", "The list.")], [P("length", "integer", "item", None, "N", "Number of items, nulls included.")], solve=lambda ctx, lst: len(lst), description="Counts the items of each list.")


def sublist(ctx, lst, start, end):
    n = len(lst)
    a = head(start, 0)
    b = head(end, None)
    b = n - 1 if b is None else b
    a = a + n if a < 0 else a
    b = b + n if b < 0 else b
    a = max(a, 0)
    b = min(b, n - 1)
    return lst[a:b + 1] if a <= b else []


add("list.sublist", "78678986-9431-4fd8-a4f8-cd59144d3a61", "Sub List", "Sub", CAT, "Pick", [P("list", "any", LIST, None, "L", "The list."), P("start", "integer", LIST, 0, "A", "First index kept."), P("end", "integer", LIST, None, "B", "Last index kept, included; the end of the list when empty.", True)], [P("list", "any", LIST, None, "L", "The items from start to end.")], solve=sublist, multi=True, description="The items from one index to another, both included; negative indices count from the end.")
add("list.reverse", "428e2022-bcd9-4c04-9f8a-63e766ceb439", "Reverse List", "Rev", CAT, "Order", [P("list", "any", LIST, None, "L", "The list.")], [P("list", "any", LIST, None, "L", "The list backwards.")], solve=lambda ctx, lst: lst[::-1], multi=True, description="Reverses the order of each list.")


def sort(ctx, keys, values):
    n = len(keys)
    order = sorted(range(n), key=lambda i: sort_rank(keys[i]))
    vals = []
    if not absent(values):
        if len(values) != n:
            raise NodeError("The keys and the values need the same number of items.", "SORT_LENGTH", "values")
        vals = [values[i] for i in order]
    return [keys[i] for i in order], vals, order


add("list.sort", "a784dff7-4157-4185-9dd8-b0b7ad44f0dd", "Sort List", "Sort", CAT, "Order", [P("keys", "any", LIST, None, "K", "Items to sort by: nulls first, then booleans, numbers and text."), P("values", "any", LIST, None, "V", "Items moved along with the keys.", True)], [P("keys", "any", LIST, None, "K", "The sorted keys."), P("values", "any", LIST, None, "V", "The values in key order."), P("indices", "integer", LIST, None, "I", "Where each sorted item came from.")], solve=sort, multi=True, description="Sorts a list in ascending order and moves a second list along with it; equal keys keep their order.")


def shift(ctx, lst, offset, wrap):
    n = len(lst)
    k = head(offset, 1)
    if n == 0:
        return []
    if head(wrap, True):
        k %= n
        return lst[n - k:] + lst[:n - k] if k else list(lst)
    return [lst[i - k] if 0 <= i - k < n else None for i in range(n)]


add("list.shift", "cb9bd222-bbf1-43d6-8eb9-06cb58146623", "Shift List", "Shift", CAT, "Order", [P("list", "any", LIST, None, "L", "The list."), P("offset", "integer", LIST, 1, "O", "Places to move items toward the end; negative moves them back."), P("wrap", "boolean", LIST, True, "W", "Items leaving one end come back at the other; off leaves nulls.")], [P("list", "any", LIST, None, "L", "The shifted list, same length.")], solve=shift, multi=True, description="Moves every item along the list by an offset.")


def cull_pattern(ctx, lst, pattern):
    pat = [bool(p) for p in pattern if p is not None]
    if not pat:
        return list(lst)
    return [v for i, v in enumerate(lst) if not pat[i % len(pat)]]


add("list.cull_pattern", "9e8d7dd0-45ec-4612-a8cc-abdf60cbb8bb", "Cull Pattern", "CullP", CAT, "Filter", [P("list", "any", LIST, None, "L", "The list."), P("pattern", "boolean", LIST, None, "P", "Repeating mask: true removes the item at that place.")], [P("list", "any", LIST, None, "L", "The items kept.")], solve=cull_pattern, multi=True, description="Removes items by a repeating true or false pattern.")


def cull_index(ctx, lst, indices, wrap):
    n = len(lst)
    drop = set()
    w = head(wrap, False)
    for k in indices:
        if k is None or n == 0:
            continue
        if w:
            k %= n
        if 0 <= k < n:
            drop.add(k)
    return [v for i, v in enumerate(lst) if i not in drop]


add("list.cull_index", "28ab66af-7021-4524-9782-6c772ed3eab3", "Cull Index", "CullI", CAT, "Filter", [P("list", "any", LIST, None, "L", "The list."), P("indices", "integer", LIST, None, "I", "Positions to remove."), P("wrap", "boolean", LIST, False, "W", "Indices count around the list; off ignores indices outside it.")], [P("list", "any", LIST, None, "L", "The items kept.")], solve=cull_index, multi=True, description="Removes the items at given indices.")


def dispatch(ctx, lst, pattern):
    pat = [bool(p) for p in pattern if p is not None]
    if not pat:
        raise NodeError("The pattern needs at least one value.", "PATTERN_EMPTY", "pattern")
    a, b = [], []
    for i, v in enumerate(lst):
        (a if pat[i % len(pat)] else b).append(v)
    return a, b


add("list.dispatch", "32dca5a1-13ed-4a43-a65f-952a65b7dc52", "Dispatch", "Disp", CAT, "Filter", [P("list", "any", LIST, None, "L", "The list."), P("pattern", "boolean", LIST, None, "P", "Repeating mask: true sends an item to A, false to B.")], [P("a", "any", LIST, None, "A", "Items where the pattern is true."), P("b", "any", LIST, None, "B", "Items where the pattern is false.")], solve=dispatch, multi=True, description="Splits a list in two by a repeating true or false pattern.")


def weave(ctx, pattern, a, b, c, d, rule):
    pat = [int(p) for p in pattern if p is not None]
    if not pat:
        raise NodeError("The pattern needs at least one number.", "PATTERN_EMPTY", "pattern")
    srcs = [[] if absent(x) else list(x) for x in (a, b, c, d)]
    if any(p < 0 or p > 3 for p in pat):
        raise NodeError("The pattern may only use 0 to 3.", "PATTERN_RANGE", "pattern")
    mode = head(rule, 0)
    used = sorted(set(pat))
    cursor = [0, 0, 0, 0]
    out = []
    step = 0
    cap = (sum(len(s) for s in srcs) + 1) * (len(pat) + 1) + 8
    while step < cap:
        if mode != 0 and all(cursor[k] >= len(srcs[k]) for k in used):
            break
        k = pat[step % len(pat)]
        step += 1
        if cursor[k] >= len(srcs[k]):
            if mode == 0:
                break
            if mode == 1:
                out.append(None)
            continue
        out.append(srcs[k][cursor[k]])
        cursor[k] += 1
    return out


add("list.weave", "202da297-f236-4ab6-8f59-8212e195acf2", "Weave", "Weave", CAT, "Combine", [P("pattern", "integer", LIST, None, "P", "Repeating list of sources: 0 for A, 1 for B, 2 for C, 3 for D."), P("a", "any", LIST, None, "A", "First source.", True), P("b", "any", LIST, None, "B", "Second source.", True), P("c", "any", LIST, None, "C", "Third source.", True), P("d", "any", LIST, None, "D", "Fourth source.", True), P("rule", "integer", LIST, 0, "R", "When a source runs out: 0 stop, 1 fill with nulls until all are used, 2 skip it.")], [P("list", "any", LIST, None, "L", "The woven list.")], solve=weave, multi=True, description="Interleaves up to four lists following a pattern.")


def insert(ctx, lst, items, index):
    n = len(lst)
    i = head(index, 0)
    i = i + n if i < 0 else i
    i = min(max(i, 0), n)
    return list(lst[:i]) + list(items) + list(lst[i:])


add("list.insert", "21c737ee-af84-49fd-bce6-e5e2bf33dc81", "Insert Items", "Ins", CAT, "Edit", [P("list", "any", LIST, None, "L", "The list."), P("items", "any", LIST, None, "I", "Items to put in."), P("index", "integer", LIST, 0, "N", "Position of the first inserted item; negative counts from the end.")], [P("list", "any", LIST, None, "L", "The longer list.")], solve=insert, multi=True, description="Puts items into a list at an index.")


def replace(ctx, lst, items, indices):
    out = list(lst)
    n = len(out)
    if not items:
        return out
    for k, i in enumerate(indices):
        if i is None:
            continue
        if not -n <= i < n:
            ctx.warn("Index %d is outside a list of %d items." % (i, n), "INDEX_RANGE", "indices")
            continue
        out[i] = items[min(k, len(items) - 1)]
    return out


add("list.replace", "7997911d-b225-4fd2-ad96-a3fa0bb66155", "Replace Items", "Repl", CAT, "Edit", [P("list", "any", LIST, None, "L", "The list."), P("items", "any", LIST, None, "I", "New items; the last one repeats when there are fewer than indices."), P("indices", "integer", LIST, None, "N", "Positions to overwrite.")], [P("list", "any", LIST, None, "L", "The edited list.")], solve=replace, multi=True, description="Overwrites the items at given indices.")


def split(ctx, lst, index):
    n = len(lst)
    i = head(index, 1)
    i = i + n if i < 0 else i
    i = min(max(i, 0), n)
    return list(lst[:i]), list(lst[i:])


add("list.split", "4df901ec-254f-4e43-a06b-089e1886fb68", "Split List", "Split", CAT, "Edit", [P("list", "any", LIST, None, "L", "The list."), P("index", "integer", LIST, 1, "N", "Where to cut; items before it go to A.")], [P("a", "any", LIST, None, "A", "Items before the index."), P("b", "any", LIST, None, "B", "Items from the index on.")], solve=split, multi=True, description="Cuts a list in two at an index.")


def partition(ctx, trees):
    lists = trees["list"]
    sizes = trees["size"].items()
    out = T.DataTree()
    for k, (path, items) in enumerate(lists.items()):
        row = [int(v) for v in sizes[min(k, len(sizes) - 1)][1] if v is not None] or [2]
        if any(s < 1 for s in row):
            raise NodeError("A partition size must be at least 1.", "PARTITION_SIZE", "size")
        pos = 0
        j = 0
        while pos < len(items):
            s = row[j % len(row)]
            out.set_branch(path.child(j), items[pos:pos + s])
            pos += s
            j += 1
    return {"lists": out}


add("list.partition", "ada280de-d96c-42fb-af31-18f4ec328371", "Partition List", "Part", CAT, "Edit", [P("list", "any", "tree", None, "L", "The lists to cut into pieces."), P("size", "integer", "tree", 2, "S", "Piece sizes, repeated in turn.")], [P("lists", "any", "tree", None, "P", "One new branch per piece, below the path of its list.")], run=partition, description="Cuts each list into pieces of given sizes; every piece becomes a branch.")


def combine(ctx, a, b, c, d):
    out = list(a)
    for x in (b, c, d):
        if not absent(x):
            out.extend(x)
    return out


add("list.combine", "4d720600-ad84-4bf3-bc1c-8e38a1f0ae77", "Combine Lists", "Comb", CAT, "Combine", [P("a", "any", LIST, None, "A", "First list."), P("b", "any", LIST, None, "B", "Second list.", True), P("c", "any", LIST, None, "C", "Third list.", True), P("d", "any", LIST, None, "D", "Fourth list.", True)], [P("list", "any", LIST, None, "L", "All items one after the other.")], solve=combine, multi=True, description="Joins up to four lists into one.")
