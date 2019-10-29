#!/usr/bin/env python3
"""
Helper script for Docker build to install packages from Pipfile.lock without installing Pipenv
"""
import json
import subprocess

with open("Pipfile.lock") as fd:
    data = json.load(fd)

packages = []
for k, v in data["default"].items():
    if 'version' in v:
        packages.append(k + v["version"])
    elif 'git' in v:
        packages.append(f"git+{v['git']}.git@{v['ref']}")
    else:
        raise Exception(f"Could not find a valid version for {k}")

subprocess.run(["pip3", "install"] + packages, check=True)
