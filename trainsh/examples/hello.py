from trainsh.pyrecipe import *

recipe("hello-world", callbacks=["console", "sqlite"])
var("MESSAGE", "Hello from trainsh")

hello = session("hello", on="local")
printed = hello('echo "$MESSAGE"')
noticed = notice("$MESSAGE", after=printed)
hello.close(after=noticed)
