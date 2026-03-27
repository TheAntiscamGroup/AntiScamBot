#!/bin/bash
trap '' HUP
# weird bash magic to rerun as a daemon
case "$1" in
    -d)
    $0 < /dev/null &> /dev/null & disown
    exit 0
    ;;
*)
    ;;
esac
pwd | grep -q .runtime
if [ "$?" -eq "0" ]; then
    cd ..
fi
python3 -m venv .venv
source .venv/bin/activate
python3 ./Main.py
