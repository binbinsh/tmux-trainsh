from trainsh.pyrecipe import *

recipe("brewup", callbacks=["console", "sqlite"])

update = session("update", on="local")
refresh = update("brew update")
upgrade = update("brew upgrade", after=refresh)
casks = update("brew upgrade --greedy --cask $(brew list --cask)", after=upgrade)
cleanup = update("brew cleanup", after=casks)
noticed = notice("brew upgrade complete!", after=cleanup)
update.close(after=noticed)
