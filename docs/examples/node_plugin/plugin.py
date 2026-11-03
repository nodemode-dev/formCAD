def repeat_text(ctx, text, count):
    return text * max(0, int(count))


def spread(ctx, values):
    numbers = [float(v) for v in values if v is not None]
    if not numbers:
        ctx.warn("The list holds no numbers.", "NO_NUMBERS", "values")
        return None, None, None
    return min(numbers), max(numbers), sum(numbers) / len(numbers)


def register(api):
    api.node(
        "repeat_text",
        guid="0b7f3e1a-4c52-4d8e-9f6a-2a1d5c7b9e30",
        name="Repeat Text",
        nick="Rep",
        category="Example",
        group="Text",
        description="Writes a piece of text several times in a row.",
        inputs=[api.port("text", "text", default="ab", description="The text to repeat."), api.port("count", "integer", default=2, min=0, max=100, description="How many copies.")],
        outputs=[api.port("result", "text", description="The repeated text.")],
        solve=repeat_text,
    )
    api.node(
        "spread",
        guid="5d2a8c90-1e47-4b36-a8f5-7c3e9b0d6a14",
        name="Spread",
        nick="Spr",
        category="Example",
        group="Numbers",
        description="The smallest, largest and average of a list of numbers.",
        inputs=[api.port("values", "number", "list", description="The numbers to measure.")],
        outputs=[api.port("min", "number"), api.port("max", "number"), api.port("mean", "number")],
        solve=spread,
    )
