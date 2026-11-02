; FormCAD LISP routine: parametric bolt-hole pattern
; draws N circles on a pitch circle, moves the set, then rotates it about the moved centre
(defun bp:hole (x y d / e)
  (command "_circle" (list x y) (/ d 2.0))
  (setq e (entlast))
  (entmod (subst (cons 8 "BOLTS") (assoc 8 (entget e)) (entget e)))
  e)

(defun bolt-pattern (cx cy pcd n d rot dx dy / i a ss r)
  (setq ss (ssadd) r (/ pcd 2.0) i 0)
  (repeat n
    (setq a (* 2.0 pi (/ i (float n))))
    (setq ss (ssadd (bp:hole (+ cx (* r (cos a))) (+ cy (* r (sin a))) d) ss))
    (setq i (1+ i)))
  (command "_move" ss "" (list 0.0 0.0) (list dx dy))
  (command "_rotate" ss "" (list (+ cx dx) (+ cy dy)) rot)
  ss)

(defun bolt-centres (/ ss i out e g)
  (setq ss (ssget "X" '((0 . "CIRCLE") (8 . "BOLTS"))) i 0 out nil)
  (if ss
    (repeat (sslength ss)
      (setq g (cdr (assoc 10 (entget (ssname ss i)))))
      (setq out (cons (list (car g) (cadr g)) out) i (1+ i))))
  (reverse out))

(defun c:boltdemo ()
  (bolt-pattern 100.0 100.0 60.0 6 8.0 15.0 50.0 20.0)
  (princ))
