from app.graph.nodes.common import P, T, add

CAT = "Sets"
LIST = "list"
TOL = 1e-9


def has(seq, v) -> bool:
    return any(T.values_equal(v, w, TOL) for w in seq)


def unique(seq) -> list:
    out = []
    for v in seq:
        if not has(out, v):
            out.append(v)
    return out


def union(ctx, a, b):
    return unique(list(a) + list(b))


def intersection(ctx, a, b):
    return unique([v for v in a if has(b, v)])


def difference(ctx, a, b):
    return unique([v for v in a if not has(b, v)])


add("set.union", "d00b4f59-708a-4e00-a7bc-7b8b91c9d21f", "Union", "Union", CAT, "Set", [P("a", "any", LIST, None, "A", "First set."), P("b", "any", LIST, None, "B", "Second set.")], [P("set", "any", LIST, None, "S", "Every value found in A or B, once, in order of first appearance.")], solve=union, multi=True, description="Values that are in either list, without repeats.")
add("set.intersection", "d8a1f814-4147-49da-b47a-3f77d2924112", "Intersection", "Inter", CAT, "Set", [P("a", "any", LIST, None, "A", "First set."), P("b", "any", LIST, None, "B", "Second set.")], [P("set", "any", LIST, None, "S", "Values found in both, once, in the order of A.")], solve=intersection, multi=True, description="Values that are in both lists.")
add("set.difference", "ec4287d0-f04a-4685-b8bd-960aceabccc0", "Difference", "Diff", CAT, "Set", [P("a", "any", LIST, None, "A", "First set."), P("b", "any", LIST, None, "B", "Second set.")], [P("set", "any", LIST, None, "S", "Values of A that are not in B, once, in the order of A.")], solve=difference, multi=True, description="Values of the first list that are missing from the second.")


def cull_duplicates(ctx, lst):
    seen = []
    first = []
    counts = []
    for i, v in enumerate(lst):
        for k, w in enumerate(seen):
            if T.values_equal(v, w, TOL):
                counts[k] += 1
                break
        else:
            seen.append(v)
            first.append(i)
            counts.append(1)
    return seen, first, counts


add("set.unique", "6df6c739-8562-4e05-a0d9-ede6f91a051c", "Unique Values", "Uniq", CAT, "Set", [P("list", "any", LIST, None, "L", "The list.")], [P("list", "any", LIST, None, "U", "The values without repeats."), P("indices", "integer", LIST, None, "I", "Index of the first appearance of each value."), P("counts", "integer", LIST, None, "C", "How often each value appears.")], solve=cull_duplicates, multi=True, description="Removes repeated values, numbers within a tolerance of 1e-9.")


def member_index(ctx, lst, member):
    for i, v in enumerate(lst):
        if T.values_equal(v, member, TOL):
            return i, True
    return -1, False


add("set.member_index", "e367b412-6630-4b3f-bc93-d5c48b0e9782", "Member Index", "Index", CAT, "Set", [P("list", "any", LIST, None, "L", "The list to search."), P("member", "any", "item", None, "M", "The value to look for.")], [P("index", "integer", "item", None, "I", "Position of the first match, or -1."), P("found", "boolean", "item", None, "F", "True when the value is in the list.")], solve=member_index, description="Finds where a value first appears in a list.")
