from trainsh import Recipe

recipe = Recipe(
    "hello-world",
    owner="examples",
    tags=["bundle", "local", "intro"],
    callbacks=["console", "sqlite"],
)
message = "Hello from trainsh"

with recipe.linear():
    hello = recipe.session("hello", host="local", id="open_hello")
    hello.run(["printf", "%s\n", message], id="print_hello")
    recipe.notify(message, id="notify_hello")
    hello.close(id="close_hello")
