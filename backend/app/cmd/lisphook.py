def lisp_line(runner, text: str) -> None:
    if runner.run is None:
        from app.lisp import hooks

        hooks.run_line(runner, text)
        return
    runner._submit(text)
