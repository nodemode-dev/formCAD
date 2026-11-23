import math

import pytest

from tests.support import geometry


def lisp(doc, code: str) -> dict:
    return doc.command("lisp", code=code)["result"]


def value(doc, code: str) -> str:
    out = lisp(doc, code)
    assert out["error"] == "", out
    return out["value"]


@pytest.mark.parametrize(
    "code, expected",
    [
        ("(+ 1 2)", "3"),
        ("(- 10 4 3)", "3"),
        ("(* 6 7)", "42"),
        ("(/ 7 2)", "3"),
        ("(rem 17 5)", "2"),
        ("(expt 2 10)", "1024"),
        ("(abs -5)", "5"),
        ("(max 1 9 3)", "9"),
        ("(fix 3.7)", "3"),
        ("(type (/ 7 2))", "INT"),
        ("(type (/ 7 2.0))", "REAL"),
        ("(type (+ 1 2.0))", "REAL"),
        ("(type (fix 3.7))", "INT"),
    ],
)
def test_integer_arithmetic_stays_integer_and_any_real_operand_makes_a_real(doc, code, expected):
    assert value(doc, code) == expected


@pytest.mark.parametrize(
    "code, expected",
    [
        ("(/ 7 2.0)", 3.5),
        ("(* 2 3.5)", 7.0),
        ("(sqrt 16)", 4.0),
        ("(float 3)", 3.0),
        ("(sin (/ pi 2))", 1.0),
        ("(atan 1.0 1.0)", math.pi / 4),
    ],
)
def test_real_arithmetic_gives_the_closed_form_value(doc, code, expected):
    assert float(value(doc, code)) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    "code, expected",
    [
        ("(car (list 1 2 3))", "1"),
        ("(cdr (list 1 2 3))", "(2 3)"),
        ("(cons 1 '(2 3))", "(1 2 3)"),
        ("(cons 1 2)", "(1 . 2)"),
        ("(nth 1 '(10 20 30))", "20"),
        ("(nth 5 '(10 20 30))", "nil"),
        ("(length '(1 2 3 4))", "4"),
        ("(append '(1 2) '(3) '(4 5))", "(1 2 3 4 5)"),
        ("(reverse '(1 2 3))", "(3 2 1)"),
        ("(mapcar '1+ '(1 2 3))", "(2 3 4)"),
        ("(mapcar '+ '(1 2 3) '(10 20 30))", "(11 22 33)"),
        ("(last '(1 2 3))", "3"),
        ("(cadr '(1 2 3))", "2"),
        ("(assoc 2 (list (cons 1 \"a\") (cons 2 \"b\")))", "(2 . \"b\")"),
        ("(car nil)", "nil"),
    ],
)
def test_list_functions_follow_the_language_rules(doc, code, expected):
    assert value(doc, code) == expected


@pytest.mark.parametrize(
    "code, expected",
    [
        ('(strcat "form" "CAD")', '"formCAD"'),
        ('(strlen "hello")', "5"),
        ('(substr "hello" 2 3)', '"ell"'),
        ('(strcase "abc")', '"ABC"'),
        ('(strcase "ABC" T)', '"abc"'),
        ('(atoi "42")', "42"),
        ('(itoa 7)', '"7"'),
        ('(rtos 3.14159 2 2)', '"3.14"'),
    ],
)
def test_string_functions_follow_the_language_rules(doc, code, expected):
    assert value(doc, code) == expected


@pytest.mark.parametrize(
    "code, expected",
    [
        ('(if (> 2 1) "yes" "no")', '"yes"'),
        ('(if (< 2 1) "yes")', "nil"),
        ("(cond ((= 1 2) 'a) ((= 1 1) 'b) (T 'c))", "B"),
        ("(cond ((= 1 2) 'a))", "nil"),
        ("(and T nil)", "nil"),
        ("(and 1 2)", "T"),
        ("(or nil nil)", "nil"),
        ("(or nil 3)", "T"),
        ("(not nil)", "T"),
        ("(= 2 2.0)", "T"),
        ("(/= 1 2)", "T"),
        ("(<= 1 1 2)", "T"),
        ("(eq 'a 'a)", "T"),
        ("(equal (list 1 2) (list 1 2))", "T"),
        ("(minusp -3)", "T"),
        ("(zerop 0)", "T"),
    ],
)
def test_conditionals_comparison_and_logic_follow_the_language_rules(doc, code, expected):
    assert value(doc, code) == expected


def test_setq_keeps_a_value_for_later_expressions_in_the_same_drawing(doc):
    assert value(doc, "(setq side 12)") == "12"
    assert value(doc, "(* side side)") == "144"


def test_a_recursive_defun_computes_factorial(doc):
    value(doc, "(defun fact (n) (if (<= n 1) 1 (* n (fact (- n 1)))))")
    assert value(doc, "(fact 10)") == str(math.factorial(10))
    assert value(doc, "(fact 1)") == "1"


