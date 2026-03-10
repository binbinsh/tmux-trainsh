from trainsh.pyrecipe import *

recipe("aptup", callbacks=["console", "sqlite"])

update = session("update", on="local")
refresh = update("sudo apt update")
upgrade = update("sudo apt -y dist-upgrade", after=refresh)
cleanup = update("sudo apt -y autoremove", after=upgrade)
noticed = notice("apt upgrade complete!", after=cleanup)
update.close(after=noticed)
