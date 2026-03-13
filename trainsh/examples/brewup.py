from trainsh import Recipe

recipe = Recipe(
    "brewup",
    owner="ops",
    tags=["bundle", "local", "maintenance"],
    callbacks=["console", "sqlite"],
)

with recipe.linear():
    update = recipe.session("update", host="local", id="open_update")
    update.run("brew update", id="brew_update")
    update.run("brew upgrade", id="brew_upgrade")
    update.run("brew upgrade --greedy --cask $(brew list --cask)", id="brew_upgrade_casks")
    update.run("brew cleanup", id="brew_cleanup")
    recipe.notify("brew upgrade complete!", id="notify_complete")
    update.close(id="close_update")