@pytest.mark.parametrize(
    "code, word",
    [
        ("(/ 1 0)", "divide by zero"),
        ("(no-such-function 3)", "no function definition"),
        ('(+ 1 "a")', "bad argument type"),
        ("(+ 1 2", "malformed"),
        ("(car 5)", "bad argument type"),
    ],
)
def test_an_error_in_an_expression_is_reported_and_the_interpreter_stays_usable(doc, code, word):
    value(doc, "(setq kept 7)")
    out = lisp(doc, code)
    assert word in out["error"].lower()
    assert value(doc, "(+ kept 1)") == "8"


def test_command_line_from_lisp_draws_the_line_it_was_given(doc):
    value(doc, '(command "LINE" "0,0" "30,40" "")')
    line = doc.only("line")
    assert geometry.same_point(line["start"], (0, 0)) and geometry.same_point(line["end"], (30, 40))


def test_entget_of_entlast_reads_back_the_drawn_line(doc):
    value(doc, '(command "LINE" "0,0" "30,40" "")')
    assert value(doc, "(cdr (assoc 0 (entget (entlast))))") == '"LINE"'
    start = value(doc, "(cdr (assoc 10 (entget (entlast))))")
    end = value(doc, "(cdr (assoc 11 (entget (entlast))))")
    assert [float(v) for v in start.strip("()").split()] == pytest.approx([0, 0, 0], abs=1e-9)
    assert [float(v) for v in end.strip("()").split()] == pytest.approx([30, 40, 0], abs=1e-9)


def test_entmake_entmod_and_entdel_create_change_and_remove_objects(doc):
    value(doc, '(entmake (list (cons 0 "CIRCLE") (list 10 1.0 2.0 0.0) (cons 40 3.0)))')
    circle = doc.only("circle")
    assert geometry.same_point(circle["center"], (1, 2)) and circle["radius"] == pytest.approx(3.0, abs=1e-9)
    value(doc, "(setq e (entlast) d (entget e))")
    value(doc, "(entmod (subst (cons 40 5.0) (assoc 40 d) d))")
    assert doc.only("circle")["radius"] == pytest.approx(5.0, abs=1e-9)
    value(doc, "(entdel e)")
    assert doc.entities() == []


def test_ssget_all_counts_the_objects_in_the_drawing(doc):
    doc.type("LINE", "0,0", "10,0", "")
    doc.type("CIRCLE", "5,5", "2")
    doc.type("CIRCLE", "50,5", "2")
    assert value(doc, '(sslength (ssget "X"))') == "3"
    assert value(doc, "(sslength (ssget \"X\" '((0 . \"CIRCLE\"))))") == "2"


def test_an_error_halfway_through_a_routine_leaves_the_drawing_consistent_and_one_undo_takes_it_back(doc):
    out = lisp(doc, '(progn (command "LINE" "0,0" "10,0" "") (command "CIRCLE" "5,5" "2") (car 5) (command "LINE" "0,0" "0,10" ""))')
    assert "bad argument type" in out["error"]
    assert doc.kinds() == {"line": 1, "circle": 1}
    assert doc.idle()
    made = sorted((e["kind"], tuple(e.get("start") or e.get("center"))) for e in doc.entities())
    doc.undo()
    assert doc.entities() == []
    doc.redo()
    assert sorted((e["kind"], tuple(e.get("start") or e.get("center"))) for e in doc.entities()) == made


def test_lisp_typed_at_the_command_line_is_evaluated(doc):
    doc.type('(command "CIRCLE" "10,10" "4")')
    circle = doc.only("circle")
    assert geometry.same_point(circle["center"], (10, 10)) and circle["radius"] == pytest.approx(4.0, abs=1e-9)


def test_the_bolt_pattern_routine_puts_six_holes_where_its_fixture_says_and_one_undo_takes_it_back(doc, fixtures):
    doc.type("APPLOAD", str(fixtures / "lisp/bolt-pattern.lsp"))
    doc.type("BOLTDEMO")
    holes = doc.entities("circle")
    assert len(holes) == 6
    assert {h["layer"] for h in holes} == {"BOLTS"}
    assert all(h["radius"] == pytest.approx(4.0, abs=1e-9) for h in holes)
    want = sorted((150 + 30 * math.cos(math.radians(60 * i + 15)), 120 + 30 * math.sin(math.radians(60 * i + 15))) for i in range(6))
    got = sorted((h["center"][0], h["center"][1]) for h in holes)
    for (gx, gy), (wx, wy) in zip(got, want):
        assert gx == pytest.approx(wx, abs=1e-6) and gy == pytest.approx(wy, abs=1e-6)
    doc.type("U")
    assert doc.entities() == []
