"""Initialize OpsMesh driver once for unit tests using direct on_command matchers."""

import opsmesh

try:
    opsmesh.get_driver()
except ValueError:
    opsmesh.init()
