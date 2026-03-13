from trainsh import Recipe

recipe = Recipe(
    "aptup",
    owner="ops",
    tags=["bundle", "local", "maintenance"],
    callbacks=["console", "sqlite"],
)

with recipe.linear():
    update = recipe.session("update", host="local", id="open_update")
    update.run("sudo apt update", id="apt_update")
    update.run("sudo apt -y dist-upgrade", id="apt_dist_upgrade")
    update.run("sudo apt -y autoremove", id="apt_autoremove")
    recipe.notify("apt upgrade complete!", id="notify_complete")
    update.close(id="close_update")
